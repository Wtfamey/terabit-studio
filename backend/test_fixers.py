"""Regression tests for the generation-integrity fixers.

Covers the failures that cost real runs their sections:
  - stray unpaired fence backtick around a file (portfolio 20260930-174958:
    Faq dropped after two failed LLM repairs on a leading '`')
  - generation cut off mid-string / mid-structure
  - fix_missing_export's wrapper emitting a literal '}}' (unbalanced output)

Run:  cd backend && python test_fixers.py
"""
import json
import os

import agentic_generator as ag

# ── fix_stray_fence ─────────────────────────────────────────────────────────
FENCED = "`import React from 'react';\n\nexport default function Faq() {\n  return <div>ok</div>;\n}\n"
fenced_fixed = ag.fix_stray_fence("src/components/Faq.jsx", FENCED)
assert fenced_fixed.startswith("import React"), repr(fenced_fixed[:20])
assert ag._balanced_syntax(fenced_fixed)

# paired backticks (a real template literal) must be left alone
healthy_tmpl = "export default function X() {\n  return <div>{`hi ${1}`}</div>;\n}\n"
assert ag.fix_stray_fence("src/components/X.jsx", healthy_tmpl) == healthy_tmpl

# non-JSX files untouched
assert ag.fix_stray_fence("index.html", "`x`") == "`x`"

# ── fix_truncated ───────────────────────────────────────────────────────────
TRUNCATED = (
    "import React from 'react';\n\nconst items = [\n"
    '  { id: 1, q: "Refunds?", a: "Yes, within 30 days." },\n'
    '  { id: 2, q: "Support?", a: "We reply fast and never leave a sentence half'
)
repaired = ag.fix_truncated("src/components/Faq.jsx", TRUNCATED)
assert repaired != TRUNCATED
assert ag._balanced_syntax(repaired)
assert "export default" in repaired
assert "never leave a sentence half" not in repaired, "truncated fragment must be shed"

# healthy files are never touched
HEALTHY = ("import React from 'react';\n\nexport default function Faq() {\n"
           "  return <div className=\"x\">hi</div>;\n}\n")
assert ag.fix_truncated("src/components/Faq.jsx", HEALTHY) == HEALTHY
assert ag.fix_truncated("src/App.jsx", HEALTHY) == HEALTHY

# A repair must never return something LESS balanced than the input. When
# bracket closing cannot converge, the ORIGINAL comes back; when it can, the
# result is balanced and any remaining JSX-level breakage is caught by the
# real bundler verify that runs immediately after this fixer in the pipeline.
HOPELESS = "export default function X() {\n  return <div>{broken"
h = ag.fix_truncated("src/components/X.jsx", HOPELESS)
assert h == HOPELESS or ag._balanced_syntax(h), h
assert "broken" in h, "content must never be silently lost"
# unbalanced-in-a-way-closers-cannot-fix -> original preserved
UNFIXABLE = "export default function X() { return (}}} </div>"
assert ag.fix_truncated("src/components/X.jsx", UNFIXABLE) == UNFIXABLE

# ── fix_missing_export wrapper balance (regression: literal '}}') ────────────
NO_EXPORT = ("import React from 'react';\n\nconst items = [\n"
             '  { id: 1, q: "x", a: "y" },\n];\n')
wrapped = ag.fix_missing_export("src/components/Faq.jsx", NO_EXPORT)
assert ag._balanced_syntax(wrapped), wrapped[-60:]
assert wrapped.count("{") == wrapped.count("}")
assert "}}\n" not in wrapped

# ── fix_bad_jsx_tag_names ──────────────────────────────────────────────────
# Live: law run 20260930-182939 dropped Fees.jsx on
#   <mockFees[selected - 1].icon className="w-5 h-5" />
# esbuild: 'Expected ">" but found "["'. Both LLM repairs failed.
EXPR_CONTAINER = (
    "export default function Fees() {\n"
    "  return (\n    <div>\n"
    "      {active && <mockFees[selected - 1].icon className=\"w-5 h-5\" />}\n"
    "    </div>\n  );\n}\n"
)
fix1 = ag.fix_bad_jsx_tag_names("src/components/Fees.jsx", EXPR_CONTAINER)
assert "React.createElement" in fix1
assert ag._balanced_syntax(fix1), fix1
assert "import React" in fix1  # default import injected
assert "[" in fix1  # the index expression itself is preserved as an argument
# inside an expression container the bare call is spliced in (no extra braces)
assert "{active && React.createElement(" in fix1, fix1

# children position -> the call must be wrapped in {}
CHILD_POS = (
    "export default function X() {\n"
    "  return (\n    <div className=\"grid\">\n"
    "      <icons[i] className=\"w-6 h-6\" />\n"
    "    </div>\n  );\n}\n"
)
fix2 = ag.fix_bad_jsx_tag_names("src/components/X.jsx", CHILD_POS)
assert "{React.createElement(icons[i], {className: \"w-6 h-6\"})}" in fix2, fix2
assert ag._balanced_syntax(fix2)

