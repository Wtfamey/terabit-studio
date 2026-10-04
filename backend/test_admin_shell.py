"""Tests for the back-office (admin / management system) archetype.

Before this, "a store management system" routed to the ecommerce storefront
(cart and all) and "a hospital management system" fell through to the SaaS
marketing scaffold. Management systems are multi-view admin apps, so they now
have their own archetype, a deterministic view plan, and a composed shell.

Run:  cd backend && python test_admin_shell.py
"""
import re

import agentic_generator as ag
import domain_profiles as dp
from scaffolds import get_archetype_for_prompt

# ── archetype routing ──────────────────────────────────────────────────────
ROUTING = {
    "a hospital management system": "admin",
    "a store management system": "admin",
    "an employee management system": "admin",
    "build an inventory management system": "admin",
    "a clinic management system": "admin",
    "a POS system for my shop": "admin",
    "a restaurant site": "landing",
    "a restaurant website": "landing",
    "a website for a law firm": "landing",
    "a portfolio website": "landing",
    "an ecommerce store": "ecommerce",
    "build me a CRM for leads": "crm",
}
for prompt, want in ROUTING.items():
    got = get_archetype_for_prompt(prompt, "")
    assert got == want, f"{prompt!r} -> {got!r}, want {want!r}"
print(f"routing ok for {len(ROUTING)} prompts")

# ── admin view sets ────────────────────────────────────────────────────────
HOSPITAL = {"domain": "hospital management system", "business_type": "", "offerings": [], "prompt": ""}
STORE = {"domain": "", "business_type": "", "offerings": [], "prompt": "a store management system"}
EMPLOYEE = {"domain": "", "business_type": "", "offerings": [], "prompt": "an employee management system"}

assert [v["stem"] for v in dp.admin_views(HOSPITAL)][:2] == ["Dashboard", "Patients"]
assert "Products" in [v["stem"] for v in dp.admin_views(STORE)]
assert "Employees" in [v["stem"] for v in dp.admin_views(EMPLOYEE)]
# unknown back-office domain still gets a usable generic set
GENERIC = {"domain": "", "business_type": "", "offerings": [], "prompt": "a management system for widgets"}
assert len(dp.admin_views(GENERIC)) >= 3
# every view declares a lucide icon name and a spec
for brief in (HOSPITAL, STORE, EMPLOYEE, GENERIC):
    for v in dp.admin_views(brief):
        assert v["icon"] and v["icon"][0].isupper(), v
        assert len(v["spec"]) > 40, v
print("admin view sets ok")

# ── plan is deterministic and covers every view ───────────────────────────
plan = ag._plan_files_admin([{"role": "system", "content": ""}, {"role": "user", "content": "hospital management system"}], HOSPITAL)
paths = [p["path"] for p in plan]
assert paths[0] == "src/App.jsx", paths
assert "src/components/Patients.jsx" in paths and "src/components/Dashboard.jsx" in paths
assert len(paths) == 1 + len(dp.admin_views(HOSPITAL)), paths
print(f"plan ok: {paths}")

# ── shell composition ─────────────────────────────────────────────────────
_VIEW = (
    "import React, {{ useState }} from 'react';\n"
    "import {{ Plus, Search }} from 'lucide-react';\n\n"
    "const rows = [{{ id: 'P-001', name: 'Ada Lovelace', ward: 'A', status: 'Active' }}];\n\n"
    "export default function {stem}() {{\n"
    "  const [q, setQ] = useState('');\n"
    "  return (\n"
    "    <section className=\"space-y-4\">\n"
    "      <div className=\"rounded-2xl bg-white border border-slate-200 p-4\">\n"
    "        <input value={{q}} onChange={{(e) => setQ(e.target.value)}} className=\"w-full\" />\n"
    "        <button className=\"rounded-lg bg-slate-900 px-3 py-2 text-white\">\n"
    "          <Plus className=\"w-4 h-4\" /> Add\n"
    "        </button>\n"
    "      </div>\n"
    "      {{rows.map((r) => (\n"
    "        <div key={{r.id}} className=\"rounded-xl bg-white p-4\">{{r.name}}</div>\n"
    "      ))}}\n"
    "    </section>\n"
    "  );\n"
    "}}\n"
)

for label, brief in (("hospital", HOSPITAL), ("store", STORE), ("employee", EMPLOYEE)):
    gen = {f"src/components/{v['stem']}.jsx": _VIEW.format(stem=v["stem"])
           for v in dp.admin_views(brief)}
    shell, dropped = ag._compose_admin_shell(
        gen, {"archetype": "admin", "app_name": "MediCore"}, {"name": "MediCore"}, brief,
    )
    assert shell, f"{label}: no shell"
    assert dropped == [], f"{label}: views dropped -> {dropped}"
    # every view is imported once and present in the registry
    for stem in gen:
        name = stem.split("/")[-1][:-4]
        assert shell.count(f"import {name} from") == 1, f"{label}: {name} import count"
        assert f"View: {name} }}" in shell, f"{label}: {name} missing from registry"
    # the gradient placeholder must be substituted with a real class string,
    # and no unresolved Python-side token lookup may survive into the client
    assert "__GRAD__" not in shell, "GRAD placeholder leaked into output"
    assert "tw." not in shell, "design-token lookup leaked into the client template"
    assert ".page_bg}" not in shell and ".accent_bg}" not in shell, "raw token name in output"
    # nav, view switching and motion must be present
    assert "setActive(" in shell and "ActiveView" in shell
    assert "animate-fade-up" in shell
    assert shell.count("transition-all duration-200") >= 2, "controls without transitions"

    files = dict(gen)
    files["src/App.jsx"] = shell
    files["src/main.jsx"] = (
        "import React from 'react';\nimport { createRoot } from 'react-dom/client';\n"
        "import App from './App';\ncreateRoot(document.getElementById('root')).render(<App />);\n"
    )
    ok_b, err_b = ag.bundle_check(files)
    assert ok_b, f"{label}: admin shell does not bundle: {err_b[:300]}"
    ok_r, err_r = ag.render_check(files)
    assert ok_r, f"{label}: admin shell does not render: {err_r[:300]}"
    print(f"  {label:10s} views={len(gen)} bundle=OK render=OK")

# ── a broken view is dropped, not fatal ───────────────────────────────────
gen = {f"src/components/{v['stem']}.jsx": _VIEW.format(stem=v["stem"]) for v in dp.admin_views(HOSPITAL)}
gen["src/components/Appointments.jsx"] = "export default function Appointments() { return <div>{oops</div>; }\n"
shell, dropped = ag._compose_admin_shell(gen, {"archetype": "admin", "app_name": "X"}, {"name": "X"}, HOSPITAL)
assert dropped == ["src/components/Appointments.jsx"], dropped
assert "Appointments" not in shell.split("const VIEWS")[0].replace("VIEWS.find", ""), "broken view still imported"
files = {k: v for k, v in gen.items() if k not in dropped}
files["src/App.jsx"] = shell
files["src/main.jsx"] = (
    "import React from 'react';\nimport { createRoot } from 'react-dom/client';\n"
    "import App from './App';\ncreateRoot(document.getElementById('root')).render(<App />);\n"
)
ok, err = ag.bundle_check(files)
assert ok, f"shell with a dropped view must still bundle: {err[:250]}"
print("broken-view drop ok")

print("ALL ADMIN-SHELL TESTS PASS")
