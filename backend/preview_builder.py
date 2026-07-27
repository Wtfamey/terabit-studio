import json
import re

JS_EXTENSIONS = (".js", ".jsx", ".ts", ".tsx", ".mjs")

CDN_HEAD = """<script crossorigin src="https://unpkg.com/react@18/umd/react.production.min.js"></script>
<script crossorigin src="https://unpkg.com/react-dom@18/umd/react-dom.production.min.js"></script>
<script src="https://unpkg.com/@babel/standalone/babel.min.js"></script>
<script src="https://cdn.tailwindcss.com"></script>"""

# ───────── import / export rewriting ─────────
# We don't have a real bundler in the preview iframe, so instead of letting
# Babel turn `import`/`export` into CommonJS (which throws "require is not
# defined" in a plain browser script - this was the previous, broken
# behavior), we rewrite each file's imports/exports ourselves into reads and
# writes on a shared `__modules__` registry object, then execute all files in
# dependency order so each module exists before anything that imports it runs.

_IMPORT_DEFAULT_NAMED = re.compile(r'''import\s+(\w+)\s*,\s*\{\s*([^}]*)\s*\}\s*from\s*['"]([^'"]+)['"]\s*;?''')
_IMPORT_NAMESPACE = re.compile(r'''import\s+\*\s+as\s+(\w+)\s+from\s*['"]([^'"]+)['"]\s*;?''')
_IMPORT_NAMED = re.compile(r'''import\s*\{\s*([^}]*)\s*\}\s*from\s*['"]([^'"]+)['"]\s*;?''')
_IMPORT_DEFAULT = re.compile(r'''import\s+(\w+)\s+from\s*['"]([^'"]+)['"]\s*;?''')
_IMPORT_SIDE_EFFECT = re.compile(r'''import\s*['"]([^'"]+)['"]\s*;?''')
_ANY_IMPORT_SPEC = re.compile(r'''import\s+(?:[^'";]+from\s+)?['"]([^'"]+)['"]''')

_EXPORT_DEFAULT_INLINE_FN = re.compile(r'''export\s+default\s+function\s+(\w+)''')
_EXPORT_DEFAULT_INLINE_CLASS = re.compile(r'''export\s+default\s+class\s+(\w+)''')
_EXPORT_DEFAULT_NAMED = re.compile(r'''export\s+default\s+(\w+)\s*;''')
_EXPORT_DEFAULT_ANON = re.compile(r'''export\s+default\s+''')
_EXPORT_NAMED_DECL = re.compile(r'''export\s+(const|let|var|function|class)\s+(\w+)''')
_EXPORT_LIST = re.compile(r'''export\s*\{\s*([^}]*)\s*\}\s*;?''')


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
    for ext in JS_EXTENSIONS:
        if combined + ext in existing:
            return combined + ext
    for ext in JS_EXTENSIONS:
        cand = f"{combined}/index{ext}"
        if cand in existing:
            return cand
    return None


def _module_key(importer: str, spec: str, existing: set) -> str:
    if spec.startswith("."):
        resolved = _resolve(importer, spec, existing)
        return resolved if resolved else spec
    return spec  # bare package name -> 'react', 'lucide-react', 'react-router-dom', ...


def _topo_order(seed_paths: list, files: dict, existing: set) -> list:
    visited: set = set()
    order: list = []

    def visit(path: str):
        if path in visited or path not in files:
            return
        visited.add(path)
        for m in _ANY_IMPORT_SPEC.finditer(files[path]):
            spec = m.group(1)
            if spec.startswith("."):
                resolved = _resolve(path, spec, existing)
                if resolved:
                    visit(resolved)
        order.append(path)

    for p in seed_paths:
        visit(p)
    return order


