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


def _column(row: sqlite3.Row, name: str, default):
    """
    Reads a column that may not exist yet.

    hardware.db ships with the agent and is upgraded in place, so a machine
    running an older copy has rows without `source`. Those rows predate the
    IT setup screen and can only have come from a calibration sweep, which is
    why the default is "measured" rather than something more cautious -
    treating genuine measurements as unknown would raise a false warning on
    every correctly calibrated machine in the fleet.
    """
    return row[name] if name in row.keys() else default


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
            # THESE THREE WERE BEING DROPPED, and two of them mattered.
            #
            # `source` was not passed at all, so every stored row inherited
            # CalibrationProfile's "measured" default no matter how it got
            # into the table. That made provenance unfalsifiable and, worse,
            # would have let a typed-in profile switch off the "this machine
            # is not calibrated" finding, which fires only on "estimated".
            #
            # `notes` and `calibrated_at` were columns the schema has always
            # had and nothing ever read - so the real profile's provenance
            # ("Mean of 5 direct measurements, stdev=0.702 W") existed on disk
            # and was invisible everywhere above this line.
            source=_column(row, "source", "measured"),
            notes=_column(row, "notes", "") or "",
            calibrated_at=_column(row, "calibrated_at", None),
        )

    def list_profiles(self) -> list[CalibrationProfile]:
        """
        Every profile in the database.

        The IT setup screen needs this to show what the fleet already knows,
        so somebody about to type a profile in can first check whether an
        identical model has already been swept - which is the difference
        between copying a measurement and inventing one.
        """
        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM calibration_profiles ORDER BY machine_model"
            ).fetchall()

        return [
            CalibrationProfile(
                machine_model=row["machine_model"],
                cpu=CpuCalibration(
                    watts_per_percent_usage=row["cpu_watts_per_percent_usage"]),
                ram=RamCalibration(watts_per_gb_used=row["ram_watts_per_gb_used"]),
                baseline_watts=row["baseline_watts"],
                source=_column(row, "source", "measured"),
                notes=_column(row, "notes", "") or "",
                calibrated_at=_column(row, "calibrated_at", None),
            )
            for row in rows
        ]
