"""Open-vocabulary task understanding for Terabit Studio.

Why this exists
---------------
Until now the generator decided "what kind of thing is this" by looking the
user's trade up in a keyword table (`domain_profiles._KEYWORDS`) and then
reading a hand-written skeleton off a second table (`_PROFILE_OVERRIDES`).
That works for the trades somebody thought to write down, and fails -- with a
confident, perfectly-formatted SaaS page -- for everyone else. A business
student, a beekeeper, a luthier, an arborist, a wedding planner all fell
through to `Features / Pricing / Testimonials / Process`, which is the
"it just gives me a template" complaint wearing a different hat. Adding a
profile per trade cannot close this gap: there is no list of trades, and the
list was never the point.

The insight this module is built on: **structure generalises across function,
not across domain.** A music producer's "tracks", a plumber's "services", a
bakery's "cakes" and a lawyer's "practice areas" are all the same kind of
section -- an offering/showcase grid -- and any of them can be described
without naming a single trade. A booking form is a booking form whether the
clinic books physiotherapy or tattoos.

So the vocabulary here is about **what the user asked for** -- appointments,
prices, gallery, records, checkout, events -- and never about **who the user
is**. No profession, industry or country appears anywhere in this file, and
adding one is not the way to extend it. To support a new *shape* of digital
task, add a role or a family; that is a capability of the product, not a
customer of it.

Public surface
--------------
  infer_spec(brief)          -> the TaskSpec (family, roles, evidence)
  build_profile(brief)       -> {key, sections, icons, family, evidence} in the
                                exact shape `domain_profiles.get_profile`
                                has always returned, so the pipeline and the
                                composer do not change
  build_admin_views(brief)   -> entity views for a back-office ask
  model_hint(brief, chat_fn) -> optional bounded escalation: ask the local
                                model to CHOOSE from this registry when the
                                deterministic pass is unsure. It may only pick
                                an existing family/role; anything else is
                                discarded and the deterministic answer stands.

Everything except `model_hint` is zero-token, and `model_hint` is never on by
default -- it cannot make a run slower or flakier unless a caller opts in.
"""
from __future__ import annotations

import json
import re

# --------------------------------------------------------------- tokenisation
try:  # The project tokeniser understands whole Unicode blocks, so Marathi or
    from multilingual import tokens as _ml_tokens  # Bengali text is not
except Exception:  # noqa: BLE001                   # shredded at combining marks.
    _ml_tokens = None


def _tokens(text: str) -> list[str]:
    if _ml_tokens is not None:
        try:
            return _ml_tokens(text)
        except Exception:  # noqa: BLE001
            pass
    return re.findall(r"[^\W\d_]+", text.lower())


# Nouns that describe the ARTIFACT ("modern responsive website with dark
# mode") and therefore name nothing a section can be about. Same discipline
# as main._DERIVE_NOISE; duplicated rather than imported because main imports
# domain_profiles which imports this module (a cycle).
_ARTIFACT_NOISE = re.compile(
    r"website|web\s?site|\bsite\b|\bapp\b|application|landing|homepage|"
    r"\bpage\b|\bpages\b|template|responsive|modern|beautiful|professional|"
    r"clean|simple|minimal|elegant|attractive|\bdark\b|navbar|footer|header|"
    r"hero|banner|layout|styling|\bstyle\b|\bui\b|\bux\b|animation|animations|"
    r"\bbutton\b|\bimage\b|\bimages\b|\bphoto\b|\bphotos\b|\blogo\b|\bsection\b|"
    r"colou?r|colou?rs|\bfont\b|\bfonts\b|interactive|nice|good|great|awesome|"
    r"stunning|smooth|cool|\bfast\b|loading|seo|\bblog\b|domain|hosting|\bssl\b|"
    r"साइट|ऐप|वेबसाइट|पेज",
    re.IGNORECASE,
)

# Abstract words that describe a SECTION rather than what the section is
# about. "services" is a fine label and a useless noun; "pollination services"
# is what the page is actually about, so the ban is on the bare word.
_ABSTRACT_NOUNS = {
    "service", "services", "work", "works", "business", "company", "thing",
    "things", "stuff", "quality", "price", "prices", "pricing", "features",
    "feature", "testimonials", "testimonial", "reviews", "review", "contact",
    "about", "faq", "faqs", "options", "option", "people", "area", "areas",
}

