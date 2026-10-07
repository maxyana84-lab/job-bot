"""SQLite persistence: which jobs were already sent, and application follow-ups."""

from __future__ import annotations

import datetime as dt
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from .sources import Job

SCHEMA = """
CREATE TABLE IF NOT EXISTS seen_jobs (
    id         INTEGER PRIMARY KEY,
    key        TEXT UNIQUE NOT NULL,
    company    TEXT NOT NULL,
    title      TEXT NOT NULL,
    location   TEXT NOT NULL,
    url        TEXT NOT NULL,
    first_seen TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS applications (
    id          INTEGER PRIMARY KEY,
    company     TEXT NOT NULL,
    role        TEXT NOT NULL,
    url         TEXT NOT NULL DEFAULT '',
    applied_at  TEXT NOT NULL,
    followup_at TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'active'
);
CREATE INDEX IF NOT EXISTS idx_applications_due ON applications(status, followup_at);
"""


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


@dataclass(frozen=True)
class SavedJob:
    id: int
    company: str
    title: str
    location: str
    url: str


@dataclass(frozen=True)
class Application:
    id: int
    company: str
    role: str
    url: str
    applied_at: dt.datetime
    followup_at: dt.datetime
    status: str


class Storage:
    def __init__(self, path: str | Path) -> None:
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    def close(self) -> None:
        self.db.close()

    # --- jobs -----------------------------------------------------------------

    def add_new_jobs(self, jobs: Iterable[Job]) -> list[SavedJob]:
        """Insert jobs not seen before; return only the newly inserted ones."""
        new: list[SavedJob] = []
        now = utcnow().isoformat()
        with self.db:
            for job in jobs:
                cur = self.db.execute(
                    "INSERT OR IGNORE INTO seen_jobs"
                    " (key, company, title, location, url, first_seen) VALUES (?, ?, ?, ?, ?, ?)",
                    (job.key, job.company, job.title, job.location, job.url, now),
                )
                if cur.rowcount:
                    new.append(
                        SavedJob(cur.lastrowid, job.company, job.title, job.location, job.url)
                    )
        return new

    def get_job(self, job_id: int) -> SavedJob | None:
        row = self.db.execute(
            "SELECT id, company, title, location, url FROM seen_jobs WHERE id = ?", (job_id,)
        ).fetchone()
        return SavedJob(**row) if row else None

    # --- applications ---------------------------------------------------------

    def add_application(self, company: str, role: str, url: str, followup_days: int) -> Application:
        now = utcnow()
        followup = now + dt.timedelta(days=followup_days)
        with self.db:
            cur = self.db.execute(
                "INSERT INTO applications (company, role, url, applied_at, followup_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (company, role, url, now.isoformat(), followup.isoformat()),
            )
        return self.get_application(cur.lastrowid)

    def has_application_for_url(self, url: str) -> bool:
        if not url:
            return False
        row = self.db.execute("SELECT 1 FROM applications WHERE url = ?", (url,)).fetchone()
        return row is not None

    def get_application(self, app_id: int) -> Application | None:
        row = self.db.execute("SELECT * FROM applications WHERE id = ?", (app_id,)).fetchone()
        return _application(row) if row else None

    def active_applications(self) -> list[Application]:
        rows = self.db.execute(
            "SELECT * FROM applications WHERE status = 'active' ORDER BY followup_at"
        ).fetchall()
        return [_application(r) for r in rows]

    def due_followups(self, now: dt.datetime | None = None) -> list[Application]:
        now = now or utcnow()
        rows = self.db.execute(
            "SELECT * FROM applications WHERE status = 'active' AND followup_at <= ?"
            " ORDER BY followup_at",
            (now.isoformat(),),
        ).fetchall()
        return [_application(r) for r in rows]

    def snooze(self, app_id: int, days: int) -> None:
        followup = utcnow() + dt.timedelta(days=days)
        with self.db:
            self.db.execute(
                "UPDATE applications SET followup_at = ? WHERE id = ?",
                (followup.isoformat(), app_id),
            )

    def close_application(self, app_id: int) -> None:
        with self.db:
            self.db.execute("UPDATE applications SET status = 'closed' WHERE id = ?", (app_id,))

    def stats(self) -> dict[str, int]:
        q = self.db.execute
        return {
            "jobs_seen": q("SELECT COUNT(*) FROM seen_jobs").fetchone()[0],
            "active": q("SELECT COUNT(*) FROM applications WHERE status='active'").fetchone()[0],
            "closed": q("SELECT COUNT(*) FROM applications WHERE status='closed'").fetchone()[0],
        }


def _application(row: sqlite3.Row) -> Application:
    return Application(
        id=row["id"],
        company=row["company"],
        role=row["role"],
        url=row["url"],
        applied_at=dt.datetime.fromisoformat(row["applied_at"]),
        followup_at=dt.datetime.fromisoformat(row["followup_at"]),
        status=row["status"],
    )
