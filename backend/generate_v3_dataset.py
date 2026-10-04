"""Generate the v3 TerabitStudio training dataset.

v3 strategy (user directive: no external teacher -- the exemplars are
hand-authored HERE and parameterized by design_system.THEMES):

  one gold exemplar  x  9 domain themes  x  2 business names
  = 162 (instruction, output) pairs

The instruction replicates the RUNTIME ask format -- user prompt + the exact
DESIGN SYSTEM block the generator injects -- so the model learns the single
skill that fixes the live complaints: read the design block, use ONLY those
classes, ship Playfair restaurants / navy-serif law firms / editorial-dark
fashion instead of dark-indigo glassmorphism everywhere (the v2 dataset
hardcoded that style, which is where it came from).

Every (exemplar, theme) pair is validated through the REAL esbuild bundler
before it enters the dataset; a pair that fails never ships (gold data must
be perfect -- one malformed exemplar taught v1 broken syntax).

Output: training_data_v3.jsonl in the schema train_unsloth.py expects.
"""
import json
import re
import sys
from pathlib import Path

import design_system
from gold_exemplars import EXEMPLARS

# Per-domain sample brand names (2 each) so the model learns name is a
# parameter, not a constant.
NAMES = {
    "restaurant": ["Casa Verde", "Osteria Nove"],
    "law": ["Sterling & Cole", "Hale & Marlow"],
    "hospital": ["Happy Tails", "Northside Clinic"],
    "fashion": ["Velvet Thread", "Atelier Noir"],
    "art": ["Milestone Gallery", "Studio Verve"],
    "fitness": ["Iron Yard", "Pulse Studio"],
    "realestate": ["Keystone Realty", "Haven Estates"],
    "education": ["Bright Minds Academy", "Lumen Tutors"],
    "saas": ["Flowboard", "TaskPilot"],
}

# Realistic user asks per exemplar kind (varied phrasing, one per exemplar).
ASKS = {
    "Hero": "Build a landing page for {name}, a {domain_label}. Start with a striking hero section.",
    "Menu": "Build a landing page for {name}, a {domain_label}. I need a beautiful menu/offerings section.",
    "Reservations": "Build a landing page for {name}, a {domain_label}. Include a reservations/booking section with a form.",
    "Faq": "Build a landing page for {name}, a {domain_label}. Add an FAQ section.",
    "Features": "Build a landing page for {name}, a {domain_label}. Start with a features section.",
    "Pricing": "Build a landing page for {name}, a {domain_label}. Add a pricing section with three tiers.",
    "Testimonials": "Build a landing page for {name}, a {domain_label}. Add a testimonials section with real quotes.",
    "Cta": "Build a landing page for {name}, a {domain_label}. Add a closing call-to-action banner with the booking link.",
    "StatCards": "Build a {domain_label} dashboard for {name}. Start with a KPI stat-card row.",
    "DataTable": "Build a {domain_label} dashboard for {name}. I need a searchable accounts data table.",
    "Dashboard": "Build the main dashboard screen for {name}, a {domain_label} product.",
}

SECTION_PATHS = {
    "Hero": "src/components/Hero.jsx",
    "Menu": "src/components/Menu.jsx",
    "Reservations": "src/components/Reservations.jsx",
    "Faq": "src/components/Faq.jsx",
    "Features": "src/components/Features.jsx",
    "Pricing": "src/components/Pricing.jsx",
    "Testimonials": "src/components/Testimonials.jsx",
    "Cta": "src/components/Cta.jsx",
    "StatCards": "src/components/StatCards.jsx",
    "DataTable": "src/components/DataTable.jsx",
    "Dashboard": "src/pages/Dashboard.jsx",
}

DOMAIN_LABELS = {
    "restaurant": "restaurant", "law": "law firm", "hospital": "healthcare practice",
    "fashion": "fashion boutique", "art": "art gallery", "fitness": "fitness studio",
    "realestate": "real estate agency", "education": "education platform",
    "saas": "SaaS",
}


