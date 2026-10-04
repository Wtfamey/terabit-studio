"""Tests for open-vocabulary task understanding.

The point of this layer is that the *shape* of the deliverable is inferred
from what the user asked for (gallery, fees, booking, records, checkout),
never from a list of professions. So the test suite is a list of people, not
a list of keywords: each case is a real-sounding request from somebody whose
trade has no curated profile, and the assertions are about the structure that
comes back.

Run:  cd backend && python test_task_understanding.py
"""
import re

import domain_profiles as dp
import task_understanding as tu

PASS = 0


def check(cond, msg):
    global PASS
    assert cond, msg
    PASS += 1


def stems(profile):
    return [s["stem"] for s in profile["sections"]]


def specs(profile):
    return " ".join(s["spec"] for s in profile["sections"])


# ── 1. a lawyer whose brief never says "law" ──────────────────────────────
# The curated law profile is unreachable here (no law keyword anywhere), which
# is exactly the point: the sections come from "practice areas" and "fees".
LAWYER = {
    "domain": "private practice", "business_type": "",
    "offerings": ["mediation", "contract drafting"],
    "prompt": "a website for my practice with my practice areas and fees",
}
p = tu.build_profile(LAWYER)
check(tu.infer_spec(LAWYER)["family"] == "site", f"lawyer family: {tu.infer_spec(LAWYER)}")
check("PracticeAreas" in stems(p), f"lawyer stems: {stems(p)}")
check("Fees" in stems(p), f"lawyer fees: {stems(p)}")
check("Pricing" not in stems(p), "variant must bow to the user's word: Fees, not Pricing")
check("Features" not in stems(p) and len(stems(p)) >= 4, f"stems: {stems(p)}")
check("mediation" in specs(p), "the user's own practice areas must reach the section ask")

# ── 2. a business student with a portfolio of client work ─────────────────
STUDENT = {
    "prompt": "portfolio site for my consulting projects with client testimonials",
    "offerings": ["market research", "pitch decks"],
}
p = tu.build_profile(STUDENT)
check(tu.infer_spec(STUDENT)["family"] == "showcase", f"student: {tu.infer_spec(STUDENT)}")
check("Work" in stems(p), f"student stems: {stems(p)}")
check("Testimonials" in stems(p), f"student stems: {stems(p)}")
check("market research" in specs(p), "the student's own noun must appear in a section")

# ── 3. a beekeeper selling honey online ───────────────────────────────────
BEEKEEPER = {"prompt": "an online store for my raw honey with products and prices"}
p = tu.build_profile(BEEKEEPER)
check(tu.infer_spec(BEEKEEPER)["family"] == "storefront", f"bee: {tu.infer_spec(BEEKEEPER)}")
check("Products" in stems(p), f"bee stems: {stems(p)}")
check("Pricing" in stems(p), f"bee stems: {stems(p)}")
check("Booking" not in stems(p), "nothing asked for booking; nothing may invent it")

# ── 4. a luthier: work, not 'portfolio' ──────────────────────────────────
LUTHIER = {"prompt": "website for my handmade violins with photos of my work",
           "offerings": ["handmade violins"]}
p = tu.build_profile(LUTHIER)
check(tu.infer_spec(LUTHIER)["family"] == "showcase", f"luthier: {tu.infer_spec(LUTHIER)}")
check("Portfolio" in stems(p), f"luthier stems: {stems(p)}")
check("handmade violins" in specs(p), "the brief's own work noun must be used")

# ── 5. a wedding planner: services + packages + gallery + reviews ─────────
PLANNER = {
    "prompt": "site with my services, packages, gallery and testimonials",
    "offerings": ["wedding planning", "venue styling"],
}
p = tu.build_profile(PLANNER)
s = stems(p)
check("Gallery" in s, f"planner stems: {s}")
check("Services" in s and "Testimonials" in s, f"planner stems: {s}")
check(("Pricing" in s) or ("Plans" in s), f"planner stems: {s}")

# ── 6. a person with no artifact noun at all ──────────────────────────────
COACH = {"prompt": "I am a life coach and I need a site about me with my services and reviews"}
p = tu.build_profile(COACH)
check("Services" in stems(p) and "Reviews" in stems(p), f"coach stems: {stems(p)}")
check("About" in stems(p) or "Story" in stems(p), f"coach stems: {stems(p)}")

# ── 7. negative control: an artifact-only brief invents nothing ───────────
ARTIFACT_ONLY = {"prompt": "modern responsive website with dark mode and smooth animations"}
spec = tu.infer_spec(ARTIFACT_ONLY)
p = tu.build_profile(ARTIFACT_ONLY)
check(spec["matched"] == {}, f"artifact-only brief matched roles: {spec['matched']}")
check(len(stems(p)) == 4, f"expected the 4 family defaults, got {stems(p)}")
check("core offerings" not in specs(p), "the old placeholder string must be gone")
check("dark mode" not in specs(p).lower(), "chrome words must not become content")

# ── 8. same function words, different trade -> same structure ─────────────
A = {"prompt": "website for my beekeeping with services, prices and testimonials"}
B = {"prompt": "website for my arboriculture with services, prices and testimonials"}
C = {"prompt": "website for my puppet theatre with services, prices and testimonials"}
check(stems(tu.build_profile(A)) == stems(tu.build_profile(B)) == stems(tu.build_profile(C)),
      "structure must follow the request, never the trade")