_FUNCTION_WORDS = {
    "a", "an", "the", "my", "our", "your", "their", "his", "her", "its", "i",
    "me", "we", "us", "you", "it", "is", "am", "are", "was", "be", "being",
    "and", "or", "but", "with", "without", "for", "from", "to", "of", "in",
    "on", "at", "by", "as", "so", "that", "this", "these", "those", "which",
    "who", "whom", "whose", "where", "when", "why", "how", "also", "very",
    "just", "only", "some", "any", "all", "each", "every", "more", "most",
    "like", "want", "need", "make", "made", "build", "building", "create",
    "creating", "give", "get", "have", "has", "do", "does", "can", "could",
    "should", "would", "will", "please", "help", "using", "use", "into",
    "show", "showing", "shows", "display", "displaying", "featuring",
    "including", "offering", "there", "here", "then", "than", "them", "they",
    "he", "she",
}

# ---------------------------------------------------------------- role table
# A ROLE is a kind of section defined by what it does, not by what trade it
# serves. `triggers` are the user's own function words ("book", "prices",
# "gallery", "records"); `variants` re-point the same role at the user's
# vocabulary so a menu is called Menu and a CV is called Experience without a
# single trade rule. `noun_from_brief` is set only where the user's own noun
# slots into the spec grammatically; everything else keeps neutral wording, so
# a noun can never leak into a role it does not belong to.
# `{noun}` is filled at build time; `{subject}` is filled by the planner (as
# profiles have always done).

