from . import cpu
from . import memory
from . import disk
from . import network


def collect():
    """
    Aggregate hardware metrics.
    """

    return {
        "cpu": cpu.collect(),
        "memory": memory.collect(),
        "disk": disk.collect(),
        "network": network.collect(),
    }