"""Domain profiles for Terabit Studio's landing generator.

Why this exists (user-reported defect): every landing page used the same
SaaS skeleton (Hero / Features / Pricing / FAQ) with the business name
swapped in -- a law firm got "Features | Pricing" nav and dashboard icons.
The fix is a DATA-DRIVEN profile registry:

  1. detect_domain(brief)  -> picks a profile from the user's own words
  2. profile["sections"]   -> domain-appropriate section slots
                              (law: Practice Areas + Fees; hospital:
                               Services + Doctors; fashion: Collections
                               + Lookbook; unknown: Features + Pricing)
  3. profile["copy"]       -> curated fallback copy so even the safety-net
                              scaffold ships real domain content
  4. unknown domains       -> `task_understanding` infers the skeleton from
                              the FUNCTION the user asked for (gallery, fees,
                              booking, records, checkout...) instead of from a
                              trade lookup, so a trade nobody wrote down still
                              gets a structurally right page. These curated
                              profiles are quality boosts, not the gate to
                              being understood.

Core principle: the local 7B model stays the writer; profiles only decide
the SKELETON (which sections exist, what the nav says, which icons fit).
Anything the model writes well is kept verbatim; profiles only guarantee
the structure is never off-domain.
"""

from __future__ import annotations

import task_understanding

# ---------------------------------------------------------------- detection

# keyword -> profile key, checked in order; first hit wins. "generic" is the
# terminal fallback for unknown domains.
_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("law",       ("law", "lawyer", "attorney", "legal", "advocate", "solicitor",
                   "counsel", "litigation", "chambers")),
    ("hospital",  ("hospital", "clinic", "medical", "doctor", "dentist", "healthcare",
                   "health care", "physician", "patient", "therapy", "dental",
                   "veterinary", "vet clinic", "pet care", "animal hospital")),
    ("fashion",   ("fashion", "clothing", "apparel", "boutique", "clothes", "wear",
                   "style", "wardrobe", "atelier", "tailor", "garment")),
    # A parlour used to fall through to the fashion profile, whose sections
    # (Collections / Lookbook / Our Craft) are wrong for hair and beauty --
    # and the Marathi/Hindi lexicon maps "ब्यूटी पार्लर" here.
    ("beauty",    ("salon", "parlour", "parlor", "beauty studio", "beauty",
                   "hair salon", "haircut", "barber", "spa", "makeup",
                   "make-up", "skincare", "grooming", "nail")),
    ("restaurant", ("restaurant", "cafe", "caf\u00e9", "bakery", "food", "dining",
                    "kitchen", "menu", "bistro", "catering", "pizza", "coffee")),
    ("realestate", ("real estate", "realty", "property", "properties", "homes",
                    "realtor", "apartments", "villa", "estate")),
    ("fitness",   ("gym", "fitness", "yoga", "pilates", "crossfit", "trainer",
                   "wellness studio", "martial arts")),
    ("education", ("school", "academy", "university", "college", "courses",
                   "tutoring", "learning", "education", "institute", "kindergarten")),
    ("portfolio", ("portfolio", "personal site", "personal website", "designer",
                   "photographer", "freelancer", "freelance", "resume", "cv site",
                   "illustrator", "writer", "author site", "developer portfolio",
                   "ux designer", "graphic designer")),
    ("product",   ("product", "gadget", "device", "hardware", "headphones", "smartwatch",
                   "webcam", "drone", "speaker", "e-commerce", "ecommerce", "shop",
                   "store", "merch", "one product", "single product")),
    ("agency",    ("agency", "consulting", "consultancy", "marketing", "advertising",
                   "branding", "recruitment", "recruiting", "digital agency",
                   "creative agency", "design agency", "services firm")),
    ("art",       ("art", "gallery", "studio art", "artist", "museum", "exhibition",
                   "photography", "photography studio")),
    ("employee",  ("employee management", "employee", "staff", "payroll",
                   "attendance", "workforce", "hr system", "hrms", "onboarding",
                   "leave management")),
    ("store",     ("store management", "inventory", "stock levels", "warehouse",
                   "point of sale", "pos system", "purchase orders")),
    ("hospital",  ("hospital management", "patient management", "clinic management",
                   "patient records")),
    ("saas",      ("saas", "software", "app", "platform", "tool",
                   "startup", "dashboard", "analytics", "crm", "api")),
]


