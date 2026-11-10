"""Private audio storage and a small SQLite generation history."""

from __future__ import annotations

import os
import re
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True, slots=True)
class AudioRecord:
    id: str
    filename: str
    voice: str
    output_format: str
    created_at: str
    size_bytes: int


class AudioLibrary:
    def __init__(self, data_dir: Path) -> None:
        self.root = data_dir.expanduser().resolve()
        self.audio_dir = self.root / "audio"
        self.audio_dir.mkdir(parents=True, exist_ok=True)
        self.database = self.root / "history.sqlite3"
        try:
            os.chmod(self.root, 0o700)
            os.chmod(self.audio_dir, 0o700)
        except OSError:
            pass
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS generations (
                    id TEXT PRIMARY KEY,
                    filename TEXT NOT NULL,
                    voice TEXT NOT NULL,
                    output_format TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS voice_profiles (
                    name TEXT PRIMARY KEY,
                    settings_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS pronunciations (
                    term TEXT PRIMARY KEY COLLATE NOCASE,
                    pronunciation TEXT NOT NULL,
                    kind TEXT NOT NULL DEFAULT 'General'
                )
                """
            )
            columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(pronunciations)")
            }
            if "kind" not in columns:
                connection.execute(
                    "ALTER TABLE pronunciations ADD COLUMN kind TEXT NOT NULL DEFAULT 'General'"
                )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    def record(self, filename: str, voice: str, output_format: str, size_bytes: int) -> AudioRecord:
        record = AudioRecord(
            id=uuid.uuid4().hex,
            filename=filename,
            voice=voice,
            output_format=output_format,
            created_at=datetime.now(timezone.utc).isoformat(),
            size_bytes=size_bytes,
        )
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO generations VALUES (?, ?, ?, ?, ?, ?)",
                (
                    record.id,
                    record.filename,
                    record.voice,
                    record.output_format,
                    record.created_at,
                    record.size_bytes,
                ),
            )
        return record

    def recent(self, limit: int = 20) -> list[AudioRecord]:
        if not 1 <= limit <= 100:
            raise ValueError("History limit must be between 1 and 100.")
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM generations ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [AudioRecord(**dict(row)) for row in rows]

    def audio_path(self, record_id: str) -> Path:
        if len(record_id) != 32 or any(char not in "0123456789abcdef" for char in record_id):
            raise ValueError("Invalid audio identifier.")
        with self._connect() as connection:
            row = connection.execute(
                "SELECT filename, output_format FROM generations WHERE id = ?", (record_id,)
            ).fetchone()
        if row is None:
            raise FileNotFoundError("Audio was not found.")
        path = (self.audio_dir / row["filename"]).resolve()
        if path.parent != self.audio_dir or not path.is_file():
            raise FileNotFoundError("Audio file is missing.")
        return path

    def delete(self, record_id: str) -> None:
        path = self.audio_path(record_id)
        with self._connect() as connection:
            connection.execute("DELETE FROM generations WHERE id = ?", (record_id,))
        path.unlink(missing_ok=True)

    def save_voice_profile(self, name: str, settings_json: str) -> None:
        from audiogen_ai.voice_calibration import VoiceProfile

        profile = VoiceProfile.from_json(settings_json)
        safe_name = name.strip()
        if not safe_name or len(safe_name) > 64:
            raise ValueError("Profile name must be between 1 and 64 characters.")
        if profile.name != safe_name:
            from dataclasses import replace

            profile = replace(profile, name=safe_name)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO voice_profiles (name, settings_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    settings_json = excluded.settings_json,
                    updated_at = excluded.updated_at
                """,
                (safe_name, profile.to_json(), datetime.now(timezone.utc).isoformat()),
            )

    def voice_profiles(self) -> dict[str, str]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT name, settings_json FROM voice_profiles ORDER BY name"
            ).fetchall()
        return {row["name"]: row["settings_json"] for row in rows}

    def save_pronunciation(
        self, term: str, pronunciation: str, kind: str = "General"
    ) -> None:
        term, pronunciation = term.strip(), pronunciation.strip()
        if not term or len(term) > 120 or not pronunciation or len(pronunciation) > 300:
            raise ValueError("Word and pronunciation must be non-empty and within size limits.")
        if not re.search(r"[^\W_]", term, flags=re.UNICODE):
            raise ValueError("Enter a word or phrase, not only punctuation.")
        if kind not in {"General", "Hindi", "English", "Acronym", "Technical", "Proper name"}:
            raise ValueError("Choose a supported pronunciation category.")
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO pronunciations (term, pronunciation, kind) VALUES (?, ?, ?)
                ON CONFLICT(term) DO UPDATE SET
                    pronunciation = excluded.pronunciation,
                    kind = excluded.kind
                """,
                (term, pronunciation, kind),
            )

    def pronunciations(self) -> dict[str, str]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT term, pronunciation FROM pronunciations ORDER BY term"
            ).fetchall()
        return {row["term"]: row["pronunciation"] for row in rows}

    def pronunciation_entries(self) -> list[tuple[str, str, str]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT term, pronunciation, kind FROM pronunciations ORDER BY term"
            ).fetchall()
        return [(row["term"], row["pronunciation"], row["kind"]) for row in rows]

    def delete_pronunciation(self, term: str) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM pronunciations WHERE term = ?", (term,))
