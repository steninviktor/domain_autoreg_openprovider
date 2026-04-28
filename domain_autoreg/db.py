from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Iterable, Iterator

from .domain import DomainName, parse_domain


@dataclass(frozen=True)
class DomainRecord:
    id: int
    fqdn: str
    name: str
    extension: str
    status: str
    attempts: int
    last_check_at: str | None
    next_attempt_at: str | None
    last_error: str | None
    openprovider_domain_id: int | None
    registered_at: str | None

    def as_domain_name(self) -> DomainName:
        return DomainName(fqdn=self.fqdn, name=self.name, extension=self.extension, id=self.id)


def init_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS domains (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fqdn TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                extension TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                attempts INTEGER NOT NULL DEFAULT 0,
                last_check_at TEXT,
                next_attempt_at TEXT,
                last_error TEXT,
                openprovider_domain_id INTEGER,
                registered_at TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS domain_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                domain_id INTEGER,
                fqdn TEXT NOT NULL,
                event_type TEXT NOT NULL,
                message TEXT,
                payload TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(domain_id) REFERENCES domains(id)
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


class DomainRepository:
    def __init__(self, path: Path):
        self.path = path

    def import_domains(self, domains: Iterable[str]) -> int:
        imported = 0
        with self._connect() as conn:
            for raw in domains:
                if not raw.strip():
                    continue
                domain = parse_domain(raw)
                cursor = conn.execute(
                    """
                    INSERT OR IGNORE INTO domains (fqdn, name, extension)
                    VALUES (?, ?, ?)
                    """,
                    (domain.fqdn, domain.name, domain.extension),
                )
                if cursor.rowcount:
                    imported += 1
                    self._event(conn, None, domain.fqdn, "imported", "Domain imported", None)
        return imported

    def get_due_domains(self, limit: int) -> list[DomainRecord]:
        now = _now()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM domains
                WHERE status IN ('active', 'registration_failed')
                  AND (next_attempt_at IS NULL OR next_attempt_at <= ?)
                ORDER BY id
                LIMIT ?
                """,
                (now, limit),
            ).fetchall()
        return [_record(row) for row in rows]

    def list_domains(self, status: str | None = None) -> list[DomainRecord]:
        with self._connect() as conn:
            if status:
                rows = conn.execute("SELECT * FROM domains WHERE status = ? ORDER BY id", (status,)).fetchall()
            else:
                rows = conn.execute("SELECT * FROM domains ORDER BY id").fetchall()
        return [_record(row) for row in rows]

    def mark_checked(self, domain_id: int, result: dict) -> None:
        with self._connect() as conn:
            row = conn.execute("SELECT fqdn FROM domains WHERE id = ?", (domain_id,)).fetchone()
            fqdn = row["fqdn"] if row else ""
            conn.execute(
                """
                UPDATE domains
                SET status = 'active', last_check_at = ?, last_error = NULL, updated_at = ?
                WHERE id = ?
                """,
                (_now(), _now(), domain_id),
            )
            self._event(conn, domain_id, fqdn, "checked", f"Status: {result.get('status')}", result)

    def mark_registered(self, domain_id: int, openprovider_domain_id: int | None, response: dict) -> None:
        now = _now()
        with self._connect() as conn:
            row = conn.execute("SELECT fqdn FROM domains WHERE id = ?", (domain_id,)).fetchone()
            fqdn = row["fqdn"] if row else ""
            conn.execute(
                """
                UPDATE domains
                SET status = 'registered',
                    openprovider_domain_id = ?,
                    registered_at = ?,
                    last_error = NULL,
                    next_attempt_at = NULL,
                    updated_at = ?
                WHERE id = ?
                """,
                (openprovider_domain_id, now, now, domain_id),
            )
            self._event(conn, domain_id, fqdn, "registered", "Domain registered", response)

    def mark_registration_failed(self, domain_id: int, message: str, cooldown_seconds: int) -> None:
        now_dt = datetime.now(UTC)
        next_attempt = (now_dt + timedelta(seconds=cooldown_seconds)).isoformat()
        now = now_dt.isoformat()
        with self._connect() as conn:
            row = conn.execute("SELECT fqdn FROM domains WHERE id = ?", (domain_id,)).fetchone()
            fqdn = row["fqdn"] if row else ""
            conn.execute(
                """
                UPDATE domains
                SET status = 'registration_failed',
                    attempts = attempts + 1,
                    last_error = ?,
                    next_attempt_at = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (message, next_attempt, now, domain_id),
            )
            self._event(conn, domain_id, fqdn, "registration_failed", message, {"next_attempt_at": next_attempt})

    def log_event(self, domain_id: int | None, fqdn: str, event_type: str, message: str, payload: dict | None = None) -> None:
        with self._connect() as conn:
            self._event(conn, domain_id, fqdn, event_type, message, payload)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _event(
        self,
        conn: sqlite3.Connection,
        domain_id: int | None,
        fqdn: str,
        event_type: str,
        message: str,
        payload: dict | None,
    ) -> None:
        conn.execute(
            """
            INSERT INTO domain_events (domain_id, fqdn, event_type, message, payload)
            VALUES (?, ?, ?, ?, ?)
            """,
            (domain_id, fqdn, event_type, message, json.dumps(payload or {}, ensure_ascii=False)),
        )


def _record(row: sqlite3.Row) -> DomainRecord:
    return DomainRecord(
        id=row["id"],
        fqdn=row["fqdn"],
        name=row["name"],
        extension=row["extension"],
        status=row["status"],
        attempts=row["attempts"],
        last_check_at=row["last_check_at"],
        next_attempt_at=row["next_attempt_at"],
        last_error=row["last_error"],
        openprovider_domain_id=row["openprovider_domain_id"],
        registered_at=row["registered_at"],
    )


def _now() -> str:
    return datetime.now(UTC).isoformat()
