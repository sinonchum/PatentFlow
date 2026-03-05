from __future__ import annotations

import os
from pathlib import Path
import sqlite3
import time
from typing import Optional


_DEFAULT_DB_PATH = Path("data/profiles.db")


class LocalMemoryManager:
    def __init__(self, *, db_path: Optional[str] = None) -> None:
        self._db_path = Path(db_path) if db_path else _DEFAULT_DB_PATH
        self._ensure_parent_dir()
        self._init_db()

    def _ensure_parent_dir(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            str(self._db_path),
            check_same_thread=False,
            timeout=10,
            isolation_level=None,
        )
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA busy_timeout=10000;")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS attorney_profiles (
                    attorney_id TEXT PRIMARY KEY,
                    preferences TEXT NOT NULL DEFAULT '',
                    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """.strip()
            )

    def _run_with_retry(self, fn, *, retries: int = 5) -> bool:
        delay = 0.05
        for attempt in range(retries):
            try:
                fn()
                return True
            except sqlite3.OperationalError as e:
                msg = str(e).lower()
                if "locked" in msg or "busy" in msg:
                    time.sleep(delay)
                    delay = min(1.0, delay * 2)
                    continue
                raise
            except sqlite3.DatabaseError:
                if attempt >= retries - 1:
                    return False
                time.sleep(delay)
                delay = min(1.0, delay * 2)
        return False

    def get_preferences(self, attorney_id: str) -> str:
        attorney_id = (attorney_id or "").strip()
        if not attorney_id:
            return ""

        with self._connect() as conn:
            cur = conn.execute(
                "SELECT preferences FROM attorney_profiles WHERE attorney_id = ?",
                (attorney_id,),
            )
            row = cur.fetchone()
            if not row:
                return ""
            prefs = row[0]
            return str(prefs or "")

    def add_preference(self, attorney_id: str, new_rule: str) -> bool:
        attorney_id = (attorney_id or "").strip()
        rule = (new_rule or "").strip()
        if not attorney_id or not rule:
            return False

        bullet = rule
        if not bullet.startswith("-"):
            bullet = f"- {bullet}"

        def _op() -> None:
            with self._connect() as conn:
                cur = conn.execute(
                    "SELECT preferences FROM attorney_profiles WHERE attorney_id = ?",
                    (attorney_id,),
                )
                row = cur.fetchone()
                existing = str(row[0] or "") if row else ""

                if existing.strip() == "":
                    updated = bullet
                else:
                    sep = "\n" if existing.endswith("\n") else "\n"
                    updated = existing + sep + bullet

                conn.execute(
                    """
                    INSERT INTO attorney_profiles (attorney_id, preferences, updated_at)
                    VALUES (?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(attorney_id) DO UPDATE SET
                        preferences = excluded.preferences,
                        updated_at = CURRENT_TIMESTAMP
                    """.strip(),
                    (attorney_id, updated),
                )

        return self._run_with_retry(_op)
