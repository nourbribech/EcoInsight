"""
One-off migration: rebuilds calibration_profiles without the disk
column, preserving existing machine_model / cpu / ram / baseline /
calibrated_at / notes data.

Run once
"""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "database" / "data" / "hardware.db"


def main() -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("ALTER TABLE calibration_profiles RENAME TO calibration_profiles_old")
        conn.execute("""
            CREATE TABLE calibration_profiles (
                machine_model TEXT PRIMARY KEY,
                cpu_watts_per_percent_usage REAL NOT NULL,
                ram_watts_per_gb_used REAL NOT NULL,
                baseline_watts REAL NOT NULL,
                calibrated_at TEXT,
                notes TEXT
            )
        """)
        conn.execute("""
            INSERT INTO calibration_profiles (
                machine_model, cpu_watts_per_percent_usage,
                ram_watts_per_gb_used, baseline_watts, calibrated_at, notes
            )
            SELECT machine_model, cpu_watts_per_percent_usage,
                   ram_watts_per_gb_used, baseline_watts, calibrated_at, notes
            FROM calibration_profiles_old
        """)
        conn.execute("DROP TABLE calibration_profiles_old")
    print(f"Migrated {DB_PATH} — disk column removed, other data preserved.")


if __name__ == "__main__":
    main()