import json
import re
import hashlib
import subprocess
import tempfile
from pathlib import Path

JS_EXTENSIONS = (".js", ".jsx", ".ts", ".tsx", ".mjs")
IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico", ".avif", ".bmp")

# Cold esbuild + Tailwind CLI on Windows was measured timing out at its
# previous 20s/25s limits even when it would have succeeded given more time
# (first run pays node startup + module resolution). 60s covers the measured
# cold path; a build cache (below) makes warm builds ~instant.
TOOLCHAIN_TIMEOUT_TAILWIND = 60
TOOLCHAIN_TIMEOUT_ESBUILD = 60

# Only rebuild when the input files actually changed (hash of sorted
# path:content pairs). Prevents paying 20-60s on every preview refresh.
_CACHE_ROOT = Path(tempfile.gettempdir()) / "terabit_preview_cache"

# ───────────────────────────────────────────────────────────────────────────
# Why this file was rewritten
# ───────────────────────────────────────────────────────────────────────────
# The previous bundler hand-rolled regexes to turn `import`/`export` into
# reads/writes on a `__modules__` object, then executed every file once in a
# forced topological order. That breaks in a lot of ordinary cases a 7B model
# actually produces:
#   - multi-line imports, imports with inline comments, `export * from`,
#     `export { x as y }`, type-only imports -> the regexes simply don't
#     match, so the file silently keeps its raw `import`/`export` keywords,
#     which throws a hard SyntaxError in the injected <script>.
#   - only 4 packages were ever registered (react, react-dom,
#     react-router-dom, lucide-react). Any other import - axios, zustand,
#     date-fns, framer-motion, recharts, clsx, react-hook-form, etc, all
#     extremely normal in a generated business app - silently resolved to
#     `{}`, so the component using it crashed with a cryptic
#     "X is not a function".
#   - image imports (`import logo from './logo.png'`) and CSS Modules
#     (`import styles from './x.module.css'`) had no handling at all.
#   - a single `try/catch` around the whole run meant the FIRST error of any
#     kind blanked out the entire preview with no detail on the real cause.
#
# This version keeps the same "no real bundler" constraint (we're in an
# iframe with no build step) but fixes the above by:
#   1. Letting Babel Standalone's official `transform-modules-commonjs`
#      plugin do the import/export rewriting instead of hand-written
#      regexes - it correctly handles every syntax edge case above.
#   2. Implementing a tiny, lazy, Node-style `require()` in the browser
#      (module cache + on-demand execution) instead of a forced
#      pre-execution order, so load order/circular imports can't break it.
#   3. Resolving ANY bare package import at runtime via esm.sh instead of a
#      hardcoded allowlist of 4 packages.
#   4. Special-casing image imports (-> a stable placeholder URL), CSS/CSS
#      Module imports (-> bundled into <style> + an identity class map),
#      and JSON imports (-> JSON.parse'd).
#   5. Adding a visible in-iframe error overlay fed by window.onerror /
#      unhandledrejection, so failures show a real message instead of a
#      blank white screen.
#   6. Best-effort forwarding of the project's own tailwind.config.js
#      `theme` block into the Tailwind CDN build, so custom colors/fonts
#      the model defined actually show up in the preview.
# ───────────────────────────────────────────────────────────────────────────

_ANY_IMPORT_SPEC = re.compile(
    r'''import\s+(?:[^'";]+?from\s+)?['"]([^'"]+)['"]'''
    r'''|(?<![.\w])require\(\s*['"]([^'"]+)['"]\s*\)'''
    r'''|import\(\s*['"]([^'"]+)['"]\s*\)'''
)

UNSPLASH_IDS = [
    "1506744038136-46273834b3fb", "1517694712202-14dd9538aa97",
    "1551288049-bebda4e38f71", "1497366216548-37526070297c",
    "1556761175-b413da4baf72", "1504384308090-c894fdcc538d",
    "1522071820081-009f3b6b01b1", "1519389950473-47ba0277781c",
    "1454165804606-c3d57bc86b40", "1507003212552-3f11eab7bf6d",
    "1504639725590-34d0984388bd", "1498050108023-c5249f4df085",
    "1517245386807-bb43f82c33c4", "1553877522-43269d4ea984",
    "1522202176988-66273c2e55e9", "1486312338219-ce68d2c6f44d",
]