_ROLES: dict[str, dict] = {
    "showcase": {
        "stem": "Work", "label": "Work", "anchor": "work", "noun": "work",
        "noun_from_brief": True,
        "icons": ["Image", "Camera", "Frame", "Sparkles", "Award", "ArrowRight"],
        "triggers": (
            "portfolio", "showcase", "gallery", "my work", "our work",
            "earlier work", "past work", "projects", "case studies", "pieces",
            "designs", "illustrations", "paintings", "artworks", "artwork",
            "crafts", "photos", "photographs", "photoshoot", "shots", "tracks",
            "songs", "albums", "discography", "reel", "videos", "films",
            "exhibitions", "exhibition", "collection", "lookbook", "cakes",
            "dishes", "creations", "makes",
        ),
        "variants": (
            (("gallery", "exhibitions", "exhibition", "artworks", "artwork",
              "paintings", "pieces", "crafts", "creations", "makes"),
             "Gallery", "Gallery", "gallery"),
            (("photos", "photographs", "photoshoot", "shots"),
             "Portfolio", "Portfolio", "portfolio"),
            (("tracks", "songs", "albums", "discography", "reel", "videos",
              "films"), "Releases", "Releases", "releases"),
        ),
        "spec": "Selected {noun} for {subject}: 4-6 cards with image "
                "placeholders, each with a title, a one-line description and a "
                "'View details' link",
    },
    "offering_list": {
        "stem": "Services", "label": "Services", "anchor": "services",
        "noun": "what you do", "noun_from_brief": True,
        "icons": ["Sparkles", "Briefcase", "Heart", "Star", "Check", "ArrowRight"],
        "triggers": (
            "service", "services", "what i do", "what we do", "offerings",
            "practice areas", "specialities", "specialties", "specialisms",
            "treatment", "treatments", "procedure", "procedures", "menu",
            "program", "programs", "programme", "programmes", "course",
            "courses", "class", "classes", "lesson", "lessons", "workshop",
            "workshops", "package", "packages", "solutions", "capabilities",
            "expertise", "areas of work",
        ),
        "variants": (
            (("menu", "dishes"), "Menu", "Menu", "menu"),
            (("course", "courses", "class", "classes", "lesson", "lessons"),
             "Classes", "Classes", "classes"),
            (("program", "programs", "programme", "programmes", "workshop",
              "workshops"), "Programs", "Programs", "programs"),
            (("practice areas", "treatment", "treatments", "procedure",
              "procedures", "specialities", "specialties", "specialisms"),
             "PracticeAreas", "Practice Areas", "practice-areas"),
        ),
        "spec": "{noun} for {subject}: 4-6 cards with lucide icons, a name, a "
                "one-line description and a CTA on each -- the cards must name "
                "the user's own items",
    },
    "catalog": {
        "stem": "Products", "label": "Products", "anchor": "products",
        "noun": "products", "noun_from_brief": True,
        "icons": ["Package", "ShoppingBag", "Star", "Truck", "CreditCard", "Tag"],
        "triggers": (
            "product", "products", "catalog", "catalogue", "collection",
            "collections", "range", "merch", "stock", "items for sale",
            "goods", "shop", "store", "boutique", "labels", "flavours",
            "flavors", "varieties",
        ),
        "variants": (
            (("collection", "collections"),
             "Collections", "Collections", "collections"),
            (("labels", "flavours", "flavors", "varieties", "range"),
             "Products", "Range", "products"),
        ),
        "spec": "Product catalogue for {subject}: 4-6 product cards with image "
                "placeholders, name, a one-line description and a price; each "
                "card lists the user's own products",
    },
    "ordering": {
        "stem": "Order", "label": "Order", "anchor": "order", "noun": "orders",
        "icons": ["ShoppingBag", "Truck", "Clock", "MapPin", "Phone", "Check"],
        "triggers": (
            "online ordering", "order online", "ordering", "home delivery",
            "delivery", "takeaway", "take away", "pickup", "pick-up",
            "subscription", "subscriptions", "wholesale",
        ),
        "variants": (
            (("home delivery", "delivery", "takeaway", "take away", "pickup",
              "pick-up"), "Delivery", "Delivery", "delivery"),
        ),
        "spec": "How to order for {subject}: 3 steps (choose, order, receive) "
                "plus delivery/pickup options, timings and an order CTA -- "
                "working local state for the quantity controls",
    },
    "pricing": {
        "stem": "Pricing", "label": "Pricing", "anchor": "pricing",
        "noun": "pricing",
        "icons": ["Tag", "Check", "Star", "CreditCard", "Shield", "ArrowRight"],
        "triggers": (
            "pricing", "price", "prices", "price list", "fee", "fees", "rates",
            "charges", "cost", "costs", "membership", "memberships", "plans",
            "tariff", "quote", "quotes", "package", "packages",
        ),
        "variants": (
            (("fee", "fees", "charges", "tariff"), "Fees", "Fees", "fees"),
            (("rates",), "Rates", "Rates", "rates"),
            (("membership", "memberships"),
             "Membership", "Membership", "membership"),
            (("plans",), "Plans", "Plans", "plans"),
        ),
        "spec": "Pricing for {subject}: 3 rate cards or a clean two-column "
                "price list with what is included and a contact CTA",
    },
    "booking": {
        "stem": "Booking", "label": "Booking", "anchor": "booking",
        "noun": "appointments",
        "icons": ["Calendar", "Clock", "CalendarCheck", "MapPin", "Phone", "Check"],
        "triggers": (
            "book a", "book an", "book now", "book online", "booking",
            "bookings", "appointment", "appointments", "reserve", "reservation",
            "reservations", "schedule", "availability", "consultation",
            "consultations", "free consultation", "trial", "enquiry",
            "enquiries", "enquire", "enroll", "enrol", "admission",
            "admissions", "slots",
        ),
        "variants": (
            (("appointment", "appointments"),
             "Appointments", "Appointments", "appointments"),
            (("reserve", "reservation", "reservations"),
             "Reservations", "Reservations", "reservations"),
            (("schedule", "availability", "slots"),
             "Schedule", "Schedule", "schedule"),
            (("admission", "admissions", "enroll", "enrol"),
             "Admissions", "Admissions", "admissions"),
        ),
        "spec": "Booking for {subject}: availability/opening-hours card, a "
                "booking form (name, contact, preferred date and time) that "
                "updates local state on submit, and a location strip",
    },
    "events": {
        "stem": "Events", "label": "Events", "anchor": "events",
        "noun": "events",
        "icons": ["Calendar", "CalendarDays", "MapPin", "Ticket", "Clock", "ArrowRight"],
        "triggers": (
            "event", "events", "workshops", "webinars", "meetups", "shows",
            "gigs", "performances", "concerts", "timetable", "tour", "tours",
            "festival", "festivals",
        ),
        "variants": (
            (("shows", "gigs", "performances", "concerts", "tour", "tours"),
             "Shows", "Shows", "shows"),
            (("timetable",), "Timetable", "Timetable", "timetable"),
        ),
        "spec": "Upcoming {noun} for {subject}: 3-4 event cards or a month "
                "list with date, title, venue and a register/RSVP CTA",
    },
    "roster": {
        "stem": "Team", "label": "Team", "anchor": "team", "noun": "team",
        "noun_from_brief": True,
        "icons": ["Users", "UserCheck", "Award", "Briefcase", "Star", "Phone"],
        "triggers": (
            "team", "staff", "crew", "doctors", "doctor", "attorneys",
            "attorney", "lawyers", "lawyer", "teachers", "teacher", "tutors",
            "tutor", "trainers", "trainer", "coaches", "coach", "artists",
            "artist", "agents", "agent", "faculty", "instructors",
            "instructor", "therapists", "therapist", "chefs", "chef",
            "founders", "founder", "partners", "partner", "professionals",
        ),
        "variants": (
            (("doctors", "doctor", "therapists", "therapist"),
             "Doctors", "Our Doctors", "doctors"),
            (("attorneys", "attorney", "lawyers", "lawyer", "partners",
              "partner"), "Attorneys", "Our Attorneys", "attorneys"),
            (("teachers", "teacher", "tutors", "tutor", "faculty",
              "instructors", "instructor"),
             "Faculty", "Faculty", "faculty"),
            (("trainers", "trainer", "coaches", "coach"),
             "Trainers", "Trainers", "trainers"),
            (("artists", "artist"), "Artists", "Artists", "artists"),
        ),
        "spec": "{noun} for {subject}: 3 cards with an initials avatar (NOT a "
                "photo), full name, role or qualification, one-line bio and a "
                "'Get in touch' link",
    },
    "story": {
        "stem": "About", "label": "About", "anchor": "about",
        "noun": "the story",
        "icons": ["BookOpen", "Heart", "Users", "Sparkles", "Award", "Camera"],
        "triggers": (
            "about", "about me", "about us", "story", "our story", "my story",
            "bio", "biography", "journey", "history", "who we are",
            "who i am", "founded", "philosophy", "craft", "background",
            "introduction", "experience",
        ),
        "variants": (
            (("my story", "our story", "story", "journey", "history",
              "founded"), "Story", "Our Story", "story"),
        ),
        "spec": "About {subject}: a two-column section pairing one large image "
                "placeholder with 2-3 short paragraphs of real-feeling prose, "
                "plus 3 small stat cards",
    },
    "process": {
        "stem": "Process", "label": "How It Works", "anchor": "process",
        "noun": "the process",
        "icons": ["Target", "ListChecks", "TrendingUp", "ArrowRight", "Check", "Clock"],
        "triggers": (
            "how it works", "process", "steps", "what to expect", "workflow",
            "approach", "how we work", "how i work", "onboarding",
            "what happens",
        ),
        "variants": (
            (("how we work", "how i work", "approach"),
             "Process", "How We Work", "process"),
        ),
        "spec": "How it works for {subject}: 4 numbered steps with lucide "
                "icons, a title and a one-line description each",
    },
    "credentials": {
        "stem": "Experience", "label": "Experience", "anchor": "experience",
        "noun": "experience",
        "icons": ["Award", "GraduationCap", "Briefcase", "Star", "FileText", "TrendingUp"],
        "triggers": (
            "resume", "cv", "experience", "skill", "skills", "qualification",
            "qualifications", "certification", "certifications", "certificate",
            "certificates", "award", "awards", "track record", "clients",
            "publication", "publications", "achievement", "achievements",
            "highlights",
        ),
        "variants": (
            (("skill", "skills", "qualification", "qualifications",
              "certification", "certifications", "certificate",
              "certificates"), "Skills", "Skills", "skills"),
            (("award", "awards", "achievement", "achievements",
              "publication", "publications", "highlights"),
             "Awards", "Awards", "awards"),
        ),
        "spec": "Experience for {subject}: a capabilities/skills list, a short "
                "timeline of roles or milestones and an awards/credential strip",
    },
    "location": {
        "stem": "Visit", "label": "Visit", "anchor": "visit", "noun": "visits",
        "icons": ["MapPin", "Clock", "Phone", "Mail", "Navigation", "Car"],
        "triggers": (
            "visit", "location", "locations", "address", "where we are",
            "where i am", "hours", "opening hours", "opening times", "timings",
            "find us", "directions", "map", "walk-in", "walk ins",
        ),
        "variants": (
            (("hours", "opening hours", "opening times", "timings"),
             "Hours", "Hours & Location", "hours"),
            (("directions", "find us", "map", "address"),
             "FindUs", "Find Us", "find-us"),
        ),
        "spec": "Visit {subject}: opening hours card, address/location strip "
                "with a map placeholder, and how to get there or get in touch",
    },
    "proof": {
        "stem": "Testimonials", "label": "Testimonials", "anchor": "testimonials",
        "noun": "clients",
        "icons": ["Star", "Quote", "MessageSquare", "Users", "Heart", "Award"],
        "triggers": (
            "testimonial", "testimonials", "review", "reviews", "feedback",
            "client feedback", "ratings", "patient stories", "guest reviews",
            "press", "as seen in", "trusted by", "success stories",
            "transformations", "references",
        ),
        "variants": (
            (("review", "reviews", "ratings", "guest reviews"),
             "Reviews", "Reviews", "reviews"),
            (("patient stories", "success stories", "transformations"),
             "Stories", "Success Stories", "stories"),
            (("press", "as seen in"), "Press", "Press", "press"),
        ),
        "spec": "Testimonials for {subject}: 3 quote cards with the person's "
                "name, how they know {subject} and a 5-star row",
    },
    "faq": {
        "stem": "Faq", "label": "FAQ", "anchor": "faq", "noun": "questions",
        "icons": ["HelpCircle", "MessageSquare", "Check", "Info", "Users", "ArrowRight"],
        "triggers": (
            "faq", "faqs", "questions", "q&a", "common questions", "doubts",
        ),
        "variants": (),
        "spec": "FAQ for {subject}: 5 accordion questions with real answers "
                "about {noun}",
    },
}

