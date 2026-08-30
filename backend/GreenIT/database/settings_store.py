"""
User-chosen settings, stored as JSON values in a key/value table.

WHY A TABLE AND NOT A CONFIG FILE
The agent runs as a scheduled task under the user's account while the
dashboard runs in a browser; a settings file would have to be written by the
API and read by the loop, with no locking between them. SQLite already
mediates exactly that between these two processes for every other table, so
using it here costs one table and removes a whole class of race.

WHY VALUES ARE JSON
So a setting can later be a number, a string, a list of working hours, or an
object, without a schema migration each time. The cost is that callers must
validate what comes back - a value written by an older build, or hand-edited
in a SQLite browser, can be any shape at all. Validation lives with the
feature that owns the setting (see estimators/goals.normalise_target), not
here: this module knows how to persist, not what is reasonable.

Everything degrades to the default rather than raising. A dashboard that
500s because a preference row is malformed is worse than one that quietly
uses 15%.
"""

import json
import sqlite3
from datetime import datetime
from typing import Any

from GreenIT.database.database import get_connection


def _ensure_table(cursor: sqlite3.Cursor) -> None:
    """
    Created lazily rather than in initialize_database().

    The API process does not call initialize_database() - the agent does - so
    a table created only there would be missing whenever somebody starts the
    dashboard on a fresh checkout without the agent. This runs on every
    access and costs microseconds.
    """
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )


def get(key: str, default: Any = None) -> Any:
    connection = get_connection()
    try:
        cursor = connection.cursor()
        _ensure_table(cursor)
        row = cursor.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
    finally:
        connection.close()

    if row is None:
        return default

    try:
        return json.loads(row["value"])
    except (json.JSONDecodeError, TypeError):
        # A corrupt row is treated as an absent one. The alternative is
        # propagating a parse error out of every endpoint that reads a
        # preference, which turns a cosmetic problem into an outage.
        return default


def set(key: str, value: Any) -> None:
    connection = get_connection()
    try:
        cursor = connection.cursor()
        _ensure_table(cursor)
        cursor.execute(
            "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, "
            "                               updated_at = excluded.updated_at",
            (key, json.dumps(value), datetime.now().isoformat()),
        )
        connection.commit()
    finally:
        connection.close()


def updated_at(key: str) -> str | None:
    """When the user last changed this setting, or None if they never have."""
    connection = get_connection()
    try:
        cursor = connection.cursor()
        _ensure_table(cursor)
        row = cursor.execute(
            "SELECT updated_at FROM settings WHERE key = ?", (key,)
        ).fetchone()
    finally:
        connection.close()

    return row["updated_at"] if row else None
