"""Regression tests for the deterministic motion enricher.

The pass may only ADD micro-interaction classes, must be idempotent, and must
never touch layout containers or conditional/template classNames.

Run:  cd backend && python test_motion_enricher.py
"""
import glob
import json
import os

import motion_enricher as me

# ── cards ──────────────────────────────────────────────────────────────────
CARD = 'export default function X() {\n  return (\n    <div className="rounded-2xl bg-white border border-gray-200 p-6 shadow-md">\n      <h3>Hello</h3>\n    </div>\n  );\n}\n'
out, stats = me.enrich(CARD)
assert "transition-all duration-300" in out, out
assert "hover:-translate-y-1" in out and "hover:shadow-xl" in out
assert stats["cards"] == 1 and stats["total"] == 1

# idempotent
again, stats2 = me.enrich(out)
assert again == out, "second pass must be a no-op"
assert stats2["total"] == 0

# a card that already lifts is left alone
LIFTING = '<div className="rounded-xl bg-white p-4 hover:-translate-y-1 transition-all">x</div>'
assert me.enrich(LIFTING)[0] == LIFTING

# ── buttons ────────────────────────────────────────────────────────────────
BTN = '<button className="px-5 py-2.5 rounded-lg bg-blue-600 text-white font-medium">Go</button>'
out, stats = me.enrich(BTN)
assert "active:scale-[0.97]" in out, out
assert stats["buttons"] == 1

# an <a> styled as a button behaves the same
LINK = '<a href="/x" className="inline-flex rounded-full bg-slate-900 px-6 py-3 text-white">Start</a>'
out, _ = me.enrich(LINK)
assert "active:scale-[0.97]" in out, out

# ── images ─────────────────────────────────────────────────────────────────
IMG = '<img src="/a.jpg" className="w-full h-64 object-cover" alt="a" />'
out, stats = me.enrich(IMG)
assert "transition-transform duration-500" in out, out
assert stats["images"] == 1

# an image without object-cover is not touched (it may be an inline icon)
assert me.enrich('<img src="/i.svg" className="w-5 h-5" />')[0] == '<img src="/i.svg" className="w-5 h-5" />'

# ── things that must never change ──────────────────────────────────────────
LAYOUT = '<section className="min-h-screen rounded-xl bg-slate-50 p-6">x</section>'
assert me.enrich(LAYOUT)[0] == LAYOUT, "layout containers must not get a hover lift"

TEMPLATE = '<div className={`p-4 rounded-xl bg-white ${active ? "ring" : ""}`}>x</div>'
assert me.enrich(TEMPLATE)[0] == TEMPLATE, "template literals must be left alone"

SVG = '<svg className="w-6 h-6 rounded bg-white p-1"><path d="M0 0" /></svg>'
assert me.enrich(SVG)[0] == SVG, "svg internals must be left alone"

# attributes appearing BEFORE className must still resolve the tag
BEFORE = '<button type="button" onClick={go} className="rounded-md bg-emerald-600 px-4 py-2 text-white">Ok</button>'
out, _ = me.enrich(BEFORE)
assert "active:scale-[0.97]" in out, out

# level 'none' disables the pass entirely
assert me.enrich(CARD, level="none")[0] == CARD

print("core motion-enricher tests pass")

# ── real artifacts: enrichment must never break the bundle ─────────────────
_FIXTURES = glob.glob("comparison/*/*/generated.json")
checked = 0
for fixture in _FIXTURES[:6]:
    raw = json.load(open(fixture, encoding="utf-8"))
    files = raw if isinstance(raw, list) else raw.get("files", [])
    generated = {f["path"]: f["content"] for f in files
                 if isinstance(f, dict) and f.get("path", "").endswith((".jsx", ".tsx"))}
    if not generated:
        continue
    for path in list(generated):
        c = generated[path]
        c = me.enrich(c)[0]
        # the enricher must keep brace balance identical
        assert c.count("{") == generated[path].count("{"), f"{fixture} {path}: braces changed"
        assert c.count('"') == generated[path].count('"'), f"{fixture} {path}: quotes changed"
        generated[path] = c
    checked += 1

print(f"real-artifact safety check passed on {checked} fixtures")
print("ALL MOTION-ENRICHER TESTS PASS")
