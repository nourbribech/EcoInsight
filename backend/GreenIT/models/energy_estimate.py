from dataclasses import dataclass


@dataclass(frozen=True)
class EnergyEstimate:
    """
    Result of one Energy Estimator tick.

    interval_watt_hours: energy consumed since the previous tick only —
    this is what the Carbon Estimator multiplies by grid intensity to get
    that interval's emissions.

    cumulative_watt_hours: running total since the estimator started
    (i.e. since the app/session began) — what a live dashboard would show
    as "energy used this session".
    """

    interval_watt_hours: float
    cumulative_watt_hours: float