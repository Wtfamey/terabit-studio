"""Tests for imagery.enforce_imagery + imagery.fix_gradient_text.

Run:  cd backend && python test_imagery.py
"""
import re

import imagery

# ── enforce_imagery ──────────────────────────────────────────────────────────
MENU = """const dishes = [
  { id: 1, name: 'A', image: 'https://picsum.photos/id/1038/300/200?grayscale&blur=2' },
  { id: 2, name: 'B', image: '' },
  { id: 3, name: 'C', imageUrl: "" },
  { id: 4, name: 'D', image: 'https://images.unsplash.com/photo-1414235077428-338989a2e8c0?w=800&q=80' },
];"""
APP = """{LOGO_URL ? (
  <img src="" alt="Casa Verde" className="h-9 w-auto" />
) : null}
<img src="https://placehold.co/600x400" alt="Vibe" />
<img src={LOGO_URL} alt="dyn" />"""

files = [
    {"path": "src/components/Menu.jsx", "content": MENU},
    {"path": "src/App.jsx", "content": APP},
]
files, st = imagery.enforce_imagery(files, "restaurant")
print("stats:", st)
m, a = files[0]["content"], files[1]["content"]

assert st == {"rewritten_urls": 1, "filled_fields": 3}, st  # placehold img + picsum/empty fields
assert m.count("images.unsplash.com") == 4 and "picsum" not in m
assert "photo-1414235077428" in m, "real url must survive"

assert 'src=""' in a, "empty logo src (falsy ternary arm) must be kept"
assert "placehold" not in a and "images.unsplash.com" in a
assert "src={LOGO_URL}" in a, "expression src must stay untouched"

# idempotence
files2, st2 = imagery.enforce_imagery(files, "restaurant")
assert st2 == {"rewritten_urls": 0, "filled_fields": 0}, st2

# <img> tag with picsum URL gets rewritten too
tag_f = [{"path": "src/components/G.jsx",
          "content": '<img src="https://picsum.photos/seed/x/400/240" alt="Lobby" />'}]
tag_f, st3 = imagery.enforce_imagery(tag_f, "restaurant")
assert st3 == {"rewritten_urls": 1, "filled_fields": 0}, st3
assert "picsum" not in tag_f[0]["content"] and "images.unsplash.com" in tag_f[0]["content"]

# hover-hidden content images become visible
hov = [{'path': 'src/components/Menu.jsx', 'content':
        '<img src="https://images.unsplash.com/photo-1504674900247-0877df9cc836?w=800&q=80" '
        'alt="Pici alla Tramontana" className="absolute inset-0 w-full h-full object-cover '
        'opacity-0 group-hover:opacity-100 transition-opacity duration-500" />'}]
hov, st4 = imagery.enforce_imagery(hov, 'restaurant')
assert st4.get('unhidden_images') == 1, st4
assert 'opacity-0 group-hover' not in hov[0]['content']
assert 'object-cover opacity-100 group-hover:opacity-100' in hov[0]['content']
# decorative image WITHOUT object-cover stays hover-hidden
hov2 = [{'path': 'src/components/X.jsx', 'content':
         '<img src="https://images.unsplash.com/photo-1504674900247-0877df9cc836?w=800&q=80" '
         'alt="decor" className="opacity-0 group-hover:opacity-100" />'}]
hov2, st5 = imagery.enforce_imagery(hov2, 'restaurant')
assert st5.get('unhidden_images') is None, st5

# ── fix_gradient_text ────────────────────────────────────────────────────────
HERO = """<h1 className="text-6xl font-display text-transparent bg-clip-text bg-gradient-to-r from-amber-400 to-amber-500">
  <span className="inline">Savor</span> <span className="inline bg-gradient-to-br from-amber-700 to-orange-800">Seasonal</span> Flavors
</h1>
<div className="bg-gradient-to-br from-amber-700 to-orange-800 blur-3xl opacity-40 rounded-full"></div>
<span className="px-3 py-1 rounded-full bg-gradient-to-r from-amber-600 to-orange-600">chip</span>"""

g = imagery.fix_gradient_text("src/components/Hero.jsx", HERO)
sm = re.search(r'<span className="([^"]*)">Seasonal', g)
assert sm and all(
    k in sm.group(1) for k in ("bg-clip-text", "text-transparent", "bg-gradient-to-br")
), sm
assert g.count("bg-clip-text") == 2, g
assert "px-3 py-1 rounded-full bg-gradient-to-r" in g, "decor chip untouched"
assert "blur-3xl opacity-40 rounded-full" in g, "glow div untouched"
assert imagery.fix_gradient_text("src/components/Hero.jsx", g) == g, "not idempotent"

# template-literal className
t = imagery.fix_gradient_text(
    "x.jsx", "<p className={`mt-2 bg-gradient-to-r from-amber-400 to-amber-500`}>hi</p>"
)
assert "bg-clip-text" in t, t

# single-quoted className
t2 = imagery.fix_gradient_text(
    "x.jsx", "<a href='#x' className='bg-gradient-to-r from-amber-400 to-amber-500'>hi</a>"
)
assert "bg-clip-text" in t2, t2

# non-text tags never patched
t3 = imagery.fix_gradient_text(
    "x.jsx", '<div className="bg-gradient-to-br from-amber-700 to-orange-800">x</div>'
)
assert t3.count("bg-clip-text") == 0, t3

print("ALL IMAGERY + GRADIENT TESTS PASS")
