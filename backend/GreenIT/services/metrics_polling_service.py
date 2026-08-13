from datetime import datetime
from typing import Optional

from GreenIT.collectors.hardware import cpu, memory, disk
from GreenIT.models.runtime.cpu_runtime import CpuRuntimeMetrics
from GreenIT.models.runtime.memory_runtime import MemoryRuntimeMetrics
from GreenIT.models.runtime.disk_runtime import DiskRuntimeMetrics
from GreenIT.models.snapshot import SystemMetricsSnapshot
from GreenIT.collectors.hardware import network
from GreenIT.models.runtime.network_runtime import NetworkRuntimeMetrics


class MetricsPollingService:
    """
    Produces a SystemMetricsSnapshot on each call to poll().

    Owns the only piece of state in the collection path: the previous
    disk I/O counters and when they were read. psutil's disk counters are
    cumulative since boot, not instantaneous throughput, so computing
    bytes/sec requires two readings a known interval apart. That state
    lives here — not in the disk collector (which stays a stateless,
    reusable "read right now" function) and not in the Power Estimator
    (which stays a pure function of a single snapshot).

    The first call to poll() has no prior reading to diff against, so it
    returns None rather than a snapshot with a fabricated throughput
    value. Callers should skip that first tick.
    """

    # Sub-second polling makes disk throughput noisier, not more accurate
    # (small bursts get divided by a tiny interval into misleading spikes),
    # and offers no real gain since calibration itself was measured at
    # sustained load levels, not sub-second transients. 1.5s is fast
    # enough to feel real-time while keeping readings meaningful. This is
    # a default for whatever scheduling loop drives poll() — poll() itself
    # doesn't sleep; it just measures actual elapsed time.
    DEFAULT_INTERVAL_SECONDS = 1.5

    def __init__(self):
        self._previous_disk_read_bytes: Optional[int] = None
        self._previous_disk_write_bytes: Optional[int] = None
        self._previous_network_sent_bytes: Optional[int] = None
        self._previous_network_recv_bytes: Optional[int] = None
        self._previous_timestamp: Optional[datetime] = None

    def poll(self) -> Optional[SystemMetricsSnapshot]:
        now = datetime.now()

        cpu_data = cpu.collect()
        memory_data = memory.collect()
        disk_data = disk.collect()
        network_data = network.collect()

        disk_io = disk_data["io"]
        current_read_bytes = disk_io["read_bytes"]
        current_write_bytes = disk_io["write_bytes"]


        network_io = network_data["io"]
        current_sent_bytes = network_io["bytes_sent"]
        current_recv_bytes = network_io["bytes_recv"]


        if self._previous_timestamp is None:
            # First tick: nothing to diff against yet.
            self._previous_disk_read_bytes = current_read_bytes
            self._previous_disk_write_bytes = current_write_bytes
            self._previous_network_sent_bytes = current_sent_bytes
            self._previous_network_recv_bytes = current_recv_bytes
            self._previous_timestamp = now
            return None

        elapsed_seconds = (now - self._previous_timestamp).total_seconds()
        if elapsed_seconds <= 0: #if poll() ever gets called twice in immediate succession
            # Guards against a zero/negative interval (e.g. clock issues,
            elapsed_seconds = 1e-6 #epsilon

        read_bytes_per_sec = (current_read_bytes - self._previous_disk_read_bytes) / elapsed_seconds
        write_bytes_per_sec = (current_write_bytes - self._previous_disk_write_bytes) / elapsed_seconds

        sent_bytes_per_sec = (current_sent_bytes - self._previous_network_sent_bytes) / elapsed_seconds
        recv_bytes_per_sec = (current_recv_bytes - self._previous_network_recv_bytes) / elapsed_seconds
        cpu_metrics = CpuRuntimeMetrics(
            usage_percent=cpu_data["usage_percent"],
            actual_frequency_mhz=None,
            base_frequency_mhz=cpu_data.get("base_frequency_mhz"),
            processor_utility_percent=None,
            processor_performance_percent=None,
            percent_of_max_frequency=None,
        )

        memory_metrics = MemoryRuntimeMetrics(
            used_bytes=memory_data["virtual"]["used"],
            total_bytes=memory_data["virtual"]["total"],
            available_bytes=memory_data["virtual"]["available"],
            usage_percent=memory_data["virtual"]["percent"],
        )

        disk_metrics = DiskRuntimeMetrics(
            read_bytes_per_second=read_bytes_per_sec,
            write_bytes_per_second=write_bytes_per_sec,
        )

        network_metrics = NetworkRuntimeMetrics(
            bytes_sent_per_second=sent_bytes_per_sec,
            bytes_received_per_second=recv_bytes_per_sec,
        )

        snapshot = SystemMetricsSnapshot(
            cpu=cpu_metrics,
            memory=memory_metrics,
            disk=disk_metrics,
            network=network_metrics,
            timestamp=now,
        )
        self._previous_disk_read_bytes = current_read_bytes
        self._previous_disk_write_bytes = current_write_bytes
        self._previous_network_sent_bytes = current_sent_bytes
        self._previous_network_recv_bytes = current_recv_bytes
        self._previous_timestamp = now

        return snapshot