"""Capture durable visual evidence for a generation run.

Every run already saves request/result/generated/design_score JSON under
`backend/comparison/<prompt-slug>/<timestamp>/`, but nothing preserved what the
page actually LOOKED like. This script adds that:

    <run>/preview.html              exact bundled preview (self-contained)
    <run>/screenshots/desktop.jpg   full-height desktop shot  (1440 wide)
    <run>/screenshots/mobile.jpg    mobile shot               (390 wide)
    <run>/screenshots/manifest.json run metadata + capture info

Rendering uses the system Chrome/Edge in headless mode (no extra dependency);
PNG -> JPEG conversion uses Pillow. Safe to re-run: pass --force to overwrite.

Usage:
    python capture_evidence.py --run latest
    python capture_evidence.py --run comparison/casa-verde/20260930-145031
    python capture_evidence.py --all          # every run missing screenshots
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import http.server
import functools
import socketserver

from pathlib import Path

BACKEND = Path(__file__).resolve().parent
COMPARISON = BACKEND / "comparison"

_BROWSERS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]

VIEWPORTS = [
    ("desktop", 1440, 2400),
    ("mobile", 390, 1800),
]


def find_browser() -> str | None:
    for p in _BROWSERS:
        if os.path.exists(p):
            return p
    for name in ("chrome", "google-chrome", "msedge", "chromium"):
        found = shutil.which(name)
        if found:
            return found
    return None


def build_preview_html(files: list[dict]) -> str:
    """Use the running backend when available (includes the preview guard),
    else build in-process so evidence capture works fully offline."""
    import urllib.request

    try:
        req = urllib.request.Request(
            "http://localhost:8000/api/preview",
            data=json.dumps({"files": files}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=300) as r:
            return json.load(r)["html"]
    except Exception:
        import preview_builder

        return preview_builder.build_preview_html(files)


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):  # silence per-request logging
        pass


def serve_dir(directory: Path) -> tuple[str, socketserver.TCPServer, threading.Thread]:
    """Serve `directory` on a free loopback port; returns (base_url, server, thread)."""
    handler = functools.partial(_QuietHandler, directory=str(directory))
    httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return f"http://127.0.0.1:{port}", httpd, t


def shoot(browser: str, url: str, out_png: Path, width: int, height: int) -> bool:
    args = [
        browser,
        "--headless=new",
        "--disable-gpu",
        "--hide-scrollbars",
        "--no-first-run",
        "--disable-extensions",
        "--disable-background-timer-throttling",
        "--force-device-scale-factor=1",
        f"--window-size={width},{height}",
        "--virtual-time-budget=9000",
        f"--screenshot={out_png}",
        url,
    ]
    try:
        subprocess.run(args, capture_output=True, timeout=180, check=False)
    except Exception:
        return False
    return out_png.exists() and out_png.stat().st_size > 0


def to_jpeg(png: Path, jpg: Path, quality: int = 82) -> bool:
    try:
        from PIL import Image

        with Image.open(png) as im:
            im = im.convert("RGB")
            # cap absurd heights so files stay small enough to browse
            if im.height > 6000:
                im = im.crop((0, 0, im.width, 6000))
            im.save(jpg, "JPEG", quality=quality, optimize=True)
        return True
    except Exception:
        return False


def capture_run(run_dir: Path, force: bool = False) -> dict:
    """Capture (or reuse) evidence shots for one run directory."""
    result_path = run_dir / "result.json"
    if not result_path.exists():
        return {"run": str(run_dir), "skipped": "no result.json"}
    out_dir = run_dir / "screenshots"
    manifest_path = out_dir / "manifest.json"
    if manifest_path.exists() and not force:
        return {"run": str(run_dir), "skipped": "already captured"}

    result = json.loads(result_path.read_text(encoding="utf-8"))
    files = result.get("files") or []
    if not files:
        return {"run": str(run_dir), "skipped": "no files"}

    browser = find_browser()
    if not browser:
        return {"run": str(run_dir), "skipped": "no chrome/edge found"}

    html = build_preview_html(files)
    out_dir.mkdir(exist_ok=True)
    preview_path = run_dir / "preview.html"
    preview_path.write_text(html, encoding="utf-8")

    work = Path(tempfile.mkdtemp(prefix="terabit_shot_"))
    (work / "preview.html").write_text(html, encoding="utf-8")
    base, httpd, _ = serve_dir(work)
    shots: dict[str, dict] = {}
    try:
        for name, w, h in VIEWPORTS:
            png = work / f"{name}.png"
            if shoot(browser, f"{base}/preview.html", png, w, h):
                jpg = out_dir / f"{name}.jpg"
                if to_jpeg(png, jpg):
                    shots[name] = {
                        "path": f"screenshots/{name}.jpg",
                        "viewport": f"{w}x{h}",
                        "bytes": jpg.stat().st_size,
                    }
    finally:
        httpd.shutdown()
        shutil.rmtree(work, ignore_errors=True)

    design = {}
    ds = run_dir / "design_score.json"
    if ds.exists():
        try:
            design = json.loads(ds.read_text(encoding="utf-8"))
        except Exception:
            design = {}
    request_meta = {}
    rq = run_dir / "request.json"
    if rq.exists():
        try:
            request_meta = json.loads(rq.read_text(encoding="utf-8"))
        except Exception:
            request_meta = {}

    manifest = {
        "run": run_dir.name,
        "slug": run_dir.parent.name,
        "prompt": (request_meta.get("prompt") or "")[:400],
        "wall_s": result.get("wall_s"),
        "bundle_ok": result.get("bundle_ok"),
        "preview_tier": result.get("preview_tier"),
        "design_gate": design.get("gate"),
        "palette_adherence": design.get("palette_adherence"),
        "theme": design.get("theme"),
        "files": [f.get("path") for f in files],
        "shots": shots,
        "preview_html": "preview.html",
        "captured_with": Path(browser).name,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return {"run": str(run_dir), "shots": list(shots), "manifest": str(manifest_path)}


def build_gallery(out_path: Path | None = None) -> Path:
    """Write a single browsable index.html over every captured run so the
    evidence library can be reviewed side by side (and screenshotted)."""
    out_path = out_path or (COMPARISON / "gallery.html")
    cards = []
    for run in iter_runs():
        mp = run / "screenshots" / "manifest.json"
        if not mp.exists():
            continue
        try:
            m = json.loads(mp.read_text(encoding="utf-8"))
        except Exception:
            continue
        rel = f"{run.parent.name}/{run.name}"
        shots = m.get("shots") or {}
        desk = shots.get("desktop") or {}
        mob = shots.get("mobile") or {}
        gate = m.get("design_gate")
        gate_cls = "ok" if str(gate).lower() in ("pass", "true") else "warn"
        cards.append(
            {
                "slug": m.get("slug") or run.parent.name,
                "run": m.get("run") or run.name,
                "prompt": (m.get("prompt") or "").strip(),
                "wall": m.get("wall_s"),
                "tier": m.get("preview_tier"),
                "gate": gate,
                "gate_cls": gate_cls,
                "palette": m.get("palette_adherence"),
                "theme": m.get("theme"),
                "n_files": len(m.get("files") or []),
                "shots": sorted(shots),
                "desk": f"{rel}/{desk.get('path')}" if desk.get("path") else None,
                "mob": f"{rel}/{mob.get('path')}" if mob.get("path") else None,
                "preview": f"{rel}/preview.html",
                "mtime": run.stat().st_mtime,
            }
        )
    cards.sort(key=lambda c: c["mtime"], reverse=True)
    rows = []
    for c in cards:
        prompt = (c["prompt"][:220] + "...") if len(c["prompt"]) > 220 else c["prompt"]
        imgs = ""
        if c["desk"]:
            imgs += f'<a href="{c["desk"]}" target="_blank"><img loading="lazy" src="{c["desk"]}" alt="desktop"></a>'
        if c["mob"]:
            imgs += f'<a href="{c["mob"]}" target="_blank"><img loading="lazy" class="mob" src="{c["mob"]}" alt="mobile"></a>'
        rows.append(f"""<article class="card">
  <header>
    <div class="title">{c['slug']} <span class="ts">{c['run']}</span></div>
    <div class="meta">wall {c['wall']}s · tier {c['tier']} · <span class="gate {c['gate_cls']}">gate {c['gate']}</span> · palette {c['palette']} · {c['theme']} · {c['n_files']} files</div>
  </header>
  <p class="prompt">{prompt}</p>
  <div class="shots">{imgs}</div>
  <a class="open" href="{c['preview']}" target="_blank">open preview ›</a>
