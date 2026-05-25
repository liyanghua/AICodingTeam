"""Import shim for running the cloud asset center from the source tree."""

from pathlib import Path

_BACKEND_PACKAGE = Path(__file__).resolve().parents[1] / "backend" / "mobile_asset_center"
if _BACKEND_PACKAGE.exists():
    __path__.append(str(_BACKEND_PACKAGE))
