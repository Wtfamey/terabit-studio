"""Design-adherence gate for TerabitStudio generations.

Scores a run's result.json (backend/comparison/<slug>/<ts>/result.json)
against the domain's design_system theme:

  palette   -- fraction of color utility classes that belong to the theme's
               families (live failure v2: dark-indigo glassmorphism on a warm
               cream restaurant; neon indigo/violet/pink drift)
  font      -- theme font classes actually used (.font-display / heading_css)
  brand     -- brief name present in shipped JSX copy
  motion    -- reveal/animate classes present (scroll animations)
  imagery   -- real photo usage (picsum) instead of empty boxes

Gate: palette >= 0.80 (plus brand for named briefs) == PASS. The retrain
promotion decision should require this gate on live runs -- it turns "looks
better" into a number the pipeline can gate on.

Usage:
  python eval_design_gate.py backend/comparison/<slug>/<ts>/result.json
  python eval_design_gate.py --all          # sweep every saved run
"""
import argparse
import glob
import json
import re
import sys
from pathlib import Path

import design_system
import domain_profiles

# Universal utility families that are palette-neutral, plus semantic status
# colors the gold exemplars legitimately use (success/error/veg/spicy chips).
_NEUTRAL = {"white", "black", "current", "transparent"}
_SEMANTIC = {"emerald", "red", "amber", "sky"}
_NEON = {"indigo", "violet", "purple", "fuchsia", "pink"}

_COLOR_CLASS_RE = re.compile(
    r"(?:bg|text|from|via|to|border|ring)-([a-z]+)-\d{2,3}\b")


def allowed_families(theme: dict) -> set[str]:
    fams = set(_NEUTRAL) | set(_SEMANTIC)
    for v in theme["tw"].values():
        fams.update(m.group(1) for m in _COLOR_CLASS_RE.finditer(v))
        # arbitrary hex values (bg-[#faf6f0]) are always allowed
    return fams


def score_files(files: list[dict], brief: dict) -> dict:
    theme = design_system.get_design(brief)
    allowed = allowed_families(theme)
    jsx = "\n".join(f["content"] for f in files
                    if f["path"].endswith((".jsx", ".tsx")))
    # Brand may legitimately live in the shell or the tab title rather than
    # each section file.
    everything = jsx + "\n" + "\n".join(
        f["content"] for f in files if f["path"].endswith((".html", ".css")))
    classes = [m.group(1) for m in _COLOR_CLASS_RE.finditer(jsx)]
    total = len(classes)
    on = sum(1 for c in classes if c in allowed)
    neon = [c for c in classes
            if c in _NEON and c not in allowed]
    palette = round(on / total, 3) if total else 0.0

    name = (brief.get("name") or "").strip()
    has_brand = (not name) or (name.lower() in everything.lower())
    uses_display = ".font-display" in jsx or "font-display" in jsx
    has_motion = ("reveal" in jsx) or ("animate-fade" in jsx)
    has_imagery = ("picsum.photos" in jsx) or ("<img" in jsx)
    has_gradient = "bg-gradient-to-" in jsx

    passed = palette >= 0.80 and has_brand and uses_display
    return {
        "theme": theme["key"],
        "palette_adherence": palette,
        "color_classes": total,
        "neon_drift": len(neon),
        "neon_families": sorted(set(neon)),
        "font_used": uses_display,
        "brand_present": has_brand,
        "animations": has_motion,
        "imagery": has_imagery,
        "gradient": has_gradient,
        "gate": "PASS" if passed else "FAIL",
    }


def brief_of_run(run_dir: Path) -> dict:
    try:
        req = json.loads((run_dir / "request.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    brief = req.get("brief") or {}
    if not brief.get("domain"):
        # fall back to keyword detection over the prompt
        brief = dict(brief)
        brief.setdefault("domain", req.get("prompt", ""))
        brief.setdefault("business_type", "")
        brief.setdefault("offerings", [])
        brief["domain"] = domain_profiles.detect_domain(brief) and brief["domain"]
    return brief


def score_run(run_dir: Path) -> dict:
    res = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
    return score_files(res.get("files", []), brief_of_run(run_dir))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("result", nargs="?", help="path to a result.json")
    ap.add_argument("--all", action="store_true", help="score every saved run")
    args = ap.parse_args()

    if args.all:
        root = Path(__file__).parent / "comparison"
        rows = []
        for rj in sorted(root.glob("*/*/result.json")):
            try:
                s = score_run(rj.parent)
                rows.append((rj.parent.parent.name[:34], rj.parent.name, s))
            except Exception as e:  # noqa: BLE001
                rows.append((rj.parent.parent.name[:34], rj.parent.name,
                             {"gate": f"ERR {e}"}))
        for slug, ts, s in rows:
            print(f"{slug:34s} {ts} {s.get('theme', '?'):10s} "
                  f"palette={s.get('palette_adherence', '-')} "
                  f"neon={s.get('neon_drift', '-')} "
                  f"font={s.get('font_used', '-')} "
                  f"-> {s.get('gate')}")
        return

    if not args.result:
        ap.error("give a result.json path or --all")
    s = score_run(Path(args.result).parent)
    print(json.dumps(s, indent=2))
    sys.exit(0 if s["gate"] == "PASS" else 2)


if __name__ == "__main__":
    main()
