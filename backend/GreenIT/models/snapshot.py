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