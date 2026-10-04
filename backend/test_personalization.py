"""Personalization regression suite.

Covers the two live failures from the owner's report (2026-10-01):
  1. "portfolio website ... my name is X ... i am a ..." shipped as a generic
     template ("PortfolioName", placeholder bio) -- the brief now carries the
     person's name + stated facts.
  2. "i have uploaded my image" -- the image never appeared in the output --
     inject_user_assets is the deterministic backstop.
"""
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from main import extract_product_brief
import agentic_generator as ag
import imagery
import multilingual

PASS = 0


def _has_devanagari(s):
    return any("\u0900" <= ch <= "\u097f" for ch in s or "")


def check(name, cond, extra=""):
    global PASS
    if cond:
        PASS += 1
        print(f"ok   {name}")
    else:
        raise AssertionError(f"FAIL {name} {extra}")


# ── 1. brief: person name + facts ─────────────────────────────────────────
b = extract_product_brief(
    "i need you to build me a portfolio website my name is amey chikane i am a "
    "computer science graduate specializing in ai and ml tasks i am an ai "
    "engineer and consultant i have uploaded my image you can use it in site "
    "and also as my logo",
    "portfolio",
)
check("person name", b["name"] == "Amey Chikane", b["name"])
check("person flag", b["person"] is True)
check("two facts", len(b["facts"]) == 2, b["facts"])
check("fact 1", "computer science graduate" in b["facts"][0], b["facts"])
check("fact 2", b["facts"][1] == "ai engineer and consultant", b["facts"])
check("no image-noise fact", not any("upload" in f for f in b["facts"]), b["facts"])

# non-person prompts must NOT be flagged personal
biz = extract_product_brief(
    "A website for Hartwell & Sawyer, a boutique law firm, with practice areas, fees",
    "law",
)
check("biz not person", biz["person"] is False)
check("biz name kept", biz["name"] == "Hartwell & Sawyer", biz["name"])

coffee = extract_product_brief(
    "Build a modern e-commerce store for premium coffee beans with product catalog, cart",
    "ecommerce",
)
check("coffee subject", coffee["subject"] == "premium coffee beans", coffee["subject"])

# ── 2. inject_user_assets: placeholder swap ───────────────────────────────
files = {
    "src/components/Hero.jsx": (
        'export default function Hero() {\n'
        '  return (<section><img src="https://picsum.photos/800/600" '
        'className="rounded" alt="me" /><h1>Hi</h1></section>);\n}\n'
    ),
    "src/components/About.jsx": (
        'export default function About() {\n  return (<section><p>bio</p></section>);\n}\n'
    ),
}
assets = [{"url": "/uploads/amey.jpg", "filename": "amey.jpg"}]
out, injected = ag.inject_user_assets(dict(files), assets, logo_url="")
check("placeholder swapped", "/uploads/amey.jpg" in out["src/components/Hero.jsx"])
check("picsum gone", "picsum.photos" not in out["src/components/Hero.jsx"])
check("trace line", injected and "Hero.jsx" in injected[0], injected)

# ── 3. inject_user_assets: injection when no <img> exists ─────────────────
out2, injected2 = ag.inject_user_assets(dict(files), assets, logo_url="")
# second asset, same url is now absent only in About; force a fresh url
assets2 = [{"url": "/uploads/shot2.png", "filename": "shot2.png"}]
out3, injected3 = ag.inject_user_assets(dict(files), assets2, logo_url="")
hero3 = out3["src/components/Hero.jsx"]
check("injected into hero when needed",
      "/uploads/shot2.png" in hero3 or "/uploads/shot2.png" in out3["src/components/About.jsx"],
      injected3)

# ── 4. already-present url is a no-op ─────────────────────────────────────
pre = {
    "src/components/Hero.jsx": (
        'export default function Hero() {\n'
        '  return (<section><img src="/uploads/amey.jpg" alt="me" /></section>);\n}\n'
    ),
}
out4, inj4 = ag.inject_user_assets(dict(pre), assets, logo_url="")
check("no-op when present", out4 == pre and inj4 == [], (out4, inj4))

# ── 5. imagery enforcement must not touch /uploads/ ───────────────────────
files5 = {"src/components/Hero.jsx": '<img src="/uploads/amey.jpg" alt="x" />'}
out5, stats5 = imagery.enforce_imagery(dict(files5), "portfolio")
check("uploads survive imagery pass",
      "/uploads/amey.jpg" in out5["src/components/Hero.jsx"],
      out5)

