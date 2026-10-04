#!/usr/bin/env bash
# Fire one or more validation generations at a running backend.
#
# The streaming endpoint is used (not /api/generate) because a 4-section
# landing page or a 5-file admin console takes 15-30 minutes, which is past
# the non-streaming client timeout. Artifacts -- including the JPEG evidence
# shots -- are written by the backend's own dumper, so nothing is lost here.
#
# Usage:
#   ./run_validation.sh "prompt text" [business_type] [label]
set -u
PROMPT="${1:?usage: run_validation.sh <prompt> [business_type] [label]}"
BTYPE="${2:-}"
LABEL="${3:-run}"

python - "$PROMPT" "$BTYPE" "$LABEL" <<'PY'
import json, sys, time, urllib.request
# Windows consoles default to cp1252; model summaries contain emoji. Replace
# rather than crash AFTER a successful 20-minute run.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

prompt, btype, label = sys.argv[1], sys.argv[2], sys.argv[3]
body = {
    "prompt": prompt,
    "business_type": btype,
    "features": [],
    "assets": [],
    "brand": {},
    "project_files": [],
    "operation": "create",
    "temperature": 0.7,
    "use_agent": True,
}
req = urllib.request.Request(
    "http://127.0.0.1:8000/api/generate/stream",
    data=json.dumps(body).encode(),
    headers={"Content-Type": "application/json"},
)
t0 = time.perf_counter()
print(f"[{label}] start: {prompt[:80]}", flush=True)
files = 0
summary = ""
with urllib.request.urlopen(req, timeout=5400) as r:
    buf = b""
    while True:
        chunk = r.read1(4096) if hasattr(r, "read1") else r.read(4096)
        if not chunk:
            break
        buf += chunk
        while b"\n\n" in buf:
            line, buf = buf.split(b"\n\n", 1)
            if not line.startswith(b"data: "):
                continue
            try:
                payload = json.loads(line[6:])
            except Exception:
                continue
            if payload.get("conversational") and payload.get("token"):
                tok = payload["token"].strip()
                if tok:
                    print(f"    {tok[:110]}", flush=True)
            if payload.get("error"):
                print(f"    ERROR: {payload['error']}", flush=True)
            if payload.get("done"):
                files = len(payload.get("files") or [])
                summary = payload.get("summary") or ""
print(f"[{label}] done in {time.perf_counter() - t0:.0f}s, {files} files")
print(f"[{label}] {summary}")
PY