# Page order. A visitor reads what you make before what it costs, and what it
# costs before how to book; proof earns the booking.
_ROLE_ORDER = (
    "showcase", "offering_list", "catalog", "ordering", "pricing", "booking",
    "events", "roster", "story", "process", "credentials", "location",
    "proof", "faq",
)

# The landing shell always ships its own FAQ slot (see _LANDING_FAQ_STEM), so
# a profile-generated Faq section would be generated twice and rendered once.
_SHELL_OWNED_ROLES = ("faq",)

# ------------------------------------------------------------------ families
# A FAMILY is the shape of the artifact, not the market it serves. Decision
# rules are deliberately conservative: the back-office family needs an
# explicit system phrase or management verbs AND no marketing-artifact word,
# because "a website ... with an admin dashboard" is a website that contains
# a dashboard, not an admin console.

_FAMILIES: list[dict] = [
    {
        "key": "console", "label": "back-office system",
        "default_roles": ("story", "process"),
        "strong": (
            "management system", "management software", "management app",
            "management platform", "admin panel", "admin dashboard",
            "back office", "back-office", "backoffice", "internal tool",
            "erp", "pos system", "point of sale", "point-of-sale",
            "billing system", "inventory system", "attendance system",
            "payroll system", "crm",
        ),
        "verbs": (
            "manage", "managed", "managing", "management", "track",
            "tracking", "keep track", "record", "records", "record keeping",
            "inventory", "attendance", "payroll", "roster", "queue",
            "monitor", "log every", "keep a log",
        ),
    },
    {
        "key": "storefront", "label": "online store",
        "default_roles": ("catalog", "pricing", "proof", "process"),
        "strong": (
            "cart", "shopping cart", "add to cart", "checkout", "buy online",
            "order online", "place an order", "online store", "online shop",
            "storefront", "shipping", "sell online", "payment", "payments",
            "e-commerce", "ecommerce",
        ),
        "verbs": (),
    },
    {
        "key": "showcase", "label": "showcase site",
        "default_roles": ("showcase", "story", "proof", "offering_list"),
        "strong": (
            "portfolio", "showcase", "gallery", "lookbook", "my work",
            "our work", "case studies", "discography", "reel",
        ),
        "verbs": (),
    },
    {
        "key": "site", "label": "website",
        "default_roles": ("offering_list", "proof", "process", "story"),
        "strong": (), "verbs": (),
    },
]