def detect_domain(brief: dict | None) -> str:
    """Pick the profile key from the brief's domain/business_type/offerings.

    Keyword matching is word-boundary aware: plain substring matching made
    "art" match "smart" (a smart-analytics SaaS landed on the art profile)
    and "pet" match "carpet".
    """
    import re as _re
    blob = " ".join([
        (brief or {}).get("domain", "") or "",
        (brief or {}).get("business_type", "") or "",
        " ".join((brief or {}).get("offerings", []) or []),
    ]).lower()
    if not blob.strip():
        return "generic"
    for key, words in _KEYWORDS:
        if any(_re.search(rf"\b{_re.escape(w)}\b", blob) for w in words):
            return key
    return "generic"


# Human-readable label per profile key, for briefs that name the domain by
# keyword only ("... Veterinary Hospital" -> hospital -> "healthcare practice").
_DOMAIN_LABELS = {
    "law": "law firm",
    "hospital": "healthcare practice",
    "fashion": "fashion boutique",
    "beauty": "beauty and wellness studio",
    "restaurant": "restaurant",
    "realestate": "real estate agency",
    "fitness": "fitness studio",
    "education": "education provider",
    "art": "art studio",
    "portfolio": "portfolio",
    "product": "product site",
    "agency": "agency",
    "saas": "software product",
}


def domain_label(key: str) -> str:
    return _DOMAIN_LABELS.get(key, key)


# ---------------------------------------------------------------- profiles
# "sections" slots feed _plan_files_landing and _compose_landing_shell.
# "icons" seeds the per-file icon guidance. "copy" feeds the curated
# fallback scaffold (see scaffolds.py -- rendered by the same template).

