from GreenIT.models.energy_estimate import EnergyEstimate
from GreenIT.models.carbon_estimate import CarbonEstimate

# Tunisia grid carbon intensity: ~483 gCO2eq/kWh (2025), reflecting a grid
# that is over 98% gas-fired with low-carbon sources contributing ~1%.
# Source: lowcarbonpower.org/region/Tunisia. Deliberately country-specific
# rather than a generic world-average fallback (CodeCarbon's own default
# is ~475 gCO2eq/kWh globally, which would understate/mismatch reality
# here in either direction depending on the actual figure at query time).
TUNISIA_GRID_CARBON_INTENSITY_KG_PER_KWH = 0.483


class CarbonEstimator:
    """
    Converts energy (kWh) into emissions (kgCO2eq) via a grid carbon
    intensity factor: CO2eq = Energy x intensity — the same two-stage
    formula CodeCarbon uses internally.

    Stateless with respect to time (no diffing needed, unlike Energy):
    it just applies a constant conversion factor to whatever
    EnergyEstimate it's given. It does hold a running cumulative total
    across calls, since "total emissions this session" is meaningful
    output on its own, mirroring EnergyEstimator's cumulative tracking.

    grid_intensity_kg_per_kwh is constructor-injected rather than
    hardcoded so it can be swapped per deployment region without
    touching this class — e.g. if EcoInsight is ever deployed outside
    Tunisia.
    """

    def __init__(self, grid_intensity_kg_per_kwh: float = TUNISIA_GRID_CARBON_INTENSITY_KG_PER_KWH):
        self._grid_intensity_kg_per_kwh = grid_intensity_kg_per_kwh
        self._cumulative_kg_co2eq: float = 0.0

    def estimate(self, energy_estimate: EnergyEstimate) -> CarbonEstimate:
        interval_kwh = energy_estimate.interval_watt_hours / 1000
        interval_kg_co2eq = interval_kwh * self._grid_intensity_kg_per_kwh
        self._cumulative_kg_co2eq += interval_kg_co2eq

        return CarbonEstimate(
            interval_kg_co2eq=interval_kg_co2eq,
            cumulative_kg_co2eq=self._cumulative_kg_co2eq,
        )