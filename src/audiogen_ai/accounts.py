"""Verified accounts, password hashing, and email delivery."""

from __future__ import annotations

from dataclasses import dataclass
from email.message import EmailMessage
import hashlib
import hmac
import os
from pathlib import Path
import re
import secrets
import smtplib
import sqlite3
import ssl
import time
from urllib.parse import urlencode, urlsplit
import uuid

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_PASSWORDS = PasswordHasher(time_cost=3, memory_cost=65_536, parallelism=2)
_DUMMY_PASSWORD_HASH = _PASSWORDS.hash("AUDIOGEN AI invalid account timing sentinel")
_COMMON_PASSWORDS = {
    "123456789012345",
    "1234567890123456",
    "passwordpassword",
    "password1234567",
    "qwertyuiopasdfg",
    "letmeinletmein!",
    "iloveyouiloveyou",
}
_EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s.]+(?:\.[^@\s.]+)+$")
_TOKEN_PURPOSES = {"verify", "reset"}


class AccountError(ValueError):
    """A safe account or credential validation error."""


class RateLimitError(AccountError):
    """The account operation exceeded its per-address limit."""


class EmailDeliveryError(RuntimeError):
    """The configured SMTP service could not deliver a message."""


@dataclass(frozen=True, slots=True)
class Account:
    id: str
    name: str
    email: str


@dataclass(frozen=True, slots=True)
class EmailSettings:
    host: str
    port: int
    username: str
    password: str
    from_address: str
    use_ssl: bool

    @classmethod
    def from_env(cls) -> EmailSettings | None:
        host = os.environ.get("SMTP_HOST", "").strip()
        from_address = os.environ.get("SMTP_FROM_EMAIL", "").strip()
        username = os.environ.get("SMTP_USERNAME", "").strip()
        password = os.environ.get("SMTP_PASSWORD", "")
        if not any((host, from_address, username, password)):
            return None
        if not host or not from_address:
            raise EmailDeliveryError("Configure both SMTP_HOST and SMTP_FROM_EMAIL.")
        if bool(username) != bool(password):
            raise EmailDeliveryError("Configure both SMTP_USERNAME and SMTP_PASSWORD.")
        try:
            port = int(os.environ.get("SMTP_PORT", "465" if os.environ.get("SMTP_USE_SSL") == "true" else "587"))
        except ValueError as exc:
            raise EmailDeliveryError("SMTP_PORT must be a valid port number.") from exc
        if not 1 <= port <= 65535:
            raise EmailDeliveryError("SMTP_PORT must be between 1 and 65535.")
        if not _EMAIL.fullmatch(from_address):
            raise EmailDeliveryError("SMTP_FROM_EMAIL must be a valid email address.")
        return cls(
            host=host,
            port=port,
            username=username,
            password=password,
            from_address=from_address,
            use_ssl=os.environ.get("SMTP_USE_SSL", "").casefold() == "true",
        )


def validate_email(value: str) -> str:
    email = value.strip().casefold()
    if len(email) > 254 or not _EMAIL.fullmatch(email):
        raise AccountError("Enter a valid email address.")
    return email


def validate_password(value: str) -> None:
    if not isinstance(value, str) or not 15 <= len(value) <= 128:
        raise AccountError("Use a password or passphrase between 15 and 128 characters.")
    if value.casefold() in _COMMON_PASSWORDS:
        raise AccountError("Choose a less common password or passphrase.")


def public_base_url() -> str:
    value = (
        os.environ.get("AUDIOGEN_BASE_URL")
        or os.environ.get("RENDER_EXTERNAL_URL")
        or "http://localhost:8501"
    ).strip().rstrip("/")
    parts = urlsplit(value)
    if (
        parts.scheme not in {"http", "https"}
        or not parts.netloc
        or parts.username
        or parts.password
        or parts.query
        or parts.fragment
    ):
        raise EmailDeliveryError("AUDIOGEN_BASE_URL must be an absolute HTTP(S) URL.")
    if parts.scheme != "https" and parts.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise EmailDeliveryError("Public account links require HTTPS.")
    return value


def local_verification_enabled() -> bool:
    if os.environ.get("AUDIOGEN_ENABLE_LOCAL_VERIFICATION", "").casefold() != "true":
        return False
    parts = urlsplit(public_base_url())
    if parts.scheme != "http" or parts.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise EmailDeliveryError(
            "Local verification links require an HTTP localhost AUDIOGEN_BASE_URL."
        )
    return True


def local_verification_url(token: str) -> str:
    if not local_verification_enabled():
        raise EmailDeliveryError("Local verification links are disabled.")
    if not token or len(token) > 128:
        raise EmailDeliveryError("The verification token is invalid.")
    return f"{public_base_url()}/?{urlencode({'verify': token})}"


