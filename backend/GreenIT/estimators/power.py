from GreenIT.models.snapshot import SystemMetricsSnapshot
from GreenIT.models.calibration import CalibrationProfile
from GreenIT.models.power_estimate import PowerEstimate
from GreenIT.models.calibration import CpuCalibration, RamCalibration, DiskCalibration

_BYTES_PER_GB = 1024 ** 3
_BYTES_PER_MB = 1024 ** 2


class CpuPowerModel:
    """CPU power: idle floor plus a linear relationship to usage percent."""

    def estimate(self, snapshot: SystemMetricsSnapshot, calibration: CpuCalibration) -> float:
        return calibration.idle_watts + calibration.watts_per_percent_usage * snapshot.cpu_usage_percent


class RamPowerModel:
    """RAM power: idle floor plus a linear relationship to GB used."""

    def estimate(self, snapshot: SystemMetricsSnapshot, calibration: RamCalibration) -> float:
        used_gb = snapshot.ram_used_bytes / _BYTES_PER_GB
        return calibration.idle_watts + calibration.watts_per_gb_used * used_gb


class DiskPowerModel:
    """Disk power: idle floor plus a linear relationship to combined read+write throughput."""

    def estimate(self, snapshot: SystemMetricsSnapshot, calibration: DiskCalibration) -> float:
        total_bytes_per_sec = snapshot.disk_read_bytes_per_sec + snapshot.disk_write_bytes_per_sec
        total_mb_per_sec = total_bytes_per_sec / _BYTES_PER_MB
        return calibration.idle_watts + calibration.watts_per_mb_per_sec * total_mb_per_sec


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
        disk_model: DiskPowerModel = None,
    ):
        self._cpu_model = cpu_model or CpuPowerModel()
        self._ram_model = ram_model or RamPowerModel()
        self._disk_model = disk_model or DiskPowerModel()

    def estimate(self, snapshot: SystemMetricsSnapshot, profile: CalibrationProfile) -> PowerEstimate:
        return PowerEstimate(
            cpu_watts=self._cpu_model.estimate(snapshot, profile.cpu),
            ram_watts=self._ram_model.estimate(snapshot, profile.ram),
            disk_watts=self._disk_model.estimate(snapshot, profile.disk),
            baseline_watts=profile.baseline_watts,
        )