# ── 6. AssetInfo pydantic objects must not crash the asset pass ───────────
# Live failure (2026-10-01 19:17): run_agent called .get() on pydantic
# AssetInfo objects -> whole agent run crashed -> silent fallback to the
# single-shot path and a lost 10-minute run.
from main import AssetInfo
import inspect as _inspect

src = _inspect.getsource(ag.run_agent)
check("run_agent normalizes assets", "model_dump" in src, "asset normalization missing")

obj = AssetInfo(url="/uploads/x.jpg", filename="x.jpg", mime_type="image/jpeg",
                original_name="logo.png")
normalized = obj.model_dump()
check("AssetInfo.model_dump works", normalized["original_name"] == "logo.png")
check("AssetInfo has no .get (regression guard)", not hasattr(obj, "get"))

# ── 7. multilingual briefs (Hinglish / Marathi / Devanagari) ─────────────
# Live failure (2026-10-02): every regex in extract_product_brief is English,
# so a brief typed in Hinglish, romanised Marathi or Devanagari produced an
# EMPTY record -- no name, no domain, no facts -- which is precisely what
# ships a perfectly built, perfectly generic template.
ML_CASES = [
    ("hinglish portfolio",
     "mera naam Rahul Sharma hai aur main ek full stack developer hu, "
     "mera personal portfolio website banani hai dark theme me",
     "Rahul Sharma", "portfolio"),
    ("marathi roman grocery",
     "maza naav Sangam Kulkarni aahe ani mala ek kiranacha dukhan "
     "banvayacha aahe, shimla bhanda pan rate chhandi pahijet",
     "Sangam Kulkarni", "grocery shop"),
    ("marathi devanagari shop",
     "माझे नाव अमेय चिकाणे आहे आणि मी एक दुकान बनवू इच्छितो "
     "आणि त्यात कपडे विकणे आहेत",
     "अमेय चिकाणे", "retail shop"),
    ("hindi devanagari grocery",
     "मेरा नाम राज शर्मा है और मुझे एक किराना दुकान की वेबसाइट चाहिए "
     "जिसमें ऑर्डर करने की सुविधा हो",
     "राज शर्मा", "grocery shop"),
    ("hindi devanagari parlour",
     "मेरा नाम सुनीता शर्मा है और मी एक ब्यूटी पार्लर हूँ, मुझे "
     "वेबसाइट चाहिए",
     "सुनीता शर्मा", "beauty parlour"),
]
for _label, _prompt, _want_name, _want_domain in ML_CASES:
    _b = extract_product_brief(_prompt)
    check(f"ml {_label}: name", _b["name"] == _want_name, _b["name"])
    check(f"ml {_label}: person", _b["person"] is True)
    check(f"ml {_label}: domain", _b["domain"] == _want_domain, _b["domain"])
    check(f"ml {_label}: facts", len(_b["facts"]) >= 1, _b["facts"])
    check(f"ml {_label}: language tagged", _b["language"] != "English",
          _b["language"])
    for _f in _b["facts"]:
        check(f"ml {_label}: fact usable", multilingual._usable_fact(_f), _f)

check("ml hindi grocery offerings",
      "online ordering" in extract_product_brief(ML_CASES[3][1])["offerings"])
check("ml hindi grocery cta",
      extract_product_brief(ML_CASES[3][1])["cta"] == "order now")
check("english language untouched",
      extract_product_brief("my name is Amey Chikane i am a developer"
                            )["language"] == "English")
check("english brief has no junk devanagari",
      all(not _has_devanagari(f) for f in b["facts"]))

# ── 8. business/person names stated the other common ways ───────────────
# Found while building the self-distillation brief bank: 2 of 22 realistic
# briefs lost their name entirely, which means 2 of 22 shipped pages get
# branded with an archetype name instead of the customer's.
NAME_SHAPES = [
    ("called the business",
     "build a landing page for a dental clinic called Bright Smile in Nashik, "
     "we do root canals and implants, show a price list",
     "Bright Smile"),
    ("called the brand",
     "i run a small bakery called Crumb in pune, we sell sourdough bread and "
     "add an faq about pre orders",
     "Crumb"),
    ("trade noun then name",
     "a website for my tailoring business, Meera Stitch, I do wedding lehenga "
     "and blouse stitching in Jaipur",
     "Meera Stitch"),
    ("i am Name, comma appositive",
     "I am Priya Nair, a freelance product designer in Pune. Build me a "
     "personal portfolio site for my design work",
     "Priya Nair"),
    ("for Name, appositive",
     "build a website for Casa Verde, an italian restaurant in pune, our "
     "speciality is wood fired pizza",
     "Casa Verde"),
]
for _label, _prompt, _want in NAME_SHAPES:
    _got = extract_product_brief(_prompt, "landing")["name"]
    check(f"name shape: {_label}", _got == _want, f"got {_got!r} want {_want!r}")

