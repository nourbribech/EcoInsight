from dataclasses import dataclass
@dataclass(frozen=True)
class DiskRuntimeMetrics:

    read_bytes_per_second: float

    write_bytes_per_second: float