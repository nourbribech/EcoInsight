from dataclasses import dataclass

#calibration is for current pc state, its gonna keep degrading;
# is the carbon estimation gonna be accurate even then?

@dataclass(frozen=True)
class CpuCalibration:
    """
    Coefficients for the CPU power model: idle power plus a linear
    relationship between usage percent and package power, derived from
    LibreHardwareMonitor readings at controlled loads (0/25/50/75/100%)
    during offline calibration.
    """

    idle_watts: float
    watts_per_percent_usage: float


@dataclass(frozen=True)
class RamCalibration:
    """Coefficients for the RAM power model."""

    watts_per_gb_used: float
    idle_watts: float = 0.0


@dataclass(frozen=True)
class DiskCalibration:
    """Coefficients for the disk power model."""

    watts_per_mb_per_sec: float
    idle_watts: float = 0.0


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
    disk: DiskCalibration
    baseline_watts: float  # constant draw: motherboard, chipset, fans, etc.