_MARKETING_ARTIFACT = re.compile(
    r"\b(?:website|web\s?site|\bsite\b|webpage|web\s?page|homepage|"
    r"landing\s?page|one-?pager|marketing\s+(?:site|page))\b", re.IGNORECASE)

_MARKETING_BLOCKERS = ("management system", "admin panel", "internal tool",
                       "back office", "back-office", "backoffice", "crm")


def _brief_text(brief: dict | None) -> str:
    """One searchable blob out of whatever shape the caller has.

    Callers pass the brief record (domain / business_type / offerings /
    subject / facts / language) and sometimes an added `prompt`. Nothing here
    requires a field to exist; a missing one is simply "".
    """
    b = brief or {}
    parts = [
        str(b.get("domain") or ""),
        str(b.get("business_type") or ""),
        str(b.get("subject") or ""),
        str(b.get("prompt") or ""),
        str(b.get("name") or ""),
        " ".join(str(x) for x in (b.get("offerings") or [])),
        " ".join(str(x) for x in (b.get("facts") or [])),
    ]
    return " ".join(p for p in parts if p).strip()


def _hits(blob: str, phrases: tuple[str, ...]) -> list[str]:
    """Which of `phrases` the brief actually says.

    Whole words only. Prefix matching looked harmless and wasn't: `book`
    matched "books" (a bookshop got a Booking section), `store` matched
    "storage", `demo` matched "demolition". Every inflection a role wants is
    spelled out in its trigger list instead.
    """
    low = blob.lower()
    out: list[str] = []
    for p in phrases:
        if " " in p:
            if p in low:
                out.append(p)
        elif re.search(rf"\b{re.escape(p)}\b", low):
            out.append(p)
    return out


