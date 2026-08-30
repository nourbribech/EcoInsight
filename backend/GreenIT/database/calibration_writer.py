"""
Writing calibration profiles into hardware.db.

WHY THIS IS NOT A METHOD ON HardwareRepository
That class documents itself as read-only access, and the guarantee is worth
keeping: every estimator, the API and the estimation loop hold a repository,
and none of them should be one typo away from rewriting the coefficients the
whole fleet's numbers depend on. Writing is a different capability with a
different caller, so it gets a different object.

WHY PERMISSION IS THE REAL GATE, AND `--mode it` IS NOT
The agent takes a `--mode it` flag, and it would have been easy to gate this
on it. That would be security theatre: any employee can type
`python -m GreenIT.agent --mode it`. If a flag were enough to rewrite
coefficients, anybody could drop their own baseline from 5 W to 1 W and watch
a third of their reported waste disappear - in a tool whose entire output is
a waste figure, and which is being considered for manager-visible reporting.

So the write is attempted and the operating system decides. On a managed
fleet hardware.db is admin-writable only, which makes the boundary real and
enforced by Windows rather than decorated by a UI. `--mode it` stays what it
honestly is: a view switch.

WHY VALIDATION IS PHYSICS AND NOT TASTE
A fat-fingered 0.105 -> 1.05 produces numbers that look plausible and are
wrong forever, with nothing downstream able to notice. The bounds below come
from what a laptop can actually do, so they reject the typo without
second-guessing a legitimate measurement.
"""

import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from GreenIT.models.calibration import CalibrationProfile, CpuCalibration, RamCalibration

# Provenance the writer is allowed to record. "estimated" is deliberately not
# here: it describes a profile generic_calibration built at runtime because
# nothing was stored, so storing one would be a contradiction.
WRITABLE_SOURCES = ("measured", "entered")

# Bounds from what the hardware can do, not from taste.
#
# CPU: generic_calibration puts a laptop at roughly TDP x 0.70 / 100 W per
# percent. A 7 W tablet part gives 0.049 and a 55 W HX part gives 0.385, so
# the range below spans every mobile CPU with room at both ends, while
# rejecting a decimal-point slip by an order of magnitude.
CPU_WATTS_PER_PERCENT_RANGE = (0.02, 0.60)

# RAM: the sweep run for this project measured -0.09 +/- 0.22 W/GB, i.e.
# indistinguishable from zero, and published per-module figures top out well
# under 1 W/GB. Zero is allowed because it is an honest answer.
RAM_WATTS_PER_GB_RANGE = (0.0, 1.0)

# Baseline: everything that draws power while the machine is on and idle.
# Under half a watt is not a laptop; over 20 W is not a baseline.
BASELINE_WATTS_RANGE = (0.5, 20.0)

MAX_NOTES_LENGTH = 500


class CalibrationWriteError(Exception):
    """A profile could not be written. The message is shown to the user."""


class CalibrationPermissionError(CalibrationWriteError):
    """
    hardware.db is not writable by this account.

    Separate from the general error because it is not a mistake - it is the
    fleet's access control working exactly as intended, and the UI should say
    so rather than implying something broke.
    """


@dataclass(frozen=True)
class ValidationIssue:
    field: str
    message: str


def _check_range(field: str, value: float, bounds: tuple[float, float],
                 unit: str) -> Optional[ValidationIssue]:
    low, high = bounds
    if not isinstance(value, (int, float)) or value != value:  # NaN != NaN
        return ValidationIssue(field, f"{field} must be a number.")
    if not low <= value <= high:
        return ValidationIssue(
            field,
            f"{field} is {value:g} {unit}, outside the plausible range "
            f"{low:g}-{high:g}. Check for a misplaced decimal point.",
        )
    return None


def validate(
    machine_model: str,
    cpu_watts_per_percent: float,
    ram_watts_per_gb: float,
    baseline_watts: float,
    source: str,
    notes: str = "",
) -> list[ValidationIssue]:
    """Every problem at once, so the form can show them together."""
    issues: list[ValidationIssue] = []

    if not machine_model or not machine_model.strip():
        issues.append(ValidationIssue(
            "machine_model", "A machine model key is required."))
    elif len(machine_model) > 200:
        issues.append(ValidationIssue(
            "machine_model", "Machine model key is unreasonably long."))

    for field, value, bounds, unit in (
        ("cpu_watts_per_percent", cpu_watts_per_percent,
         CPU_WATTS_PER_PERCENT_RANGE, "W per CPU %"),
        ("ram_watts_per_gb", ram_watts_per_gb, RAM_WATTS_PER_GB_RANGE, "W per GB"),
        ("baseline_watts", baseline_watts, BASELINE_WATTS_RANGE, "W"),
    ):
        issue = _check_range(field, value, bounds, unit)
        if issue:
            issues.append(issue)

    if source not in WRITABLE_SOURCES:
        issues.append(ValidationIssue(
            "source",
            f"Source must be one of {', '.join(WRITABLE_SOURCES)}. "
            f"'estimated' describes a runtime fallback and is never stored.",
        ))

    if notes and len(notes) > MAX_NOTES_LENGTH:
        issues.append(ValidationIssue(
            "notes", f"Notes must be under {MAX_NOTES_LENGTH} characters."))

    return issues