# A sentence-initial capitalised word must never become the brand.
check("sentence-initial verb is not a name",
      extract_product_brief("Build a landing page for a law firm in Pune, "
                            "we handle property disputes", "landing")["name"]
      not in ("Build", "Landing"))

# \u2500\u2500 9. script-safe tokenising: \w shreds Devanagari at every matra \u2500\u2500\u2500\u2500\u2500\u2500\u2500
# Found while generalising section asks (2026-10-02). Python's \w matches
# Devanagari LETTERS but not the Mn/Mc combining marks that carry the vowel,
# so re.findall(r"[\w']+", ...) turned "\u091a\u093f\u0924\u094d\u0930\u0915\u093e\u0930" into three tokens and the
# derived asks for a Marathi brief came back as bare consonants ("\u092c\u0938 \u0907\u091f \u092c\u0928"
# is "\u0935\u0947\u092c\u0938\u093e\u0907\u091f" and "\u092c\u0928\u093e\u0913" with every vowel deleted). No English test could
# see it, and the output looked like a plausible short string.
_TOK_CASES = [
    ("devanagari word stays whole",
     "\u091a\u093f\u0924\u094d\u0930\u0915\u093e\u0930", ["\u091a\u093f\u0924\u094d\u0930\u0915\u093e\u0930"]),
    ("devanagari sentence keeps every word",
     "\u092e\u0948\u0902 \u090f\u0915 \u091a\u093f\u0924\u094d\u0930\u0915\u093e\u0930 \u0939\u0942\u0901, \u092e\u0947\u0930\u0947 \u091a\u093f\u0924\u094d\u0930\u094b\u0902 \u0915\u0947 \u0932\u093f\u090f \u0935\u0947\u092c\u0938\u093e\u0907\u091f \u092c\u0928\u093e\u0913",
     ["\u092e\u0948\u0902", "\u090f\u0915", "\u091a\u093f\u0924\u094d\u0930\u0915\u093e\u0930", "\u0939\u0942\u0901", "\u092e\u0947\u0930\u0947", "\u091a\u093f\u0924\u094d\u0930\u094b\u0902", "\u0915\u0947", "\u0932\u093f\u090f",
      "\u0935\u0947\u092c\u0938\u093e\u0907\u091f", "\u092c\u0928\u093e\u0913"]),
    ("bengali word stays whole", "\u09b6\u09bf\u09b2\u09cd\u09aa\u09c0", ["\u09b6\u09bf\u09b2\u09cd\u09aa\u09c0"]),
    ("gujarati stays whole", "ગுજરાਤી", ["ગுજરાਤી"]),
    ("bengali sentence",
     "\u0986\u09ae\u09bf \u098f\u0995\u099c\u09a8 \u099b\u09ac\u09bf\u09b0 \u09b6\u09bf\u09b2\u09cd\u09aa\u09c0, \u0986\u09ae\u09be\u09b0 \u09b6\u09bf\u09b2\u09cd\u09aa\u09c7\u09b0 \u099c\u09a8\u09cd\u09af \u0993\u09af\u09bc\u09c7\u09ac\u09b8\u09be\u0987\u099f \u09ac\u09be\u09a8\u09be\u09a8",
     ["\u0986\u09ae\u09bf", "\u098f\u0995\u099c\u09a8", "\u099b\u09ac\u09bf\u09b0", "\u09b6\u09bf\u09b2\u09cd\u09aa\u09c0", "\u0986\u09ae\u09be\u09b0", "\u09b6\u09bf\u09b2\u09cd\u09aa\u09c7\u09b0", "\u099c\u09a8\u09cd\u09af",
      "\u0993\u09af\u09bc\u09c7\u09ac\u09b8\u09be\u0987\u099f", "\u09ac\u09be\u09a8\u09be\u09a8"]),
    ("ascii behaviour is unchanged",
     "I am a farrier, I need a website",
     ["I", "am", "a", "farrier", "I", "need", "a", "website"]),
    ("apostrophe and hyphen survive", "don't re-do",
     ["don't", "re-do"]),
    ("accented latin survives", "caf\u00e9", ["caf\u00e9"]),
    ("empty input is not an exception", "", []),
]
for _label, _text, _want in _TOK_CASES:
    _got = multilingual.tokens(_text)
    check(f"tokens: {_label}", _got == _want, f"got {_got!r} want {_want!r}")

