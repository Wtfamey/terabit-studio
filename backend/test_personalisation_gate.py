"""Unit tests for the personalisation gate.

bundle_ok only proves the app runs. These prove the app is the USER'S, which
is the complaint that has no automated check behind it until now.

Run:  python test_personalisation_gate.py
"""
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parent))

import agentic_generator as ag  # noqa: E402
from main import extract_product_brief  # noqa: E402

PASS = 0


def check(name, cond, extra=""):
    global PASS
    if cond:
        PASS += 1
        print(f"ok   {name}")
    else:
        raise AssertionError(f"FAIL {name}  {extra}")


HINGLISH = ("mera naam Rahul Sharma hai aur main ek full stack developer hu, "
            "3 saal ka experience hai React aur Node me. Mera personal "
            "portfolio website banani hai dark theme me")
DEVA = ("मेरा नाम राज शर्मा है और मुझे एक किराना दुकान की वेबसाइट चाहिए "
        "जिसमें ऑर्डर करने की सुविधा हो")

TEMPLATE = {"src/App.jsx": (
    'export default function App(){return (<div className="min-h-screen">'
    '<h1>Welcome to Our Platform</h1>'
    '<p>We help you streamline your workflow with powerful tools.</p>'
    '<button className="bg-indigo-600 text-white px-4">Get Started</button>'
    '<h2>Our Services</h2><p>lorem ipsum dolor sit amet</p>'
    '<p>John Doe, CEO</p></div>);}')}

PERSONALISED = {"src/components/Hero.tsx": (
    'export default function Hero(){const a = "Rahul Sharma";'
    'const b = "full stack developer building real time dashboards";'
    'return (<section className="bg-slate-950">'
    '<h1>{a}</h1><p>{b}</p>'
    '<button className="mt-4 px-4">Mujhe contact karo</button>'
    '</section>);}')}

PERSONALISED_DEVA = {"src/components/Hero.tsx": (
    'export default function Hero(){const a = "राज शर्मा";'
    'const b = "किराना दुकान जिसमें ऑर्डर करने की सुविधा है";'
    'return (<section className="bg-stone-950">'
    '<h1>{a}</h1><p>{b}</p></section>);}')}


def main() -> None:
    # 1. a real personalised page passes
    b = extract_product_brief(HINGLISH, "portfolio")
    s = ag.personalisation_score(PERSONALISED, b)
    check("personalised: name found", s["name_used"], s)
    check("personalised: fact found", s["fact_used"], s)
    check("personalised: clean", s["clean"], s)
    check("personalised: language ok", s["lang_ok"], s)
    check("personalised: full score", s["score"] == 1.0, s)

    # 2. a classic template fails the same check
    t = ag.personalisation_score(TEMPLATE, b)
    check("template: name missing", not t["name_used"], t)
    check("template: fact missing", not t["fact_used"], t)
    check("template: seeded filler caught", not t["clean"], t)
    check("template: scores below personalised", t["score"] < s["score"],
          (t, s))

    # 3. Devanagari brief, Devanagari copy
    bd = extract_product_brief(DEVA, "portfolio")
    sd = ag.personalisation_score(PERSONALISED_DEVA, bd)
    check("devanagari: name found", sd["name_used"], sd)
    check("devanagari: language ok", sd["lang_ok"], sd)

    # 4. Devanagari brief, ENGLISH copy must fail the language check
    se = ag.personalisation_score(PERSONALISED, bd)
    check("devanagari brief + english copy: name missing", not se["name_used"], se)
    check("devanagari brief + english copy: language fails", not se["lang_ok"], se)

    # 5. class lists must not be mistaken for copy (the bug that made the
    #    first v2/v3 A/B report name=False for every model)
    cls = {"src/App.tsx": (
        'export default function App(){return (<div className='
        '"flex flex-col items-center justify-center min-h-screen '
        'bg-gradient-to-br from-slate-950 via-slate-900 to-slate-950">'
        '<span className="text-4xl font-bold tracking-tight">x</span>'
        '</div>);}')}
    sc = ag.personalisation_score(cls, b)
    check("class lists are not copy", sc["copy_chars"] == 0, sc)

    # 6. the gate would fire on the template, and stay quiet on the real page
    check("gate fires on template", not t["name_used"] and bool(b["name"]))
    check("gate quiet on personalised", s["name_used"])

    # 7. a brief with no name must not make the gate demand one
    anon = extract_product_brief("build a landing page for a coffee shop", "landing")
    check("anonymous brief has no name", anon["name"] == "", anon)
    sa = ag.personalisation_score(TEMPLATE, anon)
    check("anonymous brief does not penalise missing name",
          sa["name_used"] is False and sa["score"] >= 0.5, sa)

    # 8. the HERO must be in the user's language, not just the page.
    #    Measured 2026-10-02 on a real 19-minute v3 run from a Hinglish
    #    brief: the body copy was correctly Hinglish ("Mujhe Kahaan Se Kahaan
    #    Kariwale Hoon?") while the hero -- the first thing anyone sees --
    #    was plain English. A page-wide language check passed that run at a
    #    false 1.0. This is the check that catches it.
    body_hinglish = {"src/components/About.jsx": (
        'export default function About(){const a = "Mera Profile";'
        'const b = "Mujhe Kahaan Se Kahaan Kariwale Hoon? Aur mera kaam hai";'
        'return (<section><h1>{a}</h1><p>{b}</p></section>);}')}
    hero_english = {"src/components/Hero.jsx": (
        'export default function Hero(){const a = "Rahul Sharma";'
        'const b = "Full Stack Developer building real time dashboards";'
        'return (<section><h1>{a}</h1><p>{b}</p>'
        '<button>Get started</button></section>);}')}
    mixed = dict(body_hinglish, **hero_english)
    sm = ag.personalisation_score(mixed, b)
    check("hero english + body hinglish: HERO lang fails",
          not sm["hero_lang_ok"], sm)
    check("hero english + body hinglish: score below full",
          sm["score"] < 1.0, sm)
    # A localised hero must now PASS. This is the regression guard for the
    # 0.06 -> 0.03 threshold fix: a genuinely translated hero carries only a
    # handful of markers because a hero is short, and the old threshold called
    # it English, so the gate could never be satisfied.
    hero_localised = {"src/components/Hero.jsx": (
        'export default function Hero(){'
        'const a = "Rahul Sharma - Full Stack Developer banaane wale";'
        'const b = "Building real-time dashboards aur secure payment gateways";'
        'return (<section><h1>{a}</h1><p>{b}</p>'
        '<button>Portfolio dekhein</button></section>);}')}
    sl = ag.personalisation_score(hero_localised, b)
    check("localised hero PASSES the hero check", sl["hero_lang_ok"], sl)
    check("localised hero scores full", sl["score"] == 1.0, sl)

    # 9. one stray register word in a page of English is not a translation
    stray = {"src/components/Hero.jsx": (
        'export default function Hero(){const a = "Rahul Sharma";'
        'const b = "Get started building real time dashboards with React";'
        'return (<section><h1>{a}</h1><p>{b}</p>'
        '<span>mujhe</span></section>);}')}
    ss = ag.personalisation_score(stray, b)
    check("single stray marker does not pass", not ss["lang_ok"], ss)

    print(f"\nALL PERSONALISATION-GATE TESTS PASS ({PASS} checks)")


if __name__ == "__main__":
    main()
