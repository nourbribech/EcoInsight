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

    def tick(self):
        """One iteration. Returns (power, energy, carbon) or None if this tick had nothing to report yet."""
        snapshot = self._polling_service.poll()
        if snapshot is None:
            return None

        recommendations = self._maybe_save_telemetry(snapshot)

        self._maybe_save_telemetry(snapshot)

        power = self._power_estimator.estimate(snapshot, self._calibration_profile)

        energy = self._energy_estimator.estimate(power, snapshot.timestamp)
        if energy is None:
            return None

        carbon = self._carbon_estimator.estimate(energy)
        database.save_measurement(snapshot.timestamp, power, energy, carbon)

        return power, energy, carbon, recommendations

    def _maybe_save_telemetry(self, snapshot) -> None:
        """Writes a telemetry snapshot at most once per TELEMETRY_INTERVAL_SECONDS."""
        if (
                self._last_telemetry_write is not None
                and (snapshot.timestamp - self._last_telemetry_write).total_seconds()
                < self.TELEMETRY_INTERVAL_SECONDS
        ):
            return[]

        database.save_telemetry_snapshot(snapshot)
        self._last_telemetry_write = snapshot.timestamp
        return self._recommendation_engine.evaluate(snapshot)

    def run_forever(self, interval_seconds: float = None) -> None:
        """Blocking loop. Call from a background thread in a real app."""
        interval = interval_seconds or MetricsPollingService.DEFAULT_INTERVAL_SECONDS
        print(f"Starting estimation loop for: {self._calibration_profile.machine_model}")

        while True:
            result = self.tick()
            if result is not None:
                power, energy, carbon, recommendations = result
                print(
                    f"{power.total_watts:6.2f} W | "
                    f"{energy.cumulative_watt_hours:8.4f} Wh total | "
                    f"{carbon.cumulative_kg_co2eq * 1000:8.3f} gCO2eq total"
                )
            for rec in recommendations:
                print(f"  [!] {rec.message}")

if __name__ == "__main__":
    EstimationLoop().run_forever()