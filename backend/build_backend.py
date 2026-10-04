"""Build the shippable backend: one folder the installer can copy.

What it produces
----------------
  backend/dist/terabit-backend/
      terabit-backend.exe      <- started by the desktop shell (--host/--port)
      .env.example             <- the knobs, next to the executable
      BUILD.json               <- what this build is (reported by /api/app/env)
      _internal/...            <- Python runtime, deps, registry/, web/

Why one folder rather than one file: a one-file bundle unpacks ~150 MB to a
temp directory on EVERY launch, which turns the app's "start the backend"
phase into a multi-second silence and doubles disk churn. The shell already
starts this with the right flags; see app/boot.js (`kind: "bundled"`).

Usage
-----
    cd backend && python build_backend.py            # build
    cd backend && python build_backend.py --keep     # keep PyInstaller work dir
Then verify it really runs (this is not optional):
    app/scripts/build-backend.js runs the bundle, waits for /api/health and
    reads /api/app/env before it calls the build a success.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parent
REPO = BACKEND.parent
DIST = BACKEND / "dist" / "terabit-backend"
WORK = BACKEND / "build" / "pyinstaller"
ENTRY = BACKEND / "terabit_main.py"

# uvicorn, anyio and SQLAlchemy import parts of themselves dynamically, which
# is exactly the shape a frozen build cannot see. Every one of these was a
# real "works on my machine, ImportError in the bundle" candidate.
HIDDEN_IMPORTS = [
    "uvicorn.logging",
    "uvicorn.loops.auto", "uvicorn.loops.asyncio", "uvicorn.loops.uvloop",
    "uvicorn.protocols.http.auto", "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.http.httptools_impl",
    "uvicorn.protocols.websockets.auto", "uvicorn.protocols.websockets.wsproto_impl",
    "uvicorn.protocols.websockets.websockets_impl",
    "uvicorn.lifespan.on", "uvicorn.lifespan.off", "uvicorn.lifespan.auto",
    "anyio._backends._asyncio",
    "sqlalchemy.dialects.sqlite",
    "email_validator",
    "multipart",
]

# The fine-tuning pipeline shells out to training scripts, and the retrieval
# path is deliberately lexical (see rag_engine.py) -- none of the ML stack is
# imported at runtime. Excluding it keeps the installer at a few hundred MB
# instead of several GB, and turns "why is the download 6 GB" into a
# non-question. If model training is ever needed on the user's machine, it
# stays a source-tree feature.
EXCLUDES = [
    "torch", "torchvision", "torchaudio", "transformers", "unsloth",
    "sentence_transformers", "sklearn", "scipy", "pandas", "matplotlib",
    "datasets", "peft", "trl", "bitsandbytes", "accelerate", "xformers",
    "tkinter", "IPython", "jupyter", "notebook", "pytest", "sphinx",
]


def build_label() -> str:
    version = "unknown"
    try:
        version = json.loads((REPO / "app" / "package.json").read_text(encoding="utf-8"))["version"]
    except Exception:  # noqa: BLE001
        pass
    sha = ""
    try:
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO,
                             capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:  # noqa: BLE001
        pass
    stamp = time.strftime("%Y%m%d-%H%M%S")
    label = f"v{version}+{stamp}" + (f"+{sha}" if sha else "")
    return label


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", action="store_true", help="keep the PyInstaller work dir")
    ap.add_argument("--no-web", action="store_true",
                    help="skip bundling the built frontend (backend only)")
    args = ap.parse_args()

    web = REPO / "frontend" / "dist"
    if not args.no_web and not (web / "index.html").is_file():
        print("frontend/dist is missing. Build it first:\n"
              "    cd frontend && npm install && npm run build", file=sys.stderr)
        return 2

    try:
        import PyInstaller  # noqa: F401
    except Exception:  # noqa: BLE001
        print("PyInstaller is not installed. Run: pip install pyinstaller", file=sys.stderr)
        return 2

    add_data = [f"{BACKEND / 'registry'}{os.pathsep}registry"]
    if not args.no_web:
        add_data.append(f"{web}{os.pathsep}web")
    icon = REPO / "app" / "build" / "icon.ico"
    if icon.is_file():
        add_data.append(f"{icon}{os.pathsep}.")

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--name", "terabit-backend",
        "--onedir", "--console",
        "--distpath", str(DIST.parent),
        "--workpath", str(WORK),
        "--specpath", str(WORK),
        str(ENTRY),
    ]
    for item in add_data:
        cmd += ["--add-data", item]
    for name in HIDDEN_IMPORTS:
        cmd += ["--hidden-import", name]
    for name in EXCLUDES:
        cmd += ["--exclude-module", name]
    if icon.is_file():
        cmd += ["--icon", str(icon)]

    print(f"[build] {' '.join(cmd[:8])} ...")
    started = time.time()
    proc = subprocess.run(cmd, cwd=BACKEND)
    if proc.returncode != 0:
        print(f"[build] PyInstaller failed with exit code {proc.returncode}", file=sys.stderr)
        return proc.returncode

    exe = DIST / ("terabit-backend.exe" if sys.platform == "win32" else "terabit-backend")
    if not exe.is_file():
        print(f"[build] expected binary missing: {exe}", file=sys.stderr)
        return 1

    # Ship the two files a user is allowed to touch, next to the executable
    # (paths.env_file() and paths.build_info() look exactly there).
    example = REPO / ".env.example"
    if example.is_file():
        shutil.copy2(example, DIST / ".env.example")
    (DIST / "BUILD.json").write_text(json.dumps({
        "label": build_label(),
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "python": sys.version.split()[0],
        "platform": sys.platform,
        "archetype": "onedir",
    }, indent=2), encoding="utf-8")

    size_mb = sum(f.stat().st_size for f in DIST.rglob("*") if f.is_file()) / 1e6
    print(f"[build] {DIST}")
    print(f"[build] {exe.name} + {size_mb:.0f} MB of runtime, "
          f"{time.time() - started:.0f}s")
    print("[build] next: node ../app/scripts/build-backend.js --verify")
    if not args.keep:
        shutil.rmtree(WORK, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