def substitute(exemplar: str, theme: dict, name: str) -> str:
    tw = theme["tw"]
    slug = "".join(ch for ch in name.lower() if ch.isalnum())
    tokens = {
        "@@PAGE_BG@@": tw["page_bg"], "@@SURFACE@@": tw["surface"],
        "@@SURFACE2@@": tw["surface_2"], "@@HEAD@@": tw["heading_text"],
        "@@BODY@@": tw["body_text"], "@@MUTED@@": tw["muted_text"],
        "@@PRIMARY@@": tw["primary"], "@@PRIMARY_HOVER@@": tw["primary_hover"],
        "@@ON_PRIMARY@@": tw["on_primary"], "@@BORDER@@": tw["border"],
        "@@ACCENT_TEXT@@": tw["accent_text"], "@@ACCENT_BG@@": tw["accent_bg"],
        "@@GRAD@@": tw["gradient"], "@@RADIUS@@": theme["radius"],
        "@@NAME@@": name, "@@SLUG@@": slug,
    }
    out = exemplar
    for k, v in tokens.items():
        out = out.replace(k, v)
    leftover = re.findall(r"@@[A-Z_]+@@", out)
    if leftover:
        raise ValueError(f"unsubstituted tokens: {leftover}")
    return out


def validate_component(path: str, code: str,
                       extra_files: dict | None = None) -> tuple[bool, str]:
    """Bundle + server-render the component through the REAL checkers."""
    from agentic_generator import bundle_check, render_check
    stem = Path(path).stem
    entry = "src/main.jsx"
    files = {
        path: code,
        **(extra_files or {}),
        entry: (
            "import React from 'react';\n"
            "import ReactDOM from 'react-dom/client';\n"
            f"import {stem} from './{path.split('src/')[-1][:-4]}';\n"
            f"ReactDOM.createRoot(document.getElementById('root')).render(<{stem} />);"
        ),
        "index.html": '<!doctype html><html><body><div id="root"></div>'
                      '<script type="module" src="/src/main.jsx"></script></body></html>',
    }
    ok, err = bundle_check(files)
    if not ok:
        return False, f"bundle: {err[:200]}"
    ok, err = render_check(files)
    if not ok:
        return False, f"render: {err[:200]}"
    return True, ""


def main() -> None:
    out_path = Path(__file__).parent / "training_data_v3.jsonl"
    seen = set()
    examples = []
    failures = []

    for key, theme_key in [(k, k) for k in NAMES]:
        theme = design_system.get_design({"domain": theme_key, "business_type": "", "offerings": []})
        label = DOMAIN_LABELS[theme_key]
        for name in NAMES[theme_key]:
            for stem, code in EXEMPLARS.items():
                inst = ASKS[stem].format(name=name, domain_label=label)
                design_txt = design_system.design_block(theme, name)
                instruction = (
                    f"Create a React component {SECTION_PATHS[stem]}: {inst}\n\n"
                    f"{design_txt}\n\n"
                    f"Write {SECTION_PATHS[stem]} now -- path in backticks on its own "
                    "line, then one complete fenced block."
                )
                filled = substitute(code, theme, name)
                output = f"`{SECTION_PATHS[stem]}`\n```jsx\n{filled}\n```"
                extra_files = {}
                if stem == "Dashboard":
                    # Dashboard imports './StatCards' from src/pages/ -- the
                    # validation copies must sit beside it to resolve.
                    for child in ("StatCards", "DataTable"):
                        extra_files[f"src/pages/{child}.jsx"] = substitute(
                            EXEMPLARS[child], theme, name)
                sig = (stem, theme_key, name)
                if sig in seen:
                    continue
                seen.add(sig)

                ok, err = validate_component(SECTION_PATHS[stem], filled, extra_files)
                if not ok:
                    failures.append((stem, theme_key, name, err))
                    continue
                examples.append({"instruction": instruction, "output": output})

    with out_path.open("w", encoding="utf-8") as f:
        for ex in examples:
            f.write(json.dumps(ex, ensure_ascii=False) + "\n")

    print(f"[v3] wrote {len(examples)} examples -> {out_path}")
    if failures:
        print(f"[v3] {len(failures)} FAILURES (excluded):")
        for stem, tk, name, err in failures[:10]:
            print(f"  - {stem}/{tk}/{name}: {err}")
        sys.exit(1)


if __name__ == "__main__":
    main()
