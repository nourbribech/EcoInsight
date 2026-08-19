import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from GreenIT.database.hardware_repository import HardwareRepository
from GreenIT.database import database
from GreenIT.services.hardware_service import HardwareService
from GreenIT.services.metrics_polling_service import MetricsPollingService
from GreenIT.estimators.power import PowerEstimator
from GreenIT.estimators.energy import EnergyEstimator
from GreenIT.estimators.carbon import CarbonEstimator
from GreenIT.estimators.recommendations import RecommendationEngine
from GreenIT.collectors.hardware import processes
from GreenIT.estimators.process_attribution import attribute_cpu_watts

HARDWARE_DB_PATH = Path(__file__).resolve().parent.parent / "database" / "data" / "hardware.db"


class EstimationLoop:
    """
    Ties the whole pipeline together: poll -> power -> energy -> carbon
    -> persist. Deliberately a thin orchestrator with no estimation logic
    of its own — every calculation lives in its own estimator; this class
    only sequences them and hands results to persistence.

    Two ticks of "warm-up" before real output appears, not one: the
    polling service's first tick has no prior disk reading to diff
    against (returns None), and separately the energy estimator's first
    tick has no prior timestamp to diff against (also returns None).
    Both are expected, not bugs — see each class's own docstring.


     Telemetry (for the Recommendation Engine's baseline) is written on a
    much slower cadence than power measurements — every tick would
    produce far more rows than a daily rolling baseline needs. A simple
    elapsed-time check gates the write; no separate timer/thread needed
    since tick() already runs frequently enough to check the clock.
    """

    TELEMETRY_INTERVAL_SECONDS = 120  # 2 minutes

    def __init__(self):
        hardware_repository = HardwareRepository(HARDWARE_DB_PATH)
        hardware_service = HardwareService(hardware_repository)
        self._calibration_profile = hardware_service.get_current_machine_profile()

        self._polling_service = MetricsPollingService()
        self._power_estimator = PowerEstimator()
        self._energy_estimator = EnergyEstimator()
        self._carbon_estimator = CarbonEstimator()
        self._recommendation_engine = RecommendationEngine()
        self._last_telemetry_write: Optional[datetime] = None
        database.initialize_database()

        # Prime psutil's per-process CPU counters. The first reading for each
        # process has no previous value to diff against and comes back 0.0,
        # so discarding one here means the first real sample is meaningful
        # rather than an empty table.
        processes.collect()

    PROCESS_SAMPLE_LIMIT = 10

    def _maybe_save_telemetry(self, snapshot, power) -> list:
        """Writes a telemetry snapshot at most once per TELEMETRY_INTERVAL_SECONDS."""
        if (
                self._last_telemetry_write is not None
                and (snapshot.timestamp - self._last_telemetry_write).total_seconds()
                < self.TELEMETRY_INTERVAL_SECONDS
        ):
            return[]

        database.save_telemetry_snapshot(snapshot)
        self._last_telemetry_write = snapshot.timestamp

        # Sampled on this slower cadence too — walking every process is far
        # more expensive than the handful of counters the snapshot needs.
        raw = processes.collect(limit=self.PROCESS_SAMPLE_LIMIT)
        attributed = attribute_cpu_watts(
            raw["processes"], raw["total_cpu_percent"], power.cpu_watts
        )
        database.save_process_samples(snapshot.timestamp, attributed)

        # The same sample feeds both the dashboard table and the messages, so
        # a recommendation can never name a process that the Top Consumers
        # panel is not also showing at that moment.
        recommendations = self._recommendation_engine.evaluate(
            snapshot,
            power.total_watts,
            processes=attributed,
            total_cpu_percent=raw["total_cpu_percent"],
        )

        # Persistence lives here, not in the engine. The engine computes and
        # holds the elevated/reminder state; the loop is what hands results to
        # the database — same division as save_measurement() in tick().
        # Without this the recommendations table stays permanently empty and
        # /api/recommendations returns [] no matter what the engine detects.
        for recommendation in recommendations:
            database.save_recommendation(recommendation)

        return recommendations

    def tick(self):
        """One iteration. Returns (power, energy, carbon) or None if this tick had nothing to report yet."""
        snapshot = self._polling_service.poll()
        if snapshot is None:
            return None

        power = self._power_estimator.estimate(snapshot, self._calibration_profile)
        recommendations = self._maybe_save_telemetry(snapshot, power)
        energy = self._energy_estimator.estimate(power, snapshot.timestamp)
        if energy is None:
            return None

        carbon = self._carbon_estimator.estimate(energy)
        database.save_measurement(snapshot.timestamp, power, energy, carbon)

        return power, energy, carbon, recommendations



    def run_forever(self, interval_seconds: float = None) -> None:
        """Blocking loop. Call from a background thread in a real app."""
        interval = interval_seconds or MetricsPollingService.DEFAULT_INTERVAL_SECONDS
        print(f"Starting estimation loop for: {self._calibration_profile.machine_model}")

        while True:
            started_at = time.monotonic()

            result = self.tick()
            if result is not None:
                power, energy, carbon, recommendations = result
                print(
                    f"{power.total_watts:6.2f} W | "
                    f"{energy.cumulative_watt_hours:8.4f} Wh total | "
                    f"{carbon.cumulative_kg_co2eq * 1000:8.3f} gCO2eq total"
                )
                # Was outside this block, which raised NameError on the first
                # (warm-up) tick, when tick() returns None and `recommendations`
                # was never bound.
                for rec in recommendations:
                    print(f"  [!] {rec.message}")

            # `interval` is a floor, not an added delay. poll() already blocks
            # ~1.1s inside psutil.cpu_percent(interval=1), so sleeping the full
            # interval on top would stretch ticks well past the intended
            # cadence. Sleeping only the remainder keeps the loop honest if
            # collection ever gets faster, and is a no-op while it doesn't.
            elapsed = time.monotonic() - started_at
            if elapsed < interval:
                time.sleep(interval - elapsed)

if __name__ == "__main__":
    EstimationLoop().run_forever()