# ...and the same trade word with different function words MUST diverge:
D = {"prompt": "website for my beekeeping with my gallery and booking"}
check(stems(tu.build_profile(A)) != stems(tu.build_profile(D)),
      "function words are what change the structure")

# ── 9. every stem is a safe filename and every spec is usable ─────────────
_CASES = [LAWYER, STUDENT, BEEKEEPER, LUTHIER, PLANNER, COACH, ARTIFACT_ONLY, A, B, C, D,
          {"prompt": "a management system for widgets"},
          {"prompt": "माझ्या सलूनसाठी वेबसाइट आणि किंमती", "domain": "beauty and wellness studio",
           "offerings": ["haircut", "bridal makeup"]}]
for brief in _CASES:
    p = tu.build_profile(brief)
    s = stems(p)
    check(len(s) == len(set(s)) and len(s) >= 4, f"unique stems: {s} for {brief['prompt'][:30]}")
    for st in s:
        check(bool(re.fullmatch(r"[A-Za-z][A-Za-z0-9]*", st)), f"unsafe stem {st!r}")
    for sec in p["sections"]:
        check(len(sec["spec"]) > 40, f"thin spec: {sec}")
        check("{subject}" in sec["spec"], f"spec must leave {{subject}} to the planner: {sec}")
    check(len(p["icons"]) >= 4 and all(i[:1].isupper() for i in p["icons"]), p["icons"])

# ── 10. back-office views come from the user's nouns ──────────────────────
TUITION = {"prompt": "an internal tool to manage students and batches",
           "offerings": ["students", "batches", "fees"]}
views = tu.build_admin_views(TUITION)
v_stems = [v["stem"] for v in views]
check(v_stems[0] == "Dashboard" and v_stems[-1] == "Reports", f"views: {v_stems}")
check("Students" in v_stems and "Batches" in v_stems, f"views: {v_stems}")
check(all(re.fullmatch(r"[A-Za-z][A-Za-z0-9]*", st) for st in v_stems), v_stems)
check(all(len(v["spec"]) > 40 for v in views), views)
check(tu.build_admin_views({"prompt": "a management system"}) == [],
      "no entity named -> no derived views (caller uses its own fallback)")

# ── 11. domain_profiles integration ───────────────────────────────────────
unknown = dp.get_profile(LAWYER)
check([s["stem"] for s in unknown["sections"]] == stems(tu.build_profile(LAWYER)),
      "unknown trades must be understood by task_understanding")
check(unknown["key"] == "generic", unknown["key"])
check(dp.all_section_stems(LAWYER) == stems(unknown), "stems helper must agree")

# curated profiles are untouched quality boosts
law = dp.get_profile({"domain": "law firm", "business_type": "law", "offerings": [], "prompt": ""})
check(law["sections"][0]["stem"] == "PracticeAreas", stems(law))
resto = dp.get_profile({"domain": "restaurant", "business_type": "restaurant", "offerings": [], "prompt": ""})
check("Menu" in stems(resto) and "Reservations" in stems(resto), stems(resto))
admin = dp.admin_views({"prompt": "a management system"})
check(len(admin) >= 3 and admin[0]["stem"] == "Dashboard", [v["stem"] for v in admin])
admin2 = dp.admin_views(TUITION)
check("Students" in [v["stem"] for v in admin2], [v["stem"] for v in admin2])

# ── 12. planner integration: the plan matches the understanding ───────────
import agentic_generator as ag

PRODUCT = {"domain": "product", "business_type": "product",
           "offerings": [], "prompt": "one product"}
for brief, prompt in ((LAWYER, LAWYER["prompt"]), (PRODUCT, PRODUCT["prompt"])):
    plan = ag._plan_files_landing(
        [{"role": "system", "content": ""}, {"role": "user", "content": prompt}], brief)
    paths = [i["path"] for i in plan]
    check(len(paths) == len(set(paths)), f"duplicate paths in plan: {paths}")
    prof = dp.get_profile(brief)
    for st in stems(prof):
        check(f"src/components/{st}.jsx" in paths, f"{st} missing from plan {paths}")

# ── 13. model escalation is bounded by the registry ───────────────────────
def _fake(reply):
    def chat(messages, max_tokens=0, temperature=0):
        return reply, "stop"
    return chat


hint = tu.model_hint(LAWYER, _fake('{"family": "showcase", "roles": ["showcase", "pricing", "nonsense"]}'))
check(hint and hint["family"] == "showcase", hint)
check("pricing" in hint["roles"] and all(r in tu._ROLES for r in hint["roles"]), hint)
check("nonsense" not in hint["roles"], hint)
check("showcase" in hint["roles"], f"a valid pick must survive: {hint}")

check(tu.model_hint(LAWYER, _fake('{"family": "moonbase", "roles": ["showcase"]}')) is None,
      "out-of-registry family must be discarded")
check(tu.model_hint(LAWYER, _fake("I think it is a portfolio, honestly.")) is None,
      "prose must be discarded")
check(tu.model_hint(LAWYER, _fake('{"family": "site", "roles": []}')) is None,
      "empty roles must be discarded")


def _boom(messages, max_tokens=0, temperature=0):
    raise RuntimeError("model offline")


check(tu.model_hint(LAWYER, _boom) is None, "a hint must never break a build")
check(tu.model_hint(LAWYER, None) is None, "no chat fn -> no hint")

print(f"ALL TASK-UNDERSTANDING TESTS PASS ({PASS} checks)")
