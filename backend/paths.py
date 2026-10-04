"""Where the app's data and web assets live -- frozen or from source.

A packaged build is not a source checkout: `__file__` points inside the
PyInstaller bundle, the working directory is wherever the user launched the
.exe from, and the tree next to the code is read-only-ish. Three things have
to keep working without a repo:

  * the SQLite database and the uploads folder -- mutable user data, so they
    belong in the app's own folder, not in the bundle's internal one;
  * the built web UI -- read-only assets, shipped inside the bundle as `web/`;
  * the `.env` -- user-editable configuration, looked up next to the exe.

Everything is overridable, because a portable install and a "keep my data on
D:" install are both reasonable asks: TERABIT_DATA_DIR, TERABIT_WEB_DIR.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_dir() -> Path:
    """The folder the program runs from: the exe's folder, else backend/."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _env_path(name: str) -> Path | None:
    raw = os.environ.get(name)
    return Path(raw).expanduser().resolve() if raw else None


def data_dir() -> Path:
    """Mutable data: SQLite DB, uploads, backups. Created on demand."""
    override = _env_path("TERABIT_DATA_DIR")
    target = override or app_dir()
    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError:
        # A read-only install still has to boot; the OS temp dir is the last
        # resort, and /api/app/env reports the directory so it is diagnosable.
        import tempfile
        target = Path(tempfile.gettempdir()) / "terabit-studio"
        target.mkdir(parents=True, exist_ok=True)
    return target


def web_dir() -> Path | None:
    """The built frontend (index.html + assets), wherever it was shipped."""
    candidates: list[Path] = []
    override = _env_path("TERABIT_WEB_DIR")
    if override:
        candidates.append(override)
    if is_frozen():
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(Path(meipass) / "web")
        candidates += [
            app_dir() / "web",
            app_dir().parent / "web",
            app_dir().parent / "frontend" / "dist",
        ]
    else:
        candidates.append(Path(__file__).resolve().parents[1] / "frontend" / "dist")
        candidates.append(app_dir() / "web")
    for candidate in candidates:
        if (candidate / "index.html").is_file():
            return candidate
    return candidates[0] if candidates else None


def env_file() -> Path:
    """The .env the user is expected to edit (next to the exe when frozen)."""
    return app_dir() / ".env"


def build_info() -> dict:
    """What this binary is, so /api/app/env can answer "which build am I on?".

    The build script writes BUILD.json next to the executable. Without it
    (a source run) the answer is honest about being a source run rather than
    pretending to be a release.
    """
    import json

    override = os.environ.get("TERABIT_BUILD")
    if override:
        return {"label": override, "source": "env"}
    info_file = app_dir() / "BUILD.json"
    try:
        data = json.loads(info_file.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except (OSError, ValueError):
        pass
    return {"label": "source", "source": "none"}
