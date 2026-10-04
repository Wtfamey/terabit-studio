"""Regression tests for the deterministic import fixers.

Both fixers exist because the eval gate cannot catch their failure class:

  * `fix_lucide_imports`  -- hallucinated lucide export names make esbuild
    hard-fail ("No matching export"), i.e. tier-2.
  * `fix_missing_imports` -- identifiers used but never imported (`<Plus />`,
    `useState()`) compile fine and then throw at RUNTIME, so the bundle
    verifies, the preview reaches tier-1, and the app white-screens. Observed
    live on a generated bug-tracker.

The safety cases below matter as much as the repairs: inventing an import for a
locally bound name (`const { Icon } = props`) turns a working file into a
redeclaration syntax error, which is worse than the bug being fixed.

Run:  python test_import_fixes.py        (no pytest required)
      pytest test_import_fixes.py        (also works)
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from agentic_generator import fix_imports, fix_lucide_imports, fix_missing_imports  # noqa: E402

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    status = "ok  " if condition else "FAIL"
    print(f"  [{status}] {name}" + (f" -- {detail}" if detail and not condition else ""))
    if not condition:
        FAILURES.append(name)


# ── repairs ───────────────────────────────────────────────────────────────────

def test_adds_missing_lucide_icon_without_existing_lucide_import() -> None:
    src = (
        "import { useState } from 'react'\n\n"
        "export default function App() {\n"
        "  const [t] = useState(0)\n"
        "  return <div className=\"p-4\"><Plus />{t}</div>\n}\n"
    )
    out, unresolved = fix_missing_imports("src/App.jsx", src)
    check("adds lucide import when the file has none", "from 'lucide-react'" in out)
    check("imports the exact identifier used", "Plus" in out)
    check("nothing left unresolved", unresolved == [], str(unresolved))


def test_extends_existing_lucide_import_and_keeps_local_aliases() -> None:
    src = (
        "import { Search } from 'lucide-react'\n"
        "export default function A() { return <div><Search /><Plus /></div> }\n"
    )
    out, _ = fix_missing_imports("src/A.jsx", src)
    check("keeps the original icon", "Search" in out)
    check("adds the missing one", "Plus" in out)


def test_repairs_missing_hook_import() -> None:
    src = (
        "export default function A() {\n"
        "  useEffect(() => {}, [])\n"
        "  return <div>hi</div>\n}\n"
    )
    out, _ = fix_missing_imports("src/A.jsx", src)
    check("imports an unimported hook", "useEffect" in out and "from 'react'" in out)


def test_lucide_alias_repair_still_applies() -> None:
    src = "import { Bag } from 'lucide-react'\nexport default function A() { return <Bag /> }\n"
    out, _ = fix_imports("src/A.jsx", src)
    check("hallucinated icon aliased to a real export", "ShoppingBag as Bag" in out)


# ── safety: never shadow a locally bound name ────────────────────────────────

def test_does_not_shadow_destructured_prop_component() -> None:
    src = (
        "export default function A({ Icon, children }) {\n"
        "  return <div><Icon />{children}</div>\n}\n"
    )
    out, unresolved = fix_missing_imports("src/A.jsx", src)
    check("no import invented for a destructured prop", "lucide-react" not in out)
    check("prop component not reported unresolved", unresolved == [], str(unresolved))


def test_does_not_shadow_const_destructuring() -> None:
    src = (
        "export default function A(props) {\n"
        "  const { Icon } = props\n"
        "  return <div><Icon /></div>\n}\n"
    )
    out, _ = fix_missing_imports("src/A.jsx", src)
    check("no import invented for const-destructured name", "lucide-react" not in out)


def test_locally_declared_component_is_left_alone() -> None:
    src = (
        "function Card() { return <div>c</div> }\n"
        "export default function A() { return <Card /> }\n"
    )
    out, _ = fix_missing_imports("src/A.jsx", src)
    check("locally declared component untouched", "lucide-react" not in out)


def test_unknown_component_is_reported_not_invented() -> None:
    src = "export default function A() { return <TotallyMadeUpWidget /> }\n"
    out, unresolved = fix_missing_imports("src/A.jsx", src)
    check("unknown component not silently dropped", "TotallyMadeUpWidget" in unresolved,
          str(unresolved))
    check("no bogus import added", "import" not in out.replace("export default", ""))


# ── end-to-end: the repaired file must really bundle ─────────────────────────

def test_repaired_file_bundles_with_real_esbuild() -> None:
    """The only test that matters: esbuild on the repaired source, and a probe
    that the identifier is actually bound (not left as a free variable)."""
    from agentic_generator import bundle_check

    broken_app = (
        "import { useState } from 'react'\n"
        "export default function App() {\n"
        "  const [bugs] = useState([{ id: 1, severity: 'high' }])\n"
        "  return (\n"
        "    <div className=\"p-6\">\n"
        "      <Plus className=\"w-4 h-4\" />\n"
        "      {bugs.map(b => <span key={b.id}>{b.severity}</span>)}\n"
        "    </div>\n"
        "  )\n}\n"
    )
    files = {
        "package.json": json.dumps({
            "name": "t", "private": True, "version": "0.1.0", "type": "module",
            "scripts": {"dev": "vite"},
            "dependencies": {"react": "^18.2.0", "react-dom": "^18.2.0"},
        }),
        "index.html": '<!doctype html><html><body><div id="root"></div>'
                      '<script type="module" src="/src/main.jsx"></script></body></html>',
        "src/main.jsx": "import React from 'react'\nimport { createRoot } from 'react-dom/client'\n"
                        "import App from './App.jsx'\ncreateRoot(document.getElementById('root'))"
                        ".render(<React.StrictMode><App /></React.StrictMode>)",
        "src/index.css": "@tailwind base;\n@tailwind components;\n@tailwind utilities;",
        "src/App.jsx": broken_app,
    }
    ok_before, _err = bundle_check(files)
    check("baseline bundles even though <Plus /> is undefined (the bug class)",
          ok_before is True, "esbuild should NOT catch this -- that's why the fix exists")

    files["src/App.jsx"], unresolved = fix_imports("src/App.jsx", files["src/App.jsx"])
    ok_after, err = bundle_check(files)
    check("repaired file still bundles", ok_after is True, err[:200])
    check("repair bound the identifier", "Plus" in files["src/App.jsx"].split("export default")[0])
    check("no unresolved names in the repaired file", unresolved == [], str(unresolved))


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in tests:
        print(f"\n{fn.__name__}")
        fn()
    print()
    if FAILURES:
        print(f"FAILED ({len(FAILURES)}): {', '.join(FAILURES)}")
        return 1
    print(f"all {len(tests)} import-fix tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
