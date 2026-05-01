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
    created_at: str | None = None
    display_status: str | None = None

    def as_domain_name(self) -> DomainName:
        return DomainName(fqdn=self.fqdn, name=self.name, extension=self.extension, id=self.id)


@dataclass(frozen=True)
class DomainEvent:
    id: int
    domain_id: int | None
    fqdn: str
    event_type: str
    message: str | None
    payload: dict
    created_at: str


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
        _normalize_domain_parts(conn)
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

    def get_due_domains(self, limit: int | None = None) -> list[DomainRecord]:
        now = _now()
        query = """
            SELECT * FROM domains
            WHERE status IN ('active', 'registration_failed')
              AND (next_attempt_at IS NULL OR next_attempt_at <= ?)
            ORDER BY id
        """
        params: list[object] = [now]
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [_record(row) for row in rows]

    def list_domains(self, status: str | None = None) -> list[DomainRecord]:
        with self._connect() as conn:
            if status:
                rows = conn.execute("SELECT * FROM domains WHERE status = ? ORDER BY id", (status,)).fetchall()
            else:
                rows = conn.execute("SELECT * FROM domains ORDER BY id").fetchall()
        return [_record(row) for row in rows]

    def list_domains_for_gui(self, view_filter: str | None = None) -> list[DomainRecord]:
        filter_name = (view_filter or "all").strip().lower()
        if filter_name in {"", "all"}:
            return self._list_domains_with_display_status()
        if filter_name == "registered":
            return self._list_domains_with_display_status("registered")
        if filter_name == "errors":
            return self._list_domains_with_display_status("registration_failed")

        with self._connect() as conn:
            if filter_name == "unchecked":
                rows = conn.execute(
                    """
                    SELECT * FROM domains
                    WHERE status = 'active'
                      AND last_check_at IS NULL
                      AND (
                        SELECT event_type FROM domain_events
                        WHERE domain_id = domains.id
                        ORDER BY id DESC
                        LIMIT 1
                      ) IS NULL
                    ORDER BY id
                    """
                ).fetchall()
            elif filter_name == "busy":
                rows = conn.execute(
                    """
                    SELECT * FROM domains
                    WHERE status = 'active'
                      AND last_check_at IS NOT NULL
                      AND (
                        SELECT event_type FROM domain_events
                        WHERE domain_id = domains.id
                        ORDER BY id DESC
                        LIMIT 1
                      ) = 'checked'
                    ORDER BY id
                    """
                ).fetchall()
            elif filter_name == "free":
                rows = conn.execute(
                    """
                    SELECT * FROM domains
                    WHERE status = 'active'
                      AND (
                        SELECT event_type FROM domain_events
                        WHERE domain_id = domains.id
                        ORDER BY id DESC
                        LIMIT 1
                      ) IN ('free', 'dry_run', 'manual_registration_required')
                    ORDER BY id
                    """
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM domains ORDER BY id").fetchall()
        return self._with_display_status([_record(row) for row in rows])

    def _list_domains_with_display_status(self, status: str | None = None) -> list[DomainRecord]:
        return self._with_display_status(self.list_domains(status))

    def _with_display_status(self, domains: list[DomainRecord]) -> list[DomainRecord]:
        if not domains:
            return []
        latest_events = self._latest_event_types([domain.id for domain in domains])
        return [
            DomainRecord(
                id=domain.id,
                fqdn=domain.fqdn,
                name=domain.name,
                extension=domain.extension,
                status=domain.status,
                attempts=domain.attempts,
                last_check_at=domain.last_check_at,
                next_attempt_at=domain.next_attempt_at,
                last_error=domain.last_error,
                openprovider_domain_id=domain.openprovider_domain_id,
                registered_at=domain.registered_at,
                created_at=domain.created_at,
                display_status=_display_status(domain, latest_events.get(domain.id)),
            )
            for domain in domains
        ]

    def _latest_event_types(self, domain_ids: list[int]) -> dict[int, str]:
        placeholders = ", ".join("?" for _ in domain_ids)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT domain_id, event_type
                FROM domain_events
                WHERE id IN (
                  SELECT MAX(id)
                  FROM domain_events
                  WHERE domain_id IN ({placeholders})
                  GROUP BY domain_id
                )
                """,
                domain_ids,
            ).fetchall()
        return {int(row["domain_id"]): row["event_type"] for row in rows if row["domain_id"] is not None}

    def list_domain_events(
        self,
        limit: int = 100,
        fqdn: str | None = None,
        event_type: str | None = None,
    ) -> list[DomainEvent]:
        clauses: list[str] = []
        params: list[object] = []
        if fqdn:
            clauses.append("fqdn = ?")
            params.append(fqdn.strip().lower())
        if event_type:
            clauses.append("event_type = ?")
            params.append(event_type.strip())
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(max(1, int(limit)))
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM domain_events
                {where}
                ORDER BY id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [_event_record(row) for row in rows]

    def has_domain_event(self, domain_id: int, event_type: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT 1
                FROM domain_events
                WHERE domain_id = ?
                  AND event_type = ?
                LIMIT 1
                """,
                (domain_id, event_type.strip()),
            ).fetchone()
        return row is not None

    def delete_domains(self, domain_ids: Iterable[int]) -> int:
        ids = [int(domain_id) for domain_id in domain_ids]
        if not ids:
            return 0
        placeholders = ", ".join("?" for _ in ids)
        with self._connect() as conn:
            rows = conn.execute(f"SELECT fqdn FROM domains WHERE id IN ({placeholders})", ids).fetchall()
            fqdns = [row["fqdn"] for row in rows]
            if fqdns:
                fqdn_placeholders = ", ".join("?" for _ in fqdns)
                conn.execute(
                    f"DELETE FROM domain_events WHERE domain_id IN ({placeholders}) OR fqdn IN ({fqdn_placeholders})",
                    ids + fqdns,
                )
            else:
                conn.execute(f"DELETE FROM domain_events WHERE domain_id IN ({placeholders})", ids)
            cursor = conn.execute(f"DELETE FROM domains WHERE id IN ({placeholders})", ids)
            return int(cursor.rowcount)

    def delete_all_domains(self) -> int:
        with self._connect() as conn:
            total = conn.execute("SELECT COUNT(*) AS count FROM domains").fetchone()["count"]
            conn.execute("DELETE FROM domain_events")
            conn.execute("DELETE FROM domains")
            return int(total)

    def delete_domains_imported_before_days(self, days: int, now: str | None = None) -> int:
        if days < 1:
            raise ValueError("days must be at least 1")
        now_dt = datetime.fromisoformat((now or _now()).replace("Z", "+00:00"))
        if now_dt.tzinfo is None:
            now_dt = now_dt.replace(tzinfo=UTC)
        cutoff = (now_dt.astimezone(UTC) - timedelta(days=days)).isoformat()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id FROM domains
                WHERE status = 'active'
                  AND created_at <= ?
                  AND (
                    SELECT event_type FROM domain_events
                    WHERE domain_id = domains.id
                    ORDER BY id DESC
                    LIMIT 1
                  ) = 'checked'
                ORDER BY id
                """,
                (cutoff,),
            ).fetchall()
            ids = [row["id"] for row in rows]
        return self.delete_domains(ids)

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
    parsed = parse_domain(row["fqdn"])
    return DomainRecord(
        id=row["id"],
        fqdn=row["fqdn"],
        name=parsed.name,
        extension=parsed.extension,
        status=row["status"],
        attempts=row["attempts"],
        last_check_at=row["last_check_at"],
        next_attempt_at=row["next_attempt_at"],
        last_error=row["last_error"],
        openprovider_domain_id=row["openprovider_domain_id"],
        registered_at=row["registered_at"],
        created_at=row["created_at"],
    )


def _display_status(domain: DomainRecord, latest_event_type: str | None) -> str:
    if domain.status == "registered":
        return "зарегистрирован"
    if domain.status == "registration_failed":
        return "ошибка"
    if latest_event_type in {"free", "dry_run", "manual_registration_required"}:
        return "свободен"
    if latest_event_type == "checked" or domain.last_check_at:
        return "занят"
    return "не проверен"


def _normalize_domain_parts(conn: sqlite3.Connection) -> None:
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT id, fqdn, name, extension FROM domains").fetchall()
    for row in rows:
        try:
            parsed = parse_domain(row["fqdn"])
        except ValueError:
            continue
        if row["name"] == parsed.name and row["extension"] == parsed.extension:
            continue
        conn.execute(
            """
            UPDATE domains
            SET name = ?, extension = ?, updated_at = ?
            WHERE id = ?
            """,
            (parsed.name, parsed.extension, _now(), row["id"]),
        )


def _event_record(row: sqlite3.Row) -> DomainEvent:
    try:
        payload = json.loads(row["payload"] or "{}")
    except json.JSONDecodeError:
        payload = {}
    return DomainEvent(
        id=row["id"],
        domain_id=row["domain_id"],
        fqdn=row["fqdn"],
        event_type=row["event_type"],
        message=row["message"],
        payload=payload,
        created_at=row["created_at"],
    )


def _now() -> str:
    return datetime.now(UTC).isoformat()
