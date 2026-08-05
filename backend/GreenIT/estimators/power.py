from GreenIT.models.snapshot import SystemMetricsSnapshot
from GreenIT.models.calibration import CalibrationProfile
from GreenIT.models.power_estimate import PowerEstimate
from GreenIT.models.calibration import CpuCalibration, RamCalibration


_BYTES_PER_GB = 1024 ** 3
_BYTES_PER_MB = 1024 ** 2


class CpuPowerModel:
    """CPU power: linear relationship to usage percent."""

    def estimate(self, snapshot: SystemMetricsSnapshot, calibration: CpuCalibration) -> float:
        return calibration.watts_per_percent_usage * snapshot.cpu.usage_percent


class RamPowerModel:
    """RAM power: linear relationship to GB used."""

    def estimate(self, snapshot: SystemMetricsSnapshot, calibration: RamCalibration) -> float:
        used_gb = snapshot.memory.used_bytes / _BYTES_PER_GB
        return calibration.watts_per_gb_used * used_gb





class PowerEstimator:
    """
    Composes the per-component models into a full PowerEstimate.

    Component models are constructor-injected with sane defaults rather
    than hardcoded, so each can be swapped or unit-tested independently
    (e.g. testing DiskPowerModel with fabricated coefficients, with no
    involvement of CPU/RAM logic, the database, or collectors).

    This class knows nothing about where SystemMetricsSnapshot or
    CalibrationProfile came from — not the database, not WMI, not psutil.
    It is a pure function of its two inputs, which is what makes it
    trivially testable and keeps recalibration (new coefficients) or new
    machine models from ever requiring a change here.
    """

    def __init__(
        self,
        cpu_model: CpuPowerModel = None,
        ram_model: RamPowerModel = None,
    ):
        self._cpu_model = cpu_model or CpuPowerModel()
        self._ram_model = ram_model or RamPowerModel()

    def estimate(self, snapshot: SystemMetricsSnapshot, profile: CalibrationProfile) -> PowerEstimate:
        return PowerEstimate(
            cpu_watts=self._cpu_model.estimate(snapshot, profile.cpu),
            ram_watts=self._ram_model.estimate(snapshot, profile.ram),
            baseline_watts=profile.baseline_watts,
        )