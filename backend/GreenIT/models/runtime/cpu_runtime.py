from dataclasses import dataclass

@dataclass(frozen=True)
class CpuRuntimeMetrics:
    """
    Runtime CPU telemetry collected from Windows and psutil.

    This represents the CPU's current operating state.
    It intentionally contains no hardware identity
    (model name, core count, TDP, etc.).
    """

    usage_percent: float

    actual_frequency_mhz: float | None #some machines won't expose every metric.

    base_frequency_mhz: float | None

    processor_utility_percent: float | None

    processor_performance_percent: float | None

    percent_of_max_frequency: float | None