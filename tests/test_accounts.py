import hashlib
import smtplib
from pathlib import Path

import pytest

from audiogen_ai import accounts
from audiogen_ai.accounts import (
    AccountError,
    AccountStore,
    EmailDeliveryError,
    EmailSettings,
    RateLimitError,
    local_verification_enabled,
    local_verification_url,
    send_account_email,
)


PASSWORD = "A correct horse with a battery!"


@pytest.fixture
def store(tmp_path: Path) -> AccountStore:
    return AccountStore(tmp_path)


def test_registration_requires_email_verification_and_hashes_password(store: AccountStore) -> None:
    account, token = store.register("R K Prajapati", "Person@example.com", PASSWORD)
    with store._connect() as connection:
        row = connection.execute(
            "SELECT password_hash, email_verified FROM accounts WHERE id = ?", (account.id,)
        ).fetchone()
        token_row = connection.execute("SELECT token_hash FROM account_tokens").fetchone()
    assert row["password_hash"] != PASSWORD
    assert row["email_verified"] == 0
    assert token_row["token_hash"] == hashlib.sha256(token.encode()).hexdigest()
    assert store.authenticate(account.email, PASSWORD) is None
    verified = store.verify_email(token)
    assert verified == account
    assert store.verify_email(token) is None
    assert store.authenticate("PERSON@example.com", PASSWORD) == account


def test_password_policy_and_duplicate_registration(store: AccountStore) -> None:
    with pytest.raises(AccountError, match="15 and 128"):
        store.register("Name", "person@example.com", "short")
    account, _ = store.register("Name", "person@example.com", PASSWORD)
    with pytest.raises(AccountError, match="cannot be created"):
        store.register("Another", "PERSON@example.com", PASSWORD)
    assert store.get_account(account.id) is None


def test_password_reset_is_single_use_and_updates_hash(store: AccountStore) -> None:
    account, verification_token = store.register("Name", "person@example.com", PASSWORD)
    store.verify_email(verification_token)
    issued = store.request_token(account.email, "reset")
    assert issued is not None
    reset_account, token = issued
    assert reset_account == account
    changed = store.reset_password(token, "A new secure horse battery passphrase!")
    assert changed == account
    assert store.reset_password(token, PASSWORD) is None
    assert store.authenticate(account.email, PASSWORD) is None
    assert store.authenticate(account.email, "A new secure horse battery passphrase!") == account


def test_tokens_expire(store: AccountStore) -> None:
    account, token = store.register("Name", "person@example.com", PASSWORD)
    digest = hashlib.sha256(token.encode()).hexdigest()
    with store._connect() as connection:
        connection.execute(
            "UPDATE account_tokens SET expires_at = 0 WHERE token_hash = ?", (digest,)
        )
    assert store.verify_email(token) is None
    assert store.get_account(account.id) is None


def test_account_workspace_isolated_and_validated(store: AccountStore) -> None:
    first, first_token = store.register("First", "first@example.com", PASSWORD)
    second, second_token = store.register("Second", "second@example.com", PASSWORD)
    assert store.verify_email(first_token) == first
    assert store.verify_email(second_token) == second
    first_path, second_path = store.workspace(first), store.workspace(second)
    assert first_path != second_path
    assert first_path.parent == second_path.parent
    with pytest.raises(AccountError, match="Invalid account workspace"):
        store.workspace(accounts.Account("..", "Bad", "bad@example.com"))


def test_attempts_are_rate_limited_by_email(store: AccountStore) -> None:
    for _ in range(8):
        assert store.authenticate("person@example.com", PASSWORD) is None
    assert store.authenticate("person@example.com", PASSWORD) is None
    with store._connect() as connection:
        attempts = connection.execute(
            "SELECT COUNT(*) AS count FROM account_attempts WHERE operation = 'login'"
        ).fetchone()["count"]
    assert attempts == 8
    for index in range(5):
        with pytest.raises(AccountError):
            store.register(f"Name {index}", "limited@example.com", "short")
    with pytest.raises(RateLimitError):
        store.register("Name", "limited@example.com", PASSWORD)


def test_email_settings_require_complete_auth_configuration(monkeypatch) -> None:
    for key in ("SMTP_HOST", "SMTP_PORT", "SMTP_USERNAME", "SMTP_PASSWORD", "SMTP_FROM_EMAIL"):
        monkeypatch.delenv(key, raising=False)
    assert EmailSettings.from_env() is None
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_USERNAME", "mailer")
    monkeypatch.setenv("SMTP_FROM_EMAIL", "noreply@example.com")
    with pytest.raises(EmailDeliveryError, match="both SMTP_USERNAME"):
        EmailSettings.from_env()


def test_local_verification_links_are_explicit_and_loopback_only(monkeypatch) -> None:
    monkeypatch.delenv("AUDIOGEN_ENABLE_LOCAL_VERIFICATION", raising=False)
    monkeypatch.setenv("AUDIOGEN_BASE_URL", "http://127.0.0.1:8501")
    assert not local_verification_enabled()
    with pytest.raises(EmailDeliveryError, match="disabled"):
        local_verification_url("verification-token")

    monkeypatch.setenv("AUDIOGEN_ENABLE_LOCAL_VERIFICATION", "true")
    assert local_verification_enabled()
    assert local_verification_url("verification-token") == (
        "http://127.0.0.1:8501/?verify=verification-token"
    )

    monkeypatch.setenv("AUDIOGEN_BASE_URL", "https://audiogen.example.com")
    with pytest.raises(EmailDeliveryError, match="localhost"):
        local_verification_enabled()


def test_account_email_uses_tls_and_single_use_link(monkeypatch) -> None:
    sent = []

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            assert (host, port, timeout) == ("smtp.example.com", 587, 15)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def ehlo(self):
            pass

        def starttls(self, context):
            assert context.check_hostname

        def login(self, username, password):
            assert (username, password) == ("mailer", "smtp-secret")

        def send_message(self, message):
            sent.append(message)

    monkeypatch.setattr(accounts.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setenv("AUDIOGEN_BASE_URL", "https://audiogen.example.com")
    account = accounts.Account("a" * 32, "A User", "user@example.com")
    send_account_email(
        account,
        "single-use-token",
        "verify",
        EmailSettings(
            "smtp.example.com", 587, "mailer", "smtp-secret", "noreply@example.com", False
        ),
    )
    assert len(sent) == 1
    assert sent[0]["To"] == account.email
    assert "https://audiogen.example.com/?verify=single-use-token" in sent[0].get_content()
    assert "smtp-secret" not in sent[0].get_content()


def test_email_delivery_failure_is_explicit(monkeypatch) -> None:
    class BrokenSMTP:
        def __init__(self, *args, **kwargs):
            raise smtplib.SMTPConnectError(421, b"unavailable")

    monkeypatch.setattr(accounts.smtplib, "SMTP", BrokenSMTP)
    monkeypatch.setenv("AUDIOGEN_BASE_URL", "http://localhost:8501")
    account = accounts.Account("b" * 32, "User", "user@example.com")
    with pytest.raises(EmailDeliveryError, match="Could not send account email"):
        send_account_email(
            account,
            "token",
            "reset",
            EmailSettings("smtp.example.com", 587, "", "", "noreply@example.com", False),
        )