def _rewrite_module(path: str, content: str, existing: set) -> str:
    named_exports: list = []
    state = {"default_name": None}

    def repl_default_named(m):
        default_name, named, spec = m.group(1), m.group(2), m.group(3)
        key = _module_key(path, spec, existing)
        names = [n.strip() for n in named.split(",") if n.strip()]
        destructure = ", ".join([f"default: {default_name}"] + names)
        return f"const {{ {destructure} }} = __modules__[{json.dumps(key)}] || {{}};"

    def repl_namespace(m):
        name, spec = m.group(1), m.group(2)
        key = _module_key(path, spec, existing)
        return f"const {name} = __modules__[{json.dumps(key)}] || {{}};"

    def repl_named(m):
        named, spec = m.group(1), m.group(2)
        key = _module_key(path, spec, existing)
        return f"const {{ {named} }} = __modules__[{json.dumps(key)}] || {{}};"

    def repl_default(m):
        name, spec = m.group(1), m.group(2)
        key = _module_key(path, spec, existing)
        return f"const {{ default: {name} }} = __modules__[{json.dumps(key)}] || {{}};"

    def repl_side_effect(_m):
        return ""  # e.g. `import './index.css'` - CSS is already bundled separately

    content = _IMPORT_DEFAULT_NAMED.sub(repl_default_named, content)
    content = _IMPORT_NAMESPACE.sub(repl_namespace, content)
    content = _IMPORT_NAMED.sub(repl_named, content)
    content = _IMPORT_DEFAULT.sub(repl_default, content)
    content = _IMPORT_SIDE_EFFECT.sub(repl_side_effect, content)

    def repl_export_default_fn(m):
        state["default_name"] = m.group(1)
        return f"function {m.group(1)}"

    def repl_export_default_class(m):
        state["default_name"] = m.group(1)
        return f"class {m.group(1)}"

    content = _EXPORT_DEFAULT_INLINE_FN.sub(repl_export_default_fn, content)
    content = _EXPORT_DEFAULT_INLINE_CLASS.sub(repl_export_default_class, content)

    def repl_export_default_named(m):
        state["default_name"] = m.group(1)
        return ""

    content = _EXPORT_DEFAULT_NAMED.sub(repl_export_default_named, content)

    if state["default_name"] is None and _EXPORT_DEFAULT_ANON.search(content):
        content = _EXPORT_DEFAULT_ANON.sub("const __default_export__ = ", content, count=1)
        state["default_name"] = "__default_export__"

    def repl_export_named_decl(m):
        named_exports.append(m.group(2))
        return f"{m.group(1)} {m.group(2)}"

    content = _EXPORT_NAMED_DECL.sub(repl_export_named_decl, content)

    def repl_export_list(m):
        for n in m.group(1).split(","):
            n = n.strip().split(" as ")[0].strip()
            if n:
                named_exports.append(n)
        return ""

    content = _EXPORT_LIST.sub(repl_export_list, content)

    footer = [f"if (typeof __modules__[{json.dumps(path)}] === 'undefined') __modules__[{json.dumps(path)}] = {{}};"]
    if state["default_name"]:
        footer.append(f"__modules__[{json.dumps(path)}].default = {state['default_name']};")
    for name in dict.fromkeys(named_exports):
        footer.append(f"__modules__[{json.dumps(path)}].{name} = {name};")

    return content + "\n" + "\n".join(footer)


def _extract_title(html: str | None) -> str:
    if html:
        m = re.search(r"<title>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
        if m:
            return _esc(m.group(1).strip())
    return "Preview"


def build_preview_html(files: list[dict]) -> str:
    file_map = {f["path"]: f["content"] for f in files}
    js_paths = [p for p in file_map if p.endswith(JS_EXTENSIONS)]

    if not js_paths:
        html_content = file_map.get("index.html") or file_map.get("public/index.html")
        if html_content:
            return html_content
        return _build_fallback_preview(files)

    css_bundle = "\n".join(f"/* {p} */\n{c}" for p, c in file_map.items() if p.endswith(".css"))
    existing = set(file_map.keys())

    ordered_paths = _topo_order(js_paths, file_map, existing)
    rewritten = {p: _rewrite_module(p, file_map[p], existing) for p in ordered_paths}

    title = _extract_title(file_map.get("index.html") or file_map.get("public/index.html"))
    files_json = json.dumps(rewritten).replace("</script", "<\\/script")
    order_json = json.dumps(ordered_paths)

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1.0"/>
<title>{title}</title>
{CDN_HEAD}
<style>{css_bundle}</style>
</head>
<body>
<div id="root"></div>
<script id="__raw_files__" type="application/json">{files_json}</script>
<script id="__order__" type="application/json">{order_json}</script>
<script type="module">
(async () => {{
  const files = JSON.parse(document.getElementById('__raw_files__').textContent);
  const order = JSON.parse(document.getElementById('__order__').textContent);

  let RouterDOM = {{}};
  let LucideReact = {{}};
  try {{ RouterDOM = await import('https://esm.sh/react-router-dom@6.28.0?deps=react@18.3.1,react-dom@18.3.1'); }} catch (e) {{ console.warn('react-router-dom unavailable in preview', e); }}
  try {{ LucideReact = await import('https://esm.sh/lucide-react@0.464.0?deps=react@18.3.1'); }} catch (e) {{ console.warn('lucide-react unavailable in preview', e); }}

  const __modules__ = {{
    'react': window.React,
    'react-dom': window.ReactDOM,
    'react-dom/client': window.ReactDOM,
    'react-router-dom': RouterDOM,
    'lucide-react': LucideReact,
  }};

  for (const path of order) {{
    try {{
      const isTS = path.endsWith('.ts') || path.endsWith('.tsx');
      const {{ code }} = Babel.transform(files[path], {{
        presets: isTS ? ['react', 'typescript'] : ['react'],
        filename: path,
      }});
      new Function('__modules__', code)(__modules__);
    }} catch (e) {{
      console.error('Preview error in', path, e);
      document.getElementById('root').innerHTML =
        '<div style="font-family:monospace;padding:2rem;color:#f87171;background:#0f172a;white-space:pre-wrap">Preview error in ' + path + ':\\n' + (e && e.message || e) + '</div>';
      break;
    }}
  }}
}})();
</script>
</body>
</html>"""


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