class CalibrationWriter:
    """Creates and replaces rows in hardware.db's calibration_profiles."""

    def __init__(self, db_path: Path):
        self._db_path = Path(db_path)

    # --- capability reporting -------------------------------------------

    def is_writable(self) -> bool:
        """
        Whether this account could write a profile.

        Asked by the UI so it can explain the situation up front instead of
        presenting a form that fails on submit. Opening the database and
        immediately rolling back is the only honest test - os.access reports
        the DACL, which on Windows regularly disagrees with what a write
        actually does.
        """
        if not self._db_path.exists():
            return False
        try:
            with sqlite3.connect(self._db_path) as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.rollback()
            return True
        except sqlite3.Error:
            return False

    # --- schema ----------------------------------------------------------

    def ensure_schema(self) -> None:
        """
        Adds the `source` column to an older hardware.db.

        Existing rows are backfilled to "measured" because that is what they
        are: the column was introduced alongside the screen that can write
        anything else, so every row predating it came from a sweep.
        """
        with self._connect() as connection:
            columns = {
                row[1] for row in
                connection.execute("PRAGMA table_info(calibration_profiles)")
            }
            if "source" not in columns:
                connection.execute(
                    "ALTER TABLE calibration_profiles ADD COLUMN source TEXT")
                connection.execute(
                    "UPDATE calibration_profiles SET source = 'measured' "
                    "WHERE source IS NULL")
            connection.commit()

    # --- writing ---------------------------------------------------------

    def save(
        self,
        machine_model: str,
        cpu_watts_per_percent: float,
        ram_watts_per_gb: float,
        baseline_watts: float,
        source: str = "entered",
        notes: str = "",
        calibrated_at: Optional[str] = None,
    ) -> CalibrationProfile:
        """
        Creates or replaces the profile for `machine_model`.

        Raises CalibrationWriteError (or its permission subclass) on refusal.
        Returns the profile as it will now be read back, so the caller shows
        what was stored rather than what was submitted.
        """
        issues = validate(machine_model, cpu_watts_per_percent,
                          ram_watts_per_gb, baseline_watts, source, notes)
        if issues:
            raise CalibrationWriteError(
                " ".join(issue.message for issue in issues))

        machine_model = machine_model.strip()
        stamped = calibrated_at or datetime.now(timezone.utc).isoformat()

        self.ensure_schema()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO calibration_profiles
                    (machine_model, cpu_watts_per_percent_usage,
                     ram_watts_per_gb_used, baseline_watts,
                     calibrated_at, notes, source)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(machine_model) DO UPDATE SET
                    cpu_watts_per_percent_usage = excluded.cpu_watts_per_percent_usage,
                    ram_watts_per_gb_used = excluded.ram_watts_per_gb_used,
                    baseline_watts = excluded.baseline_watts,
                    calibrated_at = excluded.calibrated_at,
                    notes = excluded.notes,
                    source = excluded.source
                """,
                (machine_model, float(cpu_watts_per_percent),
                 float(ram_watts_per_gb), float(baseline_watts),
                 stamped, notes, source),
            )
            connection.commit()

        return CalibrationProfile(
            machine_model=machine_model,
            cpu=CpuCalibration(watts_per_percent_usage=float(cpu_watts_per_percent)),
            ram=RamCalibration(watts_per_gb_used=float(ram_watts_per_gb)),
            baseline_watts=float(baseline_watts),
            source=source,
            notes=notes,
            calibrated_at=stamped,
        )

    def delete(self, machine_model: str) -> bool:
        """Removes a profile, returning whether one was there. The machine
        falls back to an estimated profile at the next restart."""
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM calibration_profiles WHERE machine_model = ?",
                (machine_model,))
            connection.commit()
            return cursor.rowcount > 0

    def backup(self) -> Path:
        """
        Copies hardware.db before a destructive change.

        This file is the only record of every sweep anybody has run, and
        re-measuring a model costs hours of controlled battery discharge.
        A copy costs 20 KB.
        """
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        destination = self._db_path.with_name(
            f"{self._db_path.stem}.backup-{stamp}{self._db_path.suffix}")
        shutil.copy2(self._db_path, destination)
        return destination

    # --- internals -------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        if not self._db_path.exists():
            raise CalibrationWriteError(
                f"Calibration database not found at {self._db_path}.")
        try:
            connection = sqlite3.connect(self._db_path)
            # Force the write lock now rather than at commit, so a read-only
            # file fails here with a clear cause instead of part-way through.
            connection.execute("BEGIN IMMEDIATE")
            connection.rollback()
            return connection
        except sqlite3.OperationalError as error:
            if "readonly" in str(error).lower() or "denied" in str(error).lower():
                raise CalibrationPermissionError(
                    "This account cannot write the calibration database. "
                    "On a managed machine that file is administrator-only, "
                    "which is what stops a calibration being changed from a "
                    "normal session."
                ) from error
            raise CalibrationWriteError(str(error)) from error
