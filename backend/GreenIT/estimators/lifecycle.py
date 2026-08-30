"""
The carbon this machine cost before it was ever switched on.

WHY THIS EXISTS
Everything else in this project measures electricity, and for an end-user
device electricity is the small number. Manufacturing a laptop emits
something on the order of 200-400 kg CO2eq; running one emits roughly 10-30
kg a year. So the machine arrives having already spent one to three decades'
worth of its own operating emissions, and the largest carbon decision anybody
makes about it is how long they keep it.

That is not an argument against measuring electricity. It is the context that
keeps the measurement honest: without it a dashboard reporting "245 g this
week" quietly implies that weekly grams are what matters, when they are a few
percent of the total. With it, the same dashboard can say what the evidence
actually supports — keep the machine longer, and separately, do not waste
power while you have it.

WHERE THE NUMBERS COME FROM, AND HOW SOFT THEY ARE
The embodied figure is a manufacturer's number, not a measurement, and it is
the softest quantity anywhere in this project. Dell, HP and Lenovo publish
per-model Product Carbon Footprint datasheets; those are what belong in the
table below. Published PCFs also carry very wide uncertainty bands of their
own — often stated as plus or minus 50% at one standard deviation — because
they depend on assumptions about the energy mix of the factories and the
lifetime the manufacturer assumed.

So this module reports a RANGE and a rounded central figure, and every string
it produces says "about". The conclusion is robust to the uncertainty even
when the number is not: at any plausible PCF, manufacturing dominates.
"""

from dataclasses import dataclass, asdict
from typing import Optional

# Per-model Product Carbon Footprint, kg CO2eq, from the manufacturer's
# datasheet. Keyed the same way as the calibration profiles.
#
# Deliberately near-empty: putting a guess here under a real model name would
# make an assumption look like a citation. Add a row only with the datasheet
# in hand.
_EMBODIED_KG_CO2E: dict[str, float] = {}

# Used when the model is not in the table. A business ultrabook is typically
# quoted in the low hundreds of kg; 300 sits mid-range and is labelled as a
# class estimate everywhere it surfaces.
DEFAULT_EMBODIED_KG_CO2E = 300.0
EMBODIED_RANGE_KG_CO2E = (200.0, 400.0)

# How long a corporate laptop is kept before replacement. Three to five years
# is the usual refresh cycle; five is the optimistic end, which makes the
# per-year embodied cost the CONSERVATIVE one — a shorter cycle would make
# manufacturing look worse, not better.
ASSUMED_SERVICE_LIFE_YEARS = 5.0


@dataclass(frozen=True)
class Lifecycle:
    embodied_kg: float
    embodied_is_estimate: bool
    embodied_low_kg: float
    embodied_high_kg: float

    annual_operating_kg: float
    # Years of running this machine that equal its manufacture.
    years_of_operation_equivalent: Optional[float]
    # Manufacturing as a share of total lifetime carbon, over the assumed life.
    manufacturing_share: Optional[float]
    # Carbon avoided by keeping it one year beyond the assumed life, expressed
    # both directly and as years of electricity.
    one_more_year_saves_kg: float
    one_more_year_in_operating_years: Optional[float]
    service_life_years: float

    def to_dict(self) -> dict:
        return asdict(self)


def embodied_for(machine_model: str) -> tuple[float, bool]:
    """Returns (kg CO2eq, is_estimate). True means no datasheet was found."""
    known = _EMBODIED_KG_CO2E.get(machine_model)
    if known is not None:
        return known, False
    return DEFAULT_EMBODIED_KG_CO2E, True


def assess(machine_model: str, annual_operating_kg: float) -> Lifecycle:
    """
    `annual_operating_kg` is this machine's measured electricity emissions
    scaled to a year. Everything else is arithmetic on top of it.
    """
    embodied, is_estimate = embodied_for(machine_model)

    # Guarded because a machine that has just been installed has effectively
    # zero measured operating emissions, and dividing by it would produce an
    # infinity where "not enough data" is meant.
    has_operating = annual_operating_kg > 0.01

    # One extra year of service spreads the same manufacturing emissions over
    # a longer life. The saving is the difference between amortising over the
    # assumed life and over one year more.
    per_year_now = embodied / ASSUMED_SERVICE_LIFE_YEARS
    per_year_extended = embodied / (ASSUMED_SERVICE_LIFE_YEARS + 1)
    saved = (per_year_now - per_year_extended) * ASSUMED_SERVICE_LIFE_YEARS

    lifetime_total = embodied + annual_operating_kg * ASSUMED_SERVICE_LIFE_YEARS

    return Lifecycle(
        embodied_kg=embodied,
        embodied_is_estimate=is_estimate,
        embodied_low_kg=EMBODIED_RANGE_KG_CO2E[0],
        embodied_high_kg=EMBODIED_RANGE_KG_CO2E[1],
        annual_operating_kg=annual_operating_kg,
        years_of_operation_equivalent=(
            embodied / annual_operating_kg if has_operating else None),
        manufacturing_share=embodied / lifetime_total if lifetime_total > 0 else None,
        one_more_year_saves_kg=saved,
        one_more_year_in_operating_years=(
            saved / annual_operating_kg if has_operating else None),
        service_life_years=ASSUMED_SERVICE_LIFE_YEARS,
    )
