import psutil


def collect():
    """
    Collect disk I/O metrics.
    """

    io = psutil.disk_io_counters()

    return {
        "io": io._asdict() if io else None
    }