_PROFILE_OVERRIDES: dict[str, dict] = {
    "law": {
        "sections": [
            {"stem": "PracticeAreas", "label": "Practice Areas", "anchor": "practice-areas",
             "spec": "Practice-area grid for {subject}: 4-6 cards (e.g. Business & Corporate, Family, Real Estate, Personal Injury, Litigation) with lucide icons, one-line description, 'Learn more' link"},
            {"stem": "Fees", "label": "Fees", "anchor": "fees",
             "spec": "Fees & engagement models for {subject}: 3 cards (Free consultation, Hourly representation, Full-service retainer) with what is included and a contact CTA"},
            {"stem": "Attorneys", "label": "Our Attorneys", "anchor": "attorneys",
             "spec": "Attorney profiles for {subject}: 3 cards, each with an initials avatar circle (NOT a photo), full name, bar-qualified title, practice focus and a 'Book a call' link"},
            {"stem": "Testimonials", "label": "Client Outcomes", "anchor": "testimonials",
             "spec": "Client testimonials for {subject}: 3 quote cards with an outcome metric (e.g. 'case dismissed', '$1.2M recovered'), a short quote and a client name/role footer"},
        ],
        "icons": ["Scale", "Gavel", "ShieldCheck", "Users", "FileText", "Landmark"],
    },
    "hospital": {
        "sections": [
            {"stem": "Services", "label": "Services", "anchor": "services",
             "spec": "Medical services grid for {subject}: 6 cards (e.g. General Medicine, Pediatrics, Cardiology, Diagnostics, Emergency) with lucide icons, one-line description and 'Book appointment' link"},
            {"stem": "Doctors", "label": "Our Doctors", "anchor": "doctors",
             "spec": "Doctor profiles for {subject}: 3-4 cards with photo placeholder (initials avatar), name, specialty, years of experience and 'Book visit' button"},
            {"stem": "Facilities", "label": "Facilities", "anchor": "facilities",
             "spec": "Facilities & technology for {subject}: 4 cards (e.g. Modern Operation Theatres, Diagnostic Lab, ICU, Pharmacy) with lucide icons and one-line descriptions, plus a stats strip (beds, doctors, years)"},
            {"stem": "PatientStories", "label": "Patient Stories", "anchor": "patient-stories",
             "spec": "Patient testimonials for {subject}: 3 quote cards with star ratings, the patient's first name and the treatment received"},
        ],
        "icons": ["Stethoscope", "HeartPulse", "Activity", "Users", "Calendar", "Ambulance"],
    },
    "fashion": {
        "sections": [
            {"stem": "Collections", "label": "Collections", "anchor": "collections",
             "spec": "Collections showcase for {subject}: 4-6 cards (e.g. New Season, Formal, Casual, Accessories) with image placeholders, name and 'Explore' link"},
            {"stem": "Lookbook", "label": "Lookbook", "anchor": "lookbook",
             "spec": "Lookbook gallery for {subject}: editorial 3-6 image grid with captions, plus a newsletter signup strip"},
            {"stem": "Craft", "label": "Our Craft", "anchor": "craft",
             "spec": "Brand story / craft section for {subject}: one large editorial image beside 2-3 short paragraphs of prose about materials and process, plus a founders quote"},
            {"stem": "Testimonials", "label": "Press & Clients", "anchor": "testimonials",
             "spec": "Press mentions and client testimonials for {subject}: 3 quote cards with a name and outlet, plus a row of text-only press logos"},
        ],
        "icons": ["Shirt", "Sparkles", "ShoppingBag", "Star", "Scissors", "Gem"],
    },
    "beauty": {
        "sections": [
            {"stem": "Services", "label": "Services", "anchor": "services",
             "spec": "Service menu for {subject}: 4-6 treatment cards (e.g. Haircut & Styling, Bridal Makeup, Facial, Hair Spa, Manicure) with lucide icons, price, duration and one-line description"},
            {"stem": "WhyUs", "label": "Why Us", "anchor": "why-us",
             "spec": "Trust row for {subject}: 4 short reasons (hygiene, trained stylists, quality products, walk-ins welcome) with icons"},
            {"stem": "Gallery", "label": "Our Work", "anchor": "gallery",
             "spec": "Work gallery for {subject}: a 6-8 image grid of real looks (before/after, recent styling) with lightbox-friendly cards and short captions"},
            {"stem": "Pricing", "label": "Price List", "anchor": "pricing",
             "spec": "Price list for {subject}: 3-4 rate cards or a clean two-column table (service / starting price) with a note on starting prices, plus the booking CTA"},
            {"stem": "Testimonials", "label": "Client Love", "anchor": "testimonials",
             "spec": "Client reviews for {subject}: 3 quote cards with the client's first name, the service taken and a 5-star row"},
        ],
        "icons": ["Scissors", "Sparkles", "Heart", "Clock", "Star", "CalendarCheck"],
    },
    "restaurant": {
        "sections": [
            {"stem": "Menu", "label": "Menu", "anchor": "menu",
             "spec": "Menu highlights for {subject}: 4-6 signature dishes with image placeholders, name, short description and price"},
            {"stem": "Reservations", "label": "Reservations", "anchor": "reservations",
             "spec": "Reservation section for {subject}: opening hours card, table-booking form (date, time, guests) and location/contact strip"},
            {"stem": "Story", "label": "Our Story", "anchor": "story",
             "spec": "Origin story for {subject}: a warm two-column section pairing one large photo with 2-3 paragraphs of real-feeling prose, plus 3 small stat cards"},
            {"stem": "Testimonials", "label": "Guest Reviews", "anchor": "testimonials",
             "spec": "Guest reviews for {subject}: 3 quote cards with 5-star ratings, the guest's name and what they ordered, plus a review-platform line"},
        ],
        "icons": ["UtensilsCrossed", "ChefHat", "Wine", "Clock", "MapPin", "Star"],
    },
    "realestate": {
        "sections": [
            {"stem": "Listings", "label": "Listings", "anchor": "listings",
             "spec": "Property listings for {subject}: 3-6 property cards with image placeholders, price, beds/baths, area and 'View details' link"},
            {"stem": "Agents", "label": "Agents", "anchor": "agents",
             "spec": "Agent profiles for {subject}: 3 cards with initials avatar, name, region, contact button"},
            {"stem": "Process", "label": "How We Work", "anchor": "process",
             "spec": "Buying/selling process for {subject}: numbered step timeline (4 steps) with lucide icons, a title and one-line explanation each"},
            {"stem": "Testimonials", "label": "Client Stories", "anchor": "testimonials",
             "spec": "Client testimonials for {subject}: 3 quote cards with the client's name, the property type and a star rating"},
        ],
        "icons": ["Home", "Building2", "KeyRound", "MapPin", "Ruler", "Phone"],
    },
    "fitness": {
        "sections": [
            {"stem": "Programs", "label": "Programs", "anchor": "programs",
             "spec": "Training programs for {subject}: 4-6 program cards (e.g. Strength, HIIT, Yoga, Personal coaching) with lucide icons, intensity level and 'Join now' CTA"},
            {"stem": "Schedule", "label": "Schedule", "anchor": "schedule",
             "spec": "Class schedule & membership for {subject}: weekly class timetable table plus 3 membership cards with pricing"},
            {"stem": "Trainers", "label": "Trainers", "anchor": "trainers",
             "spec": "Trainer profiles for {subject}: 3 cards with initials avatar, name, speciality and a certifications list"},
            {"stem": "Testimonials", "label": "Transformations", "anchor": "testimonials",
             "spec": "Member transformations for {subject}: 3 quote cards each with a before/after style metric (e.g. '-14kg in 6 months'), the member's name and how long they have trained"},
        ],
        "icons": ["Dumbbell", "Activity", "HeartPulse", "Calendar", "Users", "Trophy"],
    },
    "education": {
        "sections": [
            {"stem": "Courses", "label": "Courses", "anchor": "courses",
             "spec": "Courses / programs for {subject}: 4-6 course cards with lucide icons, age or level, duration and 'Enroll' CTA"},
            {"stem": "Faculty", "label": "Faculty", "anchor": "faculty",
             "spec": "Faculty & results for {subject}: 3 teacher cards with initials avatar and subject, plus a stats strip (students, years, results)"},
            {"stem": "Admissions", "label": "Admissions", "anchor": "admissions",
             "spec": "Admissions for {subject}: a 4-step numbered enrolment timeline (enquire, campus visit, assessment, enrol) with icons, plus intake dates"},
            {"stem": "Testimonials", "label": "Parent Voices", "anchor": "testimonials",
             "spec": "Parent and alumni testimonials for {subject}: 3 quote cards with the person's name, relationship (parent/alumnus) and year"},
        ],
        "icons": ["GraduationCap", "BookOpen", "Users", "Award", "Calendar", "Lightbulb"],
    },
    "art": {
        "sections": [
            {"stem": "Gallery", "label": "Gallery", "anchor": "gallery",
             "spec": "Gallery highlights for {subject}: editorial 4-6 image grid (artworks/exhibitions) with titles, medium and year"},
            {"stem": "Visit", "label": "Visit", "anchor": "visit",
             "spec": "Visit & events for {subject}: opening hours card, current/upcoming exhibitions list, location strip and newsletter form"},
            {"stem": "Artists", "label": "Artists", "anchor": "artists",
             "spec": "Represented artists for {subject}: 3 cards with image placeholders and a name, medium and nationality caption"},
            {"stem": "Testimonials", "label": "Press", "anchor": "testimonials",
             "spec": "Press quotes for {subject}: 3 pull-quote cards with the publication name and a review of a recent exhibition"},
        ],
        "icons": ["Palette", "Frame", "Camera", "Brush", "MapPin", "Star"],
    },
    "portfolio": {
        "sections": [
            {"stem": "Work", "label": "Work", "anchor": "work",
             "spec": "Selected work grid for {subject}: 4-6 project cards with image placeholders, project name, role/category and one-line outcome"},
            {"stem": "About", "label": "About", "anchor": "about",
             "spec": "About & contact for {subject}: short bio paragraph with initials avatar, skills/capabilities list, experience stats strip and a contact form or email CTA"},
            {"stem": "Services", "label": "Services", "anchor": "services",
             "spec": "What I do for {subject}: 3-4 service cards (e.g. Product design, Design systems, Prototyping) with lucide icons, one-line description and a deliverables list"},
            {"stem": "Testimonials", "label": "Testimonials", "anchor": "testimonials",
             "spec": "Client testimonials for {subject}: 3 quote cards with the client's name, their company and role, and a link label to the related project"},
        ],
        "icons": ["Briefcase", "Image", "Camera", "PenTool", "Award", "Mail"],
    },
    "product": {
        "sections": [
            {"stem": "Showcase", "label": "Showcase", "anchor": "showcase",
             "spec": "Product showcase for {subject}: large hero-style feature blocks (3-4) each with image placeholder, feature name and benefit, plus a specs/buy strip"},
            {"stem": "Specs", "label": "Specs", "anchor": "specs",
             "spec": "Technical specs & reviews for {subject}: two-column spec table (name/value rows) plus 3 customer review cards with star ratings and a buy CTA"},
            {"stem": "Reviews", "label": "Reviews", "anchor": "reviews",
             "spec": "In-depth customer reviews for {subject}: 3 quote cards with a 5-star row, the reviewer's name, how long they have owned it, and a pros one-liner"},
            {"stem": "Faq", "label": "FAQ", "anchor": "faq",
             "spec": "Product FAQ for {subject}: 5 accordion questions covering shipping, warranty, returns, compatibility and support, with real answers"},
        ],
        "icons": ["Package", "Star", "Battery", "Cpu", "ShoppingCart", "Truck"],
    },
    "agency": {
        "sections": [
            {"stem": "Services", "label": "Services", "anchor": "services",
             "spec": "Services grid for {subject}: 4-6 service cards (e.g. Strategy, Branding, Campaigns, Content) with lucide icons and one-line descriptions"},
            {"stem": "CaseStudies", "label": "Case Studies", "anchor": "case-studies",
             "spec": "Case studies & clients for {subject}: 3 result cards (client placeholder, challenge one-liner, outcome metric) plus a client-logo strip (text placeholders)"},
            {"stem": "Process", "label": "How We Work", "anchor": "process",
             "spec": "Engagement process for {subject}: 4 numbered steps (Discover, Strategy, Execute, Measure) with icons, a title and one-line description each"},
            {"stem": "Testimonials", "label": "Testimonials", "anchor": "testimonials",
             "spec": "Client testimonials for {subject}: 3 quote cards with the person's name, their role and company, and a star rating"},
        ],
        "icons": ["Briefcase", "Target", "TrendingUp", "Users", "Megaphone", "BarChart3"],
    },
    "saas": {
        "sections": [
            {"stem": "Features", "label": "Features", "anchor": "features",
             "spec": "Feature grid for {subject}: 4-6 capability cards with lucide icons, titles, one-line descriptions"},
            {"stem": "Pricing", "label": "Pricing", "anchor": "pricing",
             "spec": "Pricing for {subject}: 3 plan cards with feature lists and CTAs"},
            {"stem": "Testimonials", "label": "Testimonials", "anchor": "testimonials",
             "spec": "Customer testimonials for {subject}: 3 quote cards with the person's name, role, company and a star rating"},
            {"stem": "Metrics", "label": "Results", "anchor": "metrics",
             "spec": "Outcome stats for {subject}: a row of 4 large metric cards (e.g. '3.2x faster', '99.9% uptime', '12k teams') with a label and one-line context each"},
        ],
        "icons": ["Zap", "Shield", "BarChart3", "Globe", "Sparkles", "Clock"],
    },
}


