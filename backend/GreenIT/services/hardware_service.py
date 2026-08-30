import os

from GreenIT.collectors.hardware import cpu_info
from GreenIT.collectors.windows import system_identity
from GreenIT.database.hardware_repository import (
    HardwareRepository,
    UnknownMachineModelError,
)
from GreenIT.estimators import generic_calibration
from GreenIT.models.calibration import CalibrationProfile


class HardwareService:
    """
    Resolves the current machine's CalibrationProfile.

    This is the only place in the application that knows how raw machine
    identity (manufacturer + model, from WMI) gets turned into the lookup
    key used by hardware.db. If that key-building logic ever changes
    (e.g. a second field is needed to disambiguate models), it changes
    here only — the repository and the estimators are unaffected.

    Machine identity doesn't change during a running session. Callers
    should resolve this once (e.g. at application startup) and reuse the
    result, rather than calling it on every estimation tick.
    """

    def __init__(self, hardware_repository: HardwareRepository):
        self._hardware_repository = hardware_repository

    def get_current_machine_profile(self) -> CalibrationProfile:
        """
        The calibration profile for this machine, measured if it exists and
        estimated if it does not.

        THE FALLBACK LIVES HERE, NOT IN THE REPOSITORY, on purpose. The
        repository answers "is there a measured profile for this key", and
        raising when there is not is the correct answer to that question —
        see UnknownMachineModelError, which argues the case. Deciding what to
        DO about the absence is a policy question, and policy belongs to the
        service that resolves profiles for the running application.

        The policy: never stop collecting. Before this, an uncalibrated model
        raised out of EstimationLoop.__init__ and killed the collection
        thread, while the dashboard carried on serving a normal-looking page
        that would never fill in. Since the fleet is calibrated model by
        model, every machine is uncalibrated for a while — a newly issued
        laptop should produce labelled estimates in the meantime, not
        silence.
        """
        override = os.environ.get("ECOINSIGHT_MACHINE_KEY")
        if override:
            # Test identities must never be allowed to fall through to the
            # real WMI identity or a matching hardware.db row.
            machine_key = override
            details = {}
        else:
            identity = system_identity.collect()
            machine_key = system_identity.build_machine_key(identity)
            details = cpu_info.get_cpu_info() or {}

        try:
            return self._hardware_repository.get_calibration_profile(machine_key)
        except UnknownMachineModelError:
            pass

        return generic_calibration.estimated_profile(
            machine_model=machine_key,
            cpu_model=details.get("model"),
        )