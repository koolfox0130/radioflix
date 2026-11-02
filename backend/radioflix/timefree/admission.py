"""Pure capture admission policy. No environment reads or runtime preflight."""
from radioflix.timefree.contracts import CaptureAdmission, CaptureNotReady


def require_capture_start(state: CaptureAdmission) -> None:
    if (not isinstance(state, CaptureAdmission) or state.boot_mode != 'enabled'
            or state.timefree_writes is not True or state.ready is not True
            or state.bridge_approved is not True):
        raise CaptureNotReady()
