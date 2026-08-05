"""
Manual smoke test for the Power Estimator pipeline, using real collector
data and the real (currently placeholder) calibration profile.

Not a unit test — no assertions, just prints what came out so you can
eyeball whether the numbers look sane. Run from the backend/ directory:

"""

import time
from pathlib import Path

from GreenIT.database.hardware_repository import HardwareRepository
from GreenIT.services.hardware_service import HardwareService
from GreenIT.services.metrics_polling_service import MetricsPollingService
from GreenIT.estimators.power import PowerEstimator

HARDWARE_DB_PATH = Path(__file__).resolve().parent.parent / "database" / "data" / "hardware.db"


def main() -> None:
    # 1. Resolve this machine's calibration profile (once).
    repository = HardwareRepository(HARDWARE_DB_PATH)
    hardware_service = HardwareService(repository)
    profile = hardware_service.get_current_machine_profile()
    print(f"Resolved calibration profile for: {profile.machine_model}")

    # 2. Poll twice — the first tick has no prior disk reading to diff
    #    against, so it returns None and should be skipped.
    polling_service = MetricsPollingService()

    first = polling_service.poll()
    assert first is None, "expected the first poll() to return None"

    time.sleep(MetricsPollingService.DEFAULT_INTERVAL_SECONDS)
    snapshot = polling_service.poll()
    print(f"Snapshot: {snapshot}")

    # 3. Estimate power from the real snapshot + real profile.
    estimator = PowerEstimator()
    estimate = estimator.estimate(snapshot, profile)

    print(
        "PowerEstimate:\n"
        f"  cpu_watts:      {estimate.cpu_watts:.2f}\n"
        f"  ram_watts:      {estimate.ram_watts:.2f}\n"
        f"  baseline_watts: {estimate.baseline_watts:.2f}\n"
        f"  total_watts:    {estimate.total_watts:.2f}"
    )


if __name__ == "__main__":
    main()