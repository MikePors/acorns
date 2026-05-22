#!/usr/bin/env python3
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

# Allow tests (and advanced users) to redirect the DB via env var.
DB_PATH = Path(os.environ.get("TRACKER_DB", str(Path.home() / ".claude-tracker" / "tracker.db")))

HISTORY_LIMIT = 100
MAX_NAME_LEN = 256
MAX_PROJECT_LEN = 512
MAX_NOTES_LEN = 1024


# ── Helpers ────────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fmt_seconds(s: int) -> str:
    if s < 60:
        return f"{s}s"
    elif s < 3600:
        return f"{s // 60}m"
    elif s < 86400:
        return f"{s // 3600}h{(s % 3600) // 60:02d}m"
    else:
        return f"{s // 86400}d{(s % 86400) // 3600}h"


def age(iso: str | None) -> str:
    if not iso:
        return ""
    try:
        t = datetime.fromisoformat(iso)
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        return _fmt_seconds(int((datetime.now(timezone.utc) - t).total_seconds()))
    except Exception:
        return "?"


def duration_between(a_iso: str | None, b_iso: str | None) -> str:
    if not a_iso or not b_iso:
        return "?"
    try:
        a = datetime.fromisoformat(a_iso)
        b = datetime.fromisoformat(b_iso)
        if a.tzinfo is None:
            a = a.replace(tzinfo=timezone.utc)
        if b.tzinfo is None:
            b = b.replace(tzinfo=timezone.utc)
        return _fmt_seconds(abs(int((b - a).total_seconds())))
    except Exception:
        return "?"


def _validate(name: str = "", project: str = "", notes: str = "") -> None:
    if len(name) > MAX_NAME_LEN:
        raise ValueError(f"name exceeds {MAX_NAME_LEN} characters")
    if len(project) > MAX_PROJECT_LEN:
        raise ValueError(f"project exceeds {MAX_PROJECT_LEN} characters")
    if len(notes) > MAX_NOTES_LEN:
        raise ValueError(f"notes exceeds {MAX_NOTES_LEN} characters")


# ── Database ───────────────────────────────────────────────────────────────────

@contextmanager
def _db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    DB_PATH.parent.chmod(0o700)
    # Restrict file mode at creation time by narrowing the umask.
    old_umask = os.umask(0o077)
    try:
        con = sqlite3.connect(str(DB_PATH), timeout=10)
    finally:
        os.umask(old_umask)
    # Correct permissions on pre-existing files created under a loose umask.
    DB_PATH.chmod(0o600)
    con.execute("PRAGMA journal_mode=WAL")
    # executescript always commits first; safe to use for DDL init.
    con.executescript("""
        CREATE TABLE IF NOT EXISTS instances (
            name            TEXT PRIMARY KEY,
            current_project TEXT,
            notes           TEXT NOT NULL DEFAULT '',
            assigned_at     TEXT
        );
        CREATE TABLE IF NOT EXISTS history (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            instance_name TEXT NOT NULL
                          REFERENCES instances(name) ON DELETE CASCADE,
            project       TEXT NOT NULL,
            notes         TEXT NOT NULL DEFAULT '',
            assigned_at   TEXT,
            completed_at  TEXT
        );
    """)
    # Must be set per-connection after DDL so FK enforcement is active for DML.
    con.execute("PRAGMA foreign_keys=ON")
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def _trim_history(con: sqlite3.Connection, name: str) -> None:
    con.execute(
        "DELETE FROM history WHERE instance_name = ? AND id NOT IN "
        "(SELECT id FROM history WHERE instance_name = ? ORDER BY id DESC LIMIT ?)",
        (name, name, HISTORY_LIMIT),
    )


# ── Public API ─────────────────────────────────────────────────────────────────

def load() -> dict:
    with _db() as con:
        instances: dict = {}
        for name, current_project, notes, assigned_at in con.execute(
            "SELECT name, current_project, notes, assigned_at FROM instances ORDER BY name"
        ):
            rows = con.execute(
                "SELECT project, notes, assigned_at, completed_at FROM history "
                "WHERE instance_name = ? ORDER BY id",
                (name,),
            ).fetchall()
            instances[name] = {
                "current_project": current_project,
                "notes": notes or "",
                "assigned_at": assigned_at,
                "history": [
                    {
                        "project": r[0],
                        "notes": r[1] or "",
                        "assigned_at": r[2],
                        "completed_at": r[3],
                    }
                    for r in rows
                ],
            }
        return {"instances": instances}


def add(name: str) -> bool:
    """Register a new instance. Returns False if it already exists."""
    _validate(name=name)
    with _db() as con:
        try:
            con.execute("INSERT INTO instances (name) VALUES (?)", (name,))
            return True
        except sqlite3.IntegrityError:
            return False


def remove(name: str) -> bool:
    """Remove an instance and its full history. Returns False if not found."""
    _validate(name=name)
    with _db() as con:
        cur = con.execute("DELETE FROM instances WHERE name = ?", (name,))
        if cur.rowcount == 0:
            return False
        # Belt-and-suspenders: manual delete handles DBs that pre-date the FK constraint.
        con.execute("DELETE FROM history WHERE instance_name = ?", (name,))
        return True


def exists(name: str) -> bool:
    with _db() as con:
        return (
            con.execute("SELECT 1 FROM instances WHERE name = ?", (name,)).fetchone()
            is not None
        )


def assign(name: str, project: str, notes: str = "") -> bool:
    """Assign project to instance. Creates the instance if it doesn't exist.
    Returns True if the instance was newly created, False if it already existed."""
    _validate(name=name, project=project, notes=notes)
    with _db() as con:
        row = con.execute(
            "SELECT current_project, notes, assigned_at FROM instances WHERE name = ?",
            (name,),
        ).fetchone()
        if row is None:
            con.execute(
                "INSERT INTO instances (name, current_project, notes, assigned_at) "
                "VALUES (?, ?, ?, ?)",
                (name, project, notes, _now()),
            )
            return True
        if row[0]:
            con.execute(
                "INSERT INTO history "
                "(instance_name, project, notes, assigned_at, completed_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (name, row[0], row[1], row[2], _now()),
            )
            _trim_history(con, name)
        con.execute(
            "UPDATE instances SET current_project = ?, notes = ?, assigned_at = ? "
            "WHERE name = ?",
            (project, notes, _now(), name),
        )
        return False


def done(name: str) -> bool:
    """Mark active project done. Returns False if instance is idle or not found."""
    _validate(name=name)
    with _db() as con:
        row = con.execute(
            "SELECT current_project, notes, assigned_at FROM instances WHERE name = ?",
            (name,),
        ).fetchone()
        if not row or not row[0]:
            return False
        con.execute(
            "INSERT INTO history "
            "(instance_name, project, notes, assigned_at, completed_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (name, row[0], row[1], row[2], _now()),
        )
        _trim_history(con, name)
        con.execute(
            "UPDATE instances SET current_project = NULL, notes = '', assigned_at = NULL "
            "WHERE name = ?",
            (name,),
        )
        return True
