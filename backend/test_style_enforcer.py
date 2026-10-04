"""Regression tests for deterministic style enforcement rules.

Focused on the frosted-panel rule: an opaque fill combined with
`backdrop-blur-*` is self-contradictory (the blur is invisible and image-led
cards render as flat slabs over their photos -- live: portfolio work cards,
run 20260930-174958, every project image hidden behind `bg-stone-100 ...`).

Run:  cd backend && python test_style_enforcer.py
"""
import json
import os
import re

import design_system
import style_enforcer

THEME = design_system.get_design({"name": "Mara", "kind_note": "product designer portfolio"})


def _fresh():
    return design_system.get_design({"name": "Mara", "kind_note": "product designer portfolio"})


# 1) opaque bg + backdrop-blur -> translucent, family still theme-mapped
out, st = style_enforcer.rewrite(
    '<div className="relative p-6 bg-stone-100 border backdrop-blur-xl shadow-lg">x</div>',
    _fresh(),
)
assert re.search(r"\bbg-[a-z]+-\d{2,3}/70\b", out), out
assert "/70/70" not in out

# 2) idempotent
again, _ = style_enforcer.rewrite(out, _fresh())
assert again == out, (out, again)

# 3) an existing alpha is never stacked (white-alpha surfaces included)
for probe in ('<div className="bg-white/90 backdrop-blur p-4">y</div>',
              '<div className="bg-stone-100/80 backdrop-blur-md">y</div>'):
    o, _ = style_enforcer.rewrite(probe, _fresh())
    assert "/70/70" not in o and "/80/70" not in o, o

# 4) panels WITHOUT blur are untouched
o, _ = style_enforcer.rewrite('<div className="bg-stone-100 p-4">z</div>', _fresh())
assert "/70" not in o, o

# 5) real artifact: portfolio work cards become translucent
_art = "comparison/i-need-you-to-build-me-a-portfolio-websi/20260930-174958/result.json"
if os.path.exists(_art):
    d = json.load(open(_art, encoding="utf-8"))
    work = next((f["content"] for f in d["files"] if f["path"].endswith("Work.jsx")), None)
    if work:
        outw, stw = style_enforcer.rewrite(work, _fresh())
        frosted = re.findall(r"\bbg-[\w\[\]#-]+/70\b", outw)
        assert frosted, "work cards should be frosted after enforcement"
        assert style_enforcer.rewrite(outw, _fresh())[0] == outw, "not idempotent"
        print("portfolio Work.jsx:", stw["rewritten"], "rewrites,", len(frosted), "frosted panels")

# 6) display-font pass: headings get .font-display (webapp gate check)
src = ('<section>'
       '<h1 className="text-4xl font-bold">Our Menu</h1>'
       '<h2 className={`text-2xl font-semibold`}>Starters</h2>'
       '<h3>Just a heading</h3>'
       '<div className="text-xl">not a heading</div></section>')
o, st = style_enforcer.rewrite(src, _fresh())
assert o.count("font-display") == 3, o
assert 'font-display text-4xl' in o, o
assert "not a heading" not in st["examples"], st
o2, _ = style_enforcer.rewrite(o, _fresh())
assert o2 == o, "font pass not idempotent"
# a heading that ALREADY has the class is untouched
src2 = '<h1 className="font-display text-3xl">X</h1>'
o3, st3 = style_enforcer.rewrite(src2, _fresh())
assert o3.count("font-display") == 1, o3
print("font-display pass:", st["rewritten"], "headings, idempotent")

print("ALL STYLE-ENFORCER TESTS PASS")
