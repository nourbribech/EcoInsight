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