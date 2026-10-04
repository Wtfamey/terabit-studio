"""Regression test for the deterministic landing-shell composer.

The shell is what stitches the model's per-section files into a runnable
App.jsx, so a bug here silently ships a page with missing sections or a
bundle that no longer compiles. This test drives it with the REAL generated
files from the Hartwell & Sawyer law-firm run -- the one whose Fees section
used to be dropped -- and asserts the composed shell still bundles.

Run:  cd backend && python test_shell.py
"""
import json
import os

import agentic_generator as ag

_FIXTURE = "comparison/build-a-website-for-hartwell-sawyer-a/20260930-182939/generated.json"

if not os.path.exists(_FIXTURE):
    print("SKIP: law-firm fixture not present")
    raise SystemExit(0)

raw = json.load(open(_FIXTURE, encoding="utf-8"))
files = raw if isinstance(raw, list) else raw.get("files", [])
generated = {f["path"]: f["content"] for f in files if isinstance(f, dict)}

# The generated.json holds the pre-repair model output, so run the same
# deterministic repair chain the pipeline runs before composing the shell.
for path in list(generated):
    c = generated[path]
    c = ag.fix_stray_fence(path, c)
    c = ag.fix_truncated(path, c)
    c = ag.fix_bad_jsx_tag_names(path, c)
    generated[path] = c

prep = json.load(open(_FIXTURE.replace("generated.json", "request.json"), encoding="utf-8"))
brief = prep.get("brief") or {"business": "law firm", "sections": []}

trace_events: list[tuple[str, str]] = []


class _Trace:
    def add(self, kind, detail):
        trace_events.append((kind, detail))


shell, dropped = ag._compose_landing_shell(
    generated, {"archetype": "landing", "app_name": "Hartwell & Sawyer"},
    {"name": "Hartwell & Sawyer"}, brief, trace=_Trace(), logo_url="",
)

assert shell, "composer produced no shell"
assert "Reveal" in shell
# every rendered section carries a stagger delay
assert "delay={" in shell, "sections are not staggered"
delays = [int(m.group(1)) for m in __import__("re").finditer(r"delay=\{(\d+)\}", shell)]
assert delays == sorted(delays) and len(set(delays)) == len(delays), delays
assert delays[0] == 0 and len(delays) >= 3, delays

# the composed App.jsx must actually compile + render.
# src/main.jsx is injected by the pipeline as a core file (bundle_check needs
# it as the esbuild entry point), so mirror that here.
files_dict = dict(generated)
files_dict["src/App.jsx"] = shell
files_dict["src/main.jsx"] = (
    "import React from 'react';\n"
    "import { createRoot } from 'react-dom/client';\n"
    "import App from './App';\n\n"
    "createRoot(document.getElementById('root')).render(<App />);\n"
)
ok_b, err_b = ag.bundle_check(files_dict)
assert ok_b, f"composed shell does not bundle: {err_b[:300]}"

ok_r, err_r = ag.render_check(files_dict)
assert ok_r, f"composed shell does not render: {err_r[:300]}"

print(f"shell composed: {len(shell)} chars, sections={len(delays)}, delays={delays}")
print(f"dropped={[d.split('/')[-1] for d in dropped]}")

# ── every domain profile must compose to a 4+ section page ─────────────────
# Regression: profiles used to carry only 2 domain sections, so a typical
# page shipped Hero + 2 + FAQ and read as a thin template next to Bolt.
import domain_profiles

_BRIEFS = {
    "law": {"domain": "law firm", "business_type": "law", "sections": [], "offerings": []},
    "restaurant": {"domain": "restaurant", "business_type": "restaurant", "sections": [], "offerings": []},
    "hospital": {"domain": "hospital", "business_type": "clinic", "sections": [], "offerings": []},
    "portfolio": {"domain": "portfolio", "business_type": "portfolio", "sections": [], "offerings": []},
    "saas": {"domain": "saas", "business_type": "saas", "sections": [], "offerings": []},
    "ecommerce-shop": {"domain": "ecommerce shop", "business_type": "store", "sections": [], "offerings": []},
}

_TMPL = (
    "import React from 'react';\nimport {{ Sparkles }} from 'lucide-react';\n\n"
    "const items = [1, 2, 3];\n\n"
    "export default function {stem}() {{\n"
    "  return (\n    <section className=\"py-20 px-6\">\n"
    "      {{items.map((i) => (\n"
    "        <div key={{i}} className=\"rounded-xl bg-white p-6\"><Sparkles />{{i}}</div>\n"
    "      ))}}\n    </section>\n  );\n}}\n"
)

for label, brief in _BRIEFS.items():
    profile = domain_profiles.get_profile(brief)
    gen = {"src/components/Hero.jsx": _TMPL.format(stem="Hero")}
    for s in profile["sections"]:
        gen[f"src/components/{s['stem']}.jsx"] = _TMPL.format(stem=s["stem"])
    sh, dr = ag._compose_landing_shell(
        gen, {"archetype": "landing", "app_name": "Demo"}, {"name": "Demo"}, brief,
        trace=_Trace(), logo_url="",
    )
    assert sh, f"{label}: no shell"
    assert dr == [], f"{label}: sections dropped -> {dr}"
    n = len(__import__("re").findall(r"<Reveal delay=\{", sh))
    assert n >= 4, f"{label}: only {n} sections composed (want >= 4 domain sections)"
    # no duplicate imports/renders of the same component
    stems = [s["stem"] for s in profile["sections"]] + ["Hero"]
    for stem in stems:
        assert sh.count(f"<{stem} />") == 1, f"{label}: {stem} rendered {sh.count(f'<{stem} />')}x"
        assert sh.count(f"import {stem} from") <= 1, f"{label}: {stem} imported twice"
    fd = dict(gen)
    fd["src/App.jsx"] = sh
    fd["src/main.jsx"] = (
        "import React from 'react';\nimport { createRoot } from 'react-dom/client';\n"
        "import App from './App';\ncreateRoot(document.getElementById('root')).render(<App />);\n"
    )
    ok, err = ag.bundle_check(fd)
    assert ok, f"{label}: composed page does not bundle: {err[:250]}"
    print(f"  {label:16s} sections={n} bundle=OK")

print("ALL SHELL TESTS PASS")
