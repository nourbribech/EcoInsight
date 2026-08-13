from dataclasses import dataclass


@dataclass(frozen=True)
class NetworkRuntimeMetrics:

    bytes_sent_per_second: float

    bytes_received_per_second: float