</article>""")
    ui_section = _ui_section()
    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Terabit Studio — run evidence gallery</title>
<style>
  :root {{ color-scheme: dark; }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; background:#0b0f19; color:#e5e7eb; font:14px/1.5 ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,sans-serif; }}
  h1 {{ font-size:20px; margin:0; }}
  .top {{ position:sticky; top:0; z-index:5; padding:16px 24px; background:rgba(11,15,25,.9); backdrop-filter:blur(8px); border-bottom:1px solid #1f2937; display:flex; justify-content:space-between; align-items:baseline; }}
  .top .sub {{ color:#94a3b8; font-size:13px; }}
  .grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(560px,1fr)); gap:20px; padding:24px; }}
  .card {{ background:#111827; border:1px solid #1f2937; border-radius:14px; overflow:hidden; display:flex; flex-direction:column; }}
  .card header {{ padding:14px 16px 6px; }}
  .title {{ font-weight:600; }}
  .ts {{ color:#64748b; font-weight:400; font-size:12px; }}
  .meta {{ color:#94a3b8; font-size:12px; margin-top:2px; }}
  .gate {{ padding:1px 6px; border-radius:6px; }}
  .gate.ok {{ background:#052e1a; color:#4ade80; }}
  .gate.warn {{ background:#3b1d0d; color:#fbbf24; }}
  .prompt {{ margin:6px 16px; color:#cbd5e1; font-size:12.5px; }}
  .shots {{ display:flex; gap:10px; padding:8px 16px 14px; align-items:flex-start; }}
  .shots img {{ width:100%; height:420px; object-fit:cover; object-position:top; border:1px solid #1f2937; border-radius:8px; background:#020617; }}
  .shots img.mob {{ width:150px; min-width:150px; }}
  .shots a {{ flex:1; }}
  .shots a:has(img.mob) {{ flex:0 0 auto; }}
  .open {{ margin:0 16px 16px; align-self:flex-start; color:#60a5fa; text-decoration:none; font-size:13px; }}
  .uigrid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(360px,1fr)); gap:20px; padding:0 24px 24px; }}
  .uigrid img {{ width:100%; height:260px; object-fit:cover; object-position:top; border:1px solid #1f2937; border-radius:8px; background:#020617; }}
  h2.sec {{ padding:8px 24px 0; font-size:16px; color:#c4b5fd; }}
</style></head>
<body>
  <div class="top">
    <h1>Terabit Studio — run evidence</h1>
    <div class="sub">{len(cards)} runs · JPEG desktop + mobile · newest first</div>
  </div>
  <div class="grid">
{chr(10).join(rows)}
  </div>
{ui_section}
</body></html>"""
    out_path.write_text(html, encoding="utf-8")
    return out_path


