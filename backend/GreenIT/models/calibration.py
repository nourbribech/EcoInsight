from dataclasses import dataclass


@dataclass(frozen=True)
class CpuCalibration:
    """CPU power model: watts per 1% usage."""

    watts_per_percent_usage: float


@dataclass(frozen=True)
class RamCalibration:
    """RAM power model: watts per GB used."""

    watts_per_gb_used: float




@dataclass(frozen=True)
class CalibrationProfile:
    """
    All calibration coefficients required to estimate power draw for one
    specific, identified machine model.

    Resolved once per session by a Service (machine identification +
    hardware repository lookup against hardware.db), then passed into the
    Power Estimator. The Estimator never queries the database itself and
    never knows how the profile was obtained — it only ever sees this
    object. That's what lets calibration data be replaced later (new
    machine models, recalibration) without touching estimator logic.
    """

    machine_model: str
    cpu: CpuCalibration
    ram: RamCalibration
    baseline_watts: float  # constant draw: motherboard, chipset, fans, etc.

    # WHERE THESE NUMBERS CAME FROM, carried with them.
    #
    # "measured"  - battery-discharge sweeps were run on this exact model.
    # "entered"   - a person typed the coefficients in through the IT setup
    #               screen. They may be excellent (copied from a sweep run on
    #               an identical model) or a guess, and nothing here can tell
    #               the difference, so they are never promoted to "measured".
    # "estimated" - no profile exists for the model, so the coefficients were
    #               scaled from another machine by TDP. Never stored: it is
    #               produced at runtime by generic_calibration.
    #
    # Provenance travels with the profile rather than being looked up
    # separately, because every watt-hour and every gram of CO2eq downstream
    # inherits it. A figure derived from an estimate must never be presented
    # with the confidence of a measured one, and the only way to guarantee
    # that is for the object itself to know.
    #
    # THE DEFAULT IS A TRAP THAT ALREADY SPRANG. `source` was not a column in
    # hardware.db, and the repository built profiles without passing it - so
    # every stored row, however it got there, read back as "measured". A
    # typed-in guess would have inherited the authority of a discharge sweep
    # AND silenced the "not calibrated" warning, which only fires on
    # "estimated". The column exists now and the repository reads it.
    source: str = "measured"

    notes: str = ""

    # ISO-8601, from the sweep or the moment somebody typed the numbers in.
    # Read from the database rather than dropped: "calibrated in 2026" and
    # "calibrated last week" are different claims about the same coefficients.
    calibrated_at: str | None = None