def infer_family(brief: dict | None) -> tuple[str, list[str]]:
    """Pick the artifact shape and say why (evidence, for the run trace)."""
    blob = _brief_text(brief)
    low = blob.lower()
    marketing = bool(_MARKETING_ARTIFACT.search(low))

    fam = _FAMILIES[0]
    strong = _hits(blob, fam["strong"])
    verbs = _hits(blob, fam["verbs"])
    blocked = marketing and not any(b in low for b in _MARKETING_BLOCKERS)
    if strong or (verbs and not blocked):
        return fam["key"], [f"console: {w}" for w in (strong + verbs)[:3]]

    evidence = ["marketing artifact word"] if marketing else []
    for fam in (_FAMILIES[1], _FAMILIES[2]):
        hits = _hits(blob, fam["strong"])
        if hits:
            return fam["key"], evidence + [f"{fam['key']}: {w}" for w in hits[:3]]
    return "site", evidence + ["default shape"]


def _noun_for(role: dict, offerings: list[str]) -> str:
    """The user's own noun for this role, else the role's neutral default.

    A noun is never invented. `_ARTIFACT_NOISE` / `_ABSTRACT_NOUNS` keep
    "modern responsive website" from becoming a section subject, and only
    roles that declare `noun_from_brief` may take one at all -- otherwise a
    music producer's "tracks" would leak into the events section.
    """
    if not role.get("noun_from_brief"):
        return role["noun"]
    for cand in offerings or []:
        c = " ".join(str(cand).strip().strip(".,;:").split())
        if not c or len(c) > 48:
            continue
        toks = _tokens(c.lower())
        if not toks or len(toks) > 4:
            continue
        if _ARTIFACT_NOISE.search(c) or any(t in _ABSTRACT_NOUNS for t in toks):
            continue
        if any(t in _FUNCTION_WORDS for t in toks):
            continue
        return c
    return role["noun"]


def _role_entry(role: dict, offerings: list[str], matched: list[str]) -> dict:
    stem, label, anchor = role["stem"], role["label"], role["anchor"]
    joined = " ".join(matched)
    for words, v_stem, v_label, v_anchor in role.get("variants", ()):
        if any(w in matched or w in joined for w in words):
            stem, label, anchor = v_stem, v_label, v_anchor
            break
    spec = role["spec"].replace("{noun}", _noun_for(role, offerings))
    return {"stem": stem, "label": label, "anchor": anchor, "spec": spec}


