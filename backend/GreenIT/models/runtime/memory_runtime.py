from dataclasses import dataclass

@dataclass(frozen=True)
class MemoryRuntimeMetrics:

    used_bytes: int

    total_bytes: int

    available_bytes: int

    usage_percent: float