def _norm(path: str) -> str:
    parts: list[str] = []
    for p in path.replace("\\", "/").split("/"):
        if p in ("", "."):
            continue
        if p == "..":
            if parts:
                parts.pop()
        else:
            parts.append(p)
    return "/".join(parts)


def _resolve(importer: str, spec: str, existing: set) -> str | None:
    base_dir = "/".join(importer.split("/")[:-1])
    combined = _norm(f"{base_dir}/{spec}" if base_dir else spec)
    if combined in existing:
        return combined
    for ext in JS_EXTENSIONS + (".css",):
        if combined + ext in existing:
            return combined + ext
    for ext in JS_EXTENSIONS:
        cand = f"{combined}/index{ext}"
        if cand in existing:
            return cand
    return None


def _all_import_specs(content: str) -> list[str]:
    specs = []
    for m in _ANY_IMPORT_SPEC.finditer(content):
        spec = m.group(1) or m.group(2) or m.group(3)
        if spec:
            specs.append(spec)
    return specs


def _placeholder_image_url(spec: str) -> str:
    idx = int(hashlib.md5(spec.encode()).hexdigest(), 16) % len(UNSPLASH_IDS)
    return f"https://images.unsplash.com/photo-{UNSPLASH_IDS[idx]}?w=800&q=80"


def _css_class_map(css_content: str) -> dict:
    names = re.findall(r'\.([a-zA-Z_][\w-]*)\s*[{,:]', css_content)
    return {name: name for name in dict.fromkeys(names)}


def _find_entry(file_map: dict, existing: set) -> str | None:
    js_paths = [p for p in file_map if p.endswith(JS_EXTENSIONS)]
    if not js_paths:
        return None

    render_call = re.compile(r'createRoot\s*\(|ReactDOM\.render\s*\(|hydrateRoot\s*\(')
    render_candidates = [p for p in js_paths if render_call.search(file_map[p])]
    if len(render_candidates) == 1:
        return render_candidates[0]

    preferred = [
        "src/main.tsx", "src/main.jsx", "src/main.ts", "src/main.js",
        "src/index.tsx", "src/index.jsx", "src/index.ts", "src/index.js",
        "main.tsx", "main.jsx", "index.tsx", "index.jsx",
    ]
    for p in preferred:
        if p in existing:
            return p

    if render_candidates:
        return render_candidates[0]

    imported: set = set()
    for p in js_paths:
        for spec in _all_import_specs(file_map[p]):
            if spec.startswith("."):
                r = _resolve(p, spec, existing)
                if r:
                    imported.add(r)
    roots = [p for p in js_paths if p not in imported]
    if roots:
        return sorted(roots, key=lambda p: -len(file_map[p]))[0]
    return js_paths[0]