class AccountStore:
    def __init__(self, data_dir: Path) -> None:
        self.root = data_dir.expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.database = self.root / "accounts.sqlite3"
        try:
            os.chmod(self.root, 0o700)
        except OSError:
            pass
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS accounts (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    password_hash TEXT NOT NULL,
                    email_verified INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS account_tokens (
                    token_hash TEXT PRIMARY KEY,
                    account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
                    purpose TEXT NOT NULL CHECK (purpose IN ('verify', 'reset')),
                    expires_at REAL NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS account_tokens_account_purpose
                    ON account_tokens(account_id, purpose);
                CREATE TABLE IF NOT EXISTS account_attempts (
                    email TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    attempted_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS account_attempts_lookup
                    ON account_attempts(email, operation, attempted_at);
                """
            )
        try:
            os.chmod(self.database, 0o600)
        except OSError:
            pass

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @staticmethod
    def _account(row: sqlite3.Row | None) -> Account | None:
        if row is None:
            return None
        return Account(id=row["id"], name=row["name"], email=row["email"])

    @staticmethod
    def _record_attempt(
        connection: sqlite3.Connection,
        email: str,
        operation: str,
        *,
        limit: int,
        period_seconds: int,
        now: float,
    ) -> None:
        connection.execute(
            "DELETE FROM account_attempts WHERE attempted_at < ?", (now - 86_400,)
        )
        recent = connection.execute(
            """
            SELECT COUNT(*) AS count FROM account_attempts
            WHERE email = ? AND operation = ? AND attempted_at > ?
            """,
            (email, operation, now - period_seconds),
        ).fetchone()["count"]
        if recent >= limit:
            raise RateLimitError("Too many attempts. Wait a while before trying again.")
        connection.execute(
            "INSERT INTO account_attempts (email, operation, attempted_at) VALUES (?, ?, ?)",
            (email, operation, now),
        )

    @staticmethod
    def _issue_token(
        connection: sqlite3.Connection, account_id: str, purpose: str, now: float
    ) -> str:
        connection.execute(
            "DELETE FROM account_tokens WHERE account_id = ? AND purpose = ?",
            (account_id, purpose),
        )
        token = secrets.token_urlsafe(32)
        connection.execute(
            """
            INSERT INTO account_tokens (token_hash, account_id, purpose, expires_at, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (hashlib.sha256(token.encode("ascii")).hexdigest(), account_id, purpose, now + 1800, now),
        )
        return token

    def register(self, name: str, email: str, password: str) -> tuple[Account, str]:
        name = " ".join(name.split())
        email = validate_email(email)
        now = time.time()
        with self._connect() as connection:
            self._record_attempt(
                connection, email, "register", limit=5, period_seconds=3600, now=now
            )
            connection.commit()
            validate_password(password)
            if not 1 <= len(name) <= 80:
                raise AccountError("Your display name must be between 1 and 80 characters.")
            existing = connection.execute(
                "SELECT 1 FROM accounts WHERE email = ?", (email,)
            ).fetchone()
            if existing is None:
                account_id = uuid.uuid4().hex
                connection.execute(
                    """
                    INSERT INTO accounts (id, name, email, password_hash, email_verified, created_at)
                    VALUES (?, ?, ?, ?, 0, ?)
                    """,
                    (account_id, name, email, _PASSWORDS.hash(password), now),
                )
                token = self._issue_token(connection, account_id, "verify", now)
        if existing is not None:
            raise AccountError("An account cannot be created with those details.")
        return Account(account_id, name, email), token

    def request_token(self, email: str, purpose: str) -> tuple[Account, str] | None:
        if purpose not in _TOKEN_PURPOSES:
            raise AccountError("Unsupported account action.")
        email = validate_email(email)
        now = time.time()
        with self._connect() as connection:
            self._record_attempt(
                connection, email, purpose, limit=4, period_seconds=3600, now=now
            )
            row = connection.execute(
                "SELECT * FROM accounts WHERE email = ?", (email,)
            ).fetchone()
            if row is None:
                return None
            if purpose == "verify" and row["email_verified"]:
                return None
            if purpose == "reset" and not row["email_verified"]:
                return None
            token = self._issue_token(connection, row["id"], purpose, now)
            account = self._account(row)
        if account is None:
            return None
        return account, token

    def verify_email(self, token: str) -> Account | None:
        return self._consume_token(token, "verify")

    def reset_password(self, token: str, password: str) -> Account | None:
        validate_password(password)
        return self._consume_token(token, "reset", password=password)

    def _consume_token(
        self, token: str, purpose: str, *, password: str | None = None
    ) -> Account | None:
        if not token or len(token) > 128:
            return None
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        now = time.time()
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT a.*, t.token_hash, t.expires_at
                FROM account_tokens t
                JOIN accounts a ON a.id = t.account_id
                WHERE t.token_hash = ? AND t.purpose = ?
                """,
                (digest, purpose),
            ).fetchone()
            if row is None or row["expires_at"] < now:
                connection.execute("DELETE FROM account_tokens WHERE token_hash = ?", (digest,))
                return None
            if purpose == "verify":
                connection.execute(
                    "UPDATE accounts SET email_verified = 1 WHERE id = ?", (row["id"],)
                )
            else:
                connection.execute(
                    "UPDATE accounts SET password_hash = ? WHERE id = ?",
                    (_PASSWORDS.hash(password or ""), row["id"]),
                )
            connection.execute("DELETE FROM account_tokens WHERE account_id = ?", (row["id"],))
            return self._account(row)

    def authenticate(self, email: str, password: str) -> Account | None:
        email = validate_email(email)
        now = time.time()
        with self._connect() as connection:
            try:
                self._record_attempt(
                    connection, email, "login", limit=8, period_seconds=900, now=now
                )
            except RateLimitError:
                if len(password) <= 128:
                    try:
                        _PASSWORDS.verify(_DUMMY_PASSWORD_HASH, password or "invalid")
                    except (VerifyMismatchError, VerificationError, InvalidHashError):
                        pass
                return None
            row = connection.execute(
                "SELECT * FROM accounts WHERE email = ?", (email,)
            ).fetchone()
            encoded = row["password_hash"] if row is not None else _DUMMY_PASSWORD_HASH
            try:
                matches = (
                    _PASSWORDS.verify(encoded, password or "invalid")
                    if len(password) <= 128
                    else False
                )
            except (VerifyMismatchError, VerificationError, InvalidHashError):
                matches = False
            if row is None or not matches or not row["email_verified"]:
                return None
            account = self._account(row)
            if _PASSWORDS.check_needs_rehash(encoded):
                connection.execute(
                    "UPDATE accounts SET password_hash = ? WHERE id = ?",
                    (_PASSWORDS.hash(password), row["id"]),
                )
            return account

    def get_account(self, account_id: str) -> Account | None:
        if not re.fullmatch(r"[0-9a-f]{32}", account_id):
            return None
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM accounts WHERE id = ? AND email_verified = 1",
                (account_id,),
            ).fetchone()
        return self._account(row)

    def workspace(self, account: Account) -> Path:
        if not re.fullmatch(r"[0-9a-f]{32}", account.id):
            raise AccountError("Invalid account workspace.")
        path = (self.root / "users" / account.id).resolve()
        if path.parent != (self.root / "users").resolve():
            raise AccountError("Invalid account workspace.")
        path.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(path, 0o700)
        except OSError:
            pass
        return path


def send_account_email(
    account: Account, token: str, purpose: str, configuration: EmailSettings
) -> None:
    if purpose not in _TOKEN_PURPOSES:
        raise EmailDeliveryError("Unsupported account email action.")
    query = urlencode({purpose: token})
    link = f"{public_base_url()}/?{query}"
    message = EmailMessage()
    message["Subject"] = (
        "Verify your AUDIOGEN AI email"
        if purpose == "verify"
        else "Reset your AUDIOGEN AI password"
    )
    message["From"] = configuration.from_address
    message["To"] = account.email
    action = "verify your email address" if purpose == "verify" else "reset your password"
    message.set_content(
        f"Hello {account.name},\n\n"
        f"Use the secure link below to {action}. It expires in 30 minutes and can be used once.\n\n"
        f"{link}\n\n"
        "If you did not request this, you can ignore this message.\n"
    )
    try:
        context = ssl.create_default_context()
        if configuration.use_ssl:
            with smtplib.SMTP_SSL(
                configuration.host, configuration.port, timeout=15, context=context
            ) as client:
                if configuration.username:
                    client.login(configuration.username, configuration.password)
                client.send_message(message)
        else:
            with smtplib.SMTP(
                configuration.host, configuration.port, timeout=15
            ) as client:
                client.ehlo()
                client.starttls(context=context)
                client.ehlo()
                if configuration.username:
                    client.login(configuration.username, configuration.password)
                client.send_message(message)
    except (OSError, smtplib.SMTPException) as exc:
        raise EmailDeliveryError(
            "Could not send account email. Check SMTP settings and try again."
        ) from exc