# `<Foo.Bar />` is VALID JSX -- must not be touched
MEMBER_OK = "export default function X() { return <Foo.Bar n={1} />; }\n"
assert ag.fix_bad_jsx_tag_names("src/components/X.jsx", MEMBER_OK) == MEMBER_OK

# non-JSX / bracket-free files untouched
assert ag.fix_bad_jsx_tag_names("src/util.js", "const a = [1,2];") == "const a = [1,2];"

# ── fix_gradient_text_quiet (idempotent) ───────────────────────────────────
GRAD = ('export default function X() {\n  return <h1 className="text-4xl bg-gradient-to-r '
        'from-blue-500 to-purple-600 font-bold">Hi</h1>;\n}\n')
g1 = ag.fix_gradient_text_quiet("src/components/X.jsx", GRAD)
assert "bg-clip-text" in g1 and "text-transparent" in g1, g1
assert ag.fix_gradient_text_quiet("src/components/X.jsx", g1) == g1

# ── promote_tsx_files (TS syntax inside a .jsx file) ────────────────────────
# Live: law-firm Faq.jsx dropped twice on `(id: number) =>` because esbuild's
# jsx loader rejects TS annotations. The extension was the only thing wrong.
TS_JSX = ('import React, { useState } from "react";\n\n'
          'export default function Faq() {\n'
          '  const [open, setOpen] = useState<number | null>(null);\n'
          '  const toggle = (id: number) => {\n'
          '    setOpen(open === id ? null : id);\n'
          '  };\n'
          '  return <div onClick={() => toggle(1)}>ok</div>;\n}\n')
assert ag.has_ts_syntax(TS_JSX)
promoted, renames = ag.promote_tsx_files({
    "src/components/Faq.jsx": TS_JSX,
    "src/App.jsx": "import Faq from './components/Faq.jsx';\nexport default Faq;\n",
})
assert renames == [("src/components/Faq.jsx", "src/components/Faq.tsx")], renames
assert "src/components/Faq.tsx" in promoted
assert "src/components/Faq.jsx" not in promoted
# explicit .jsx import specifiers follow the rename; extensionless ones are fine
assert "./components/Faq.tsx" in promoted["src/App.jsx"]

# plain JSX must NOT be promoted
PLAIN = ("import React from 'react';\n\nexport default function X() {\n"
         "  const [n, setN] = useState(0);\n  return <div>{n}</div>;\n}\n")
plain_files = {"src/components/X.jsx": PLAIN}
assert not ag.has_ts_syntax(PLAIN)
same, renames2 = ag.promote_tsx_files(plain_files)
assert renames2 == [] and same is plain_files, "no-op must return the original dict"

# a sibling .tsx already exists -> never clobber it
coll = ag.promote_tsx_files({"src/components/A.jsx": TS_JSX, "src/components/A.tsx": "export default 1;\n"})
assert coll[1] == [], "must not rename onto an existing .tsx sibling"

# The promoted file must actually bundle -- and App must IMPORT it, otherwise
# esbuild never reaches the file and the check proves nothing.
_ENTRY = ("import React from 'react';\nimport { createRoot } from 'react-dom/client';\n"
          "import App from './App';\n"
          "createRoot(document.getElementById('root')).render(<App />);\n")
_APP = ("import Faq from './components/Faq';\n"
        "export default function App() { return <div><Faq /></div>; }\n")
_tsx_files = {
    "src/main.jsx": _ENTRY,
    "src/App.jsx": _APP,
    "src/components/Faq.tsx": TS_JSX,
}
_ok, _err = ag.bundle_check(_tsx_files)
assert _ok, f"promoted tsx must bundle: {_err[:300]}"
# the same content as .jsx must NOT bundle, proving the promotion is load-bearing
_jsx_files = dict(_tsx_files)
_jsx_files["src/components/Faq.jsx"] = _jsx_files.pop("src/components/Faq.tsx")
_bad, _berr = ag.bundle_check(_jsx_files)
assert not _bad, f"the .jsx form should have failed to bundle (fixture drift?): {_berr[:200]}"

# ── the REAL portfolio artifact that was dropped ────────────────────────────
_art = "comparison/i-need-you-to-build-me-a-portfolio-websi/20260930-174958/generated.json"
if os.path.exists(_art):
    g = json.load(open(_art, encoding="utf-8"))
    files = g if isinstance(g, list) else g.get("files", [])
    raw = next((f["content"] for f in files
                if isinstance(f, dict) and "Faq" in f.get("path", "")), None)
    if raw:
        assert not ag._balanced_syntax(raw), "fixture should start broken"
        fixed = ag.fix_stray_fence("src/components/Faq.jsx", raw)
        assert ag._balanced_syntax(fixed)
        assert "export default" in fixed
        # deterministic chain (gen-loop order) is a full no-op beyond the fence
        chained = ag.fix_truncated("src/components/Faq.jsx", fixed)
        assert ag._balanced_syntax(chained)
        print("real artifact fixture repaired:", len(raw), "->", len(fixed), "chars")

print("ALL FIXER TESTS PASS")
