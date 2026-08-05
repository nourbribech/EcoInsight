"""
Shared write helper for calibration scripts. Updates one or more
calibration_profiles columns for a given machine, leaving every other
column untouched — so a single component can be recalibrated (or set
from a literature value) without rerunning the other sweeps.
"""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

HARDWARE_DB_PATH = Path(__file__).resolve().parent.parent.parent / "database" / "data" / "hardware.db"


def update_fields(machine_key: str, fields: dict, notes: str = None) -> None:
    """
    fields: e.g. {"ram_watts_per_gb_used": 0.375}. Keys must be real
    calibration_profiles column names. Always also updates calibrated_at.
    """
    set_clauses = ", ".join(f"{column} = ?" for column in fields)
    values = list(fields.values())

    sql = f"UPDATE calibration_profiles SET {set_clauses}, calibrated_at = ?"
    values.append(datetime.now(timezone.utc).isoformat())

    if notes is not None:
        sql += ", notes = ?"
        values.append(notes)

    sql += " WHERE machine_model = ?"
    values.append(machine_key)

    with sqlite3.connect(HARDWARE_DB_PATH) as conn:
        cursor = conn.execute(sql, values)
        if cursor.rowcount == 0:
            raise RuntimeError(f"No existing row for machine model {machine_key!r}.")