def infer_spec(brief: dict | None) -> dict:
    """The TaskSpec: family + ordered roles + evidence. Zero tokens.

    A role is included when the user's own words name that function. If fewer
    than four roles are named, the family's defaults top the page up so a thin
    brief still gets a whole page -- but a default never *overrides* something
    the user asked for, and "Pricing" is not added to a plumber's page just
    because SaaS pages have one.
    """
    blob = _brief_text(brief)
    family_key, evidence = infer_family(brief)
    family = next(f for f in _FAMILIES if f["key"] == family_key)
    offerings = [str(x) for x in ((brief or {}).get("offerings") or [])]

    matched: dict[str, list[str]] = {}
    for key, role in _ROLES.items():
        if key in _SHELL_OWNED_ROLES:
            continue
        hits = _hits(blob, role["triggers"])
        if hits:
            matched[key] = hits

    roles: list[str] = [k for k in _ROLE_ORDER if k in matched]
    # A person's brief ("I am a designer ... my work") is a showcase even if
    # the word portfolio never appears: the biography sections ARE the site.
    if "showcase" in roles and "story" not in roles:
        roles.append("story")
    for k in family["default_roles"]:
        if k not in roles and k in _ROLES:
            roles.append(k)
    # A console's real plan is `build_admin_views`, not landing sections. If
    # anything still asks for a page profile for one, a complete page beats a
    # two-section stub, so the site floor applies to every family.
    if len(roles) < 4:
        for k in _FAMILIES[-1]["default_roles"]:
            if k not in roles and k in _ROLES:
                roles.append(k)
    roles = [k for k in _ROLE_ORDER if k in roles][:5]

    return {
        "family": family_key,
        "family_label": family["label"],
        "roles": roles,
        "matched": {k: matched[k][:3] for k in roles if k in matched},
        "evidence": evidence,
        "confidence": 0.85 if matched else 0.55,
    }


def build_profile(brief: dict | None) -> dict:
    """`domain_profiles.get_profile`'s contract, understood from the brief.

    Returned keys are exactly the ones the pipeline has always consumed --
    sections with stem/label/anchor/spec and a flat icon list -- plus the
    TaskSpec fields. The model still writes every word; this only decides
    which sections exist, which is the part a 7B is worst at.
    """
    spec = infer_spec(brief)
    offerings = [str(x) for x in ((brief or {}).get("offerings") or [])]
    sections: list[dict] = []
    seen: set[str] = set()
    for role_key in spec["roles"]:
        entry = _role_entry(_ROLES[role_key], offerings,
                            spec["matched"].get(role_key, []))
        if entry["stem"] in seen:
            continue
        seen.add(entry["stem"])
        sections.append(entry)
    icons: list[str] = []
    for role_key in spec["roles"]:
        for icon in _ROLES[role_key]["icons"]:
            if icon not in icons:
                icons.append(icon)
    return {
        "key": "generic",
        "family": spec["family"],
        "task": spec,
        "sections": sections,
        "icons": icons[:8],
    }


# ------------------------------------------------------------- back-office
_ADMIN_ENTITY_BAN = _ABSTRACT_NOUNS | {
    "system", "systems", "management", "dashboard", "panel", "admin",
    "records", "record", "report", "reports", "settings", "data",
}

_ENTITY_PATTERNS = (
    r"\b(?:manage|managing|track|tracking|handling|handle)\s+"
    r"((?:[a-z][\w'-]+\s*){1,3})",
    r"\b(?:records?|list|register|log)\s+of\s+((?:[a-z][\w'-]+\s*){1,3})",
    r"\b(?:for|of)\s+((?:[a-z][\w'-]+\s*){1,3})$",
)