def get_profile(brief: dict | None) -> dict:
    """Return the profile for the brief: sections, icon guidance, domain key.

    Unknown domains get the generic SaaS sections, but the brief's own
    offerings are injected into the section specs so the model still writes
    domain-specific content ("pet grooming" lands in the feature cards).
    """
    key = detect_domain(brief)
    profile = _PROFILE_OVERRIDES.get(key)
    if profile:
        return {"key": key, **profile}

    # Unknown domain: the skeleton is inferred from FUNCTION, not from a
    # trade lookup (see task_understanding). The old fallback was the same
    # Features / Pricing / Testimonials / Process skeleton for every
    # unlisted trade -- "the SaaS page with a different name", which is the
    # template complaint with extra steps. Now the user's own words decide:
    # "book appointments" -> Booking, "my paintings" -> a Gallery, "prices"
    # -> Pricing, "records" -> a back-office, and nothing is added unless it
    # was asked for. Curated profiles above stay as quality boosts for the
    # trades they cover; they are no longer the only way to be understood.
    return task_understanding.build_profile(brief)


def all_section_stems(brief: dict | None) -> list[str]:
    """Section stems for the brief's profile (composer's canonical order)."""
    return [s["stem"] for s in get_profile(brief)["sections"]]


# ------------------------------------------------------- admin / management
# Internal back-office systems (hospital / store / employee management) are
# multi-VIEW apps, not marketing pages: a sidebar shell plus one component per
# managed entity. Same philosophy as the landing profiles -- profiles decide
# the skeleton (which views exist, what the nav says), the model writes them.

