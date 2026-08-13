"""
Manual verification for RecommendationEngine's trigger/reminder logic,
using fabricated timestamps so we don't have to wait 3 real days + 1.5h
to see if it works. Uses the real save_telemetry_snapshot() write path
and a temp, isolated database — never touches the live ecoinsight.db
that's currently accumulating real data.

Throwaway script, same spirit as check_telemetry.py — not a permanent
test suite.
"""

import random
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from GreenIT.database import database
from GreenIT.estimators import recommendations as recs_module
from GreenIT.estimators.recommendations import RecommendationEngine
from GreenIT.models.runtime.cpu_runtime import CpuRuntimeMetrics
from GreenIT.models.runtime.memory_runtime import MemoryRuntimeMetrics
from GreenIT.models.runtime.disk_runtime import DiskRuntimeMetrics
from GreenIT.models.runtime.network_runtime import NetworkRuntimeMetrics
from GreenIT.models.snapshot import SystemMetricsSnapshot

random.seed(42)

_passed = 0
_failed = 0


def check(condition: bool, description: str) -> None:
    global _passed, _failed
    if condition:
        _passed += 1
        print(f"  PASS - {description}")
    else:
        _failed += 1
        print(f"  FAIL - {description}")


def make_snapshot(timestamp: datetime, cpu_pct: float, ram_pct: float) -> SystemMetricsSnapshot:
    total_ram_bytes = 16_000_000_000
    return SystemMetricsSnapshot(
        cpu=CpuRuntimeMetrics(
            usage_percent=cpu_pct,
            actual_frequency_mhz=None,
            base_frequency_mhz=None,
            processor_utility_percent=None,
            processor_performance_percent=None,
            percent_of_max_frequency=None,
        ),
        memory=MemoryRuntimeMetrics(
            used_bytes=int(ram_pct / 100 * total_ram_bytes),
            total_bytes=total_ram_bytes,
            available_bytes=int((1 - ram_pct / 100) * total_ram_bytes),
            usage_percent=ram_pct,
        ),
        disk=DiskRuntimeMetrics(read_bytes_per_second=0.0, write_bytes_per_second=0.0),
        network=NetworkRuntimeMetrics(bytes_sent_per_second=0.0, bytes_received_per_second=0.0),
        timestamp=timestamp,
    )


def tick(engine: RecommendationEngine, snapshot: SystemMetricsSnapshot) -> list:
    """Mirrors _maybe_save_telemetry: save first, then evaluate — same order as production."""
    database.save_telemetry_snapshot(snapshot)
    return engine.evaluate(snapshot)


def seed_normal_history(start: datetime, num_rows: int, interval_minutes: int) -> datetime:
    """Writes quiet baseline data (CPU ~20%, RAM ~40%, small noise) ending at `start`."""
    ts = start - timedelta(minutes=interval_minutes * num_rows)
    for _ in range(num_rows):
        snapshot = make_snapshot(
            timestamp=ts,
            cpu_pct=20 + random.uniform(-3, 3),
            ram_pct=40 + random.uniform(-2, 2),
        )
        database.save_telemetry_snapshot(snapshot)
        ts += timedelta(minutes=interval_minutes)
    return ts  # last seeded timestamp


def main():
    test_db_path = Path(tempfile.gettempdir()) / "ecoinsight_test.db"
    if test_db_path.exists():
        test_db_path.unlink()
    database.DATABASE_PATH = test_db_path
    database.initialize_database()

    recs_module.MINIMUM_DATA_WINDOW_DAYS = 0  # skip the 3-day cold-start gate for this test

    engine = RecommendationEngine()

    print("Seeding 4 days of quiet baseline history...")
    last_seed_ts = seed_normal_history(
        start=datetime(2026, 8, 12, 9, 0, 0),
        num_rows=int(4 * 24 * 60 / 2),  # 4 days at 2-min intervals
        interval_minutes=2,
    )

    print("\nScenario 1: normal reading, should not trigger")
    t = last_seed_ts + timedelta(minutes=2)
    recs = tick(engine, make_snapshot(t, cpu_pct=21, ram_pct=41))
    check(len(recs) == 0, "no recommendation for a normal reading")

    print("\nScenario 2: first crossing into elevated, should notify")
    t += timedelta(minutes=2)
    recs = tick(engine, make_snapshot(t, cpu_pct=95, ram_pct=41))
    check(len(recs) == 1, "exactly one recommendation on first crossing")
    if recs:
        check(recs[0].metric == "cpu_usage_percent", "recommendation is for cpu_usage_percent")
        check("unusually high" in recs[0].message, "message reads as a first notification")

    print("\nScenario 3: still elevated, only 2 min since last notify, should stay silent")
    t += timedelta(minutes=2)
    recs = tick(engine, make_snapshot(t, cpu_pct=96, ram_pct=41))
    check(len(recs) == 0, "no reminder before REMINDER_INTERVAL_HOURS has passed")

    print("\nScenario 4: still elevated, 1h40 since last notify, should remind")
    t += timedelta(hours=1, minutes=40)
    recs = tick(engine, make_snapshot(t, cpu_pct=96, ram_pct=41))
    check(len(recs) == 1, "reminder fires after REMINDER_INTERVAL_HOURS")
    if recs:
        check("still elevated" in recs[0].message, "message reads as a reminder, not a first notice")

    print("\nScenario 5: drops back to normal, should reset silently")
    t += timedelta(minutes=2)
    recs = tick(engine, make_snapshot(t, cpu_pct=22, ram_pct=41))
    check(len(recs) == 0, "no recommendation when dropping back under threshold")

    print("\nScenario 6: elevated again after reset, should be treated as fresh (not a reminder)")
    t += timedelta(minutes=2)
    recs = tick(engine, make_snapshot(t, cpu_pct=95, ram_pct=41))
    check(len(recs) == 1, "exactly one recommendation on the re-crossing")
    if recs:
        check("unusually high" in recs[0].message, "re-crossing reads as a fresh first notice, not a continuation")

    print(f"\n{_passed} passed, {_failed} failed")
    test_db_path.unlink()


if __name__ == "__main__":
    main()