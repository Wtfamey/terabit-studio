"""Entry point for the PACKAGED backend (PyInstaller bundle).

`uvicorn main:app` is the developer command; a frozen binary cannot be given
an import string, so this file is what the bundle runs. It accepts exactly the
flags the desktop shell passes (`--host`, `--port`), which is the contract in
app/boot.js for `kind: "bundled"`.

Kept deliberately tiny: everything the app does lives in main.py, and a
packaged build should fail loudly at startup rather than half-configure itself
here. `--print-build` exists so the shell can ask a bundle what it is without
starting a server.
"""
from __future__ import annotations

import argparse
import os
import sys


def main() -> int:
    parser = argparse.ArgumentParser(prog="terabit-backend",
                                     description="Terabit Studio local backend")
    parser.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
    parser.add_argument("--log-level", default=os.environ.get("TERABIT_LOG_LEVEL", "info"))
    parser.add_argument("--print-build", action="store_true",
                        help="print build info as JSON and exit")
    args = parser.parse_args()

    if args.print_build:
        import json
        import paths
        print(json.dumps(paths.build_info()))
        return 0

    # Import after parsing so `--print-build` stays instant.
    import uvicorn
    from main import app

    uvicorn.run(app, host=args.host, port=args.port, log_level=args.log_level)
    return 0


if __name__ == "__main__":
    sys.exit(main())