_ADMIN_VIEW_SETS: list[tuple[tuple[str, ...], list[dict]]] = [
    (("hospital", "clinic", "patient", "medical", "doctor", "ward", "pharmacy"), [
        {"stem": "Dashboard", "label": "Overview", "icon": "LayoutDashboard",
         "spec": "KPI row (patients today, beds available, appointments, revenue) plus a 'recent admissions' list and an occupancy meter"},
        {"stem": "Patients", "label": "Patients", "icon": "Users",
         "spec": "searchable patient table (name, id, age, ward, admitted date, status badge) with row actions and an 'Add patient' button that opens an inline form modal"},
        {"stem": "Appointments", "label": "Appointments", "icon": "Calendar",
         "spec": "appointment list grouped by day with doctor, department, time and status badges, plus a small calendar strip and a 'New appointment' form"},
        {"stem": "Doctors", "label": "Doctors", "icon": "Stethoscope",
         "spec": "doctor cards/table with specialty, availability toggle, weekly shift summary and on-duty count"},
    ]),
    (("employee", "staff", "hr", "payroll", "attendance", "leave", "onboarding"), [
        {"stem": "Dashboard", "label": "Overview", "icon": "LayoutDashboard",
         "spec": "KPI row (headcount, present today, on leave, open roles) plus a department breakdown and a recent-activity feed"},
        {"stem": "Employees", "label": "Employees", "icon": "Users",
         "spec": "searchable employee table (name, id, department, role, joined date, status badge) with row actions and an 'Add employee' inline form"},
        {"stem": "Attendance", "label": "Attendance", "icon": "Clock",
         "spec": "attendance view: date picker strip, present/absent/late summary counts, and a per-employee check-in table with toggle buttons"},
        {"stem": "LeaveRequests", "label": "Leave", "icon": "CalendarDays",
         "spec": "leave request queue with employee, type, dates, reason and Approve/Reject actions that update local state, plus a balance summary"},
    ]),
    (("store", "inventory", "stock", "warehouse", "supplier", "product", "order", "shop"), [
        {"stem": "Dashboard", "label": "Overview", "icon": "LayoutDashboard",
         "spec": "KPI row (SKUs, low stock, open orders, today's sales) plus a low-stock alert list and a small sales trend"},
        {"stem": "Products", "label": "Products", "icon": "Package",
         "spec": "product/inventory table (SKU, name, category, price, stock, status badge) with search, category filter and an 'Add product' inline form"},
        {"stem": "Orders", "label": "Orders", "icon": "ShoppingCart",
         "spec": "order table (id, customer, items, total, status badge) with a status filter and expandable order detail row"},
        {"stem": "Suppliers", "label": "Suppliers", "icon": "Truck",
         "spec": "supplier table with contact, lead time, outstanding purchase orders and a 'Restock' action"},
    ]),
]

