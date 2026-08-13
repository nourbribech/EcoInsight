from dataclasses import dataclass


@dataclass(frozen=True)
class CarbonEstimate:
    """Result of one Carbon Estimator tick. Mirrors EnergyEstimate's split."""

    interval_kg_co2eq: float
    cumulative_kg_co2eq: float