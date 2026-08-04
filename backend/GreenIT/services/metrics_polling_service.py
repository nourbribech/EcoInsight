from datetime import datetime
from typing import Optional

from GreenIT.collectors.hardware import cpu, memory, disk
from GreenIT.models.snapshot import SystemMetricsSnapshot


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
        self._previous_timestamp: Optional[datetime] = None

    def poll(self) -> Optional[SystemMetricsSnapshot]:
        now = datetime.now()

        cpu_data = cpu.collect()
        memory_data = memory.collect()
        disk_data = disk.collect()

        disk_io = disk_data["io"]
        current_read_bytes = disk_io["read_bytes"]
        current_write_bytes = disk_io["write_bytes"]

        if self._previous_timestamp is None:
            # First tick: nothing to diff against yet.
            self._previous_disk_read_bytes = current_read_bytes
            self._previous_disk_write_bytes = current_write_bytes
            self._previous_timestamp = now
            return None

        elapsed_seconds = (now - self._previous_timestamp).total_seconds()
        if elapsed_seconds <= 0: #if poll() ever gets called twice in immediate succession
            # Guards against a zero/negative interval (e.g. clock issues,
            elapsed_seconds = 1e-6 #epsilon

        read_bytes_per_sec = (current_read_bytes - self._previous_disk_read_bytes) / elapsed_seconds
        write_bytes_per_sec = (current_write_bytes - self._previous_disk_write_bytes) / elapsed_seconds

        snapshot = SystemMetricsSnapshot(
            cpu_usage_percent=cpu_data["usage_percent"],
            ram_used_bytes=memory_data["virtual"]["used"],
            ram_total_bytes=memory_data["virtual"]["total"],
            disk_read_bytes_per_sec=read_bytes_per_sec,
            disk_write_bytes_per_sec=write_bytes_per_sec,
            timestamp=now,
        )

        self._previous_disk_read_bytes = current_read_bytes
        self._previous_disk_write_bytes = current_write_bytes
        self._previous_timestamp = now

        return snapshot