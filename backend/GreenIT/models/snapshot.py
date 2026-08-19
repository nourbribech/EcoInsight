from dataclasses import dataclass
from datetime import datetime

from GreenIT.models.runtime.cpu_runtime import CpuRuntimeMetrics
from GreenIT.models.runtime.disk_runtime import DiskRuntimeMetrics
from GreenIT.models.runtime.memory_runtime import MemoryRuntimeMetrics
from GreenIT.models.runtime.network_runtime import NetworkRuntimeMetrics


@dataclass(frozen=True)
class SystemMetricsSnapshot:
    """
    A single point-in-time snapshot of the metrics needed to estimate
    instantaneous power draw.

    This is the contract between the Services layer (which assembles it
    from raw collector output) and the Estimators layer (which consumes
    it). Estimators should depend only on this object, never on raw
    collector dicts — that keeps them decoupled from collector internals
    (psutil field names, WMI query shapes, etc.).

    disk_read_bytes_per_sec / disk_write_bytes_per_sec are already-computed
    throughput values, not raw cumulative counters. The delta computation
    (diffing two psutil.disk_io_counters() reads against elapsed time)
    happens in the polling Service, which is the only place that needs to
    know about sampling intervals or hold state between reads.
    """

    cpu: CpuRuntimeMetrics

    memory: MemoryRuntimeMetrics

    disk: DiskRuntimeMetrics

    network: NetworkRuntimeMetrics

    timestamp: datetime

    # Seconds since the last keyboard/mouse input, from the Windows
    # GetLastInputInfo API. A bare scalar rather than a SessionRuntimeMetrics
    # object because it is currently the only session field anyone consumes —
    # promote it to its own model if a second one (locked, active user)
    # arrives.
    #
    # Optional with a default so snapshots built by tests and older callers
    # keep working, and because a machine with no input device or a failed
    # API call should report "unknown" rather than a fabricated 0.
    idle_seconds: float | None = None

    # Display state. Optional and defaulted for the same reason as
    # idle_seconds: a desktop with no readable panel, or a monitor that does
    # not answer DDC/CI, must report "unknown" rather than a fabricated zero —
    # a brightness of 0 % and a brightness we could not read are very
    # different facts.
    #
    # Sampled far less often than the rest of the snapshot: reading brightness
    # costs ~170 ms (it talks to each monitor over DDC/CI), which is 11 % of a
    # poll cycle. See MetricsPollingService.DISPLAY_REFRESH_SECONDS.
    brightness_percent: int | None = None

    monitor_count: int | None = None