"""
One-time developer setup script: creates hardware.db with its schema and
seeds it with a PLACEHOLDER calibration row so the rest of the pipeline
can be built and tested before real calibration data exists.

This is a developer tool, not part of the runtime application. In
production, hardware.db ships pre-populated with real calibration data
produced by the scripts in scripts/calibration/.

Run manually: python -m ecoinsight.scripts.setup_hardware_db
"""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "database" / "data" / "hardware.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS calibration_profiles (
    machine_model TEXT PRIMARY KEY,
    cpu_idle_watts REAL NOT NULL,
    cpu_watts_per_percent_usage REAL NOT NULL,
    ram_idle_watts REAL NOT NULL DEFAULT 0,
    ram_watts_per_gb_used REAL NOT NULL,
    disk_idle_watts REAL NOT NULL DEFAULT 0,
    disk_watts_per_mb_per_sec REAL NOT NULL,
    baseline_watts REAL NOT NULL,
    calibrated_at TEXT,
    notes TEXT
);
"""

# NOTE: these numbers are not real calibration data. They exist only so
# the pipeline can be wired end-to-end and tested. Replace once the
# scripts in scripts/calibration/ produce real regression coefficients.
PLACEHOLDER_ROW = (
    "Dell Inc. Latitude 7480",  # machine_model
    3.5,    # cpu_idle_watts
    0.25,   # cpu_watts_per_percent_usage
    0.5,    # ram_idle_watts
    0.15,   # ram_watts_per_gb_used
    0.0,    # disk_idle_watts
    0.05,   # disk_watts_per_mb_per_sec
    5.0,    # baseline_watts
    None,   # calibrated_at
    "PLACEHOLDER - not real calibration data",
)


def main() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.executescript(SCHEMA)
        conn.execute(
            """
            INSERT OR REPLACE INTO calibration_profiles (
                machine_model, cpu_idle_watts, cpu_watts_per_percent_usage,
                ram_idle_watts, ram_watts_per_gb_used,
                disk_idle_watts, disk_watts_per_mb_per_sec,
                baseline_watts, calibrated_at, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            PLACEHOLDER_ROW,
        )
    print(f"hardware.db created/updated at {DB_PATH}")


if __name__ == "__main__":
    main()