_ADMIN_GENERIC = [
    {"stem": "Dashboard", "label": "Overview", "icon": "LayoutDashboard",
     "spec": "KPI row (total records, active, pending, completed) plus a recent-activity list and a status breakdown"},
    {"stem": "Records", "label": "Records", "icon": "Table2",
     "spec": "searchable, filterable records table (id, name, category, owner, updated, status badge) with row actions and an 'Add record' inline form"},
    {"stem": "Reports", "label": "Reports", "icon": "BarChart3",
     "spec": "reports view with a summary stat row, a simple bar/line visual built from divs, and an export-styled button"},
]


def admin_views(brief: dict | None) -> list[dict]:
    """Managed-entity views for a back-office system, keyed off the brief."""
    blob = " ".join([
        (brief or {}).get("domain", "") or "",
        (brief or {}).get("business_type", "") or "",
        " ".join((brief or {}).get("offerings", []) or []),
        (brief or {}).get("prompt", "") or "",
        (brief or {}).get("name", "") or "",
    ]).lower()
    for words, views in _ADMIN_VIEW_SETS:
        if any(w in blob for w in words):
            return views
    # Unknown back-office trade: derive the managed entities from the user's
    # own nouns instead of shipping the same Dashboard/Records/Reports trio
    # to every management system. Falls back to that trio when the brief
    # names no entity at all.
    derived = task_understanding.build_admin_views(brief)
    return derived or _ADMIN_GENERIC
