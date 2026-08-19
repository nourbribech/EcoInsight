"""
One-off migration: recompute interval_* and cumulative_* in `measurements`.

WHY
The energy estimator used to integrate power across ANY elapsed time,
including the hours a laptop spent suspended with the process still alive.
Resuming from a 38-hour sleep therefore recorded a single tick worth 641 Wh
— more than a normal week of real use. Across the existing history, a
handful of such ticks account for the large majority of all recorded energy.

EnergyEstimator.MAX_INTERVAL_SECONDS now prevents this going forward. This
script repairs the rows written before that guard existed.

WHAT IT DOES
Walks the table in timestamp order and, for each row:

  * If the gap since the previous row exceeds the threshold, the interval is
    invalid — the machine was not being measured — so interval_watt_hours
    and interval_kg_co2eq are set to 0. This matches the estimator's new
    behaviour of dropping, not clamping, such intervals.
  * Otherwise the stored interval values are kept: they were computed from
    the real elapsed time and are correct.
  * cumulative_* is rebuilt as a running sum of the (repaired) intervals.

SESSION BOUNDARIES
cumulative_* means "since this estimator instance started", and the
estimator is recreated on every restart. A restart is visible in the data as
cumulative_watt_hours jumping DOWN. The script preserves that structure
rather than flattening everything into one global total — repairing corrupt
values is its job; redefining what the column means is not.

USAGE
    python -m GreenIT.scripts.migrate_recompute_cumulative           # dry run
    python -m GreenIT.scripts.migrate_recompute_cumulative --apply   # writes

A timestamped copy of the database is made before anything is written.
"""

import argparse
import shutil
import sqlite3
import sys
from datetime import datetime

from GreenIT.database.database import DATABASE_PATH
from GreenIT.estimators.energy import EnergyEstimator

# Same threshold the live estimator uses, so history and future rows are
# repaired and recorded under identical rules.
MAX_INTERVAL_SECONDS = EnergyEstimator.MAX_INTERVAL_SECONDS

# cumulative_watt_hours dropping by more than this means the estimator was
# restarted rather than just accumulating. A tolerance avoids treating float
# noise as a session boundary.
SESSION_RESET_TOLERANCE_WH = 1e-9


def recompute(rows: list[sqlite3.Row]) -> tuple[list[tuple], dict]:
    """
    Returns (updates, stats). `updates` is a list of
    (interval_wh, cumulative_wh, interval_kg, cumulative_kg, id) tuples
    ready for executemany.
    """
    updates = []
    stats = {
        "rows": len(rows),
        "sessions": 0,
        "zeroed_intervals": 0,
        "energy_removed_wh": 0.0,
        "old_total_wh": 0.0,
        "new_total_wh": 0.0,
    }

    running_wh = 0.0
    running_kg = 0.0
    previous_timestamp = None
    previous_cumulative = None

    for row in rows:
        timestamp = datetime.fromisoformat(row["timestamp"])

        is_new_session = (
            previous_cumulative is None
            or row["cumulative_watt_hours"] < previous_cumulative - SESSION_RESET_TOLERANCE_WH
        )

        if is_new_session:
            stats["sessions"] += 1
            running_wh = 0.0
            running_kg = 0.0
            # A session's first row has no previous reading to integrate
            # from, exactly like the estimator's warm-up tick.
            previous_timestamp = None

        interval_wh = row["interval_watt_hours"]
        interval_kg = row["interval_kg_co2eq"]

        if previous_timestamp is None:
            interval_wh = 0.0
            interval_kg = 0.0
        else:
            gap_seconds = (timestamp - previous_timestamp).total_seconds()
            if gap_seconds > MAX_INTERVAL_SECONDS:
                stats["zeroed_intervals"] += 1
                stats["energy_removed_wh"] += interval_wh
                interval_wh = 0.0
                interval_kg = 0.0

        running_wh += interval_wh
        running_kg += interval_kg

        stats["old_total_wh"] += row["interval_watt_hours"]
        stats["new_total_wh"] += interval_wh

        updates.append((interval_wh, running_wh, interval_kg, running_kg, row["id"]))

        previous_timestamp = timestamp
        previous_cumulative = row["cumulative_watt_hours"]

    return updates, stats


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write the changes (default is a dry run that only reports)",
    )
    args = parser.parse_args()

    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    rows = connection.execute(
        "SELECT id, timestamp, interval_watt_hours, cumulative_watt_hours, "
        "interval_kg_co2eq, cumulative_kg_co2eq "
        "FROM measurements ORDER BY timestamp ASC"
    ).fetchall()

    if not rows:
        print("No measurements to migrate.")
        return

    updates, stats = recompute(rows)

    print(f"Database:            {DATABASE_PATH}")
    print(f"Rows examined:       {stats['rows']:,}")
    print(f"Estimator sessions:  {stats['sessions']}")
    print(f"Intervals zeroed:    {stats['zeroed_intervals']}  "
          f"(gaps longer than {MAX_INTERVAL_SECONDS:.0f}s)")
    print()
    print(f"Energy before:       {stats['old_total_wh']:,.1f} Wh")
    print(f"Energy after:        {stats['new_total_wh']:,.1f} Wh")
    print(f"Phantom energy:      {stats['energy_removed_wh']:,.1f} Wh "
          f"({100 * stats['energy_removed_wh'] / stats['old_total_wh']:.1f}% of the old total)")

    if not args.apply:
        print("\nDRY RUN — nothing written. Re-run with --apply to commit.")
        return

    backup_path = DATABASE_PATH.with_suffix(
        f".backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}.db"
    )
    shutil.copy2(DATABASE_PATH, backup_path)
    print(f"\nBackup written to:   {backup_path}")

    connection.executemany(
        """
        UPDATE measurements
        SET interval_watt_hours   = ?,
            cumulative_watt_hours = ?,
            interval_kg_co2eq     = ?,
            cumulative_kg_co2eq   = ?
        WHERE id = ?
        """,
        updates,
    )
    connection.commit()
    connection.close()

    print(f"Updated {len(updates):,} rows.")


if __name__ == "__main__":
    sys.exit(main())
