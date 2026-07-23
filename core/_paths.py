import os
import sys
from pathlib import Path


def _is_frozen() -> bool:
    return hasattr(sys, "_MEIPASS")


def _bundle_root() -> Path:
    return Path(sys._MEIPASS) if _is_frozen() else Path(__file__).resolve().parent.parent


def _appdata_path(*parts: str) -> Path:
    base = os.environ.get(
        "OCR_TRIGGER_DATA",
        os.path.join(os.environ.get("APPDATA", Path.home()), "ocr-trigger-clicker"),
    )
    return Path(base).joinpath(*parts)


def get_data_path(relative_path: str) -> str:
    p = _appdata_path(relative_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    return str(p)


def get_resource_path(relative_path: str) -> str:
    return str(_bundle_root() / relative_path)