def _ui_section() -> str:
    """HTML block showing the app's own UI evidence (backend/comparison/ui/*)."""
    ui_root = COMPARISON / "ui"
    if not ui_root.exists():
        return ""
    shots = []
    for stamp in sorted(ui_root.iterdir(), reverse=True):
        if not stamp.is_dir():
            continue
        for jpg in sorted(stamp.glob("*.jpg")):
            rel = f"ui/{stamp.name}/{jpg.name}"
            shots.append(
                f'<figure><a href="{rel}" target="_blank">'
                f'<img loading="lazy" src="{rel}" alt="{jpg.stem}"></a>'
                f'<figcaption>{stamp.name} · {jpg.stem}</figcaption></figure>'
            )
    if not shots:
        return ""
    return (
        '<h2 class="sec">Terabit Studio app UI (own interface)</h2>'
        f'<div class="uigrid">{chr(10).join(shots)}</div>'
    )


def iter_runs() -> list[Path]:
    runs = []
    for slug in sorted(COMPARISON.iterdir()) if COMPARISON.exists() else []:
        if not slug.is_dir():
            continue
        for ts in sorted(slug.iterdir()):
            if ts.is_dir() and (ts / "result.json").exists():
                runs.append(ts)
    return runs


def main() -> int:
    ap = argparse.ArgumentParser(description="Save JPEG evidence of a run's preview.")
    ap.add_argument("--run", help="run dir, or 'latest' for the newest run")
    ap.add_argument("--all", action="store_true", help="capture every run missing shots")
    ap.add_argument("--force", action="store_true", help="overwrite existing shots")
    ap.add_argument("--gallery", action="store_true", help="rebuild comparison/gallery.html and exit")
    args = ap.parse_args()

    if args.gallery:
        print(json.dumps({"gallery": str(build_gallery())}))
        return 0

    targets: list[Path] = []
    if args.all:
        targets = iter_runs()
    elif args.run:
        if args.run == "latest":
            runs = iter_runs()
            if not runs:
                print("no runs found")
                return 1
            targets = [max(runs, key=lambda p: p.stat().st_mtime)]
        else:
            p = Path(args.run)
            targets = [p if p.is_absolute() else (BACKEND / p if (BACKEND / p).exists() else Path.cwd() / p)]
    else:
        ap.print_help()
        return 2

    rc = 0
    for t in targets:
        info = capture_run(t, force=args.force)
        print(json.dumps(info, ensure_ascii=False))
        if info.get("skipped"):
            rc = 0 if info["skipped"] in ("already captured",) else rc
    if targets and not args.run:
        print(json.dumps({"gallery": str(build_gallery())}))
    return rc


if __name__ == "__main__":
    sys.exit(main())
