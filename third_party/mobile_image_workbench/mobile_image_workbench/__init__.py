"""Import shim for running the workbench from the source tree."""

from pathlib import Path

_BACKEND_PACKAGE = Path(__file__).resolve().parents[1] / "backend" / "mobile_image_workbench"
if _BACKEND_PACKAGE.exists():
    __path__.append(str(_BACKEND_PACKAGE))
