"""Runtime configuration/snapshot boundary; independent of capture implementations."""
import os

from radioflix.timefree.admission import require_capture_start
from radioflix.timefree.contracts import CaptureAdmission


def capture_admission(capture) -> CaptureAdmission:
    # Local readiness is computed explicitly by the implementation; read its snapshot.
    return CaptureAdmission(
        boot_mode=os.getenv('RADIOFLIX_TIMEFREE_BOOT_MODE', 'disabled'),
        timefree_writes=os.getenv('RADIOFLIX_TIMEFREE_ENABLE_WRITES') == '1',
        ready=getattr(capture, 'ready', False) is True,
        bridge_approved=getattr(capture, 'bridge_approved', False) is True,
    )


def require_runtime_capture(capture) -> None:
    require_capture_start(capture_admission(capture))
