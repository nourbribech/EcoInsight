from GreenIT.collectors.windows import system_identity
from GreenIT.database.hardware_repository import HardwareRepository
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
        identity = system_identity.collect()
        machine_key =system_identity.build_machine_key(identity)
        return self._hardware_repository.get_calibration_profile(machine_key)