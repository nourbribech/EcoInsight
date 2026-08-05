import sqlite3
from pathlib import Path

from GreenIT.models.calibration import CalibrationProfile, CpuCalibration, RamCalibration


class UnknownMachineModelError(Exception):
    """
    Raised when hardware.db has no calibration profile for the given
    machine model.

    This is deliberately a hard failure, not a fallback to default/generic
    coefficients. EcoInsight targets a fixed set of standardized company
    PC models — an unrecognized model is an exceptional condition that
    should surface clearly, not one to silently paper over with a guess
    that could be meaningfully wrong.
    """


class HardwareRepository:
    """
    Read-only access to hardware.db.

    Owns all SQL for calibration lookups. Nothing outside this module
    should know hardware.db's schema — every caller sees only
    CalibrationProfile objects, never raw rows.
    """

    def __init__(self, db_path: Path):
        self._db_path = db_path

    def get_calibration_profile(self, machine_model: str) -> CalibrationProfile:
        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM calibration_profiles WHERE machine_model = ?",
                (machine_model,),
            ).fetchone()

        if row is None:
            raise UnknownMachineModelError(
                f"No calibration profile found for machine model: {machine_model!r}"
            )

        return CalibrationProfile(
            machine_model=row["machine_model"],
            cpu=CpuCalibration(
                watts_per_percent_usage=row["cpu_watts_per_percent_usage"],
            ),
            ram=RamCalibration(
                watts_per_gb_used=row["ram_watts_per_gb_used"],
            ),
            baseline_watts=row["baseline_watts"],
        )