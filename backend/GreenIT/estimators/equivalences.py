"""
Turns watt-hours and grams of CO2eq into quantities people have intuition for.

Nobody knows whether 476 Wh is a lot. Almost everybody knows what boiling a
kettle feels like, or how far 2 km is. The measurement is unchanged — this
only restates it in a unit the reader already owns, which is the difference
between a number that is read and a number that is skipped.

TWO KINDS, KEPT APART
Energy equivalences (kettle, phone, lamp) are conversions: watt-hours into
watt-hours, exact up to the reference appliance. The carbon equivalence
(driving) crosses into a different domain and carries a second emission
factor, so it is inherently softer. Mixing the two without saying so would
lend the weaker figure the authority of the stronger one, so each equivalence
declares which it is and every one is labelled "about".

SOURCES
The constants below are deliberately round. They are ordinary published
figures for ordinary appliances, not measurements of this machine, and
pretending to three significant figures would be false precision on top of an
estimate that already carries 8.7% error.
"""

from dataclasses import dataclass, asdict

# An electric kettle boiling roughly one litre. ~2200 W for ~3 minutes.
KETTLE_BOIL_WATT_HOURS = 110.0

# A full charge of a typical smartphone battery (~4000 mAh at 3.85 V), plus
# charger losses.
PHONE_CHARGE_WATT_HOURS = 17.0

# A 9 W LED bulb, the common replacement for a 60 W incandescent.
LED_BULB_WATTS = 9.0

# Average tailpipe CO2 of a passenger car, in grams per kilometre. European
# new-car averages sit near this; older fleets are higher, so this is the
# conservative end of the comparison.
CAR_GRAMS_CO2_PER_KM = 120.0


@dataclass(frozen=True)
class Equivalence:
    """
    label   what the quantity is, ready to follow a number
    value   the quantity itself
    kind    "energy" | "carbon" -- see the module docstring
    """
    label: str
    value: float
    kind: str

    def to_dict(self) -> dict:
        return asdict(self)


def _plural(count: float, singular: str, plural: str) -> str:
    """
    Agrees with the number the reader will SEE, not the one computed.

    These are displayed rounded to whole units, so 1.14 renders as "1" — and
    matching on the raw value produced "1 phone charges". Grammar has to
    follow the presentation, so the rounded count decides.
    """
    return singular if round(count) == 1 else plural


def for_energy(watt_hours: float, grams_co2eq: float) -> list[Equivalence]:
    """
    The two or three comparisons that best fit this magnitude.

    Which ones are chosen depends on the size of the figure: "0.02 kettles"
    tells nobody anything, and neither does "1,400 phone charges". An
    equivalence only helps while its own count stays in a range people can
    picture, so anything that would land outside roughly 0.5-500 is dropped
    rather than printed.
    """
    equivalences: list[Equivalence] = []

    kettles = watt_hours / KETTLE_BOIL_WATT_HOURS
    if 0.5 <= kettles <= 500:
        equivalences.append(Equivalence(
            label=_plural(kettles, "kettle of water boiled", "kettles of water boiled"),
            value=kettles, kind="energy",
        ))

    charges = watt_hours / PHONE_CHARGE_WATT_HOURS
    if 0.5 <= charges <= 500:
        equivalences.append(Equivalence(
            label=_plural(charges, "phone charge", "phone charges"),
            value=charges, kind="energy",
        ))

    kilometres = grams_co2eq / CAR_GRAMS_CO2_PER_KM
    if 0.3 <= kilometres <= 500:
        equivalences.append(Equivalence(
            label=_plural(kilometres, "kilometre driven", "kilometres driven"),
            value=kilometres, kind="carbon",
        ))

    bulb_hours = watt_hours / LED_BULB_WATTS
    if 0.5 <= bulb_hours <= 500:
        equivalences.append(Equivalence(
            label=_plural(bulb_hours, "hour of an LED bulb", "hours of an LED bulb"),
            value=bulb_hours, kind="energy",
        ))

    # Three is the point where a row of comparisons stops clarifying and starts
    # reading as filler. Order matters because of that cut: kilometres driven
    # sits above LED-bulb hours deliberately, since it is the one comparison
    # that crosses into carbon and the one most readers can picture. Built in
    # the other order first, it was always the item that got dropped.
    return equivalences[:3]