def _extract_title(html: str | None) -> str:
    if html:
        m = re.search(r"<title>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
        if m:
            return _esc(m.group(1).strip())
    return "Preview"


def _extract_tailwind_theme(config_content: str | None) -> str | None:
    """Best-effort lift of the `theme: {...}` block out of the project's own
    tailwind.config.* so custom colors/fonts show up in the CDN preview too.
    Not a JS parser - just brace-matches - so if it grabs something that
    isn't valid standalone JS, the injected <script> just no-ops (wrapped in
    try/catch below) and the preview falls back to default Tailwind."""
    if not config_content:
        return None
    idx = config_content.find("theme")
    if idx == -1:
        return None
    brace_start = config_content.find("{", idx)
    if brace_start == -1:
        return None
    depth = 0
    for i in range(brace_start, len(config_content)):
        ch = config_content[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return config_content[brace_start:i + 1]
    return None


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_ROOT = WORKSPACE_ROOT / "frontend"
PREVIEW_WORK_ROOT = FRONTEND_ROOT / ".preview-work"


def _safe_preview_path(path: str) -> str | None:
    normalized = _norm(path)
    if not normalized or normalized.startswith("../") or ":" in normalized:
        return None
    return normalized


def _try_local_bundle(files: list[dict]) -> str | None:
    """Compile a generated React project with the installed local toolchain.

    The former preview depended on unpkg, esm.sh and Tailwind's CDN.  Besides
    failing offline, that made preview fidelity dependent on unrelated remote
    services.  This uses the project's checked-in npm dependencies only and
    returns a self-contained iframe document.
    """
    entry_candidates = [
        "src/main.jsx", "src/main.tsx", "src/main.js", "src/main.ts",
        "src/index.jsx", "src/index.tsx", "src/index.js", "src/index.ts",
    ]
    file_map = {
        safe: str(item.get("content", ""))
        for item in files
        if (safe := _safe_preview_path(str(item.get("path", ""))))
    }
    entry = next((candidate for candidate in entry_candidates if candidate in file_map), None)
    esbuild = FRONTEND_ROOT / "node_modules" / "esbuild" / "bin" / "esbuild"
    tailwind = FRONTEND_ROOT / "node_modules" / "tailwindcss" / "lib" / "cli.js"
    if not entry or not esbuild.exists() or not tailwind.exists():
        return None

    PREVIEW_WORK_ROOT.mkdir(exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(dir=PREVIEW_WORK_ROOT, prefix="build-") as temp_dir:
            project_dir = Path(temp_dir) / "project"
            project_dir.mkdir()
            for path, content in file_map.items():
                destination = project_dir / path
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text(content, encoding="utf-8")

            # If the model didn't generate its own tailwind.config.js, write a
            # minimal one. Tailwind's CLI needs a content glob to know what to
            # scan for utility classes - the previous version built that glob
            # from an absolute Windows Path (`project_dir / "**/*.{...}"`),
            # which produces backslashes. Tailwind's glob matcher does not
            # reliably treat `\**\*.{...}` as a recursive wildcard, so it was
            # very likely matching zero files: the subprocess call would still
            # *succeed* (exit 0), so this wasn't raising the exception that
            # would trigger the tier-2 fallback - it was silently producing a
            # "working" preview containing only Tailwind's unstyled
            # preflight/reset CSS, no utility classes at all. That would look
            # exactly like the "lame, basic" output being reported, on any
            # generation where this tier succeeded. Writing a relative,
            # forward-slash, cwd-relative glob into an actual config file
            # sidesteps the Windows path issue entirely.
            if "tailwind.config.js" not in file_map and "tailwind.config.cjs" not in file_map:
                (project_dir / "tailwind.config.js").write_text(
                    "module.exports = { content: ['./**/*.{html,js,jsx,ts,tsx}'], theme: { extend: {} }, plugins: [] };\n",
                    encoding="utf-8",
                )

            input_css = project_dir / "__preview_input.css"
            input_css.write_text("@tailwind base;\n@tailwind components;\n@tailwind utilities;\n", encoding="utf-8")
            tailwind_css = project_dir / "preview-tailwind.css"
            subprocess.run(
                ["node", str(tailwind), "-i", str(input_css), "-o", str(tailwind_css)],
                cwd=project_dir,
                capture_output=True,
                text=True,
                timeout=TOOLCHAIN_TIMEOUT_TAILWIND,
                check=True,
            )
            output_js = project_dir / "preview-bundle.js"
            output_css = project_dir / "preview-bundle.css"
            subprocess.run(
                ["node", str(esbuild), entry, "--bundle", "--format=iife", "--platform=browser", f"--outfile={output_js}", f"--loader:.js=jsx", "--loader:.jsx=jsx", "--loader:.ts=ts", "--loader:.tsx=tsx"],
                cwd=project_dir,
                capture_output=True,
                text=True,
                timeout=TOOLCHAIN_TIMEOUT_ESBUILD,
                check=True,
            )
            css = tailwind_css.read_text(encoding="utf-8")
            if output_css.exists():
                css += "\n" + output_css.read_text(encoding="utf-8")
            bundle = output_js.read_text(encoding="utf-8").replace("</script", "<\\/script")
            title = _extract_title(file_map.get("index.html"))
            return f"""<!doctype html><html><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>{title}</title><style>{css}</style></head><body><div id=\"root\"></div><script>{bundle}</script></body></html>"""
    except (OSError, subprocess.SubprocessError, UnicodeError) as exc:
        stderr = getattr(exc, "stderr", None)
        print(f"[preview] local compilation failed: {exc}" + (f"\n{stderr}" if stderr else ""))
        return None


# Click-guard injected into every previewed document. The preview iframe is
# rendered from srcDoc with allow-same-origin, so the generated page inherits
# the STUDIO's origin: clicking an in-page anchor ("Reserve a table",
# "View menu", nav links) navigated the iframe itself to the parent app URL
# (localhost:5173/builder#...) -- i.e. clicking a button inside the preview
# loaded the whole TerabitStudio UI into the preview. This guard converts
# hash links into smooth scrolls, blocks same-origin navigations from plain
# links and bare form submits, and opens external links in a real tab.
_PREVIEW_GUARD_JS = """<script>(function () {
  if (window.__terabitGuard) return; window.__terabitGuard = 1;
  var BASE = 'http://terabit-preview.invalid/';
  document.addEventListener('click', function (e) {
    var el = e.target;
    while (el && el.nodeType === 1 && el.tagName !== 'A') el = el.parentNode;
    if (!el || el.nodeType !== 1) return;
    var href = el.getAttribute('href') || '';
    if (href.charAt(0) === '#') {
      e.preventDefault();
      var id = href.slice(1);
      if (!id) { try { window.scrollTo({ top: 0, behavior: 'smooth' }); } catch (_) { window.scrollTo(0, 0); } return; }
      var t = null;
      try { t = document.getElementById(id) || document.getElementsByName(id)[0]; } catch (_) {}
      if (t && t.scrollIntoView) { try { t.scrollIntoView({ behavior: 'smooth', block: 'start' }); } catch (_) { t.scrollIntoView(); } }
      return;
    }
    var u = null;
    try { u = new URL(href, BASE); } catch (_) { return; }
    if (u.origin === 'http://terabit-preview.invalid') { e.preventDefault(); return; }
    if (u.protocol === 'http:' || u.protocol === 'https:') {
      e.preventDefault();
      try { window.open(u.href, '_blank'); } catch (_) {}
    }
  }, true);
  document.addEventListener('submit', function (e) {
    var f = e.target;
    if (!f || f.tagName !== 'FORM') return;
    var act = (f.getAttribute('action') || '');
    if (!act || act.charAt(0) === '#') e.preventDefault();
  }, true);
})();</script>"""


def _inject_preview_guard(html: str) -> str:
    if "__terabitGuard" in html:
        return html
    for anchor in ("</head>", "</body>"):
        if anchor in html:
            return html.replace(anchor, _PREVIEW_GUARD_JS + anchor, 1)
    return _PREVIEW_GUARD_JS + html


def build_preview_html(files: list[dict]) -> str:
    """Three-tier preview strategy, each tier a strict fallback of the last:

      0. disk cache keyed on file-content hash - warm rebuilds are instant
         and unaffected by toolchain flakiness.
      1. _try_local_bundle - real esbuild + Tailwind CLI from this project's
         own node_modules. Best fidelity, works offline, but depends on the
         local Node toolchain being reachable from this Python process
         (PATH, working directory, etc) - which is exactly the kind of thing
         that can silently differ between an interactive terminal and a
         background job.
      2. _build_cdn_preview - Babel Standalone + esm.sh/unpkg, executed
         entirely client-side in the iframe. Needs internet in the browser,
         not on the backend, so it's a good fallback specifically because its
         failure mode is independent of tier 1's.
      3. _build_fallback_preview - static file listing. Last resort only:
         genuinely no JS files, or both bundling strategies failed.

    Previously, any failure in tier 1 jumped straight to tier 3 - which is
    why preview was working "sometimes": whenever the local Node toolchain
    call failed for any reason (and its actual error was only ever printed
    to a buffered background job's output, never surfaced anywhere visible),
    every project with JS files silently downgraded to a non-functional file
    listing, with nothing in the UI indicating why.
    """
    if not files:
        return _build_fallback_preview(files)

    # Content-hash cache: identical file sets hit an in-memory path (fast)
    # then a disk cache (survives backend restarts).
    digest = hashlib.sha256(
        "\n".join(sorted(f"{f.get('path', '')}:{f.get('content', '')}" for f in files)).encode("utf-8")
    ).hexdigest()

    cached = _CACHE_ROOT / f"{digest}.html"
    if cached.exists():
        try:
            html = cached.read_text(encoding="utf-8")
            if html:
                print(f"[preview] cache hit ({digest[:12]})")
                return html
        except OSError:
            pass

    html = _try_local_bundle(files)
    if html:
        _write_cache(cached, html)
        print(f"[preview] tier1-bundled ({len(files)} files)")
        return _inject_preview_guard(html)

    print("[preview] local bundling unavailable -> CDN tier-2")
    html = _build_cdn_preview(files)
    if html:
        _write_cache(cached, html)
        print(f"[preview] tier {preview_tier(html)}")
    return _inject_preview_guard(html)


# Markers ONLY the CDN tier emits. Deliberately NOT a bare `"babel" in html`
# check: every esbuild bundle can contain the word "babel" because esbuild's
# own __toESM interop helper carries a comment ("...converted to a CommonJS
# file using a Babel-compatible transform..."). That false positive graded
# real tier-1 previews as tier-2-cdn in the eval harness -- i.e. it silently
# scored S6 ("tier-1 build") as a failure for perfectly good generations.
_CDN_MARKERS = ("unpkg.com/@babel/standalone", "esm.sh/")


def preview_tier(html: str) -> str:
    """Classify a built preview document:

      tier1-bundled   real esbuild + Tailwind output inlined (works offline)
      tier2-cdn       Babel-standalone/esm.sh client-side fallback
      tier3-fallback  static file listing (generation unrenderable)

    Single source of truth for the eval harness, /api/selftest and the UI.
    """
    if not html or "<script" not in html:
        return "tier3-fallback"
    if any(marker in html for marker in _CDN_MARKERS):
        return "tier2-cdn"
    return "tier1-bundled"


def _write_cache(path: Path, html: str) -> None:
    """Best-effort cache write; cache failures must never break preview."""
    try:
        _CACHE_ROOT.mkdir(parents=True, exist_ok=True)
        path.write_text(html, encoding="utf-8")
    except OSError as exc:
        print(f"[preview] cache write skipped: {exc}")


def _build_cdn_preview(files: list[dict]) -> str:
    file_map = {f["path"]: f["content"] for f in files}
    js_paths = [p for p in file_map if p.endswith(JS_EXTENSIONS)]

    if not js_paths:
        html_content = file_map.get("index.html") or file_map.get("public/index.html")
        if html_content:
            return html_content
        return _build_fallback_preview(files)

    existing = set(file_map.keys())

    css_bundle = "\n".join(
        f"/* {p} */\n{c}" for p, c in file_map.items() if p.endswith(".css")
    )
    css_class_maps = {p: _css_class_map(c) for p, c in file_map.items() if p.endswith(".css")}

    entry = _find_entry(file_map, existing)
    if entry is None:
        return _build_fallback_preview(files)

    bare_specs: set = set()
    resolve_map: dict = {}
    for p in js_paths:
        m: dict = {}
        for spec in _all_import_specs(file_map[p]):
            if spec in m:
                continue
            if spec.startswith("."):
                resolved = _resolve(p, spec, existing)
                if resolved:
                    m[spec] = {"kind": "file", "key": resolved}
                elif spec.lower().endswith(IMAGE_EXTENSIONS):
                    m[spec] = {"kind": "asset", "key": _placeholder_image_url(spec)}
                else:
                    m[spec] = {"kind": "missing", "key": spec}
            else:
                m[spec] = {"kind": "external", "key": spec}
                bare_specs.add(spec)
        resolve_map[p] = m

    title = _extract_title(file_map.get("index.html") or file_map.get("public/index.html"))

    tw_config = file_map.get("tailwind.config.js") or file_map.get("tailwind.config.ts") or file_map.get("tailwind.config.cjs")
    tw_theme = _extract_tailwind_theme(tw_config)
    tw_config_script = (
        f'<script>try {{ tailwind.config = {{ theme: {tw_theme} }}; }} catch (e) {{ console.warn("Tailwind config skipped:", e); }}</script>'
        if tw_theme else ""
    )

    sources_json = json.dumps(file_map).replace("</script", "<\\/script")
    resolve_json = json.dumps(resolve_map).replace("</script", "<\\/script")
    css_maps_json = json.dumps(css_class_maps).replace("</script", "<\\/script")
    entry_json = json.dumps(entry)
    bare_json = json.dumps(sorted(bare_specs))

    head = f"""<script crossorigin src="https://unpkg.com/react@18/umd/react.production.min.js"></script>
<script crossorigin src="https://unpkg.com/react-dom@18/umd/react-dom.production.min.js"></script>
<script src="https://unpkg.com/@babel/standalone/babel.min.js"></script>
<script src="https://cdn.tailwindcss.com"></script>
{tw_config_script}"""

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1.0"/>
<title>{title}</title>
{head}
<style id="__css_bundle__">{css_bundle}</style>
<style>
  #__preview_error_overlay__ {{ display:none; position:fixed; inset:0; z-index:99999; background:rgba(10,14,26,.97); color:#fca5a5; font-family:ui-monospace,Menlo,Consolas,monospace; font-size:13px; padding:24px; overflow:auto; white-space:pre-wrap; line-height:1.6; }}
  #__preview_error_overlay__ h2 {{ color:#f87171; font-size:14px; margin:0 0 12px; font-family:system-ui,sans-serif; }}
  #__preview_error_overlay__ .hint {{ color:#64748b; font-size:11px; margin-top:16px; font-family:system-ui,sans-serif; }}
</style>
</head>
<body>
<div id="root"></div>
<div id="__preview_error_overlay__"></div>
<script id="__sources__" type="application/json">{sources_json}</script>
<script id="__resolve_map__" type="application/json">{resolve_json}</script>
<script id="__css_maps__" type="application/json">{css_maps_json}</script>
<script type="module">
const ENTRY = {entry_json};
const BARE_SPECS = {bare_json};
{_RUNTIME_JS}
</script>
<!-- Preview health check -->
<script>
  // Check if iframe can load external resources
  setTimeout(() => {{
    try {{
      fetch('https://esm.sh/react@18.3.1?deps=react@18.3.1,react-dom@18.3.1&bundle', {{method: 'HEAD', mode: 'no-cors'}}).catch(() => {{
        console.warn('[Preview] Network may be blocked - external resources might fail');
      }});
    }} catch (e) {{
      console.warn('[Preview] Network check failed:', e);
    }}
  }}, 1000);
</script>
</body>
</html>"""


_RUNTIME_JS = r"""
const sources = JSON.parse(document.getElementById('__sources__').textContent);
const resolveMap = JSON.parse(document.getElementById('__resolve_map__').textContent);
const cssMaps = JSON.parse(document.getElementById('__css_maps__').textContent);

const overlay = document.getElementById('__preview_error_overlay__');
function showError(title, detail) {
  // Forward to the parent Builder so the agent can one-click repair the
  // crash (the overlay alone dead-ends inside the iframe).
  try {
    window.parent.postMessage({
      source: 'terabit-preview',
      type: 'runtime-error',
      title: String(title),
      message: String(detail || title).slice(0, 1200),
    }, '*');
  } catch (e) { /* parent unreachable */ }
  overlay.style.display = 'block';
  overlay.innerHTML =
    '<h2>' + title + '</h2>' +
    '<div>' + (detail || '').replace(/&/g, '&amp;').replace(/</g, '&lt;') + '</div>' +
    '<div class="hint">This is an error in the generated app, shown here instead of a blank screen.</div>';
}
window.onerror = function (msg, src, line, col, err) {
  showError('Runtime error', (err && err.stack) || String(msg));
};
window.addEventListener('unhandledrejection', function (ev) {
  const r = ev.reason;
  showError('Unhandled promise rejection', (r && (r.stack || r.message)) || String(r));
});

(async () => {
  const externals = {
    'react': window.React,
    'react-dom': window.ReactDOM,
    'react-dom/client': window.ReactDOM,
  };

  await Promise.all(BARE_SPECS.filter(s => !externals[s]).map(async (spec) => {
    try {
      const mod = await import(/* @vite-ignore */ `https://esm.sh/${spec}?deps=react@18.3.1,react-dom@18.3.1&bundle`);
      externals[spec] = mod;
    } catch (e) {
      console.warn('[preview] could not load package "' + spec + '" - providing safe component proxy fallback:', e);
      const fallbackComponent = (props) => {
        return window.React.createElement('span', { className: 'inline-flex items-center text-xs opacity-75', ...props }, props.children || '');
      };
      externals[spec] = new Proxy({}, {
        get: (target, prop) => {
          if (prop === '__esModule') return true;
          if (prop === 'default') return fallbackComponent;
          return fallbackComponent;
        }
      });
    }
  }));

  const moduleCache = {};
  const compiledCache = {};

  function loadFileModule(path) {
    if (moduleCache[path]) return moduleCache[path].exports;

    if (/\.css$/.test(path)) {
      const map = cssMaps[path] || {};
      const mod = { exports: Object.assign({}, map, { default: map }) };
      moduleCache[path] = mod;
      return mod.exports;
    }
    if (/\.json$/.test(path)) {
      let data = {};
      try { data = JSON.parse(sources[path]); } catch (e) { console.warn('[preview] bad JSON in', path, e); }
      const base = (data && typeof data === 'object') ? data : {};
      const mod = { exports: Object.assign({}, base, { default: data }) };
      moduleCache[path] = mod;
      return mod.exports;
    }

    const src = sources[path];
    if (src === undefined) {
      console.warn('[preview] referenced file not found:', path);
      const mod = { exports: {} };
      moduleCache[path] = mod;
      return mod.exports;
    }

    let compiled = compiledCache[path];
    if (!compiled) {
      const isTS = /\.tsx?$/.test(path);
      const presets = [];
      if (isTS) presets.push(['typescript', { isTSX: path.endsWith('.tsx') }]);
      presets.push(['react', { runtime: 'classic' }]);
      try {
        compiled = Babel.transform(src, { presets, plugins: ['transform-modules-commonjs'], filename: path }).code;
      } catch (e) {
        throw new Error('Compile error in ' + path + ': ' + e.message);
      }
      compiledCache[path] = compiled;
    }

    const mod = { exports: {} };
    moduleCache[path] = mod;
    const req = (spec) => resolveAndLoad(path, spec);
    const fn = new Function('require', 'module', 'exports', '__filename', compiled);
    fn(req, mod, mod.exports, path);
    return mod.exports;
  }

  function resolveAndLoad(fromPath, spec) {
    const entry = (resolveMap[fromPath] || {})[spec];
    if (!entry) {
      if (externals[spec]) return externals[spec];
      console.warn('[preview] unresolved import "' + spec + '" in', fromPath);
      return {};
    }
    if (entry.kind === 'file') return loadFileModule(entry.key);
    if (entry.kind === 'asset') return { default: entry.key, __esModule: true };
    if (entry.kind === 'external') return externals[entry.key] || {};
    console.warn('[preview] could not resolve import "' + spec + '" in', fromPath);
    return {};
  }

  try {
    loadFileModule(ENTRY);
  } catch (e) {
    console.error(e);
    showError('Preview failed to start', (e && e.stack) || String(e));
  }
})();
"""


def _build_fallback_preview(files: list[dict]) -> str:
    css = """
    body{font-family:system-ui,sans-serif;background:#0f172a;color:#e2e8f0;margin:0;padding:2rem;line-height:1.6}
    pre{background:#1e293b;padding:1rem;border-radius:8px;overflow-x:auto;font-size:13px;max-height:400px}
    code{font-family:'JetBrains Mono',monospace}
    .file-list{display:grid;gap:0.5rem;max-width:800px;margin:2rem auto}
    .file-item{background:#1e293b;border-radius:8px;padding:0.75rem 1rem;border:1px solid #334155}
    .file-name{color:#38bdf8;font-weight:600;font-size:14px}
    .file-size,.file-preview{color:#64748b;font-size:12px}
    h1{background:linear-gradient(135deg,#a78bfa,#f472b6,#22d3ee);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
    details{margin-top:0.5rem}
    summary{cursor:pointer;color:#94a3b8;font-size:12px}
    """
    parts = [
        "<!DOCTYPE html><html><head><meta charset='UTF-8'><meta name='viewport' content='width=device-width,initial-scale=1'>",
        "<title>TerabitStudio Preview</title><style>", css, "</style></head><body>",
        "<div style='max-width:800px;margin:0 auto'>",
        "<h1 style='font-size:2rem;margin-bottom:0.5rem'>TerabitStudio</h1>",
        f"<p style='color:#64748b;margin-bottom:2rem'>{len(files)} files generated</p>",
        "<div class='file-list'>",
    ]
    for f in files:
        path = f.get("path", "")
        content = f.get("content", "")
        lines = content.count("\n") + 1
        size = len(content)
        ext = path.split(".")[-1] if "." in path else ""
        is_code = ext in ("js", "jsx", "ts", "tsx", "css", "html", "json", "py")
        snippet = content[:200].strip() if is_code else ""
        parts.append(f"<div class='file-item'><div class='file-name'>{_esc(path)}</div>")
        parts.append(f"<div class='file-size'>{lines} lines · {size} bytes</div>")
        if snippet:
            parts.append(f"<details><summary>Preview</summary><pre><code>{_esc(snippet)}</code></pre></details>")
        parts.append("</div>")
    parts.extend(["</div></div></body></html>"])
    return "".join(parts)


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