# The end-to-end consequence: a Marathi brief's section asks must be
# readable Marathi words, not consonant skeletons. Each derived ask must
# appear (as a substring) in the text the user actually typed -- which is
# the generalisation test: nothing may be invented, in any script.
_marathi = ("\u092e\u0948\u0902 \u090f\u0915 \u091a\u093f\u0924\u094d\u0930\u0915\u093e\u0930 \u0939\u0942\u0901, \u092e\u0947\u0930\u0947 \u091a\u093f\u0924\u094d\u0930\u094b\u0902 \u0914\u0930 \u092a\u094d\u0930\u0926\u0930\u094d\u0936\u0928\u093f\u092f\u094b\u0902 \u0915\u0947 \u0932\u093f\u090f "
            "\u0935\u0947\u092c\u0938\u093e\u0907\u091f \u092c\u0928\u093e\u0913")
_asks = extract_product_brief(_marathi)["offerings"]
check("marathi brief derives at least 2 asks", len(_asks) >= 2, f"got {_asks!r}")
_m_pool = set(multilingual.tokens(_marathi))
check("every marathi ask occurs in the user's own words",
      bool(_asks) and all(set(multilingual.tokens(a)) <= _m_pool
                           for a in _asks),
      f"got {_asks!r}")
check("marathi asks carry no vowel-less skeleton",
      bool(_asks) and all(
          not re.fullmatch(r"[\u0900-\u097f]{1,3}", a) for a in _asks),
      f"got {_asks!r}")
check("identity clause is not mined as an offering",
      not any(_a.startswith("\u092e\u0948\u0902") or _a.startswith("\u092e\u0947\u0930\u093e") for _a in _asks),
      f"got {_asks!r}")

# And the same guarantee for English: an ask must be a phrase the user
# wrote. This is what makes the derivation general rather than a per-trade
# table -- it cannot invent an offering, so it cannot be right for one
# customer and wrong for the next.
UNSEEN_TRADES = [
    ("arborist", "I'm an arborist, I need a website to show my tree care "
                 "and stump removal work", "tree care"),
    ("xerographer", "I am an xerographer, build me a portfolio of my "
                    "cyanotype prints and workshops", "cyanotype prints"),
    ("luthier", "I run a luthier workshop, need a website to sell my "
                "handmade violins and guitars", "handmade violins"),
    ("numismatist", "I'm a numismatist, want a site for my ancient coin "
                    "collection and appraisals", "ancient coin collection"),
    ("beekeeper", "I'm a beekeeper, need a website for my raw honey, hives "
                  "and pollination services", "pollination services"),
    ("cartographer", "I am a cartographer, build me a portfolio for my "
                     "topographic maps", "topographic maps"),
    ("glassblower", "I'm a glassblower, make me a site for my blown glass "
                    "vases and commissions", "blown glass vases"),
    ("saddler", "I run a saddlery, need a site for my hand-stitched "
                "leather saddles and repairs", "leather saddles"),
]
for _trade, _prompt, _must in UNSEEN_TRADES:
    _offs = extract_product_brief(_prompt)["offerings"]
    check(f"unseen trade derives asks: {_trade}", bool(_offs), f"got {_offs!r}")
    check(f"unseen trade ask is the user's own words: {_trade}",
          any(_must in _o for _o in _offs), f"want {_must!r} in {_offs!r}")
    _pool = set(multilingual.tokens(_prompt.lower()))
    check(f"unseen trade invents nothing: {_trade}",
          all(set(multilingual.tokens(_o.lower())) <= _pool for _o in _offs),
          f"got {_offs!r}")

# Negative control: a brief that is only about the ARTIFACT must derive
# nothing. If these ever come back full, the stop tables have stopped
# filtering chrome words and every trade looks personalised again.
for _label, _prompt in [
    ("dark mode", "build me a modern responsive website with dark mode and "
                  "smooth animations"),
    ("fonts and colours", "make a clean minimal one page landing site, nice "
                          "colors, good fonts"),
]:
    check(f"artifact-only brief derives nothing: {_label}",
          extract_product_brief(_prompt)["offerings"] == [],
          f"got {extract_product_brief(_prompt)['offerings']!r}")

print(f"\nALL PERSONALIZATION TESTS PASS ({PASS} checks)")
