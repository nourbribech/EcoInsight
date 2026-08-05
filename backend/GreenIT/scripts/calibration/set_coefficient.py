"""
Manually set a single calibration coefficient — for values sourced from
literature rather than local measurement (e.g. RAM, where the real power
delta is smaller than this laptop's battery sensor noise floor). Leaves
every other coefficient untouched.


"""

from collectors.windows import system_identity
from scripts.calibration.calibration_db import update_fields

VALID_FIELDS = [
    "cpu_watts_per_percent_usage",
    "ram_watts_per_gb_used",
    "baseline_watts",
]


def main() -> None:
    identity = system_identity.collect()
    machine_key = system_identity.build_machine_key(identity)

    print(f"Machine: {machine_key}")
    print("Fields: " + ", ".join(VALID_FIELDS))
    field = input("Field to set: ").strip()
    if field not in VALID_FIELDS:
        raise ValueError(f"Unknown field: {field!r}")

    value = float(input("Value: ").strip())
    notes = input("Source / notes (e.g. citation): ").strip()

    update_fields(machine_key, {field: value}, notes=notes)
    print(f"Saved {field}={value} for {machine_key}")


if __name__ == "__main__":
    main()