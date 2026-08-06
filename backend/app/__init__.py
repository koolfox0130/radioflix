
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


_legacy_app_spec = spec_from_file_location(
    "_radioflix_legacy_app", Path(__file__).parent.parent / "app.py"
)
if _legacy_app_spec is None or _legacy_app_spec.loader is None:
    raise ImportError("Unable to load the legacy app module")

_legacy_app_module = module_from_spec(_legacy_app_spec)
_legacy_app_spec.loader.exec_module(_legacy_app_module)

app = _legacy_app_module.app