def _entity_candidates(brief: dict | None) -> list[str]:
    b = brief or {}
    raw = [str(x) for x in (b.get("offerings") or [])]
    prompt = str(b.get("prompt") or "")
    for pat in _ENTITY_PATTERNS:
        for m in re.finditer(pat, prompt.lower()):
            raw.append(m.group(1).strip(" .,-"))
    out: list[str] = []
    for cand in raw:
        c = " ".join(cand.split())
        if not c or len(c) > 32:
            continue
        toks = _tokens(c.lower())
        if not toks or len(toks) > 3:
            continue
        if _ARTIFACT_NOISE.search(c) or any(t in _ADMIN_ENTITY_BAN for t in toks):
            continue
        if any(t in _FUNCTION_WORDS for t in toks):
            continue
        if c not in out:
            out.append(c)
    return out[:3]


def _title_stem(noun: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", noun)
    if not words:
        return ""
    return "".join(w[:1].upper() + w[1:] for w in words[:3])[:28]


def build_admin_views(brief: dict | None) -> list[dict]:
    """Entity views derived from the user's own nouns, for a back-office ask.

    `domain_profiles.admin_views` keeps its curated sets (a hospital really
    does want Patients / Appointments / Doctors). This is what runs when the
    trade is unknown: the managed entities are the plural nouns the user
    wrote, so "a system to manage students, batches and fees" gets a Students
    view and a Batches view instead of a generic "Records" table.
    """
    views: list[dict] = [{
        "stem": "Dashboard", "label": "Overview", "icon": "LayoutDashboard",
        "spec": "Overview dashboard: a KPI row, a recent-activity list and one "
                "small trend or status breakdown",
    }]
    for entity in _entity_candidates(brief):
        stem = _title_stem(entity)
        if not stem or stem in {v["stem"] for v in views}:
            continue
        views.append({
            "stem": stem,
            "label": stem,
            "icon": "Table2",
            "spec": (f"Searchable {entity} table (id, name, owner, updated, "
                     f"status badge) with a filter row, row actions and an "
                     f"'Add {entity}' inline form that updates local state"),
        })
    if len(views) < 2:
        return []
    views.append({
        "stem": "Reports", "label": "Reports", "icon": "BarChart3",
        "spec": "Reports view: a summary stat row, one simple bar/line visual "
                "built from divs, and an export-styled button",
    })
    return views


# --------------------------------------------------------- model escalation
_HINT_SYSTEM = (
    "You classify a software request. Reply with JSON only: "
    '{"family": "...", "roles": ["..."]}. '
    "Pick family from: site, showcase, storefront, console. "
    "Pick roles only from: " + ", ".join(_ROLE_ORDER) + ". "
    "Never invent names. Never explain."
)


def model_hint(brief: dict | None, chat_fn) -> dict | None:
    """Ask the local model to CHOOSE from the registry, never to invent.

    The deterministic pass already handles the common cases without spending a
    token, so this is an opt-in escalation for genuinely ambiguous briefs. The
    reply is parsed, checked against the registry and merged over the
    deterministic spec; anything malformed, out-of-registry or empty is
    discarded (return None) and the deterministic spec stands. That is the
    whole point: a classifier's freedom is bounded by the vocabulary it is
    allowed to choose from.
    """
    if chat_fn is None:
        return None
    blob = _brief_text(brief)
    if not blob:
        return None
    messages = [
        {"role": "system", "content": _HINT_SYSTEM},
        {"role": "user", "content": blob[:1500]},
    ]
    try:
        text, _finish = chat_fn(messages, max_tokens=120, temperature=0.1)
    except Exception:  # noqa: BLE001 -- a hint must never break a build
        return None
    try:
        m = re.search(r"\{[\s\S]*\}", text or "")
        data = json.loads(m.group(0)) if m else {}
    except (json.JSONDecodeError, AttributeError):
        return None
    family = str(data.get("family") or "").strip().lower()
    if family not in {f["key"] for f in _FAMILIES}:
        return None
    picked = [str(r).strip().lower() for r in (data.get("roles") or [])]
    roles = [r for r in _ROLE_ORDER if r in picked and r in _ROLES]
    if not roles:
        return None
    base = infer_spec(brief)
    merged = [r for r in roles if r not in base["roles"]] + base["roles"]
    merged = [r for r in _ROLE_ORDER if r in merged][:5]
    return {
        "family": family,
        "family_label": next(f["label"] for f in _FAMILIES if f["key"] == family),
        "roles": merged,
        "matched": base["matched"],
        "evidence": base["evidence"] + ["model hint"],
        "confidence": 0.9,
    }
