"""Production-grade multi-file application archetype scaffolds for Zenith.

These provide rock-solid React + Tailwind starting architectures for common SaaS domains,
allowing the local 7B model to focus on domain-specific customization and targeted feature
additions rather than inventing 800 lines of boilerplate from scratch.
"""

import json
import re
from typing import Any

import domain_profiles


# Internal back-office systems. These are multi-view admin apps (sidebar +
# tables + forms), never a marketing page or a storefront.
_ADMIN_KEYWORDS = (
    "management system", "management software", "management app",
    "management platform", "admin panel", "admin dashboard", "admin app",
    "back office", "back-office", "backoffice", "internal tool",
    "inventory management", "stock management", "warehouse management",
    "employee management", "staff management", "hr management",
    "hospital management", "patient management", "clinic management",
    "school management", "college management", "fleet management",
    "order management", "order management", "asset management",
    "pos system", "point of sale", "point-of-sale", "billing system",
    "attendance system", "payroll system", "leave management",
)


def get_archetype_for_prompt(prompt: str, business_type: str = "general") -> str:
    """Identify the best archetype from prompt and business type keywords."""
    combined = f"{prompt} {business_type}".lower()

    # Marketing sites first: "landing page for X" must not be hijacked by the
    # word "tool/product/..." inside the product description.
    if any(w in combined for w in ["landing page", "landing", "marketing site", "marketing website", "waitlist", "launch page", "product page for", "hero section", "one-pager", "startup website"]):
        return "landing"
    # Website-style prompts for people/service businesses: a portfolio,
    # agency, consultancy or law-firm "website" is a landing/marketing page,
    # NOT a SaaS dashboard or analytics app (live bug: "portfolio website"
    # fell through to the SaaS scaffold with Starter/Pro/Enterprise plans).
    if any(w in combined for w in ["portfolio", "personal website", "personal site", "resume", "cv site"]):
        return "landing"
    if any(w in combined for w in ["agency", "consultancy", "consulting firm", "law firm", "firm website", "business website", "company website", "services business", "service business"]):
        return "landing"
    if any(w in combined for w in ["product website", "product site", "product landing", "gadget"]):
        return "landing"
    # Any "<domain> site/website" is a marketing page. Without this, only the
    # words "landing page"/"website" triggered landing, so "a restaurant site"
    # fell through to the SaaS scaffold and shipped Starter/Pro/Enterprise.
    if re.search(r"\b(site|website|web page|webpage|homepage|landing)\b", combined):
        return "landing"
    # Internal management systems come BEFORE ecommerce/others: a "store
    # management system" is an admin app with a products/orders/suppliers
    # back office, NOT a storefront with a cart (live mis-route).
    if any(w in combined for w in _ADMIN_KEYWORDS):
        return "admin"
    if any(w in combined for w in ["store", "ecommerce", "e-commerce", "shop", "cart", "bakery", "retail", "clothing", "merch"]):
        return "ecommerce"
    elif any(w in combined for w in ["crm", "lead", "client", "customer", "sales", "deal", "pipeline"]):
        return "crm"
    elif any(w in combined for w in ["analytics", "chart", "metric", "revenue", "traffic", "growth", "kpi"]):
        return "analytics"
    elif any(w in combined for w in ["kanban", "task", "project", "board", "todo", "sprint", "issue"]):
        return "kanban"
    elif any(w in combined for w in ["book", "appointment", "schedule", "calendar", "reservation", "doctor", "clinic"]):
        return "booking"
    return "saas"


def get_base_scaffold(archetype: str, app_name: str = "Zenith", brand: dict[str, Any] | None = None, brief: dict | None = None) -> list[dict[str, str]]:
    """Return a complete, production-grade multi-file React application for the archetype."""
    brand = brand or {}
    name = brand.get("name") or app_name or "Zenith"
    primary_color = brand.get("primary_color") or "#7c3aed"
    
    if archetype == "landing":
        return _get_landing_scaffold(name, primary_color, brief)
    elif archetype == "admin":
        # Last-resort fallback for a back-office system. The real App.jsx is
        # composed from the model's views (see _compose_admin_shell); this only
        # ships when the model produced nothing usable, and a dashboard app is
        # the closest working shape to an admin console.
        return _get_analytics_scaffold(name, primary_color)
    elif archetype == "ecommerce":
        return _get_ecommerce_scaffold(name, primary_color)
    elif archetype == "crm":
        return _get_crm_scaffold(name, primary_color)
    elif archetype == "analytics":
        return _get_analytics_scaffold(name, primary_color)
    elif archetype == "kanban":
        return _get_kanban_scaffold(name, primary_color)
    elif archetype == "booking":
        return _get_booking_scaffold(name, primary_color)
    return _get_saas_scaffold(name, primary_color)


# ---------------------------------------------------------------- landing copy

# The curated landing scaffold is the safety net when the model's App.jsx
# fails -- but shipping it used to mean shipping GENERIC SaaS copy (live bug:
# "a law firm website" rendered "Ship work that actually ships. / Trusted by
# 12,000+ teams"). The copy library below makes the fallback domain-aware:
# the law profile turns the same tier-1 template into a real law-firm site
# with the user's actual firm name everywhere. Unknown domains get the
# generic profile with the user's name injected (never a placeholder).

_LANDING_COPY_LIBRARY = {
    "law": {
        "title_suffix": "Trusted Legal Counsel",
        "meta_description": "{name} is a client-first law firm offering clear advice, transparent fees, and proven results.",
        "badge": "Now accepting new clients",
        "hero_h1_line1": "Counsel that",
        "hero_h1_line2": "protects what matters.",
        "hero_sub": "{name} pairs seasoned attorneys with a client-first process \u2014 clear advice, honest pricing, and results you can measure.",
        "hero_primary_cta": "Book a free consultation",
        "hero_secondary_cta": "Our practice areas",
        "proof_prefix": "Trusted by",
        "proof_number": "500+",
        "proof_suffix": "clients and families",
        "features_eyebrow": "Why {name}",
        "features_h2": "Serious counsel. Straight answers.",
        "features_sub": "Four reasons clients choose {name} \u2014 and stay for decades.",
        "features": [
            {"icon": "Scale", "title": "Full-service practice", "body": "From litigation and family law to business counsel \u2014 one firm, every legal need covered."},
            {"icon": "ShieldCheck", "title": "Your interests, protected", "body": "Every engagement starts with a clear letter of engagement and a strategy built around your goals."},
            {"icon": "Clock", "title": "Responsive by design", "body": "Calls returned within one business day. You always know where your case stands and what happens next."},
            {"icon": "Users", "title": "Clients, not case numbers", "body": "A dedicated attorney \u2014 not a rotating cast \u2014 who knows your matter from first call to final filing."},
        ],
        "testimonials_eyebrow": "Client stories",
        "testimonials_h2": "Don't take our word for it.",
        "testimonials": [
            {"quote": "They handled our commercial dispute with a precision I have only seen from firms ten times their size \u2014 and billed exactly what they quoted.", "name": "Rebecca Alvarez", "role": "CEO, Alvarez Logistics", "initials": "RA"},
            {"quote": "After my accident I did not know where to start. The team took over everything and settled for more than I hoped for.", "name": "Michael Trent", "role": "Personal injury client", "initials": "MT"},
            {"quote": "Straightforward advice, no legalese, and total transparency on fees. Exactly what a family needs in a hard moment.", "name": "Priya Natarajan", "role": "Family law client", "initials": "PN"},
        ],
        "pricing_eyebrow": "Transparent fees",
        "pricing_h2": "Clear scope. Honest rates.",
        "pricing_sub": "Flat fees where possible. No surprise invoices, ever.",
        "plans": [
            {"name": "Consultation", "price": 0, "unit": "flat", "tagline": "Start with a free conversation", "features": ["30-minute strategy call", "Case assessment", "Written next steps", "No obligation"], "cta": "Book free consult", "highlighted": False},
            {"name": "Representation", "price": 195, "unit": "/hour", "tagline": "Most matters, one clear rate", "features": ["Dedicated attorney", "Transparent hourly billing", "Weekly status updates", "Document drafting included"], "cta": "Retain the firm", "highlighted": True},
            {"name": "Full-Service Counsel", "price": None, "unit": "", "tagline": "Complex matters, fully handled", "features": ["Retainer-based counsel", "Litigation & negotiation", "Priority response times", "Multi-practice coordination"], "cta": "Talk to us", "highlighted": False},
        ],
        "faqs": [
            {"q": "How much does a consultation cost?", "a": "Nothing. Your first 30-minute consultation is free \u2014 you will leave with a clear assessment of your case and a written summary of your options, whether or not you hire us."},
            {"q": "How are fees structured?", "a": "Flat fees for standard matters whenever possible; transparent hourly rates otherwise. You approve the scope in writing before any billable work begins."},
            {"q": "How long will my case take?", "a": "It depends on the matter, but you will get a realistic timeline at the first meeting \u2014 and a status update every week, so you are never left wondering."},
            {"q": "Will I work with an attorney directly?", "a": "Yes. Every client is paired with a dedicated attorney from day one \u2014 not handed off to a rotating cast of associates."},
        ],
        "cta_h2": "Ready to talk?",
        "cta_sub": "Tell us what happened \u2014 a {name} attorney will review your case and respond within one business day. The first consultation is free.",
        "cta_button": "Book a free consultation",
        "cta_note": "Free consultation \u00b7 No obligation \u00b7 Confidential",
        "logos": ["State Bar Assoc.", "Chamber of Commerce", "Alvarez Logistics", "Meridian Corp", "Oakline Trust", "Hartwell Group"],
    },
    "generic": {
        "title_suffix": "The fastest way to ship",
        "meta_description": "{name} helps teams move faster with less effort.",
        "badge": "New: real-time collaboration is here",
        "hero_h1_line1": "Ship work that",
        "hero_h1_line2": "actually ships.",
        "hero_sub": "{name} turns scattered updates, tools and approvals into one calm workspace your whole team can act on \u2014 in real time.",
        "hero_primary_cta": "Start free \u2014 no card",
        "hero_secondary_cta": "See how it works",
        "proof_prefix": "Trusted by",
        "proof_number": "12,000+",
        "proof_suffix": "teams",
        "features_eyebrow": "Why {name}",
        "features_h2": "Everything you need. Nothing you don't.",
        "features_sub": "Four capabilities that replace a shelf of subscriptions.",
        "features": [
            {"icon": "Zap", "title": "Instant setup", "body": "Go from signup to shipping in under two minutes. No config, no credit card, no calls."},
            {"icon": "Shield", "title": "Enterprise-grade security", "body": "SOC 2 Type II, SSO/SAML, and granular permissions are included on every plan."},
            {"icon": "BarChart3", "title": "Insights that act", "body": "Live dashboards turn raw activity into decisions your whole team can see."},
            {"icon": "Globe", "title": "Works everywhere", "body": "Browser, desktop and mobile \u2014 your work syncs the moment you make it."},
        ],
        "testimonials_eyebrow": "Loved by teams",
        "testimonials_h2": "Don't take our word for it.",
        "testimonials": [
            {"quote": "We replaced four tools with {name} in a week and our throughput doubled. It is the first software the whole team actually opens daily.", "name": "Maya Chen", "role": "Head of Operations, Northwind", "initials": "MC"},
            {"quote": "The onboarding was absurdly fast. My team was live before lunch and asking why we waited so long.", "name": "Daniel Okafor", "role": "CTO, Brightstack", "initials": "DO"},
            {"quote": "I have bought a lot of software. This is the first demo that ended with the team cheering.", "name": "Sofia Marino", "role": "VP Product, Lattice Labs", "initials": "SM"},
        ],
        "pricing_eyebrow": "Pricing",
        "pricing_h2": "Simple, honest plans.",
        "pricing_sub": "Start free. Upgrade when it pays for itself.",
        "plans": [
            {"name": "Starter", "price": 0, "unit": "/user/mo", "tagline": "For small teams getting going", "features": ["Up to 5 users", "Unlimited projects", "Community support", "1 GB storage"], "cta": "Start free", "highlighted": False},
            {"name": "Pro", "price": 24, "unit": "/user/mo", "tagline": "For teams that ship weekly", "features": ["Unlimited users", "Advanced analytics", "Priority support", "100 GB storage", "SSO & audit logs"], "cta": "Start 14-day trial", "highlighted": True},
            {"name": "Enterprise", "price": None, "unit": "", "tagline": "For organizations at scale", "features": ["Custom contracts & SLAs", "Dedicated success manager", "On-prem / private cloud", "Security review & DPA"], "cta": "Talk to sales", "highlighted": False},
        ],
        "faqs": [
            {"q": "How long does setup take?", "a": "Most teams are fully migrated in under an hour. Import existing projects with one click and invite unlimited teammates during a free 14-day trial."},
            {"q": "Is there a free plan?", "a": "Yes \u2014 the Starter plan is free forever for up to 5 users, with no feature floor traps. Upgrade only when you outgrow it."},
            {"q": "Can I cancel anytime?", "a": "Anytime, self-serve, two clicks. Annual plans are refunded pro-rata within the first 30 days, no questions asked."},
            {"q": "How is my data protected?", "a": "Everything is encrypted in transit (TLS 1.3) and at rest (AES-256). We are SOC 2 Type II certified and run independent penetration tests twice a year."},
        ],
        "cta_h2": "Ready to move faster?",
        "cta_sub": "Join 12,000+ teams using {name} to turn plans into shipped work. Free for 14 days.",
        "cta_button": "Get started",
        "cta_note": "Free 14-day trial \u00b7 No credit card \u00b7 Cancel anytime",
        "logos": ["Northwind", "Brightstack", "Lattice Labs", "Acme Corp", "Globex", "Initech"],
    },
}

# Per-domain overrides deep-merged over "generic" by _landing_copy(). Keep
# these tight: only what genuinely differs (hero framing, section eyebrow +
# headings, testimonial angles, CTA). Anything omitted falls back to the
# generic block with the user's name formatted in.
_DOMAIN_COPY_OVERRIDES: dict[str, dict] = {
    "portfolio": {
        "title_suffix": "Selected Work",
        "meta_description": "{name} is the personal portfolio of a designer and developer \u2014 selected projects, process and contact.",
        "badge": "Available for new projects",
        "hero_h1_line1": "Work that speaks",
        "hero_h1_line2": "before I do.",
        "hero_sub": "{name} is the studio of one: strategy, design and code for teams who care how things feel. Currently booking for next quarter.",
        "hero_primary_cta": "View the work",
        "hero_secondary_cta": "Get in touch",
        "proof_prefix": "",
        "proof_number": "8+",
        "proof_suffix": "years crafting digital products",
        "features_eyebrow": "Services",
        "features_h2": "What I do best.",
        "features_sub": "Three disciplines, one person accountable for all of them.",
        "features": [
            {"icon": "PenTool", "title": "Product design", "body": "From fuzzy idea to shippable UI \u2014 research, flows, design systems and the pixel work nobody notices but everybody feels."},
            {"icon": "Code", "title": "Front-end craft", "body": "React, motion and accessibility as standard. Designs that survive contact with real data and real screens."},
            {"icon": "Target", "title": "Brand identity", "body": "Logos, voice and visual language that hold up everywhere from a favicon to a billboard."},
            {"icon": "Users", "title": "Embedded collaboration", "body": "I work inside your team and tools \u2014 no handoffs, no black box, no vanishing act."},
        ],
        "testimonials_eyebrow": "Kind words",
        "testimonials_h2": "People I have shipped with.",
        "testimonials": [
            {"quote": "The redesign paid for itself in a quarter \u2014 conversion up 34% and support tickets down by half. And a genuine pleasure to work with.", "name": "Lena Fischer", "role": "Founder, Arcline", "initials": "LF"},
            {"quote": "Rare combination: designer who codes, coder who cares about type. Our product finally feels like one thing.", "name": "Marcus Webb", "role": "CPO, Fieldnote", "initials": "MW"},
            {"quote": "Took our scattered brand and made it coherent in six weeks. Invoices, app, website \u2014 all of it sings.", "name": "Ana Rojas", "role": "CEO, Bloomcart", "initials": "AR"},
        ],
        "pricing_eyebrow": "Engagements",
        "pricing_h2": "Three ways to work together.",
        "pricing_sub": "Clear scope, clear price, no agency overhead.",
        "plans": [
            {"name": "Design Sprint", "price": 2400, "unit": "/week", "tagline": "One focused week", "features": ["Prototype by Friday", "Daily reviews", "Design files included", "Async-friendly"], "cta": "Book a sprint", "highlighted": False},
            {"name": "Monthly Retainer", "price": 6500, "unit": "/mo", "tagline": "Your design partner", "features": ["Ongoing product work", "Priority turnaround", "Design system upkeep", "Pause anytime"], "cta": "Check availability", "highlighted": True},
            {"name": "Full Build", "price": None, "unit": "from", "tagline": "Zero to launched", "features": ["Brand + product + site", "Fixed quoted price", "Weekly demos", "Handoff & training"], "cta": "Start a project", "highlighted": False},
        ],
        "faqs": [
            {"q": "What does a project cost?", "a": "Sprints start at $2,400; full builds are quoted fixed after one call. You always know the number before any work starts."},
            {"q": "How fast can you start?", "a": "Usually within two weeks. Retainers reserve days every month; sprints book specific weeks."},
            {"q": "Do you work with existing teams?", "a": "That is the default \u2014 I embed in your Slack, your repo and your rituals."},
            {"q": "Who owns the work?", "a": "You do. Every file, every license, transferred at the final invoice."},
        ],
        "cta_h2": "Have something in mind?",
        "cta_sub": "Tell me about the project \u2014 I reply to every serious inquiry within one business day.",
        "cta_button": "Start a conversation",
        "cta_note": "Currently booking \u00b7 Replies within 24h \u00b7 Remote-friendly",
        "logos": ["Arcline", "Fieldnote", "Bloomcart", "Northwind", "Lattice Labs", "Brightstack"],
    },
    "product": {
        "title_suffix": "The thoughtful gadget",
        "meta_description": "{name} is engineered for daily use: premium materials, honest specs, no subscription required.",
        "badge": "Free shipping \u00b7 30-day returns",
        "hero_h1_line1": "Meet",
        "hero_h1_line2": "the everyday upgrade.",
        "hero_sub": "{name} packs flagship features into a device you will actually use every day \u2014 with the specs to prove it and no strings attached.",
        "hero_primary_cta": "Buy now",
        "hero_secondary_cta": "See the tech specs",
        "proof_prefix": "Rated",
        "proof_number": "4.8/5",
        "proof_suffix": "from 2,300+ verified buyers",
        "features_eyebrow": "Why {name}",
        "features_h2": "Small details. Big difference.",
        "features_sub": "Every choice made for the person holding it \u2014 not the spec sheet.",
        "features": [
            {"icon": "Battery", "title": "All-week battery", "body": "18 hours of real use per charge with the fast-charge dock included in the box \u2014 0 to 80% in 40 minutes."},
            {"icon": "Cpu", "title": "Flagship silicon", "body": "The latest low-power chipset handles everything instantly and sips battery doing it. Upgradable for 5+ years."},
            {"icon": "ShieldCheck", "title": "Built to survive", "body": "Aerospace aluminum, IP68 sealing and Gorilla glass. Survives the day \u2014 backed by a 2-year warranty."},
            {"icon": "Smartphone", "title": "Plays well with others", "body": "Pairs with iOS, Android, Mac and Windows in under a minute. No account wall, no lock-in."},
        ],
        "testimonials_eyebrow": "Owner reviews",
        "testimonials_h2": "Buyers, not reviewers.",
        "testimonials": [
            {"quote": "Third one of these I have owned. Battery life is the real headline \u2014 I charge it twice a week and forget it exists.", "name": "Jordan Blake", "role": "Verified buyer", "initials": "JB"},
            {"quote": "The build quality embarrassed a device twice the price. The details are where this thing wins.", "name": "Priya Shah", "role": "Verified buyer", "initials": "PS"},
            {"quote": "Setup took a minute, the app is optional, and it just works with everything I own. Refreshing.", "name": "Tom Nguyen", "role": "Verified buyer", "initials": "TN"},
        ],
        "pricing_eyebrow": "One device. One price.",
        "pricing_h2": "Pick your finish.",
        "pricing_sub": "Every configuration ships with the same hardware, warranty and free shipping.",
        "plans": [
            {"name": "Standard", "price": 149, "unit": "", "tagline": "Everything you need", "features": ["Matte black finish", "USB-C cable & dock", "2-year warranty", "Free shipping"], "cta": "Buy now", "highlighted": False},
            {"name": "Pro", "price": 199, "unit": "", "tagline": "The popular choice", "features": ["Silver or graphite finish", "Wireless charging pad", "2-year warranty + accident cover", "Free shipping"], "cta": "Buy Pro", "highlighted": True},
            {"name": "Bundle", "price": 249, "unit": "", "tagline": "The complete kit", "features": ["Any finish", "Travel case & spare cable", "Extended 3-year warranty", "Priority support"], "cta": "Buy bundle", "highlighted": False},
        ],
        "faqs": [
            {"q": "Is there a subscription?", "a": "No. Every feature works out of the box, forever. The companion app is optional and free."},
            {"q": "What is the return policy?", "a": "30 days, no questions, free return label in the box. Refunds process within 3 business days of arrival."},
            {"q": "Does it work with my phone?", "a": "Yes \u2014 iPhone, Android, Mac and Windows are all supported with the same feature set."},
            {"q": "How long is the warranty?", "a": "Two years standard, extendable to three with the bundle. Accidental damage is covered on Pro and Bundle."},
        ],
        "cta_h2": "Ready when you are.",
        "cta_sub": "Order today and it ships tomorrow \u2014 free delivery, 30-day returns and a 2-year warranty included.",
        "cta_button": "Buy now \u2014 ships free",
        "cta_note": "Free shipping \u00b7 30-day returns \u00b7 2-year warranty",
        "logos": ["TechWeekly", "GadgetRadar", "The Verge List", "Wirecutter Blog", "MKBHD Shorts", "Android Digest"],
    },
    "agency": {
        "title_suffix": "Growth, engineered",
        "meta_description": "{name} is a full-service agency: strategy, brand and campaigns that move the numbers that matter.",
        "badge": "Taking on 3 new clients this quarter",
        "hero_h1_line1": "We turn attention",
        "hero_h1_line2": "into revenue.",
        "hero_sub": "{name} is a senior-only team running strategy, brand and performance under one roof \u2014 measured on your numbers, not our deliverables.",
        "hero_primary_cta": "Book a strategy call",
        "hero_secondary_cta": "See case studies",
        "proof_prefix": "Driving",
        "proof_number": "$40M+",
        "proof_suffix": "in tracked client revenue",
        "features_eyebrow": "Services",
        "features_h2": "Full stack, senior only.",
        "features_sub": "Four practices that plug into each other \u2014 and into your P&L.",
        "features": [
            {"icon": "Target", "title": "Strategy & positioning", "body": "Market research, positioning and messaging that give every downstream channel something sharp to say."},
            {"icon": "Palette", "title": "Brand & identity", "body": "Identity systems built to convert \u2014 logo to landing page, one coherent voice across every touchpoint."},
            {"icon": "Megaphone", "title": "Performance campaigns", "body": "Paid social and search managed to CAC and ROAS targets, with creative testing baked in weekly."},
            {"icon": "BarChart3", "title": "Analytics & CRO", "body": "Dashboards, attribution and experiment programs that compound \u2014 you keep the infrastructure forever."},
        ],
        "testimonials_eyebrow": "Client results",
        "testimonials_h2": "The numbers, in their words.",
        "testimonials": [
            {"quote": "CAC down 41% in five months while tripling spend. They are the first agency that left our numbers better than their deck.", "name": "Dana Kim", "role": "CMO, Solace", "initials": "DK"},
            {"quote": "Rebrand to launch in 8 weeks, and the campaign beat its lead target by 60%. Senior people on the account, every call.", "name": "Omar Haddad", "role": "Founder, Kite & Co.", "initials": "OH"},
            {"quote": "They rebuilt our funnel and handed us the playbook. Two years later we still run on their infrastructure.", "name": "Grace Osei", "role": "VP Growth, Fernway", "initials": "GO"},
        ],
        "pricing_eyebrow": "Engagement models",
        "pricing_h2": "Scoped like a partner, not a vendor.",
        "pricing_sub": "Month-to-month after the initial sprint. You own everything we build.",
        "plans": [
            {"name": "Growth Sprint", "price": 9500, "unit": "one-off", "tagline": "6 weeks, one objective", "features": ["Audit & roadmap", "Positioning + messaging", "One channel launched", "Executive readout"], "cta": "Book a sprint", "highlighted": False},
            {"name": "Growth Partner", "price": 14500, "unit": "/mo", "tagline": "The embedded team", "features": ["Strategy + brand + performance", "Weekly experiments", "Senior team, no juniors", "Cancel monthly"], "cta": "Talk strategy", "highlighted": True},
            {"name": "Fractional CMO", "price": 7000, "unit": "/mo", "tagline": "Leadership without the hire", "features": ["2 days a week executive time", "Team hiring & management", "Board-ready reporting", "Vendor negotiation"], "cta": "Discuss fit", "highlighted": False},
        ],
        "faqs": [
            {"q": "What size companies do you work with?", "a": "Typically $1M-$30M revenue \u2014 big enough to have real budget, small enough that senior attention moves the needle."},
            {"q": "How is the work priced?", "a": "Fixed-fee sprints and monthly retainers. Media spend is paid directly to platforms; we never take a cut of it."},
            {"q": "Who actually does the work?", "a": "The people you meet on the sales calls. Every account is staffed senior-only, and you can veto any team member."},
            {"q": "What results can I expect?", "a": "The sprint ends with a roadmap and a launched channel; partners typically see CAC or conversion improvements within the first quarter."},
        ],
        "cta_h2": "Let's look at your numbers.",
        "cta_sub": "A 30-minute strategy call: we review your funnel live and leave you with two or three actions \u2014 whether or not we work together.",
        "cta_button": "Book a strategy call",
        "cta_note": "30-minute call \u00b7 No deck, just your data \u00b7 No obligation",
        "logos": ["Solace", "Kite & Co.", "Fernway", "Northwind", "Acme Corp", "Globex"],
    },
    "law": {
        "title_suffix": "Trusted Legal Counsel",
        "meta_description": "{name} is a client-first law firm offering clear advice, transparent fees, and proven results.",
        "badge": "Now accepting new clients",
        "hero_h1_line1": "Counsel that",
        "hero_h1_line2": "protects what matters.",
        "hero_sub": "{name} pairs seasoned attorneys with a client-first process \u2014 clear advice, honest pricing, and results you can measure.",
        "hero_primary_cta": "Book a free consultation",
        "hero_secondary_cta": "Our practice areas",
        "proof_number": "500+",
        "proof_suffix": "clients and families",
        "features_h2": "Serious counsel. Straight answers.",
        "features_sub": "Four reasons clients choose {name} \u2014 and stay for decades.",
        "features": [
            {"icon": "Scale", "title": "Full-service practice", "body": "From litigation and family law to business counsel \u2014 one firm, every legal need covered."},
            {"icon": "ShieldCheck", "title": "Your interests, protected", "body": "Every engagement starts with a clear letter of engagement and a strategy built around your goals."},
            {"icon": "Clock", "title": "Responsive by design", "body": "Calls returned within one business day. You always know where your case stands."},
            {"icon": "Users", "title": "Clients, not case numbers", "body": "A dedicated attorney \u2014 not a rotating cast \u2014 who knows your matter from first call to final filing."},
        ],
        "pricing_eyebrow": "Transparent fees",
        "pricing_h2": "Clear scope. Honest rates.",
        "pricing_sub": "Flat fees where possible. No surprise invoices, ever.",
        "plans": [{"name": "Initial Consultation", "price": 0, "unit": "free", "tagline": "Meet the team", "features": ["Case review", "Honest assessment", "Fee quote upfront", "No obligation"], "cta": "Book consultation", "highlighted": False}, {"name": "Standard Representation", "price": 250, "unit": "/hour", "tagline": "Full representation", "features": ["Dedicated attorney", "Court appearances", "Document drafting", "Weekly updates"], "cta": "Retain counsel", "highlighted": True}, {"name": "Fixed-Fee Matters", "price": 1200, "unit": "from", "tagline": "Known scope, known price", "features": ["Wills & estates", "Contracts review", "Property closings", "One flat invoice"], "cta": "Get a quote", "highlighted": False}],
        "faqs": [{"q": "What happens in the first consultation?", "a": "You tell us what happened, we tell you where you stand — candidly. You leave with a clear view of options, timelines and likely costs, whatever you decide."}, {"q": "How are fees structured?", "a": "Straightforwardly. Hourly work is billed monthly with a detailed ledger; many standard matters are quoted as one fixed fee before we begin."}, {"q": "Will I speak with the attorney or a call center?", "a": "With your attorney. Calls and emails are answered by the lawyer handling your matter, usually the same day."}, {"q": "How long will my case take?", "a": "It depends on the matter — at the first meeting you get a realistic timeline, and we flag early if it changes."}],
        "cta_h2": "Ready to talk?",
        "cta_sub": "Tell us what happened \u2014 a {name} attorney will respond within one business day. The first consultation is free.",
        "cta_button": "Book a free consultation",
        "cta_note": "Free consultation \u00b7 No obligation \u00b7 Confidential",
    },
    "hospital": {
        "title_suffix": "Care You Can Trust",
        "meta_description": "{name} delivers modern, compassionate healthcare — from everyday checkups to specialized treatment.",
        "badge": "Accepting new patients",
        "hero_h1_line1": "Your health,",
        "hero_h1_line2": "in caring hands.",
        "hero_sub": "{name} combines experienced physicians with modern facilities — same-week appointments, transparent billing, care that puts patients first.",
        "hero_primary_cta": "Book an appointment",
        "hero_secondary_cta": "Our services",
        "proof_number": "25,000+",
        "proof_suffix": "patients cared for",
        "features_eyebrow": "Why {name}",
        "features_h2": "Modern medicine. Human care.",
        "features_sub": "Everything your family needs, under one roof.",
        "features": [
            {"icon": "Stethoscope", "title": "Comprehensive services", "body": "General medicine, pediatrics, cardiology and diagnostics — coordinated in one place."},
            {"icon": "HeartPulse", "title": "Patient-first care", "body": "Longer consultations, clear explanations, and treatment plans built around your life."},
            {"icon": "Activity", "title": "Same-week appointments", "body": "Online booking with real availability — including evenings and weekends."},
            {"icon": "ShieldCheck", "title": "Transparent billing", "body": "Written estimates before treatment. No surprise bills, ever."},
        ],
        "testimonials_h2": "Patients, in their own words.",
        "pricing_eyebrow": "Health plans",
        "pricing_h2": "Simple, honest pricing.",
        "pricing_sub": "Walk-in consults, annual plans, and corporate checkups.",
        "plans": [{"name": "General Visit", "price": 60, "unit": "flat", "tagline": "Everyday care", "features": ["Consultation & exam", "Same-week booking", "On-site lab work", "Prescriptions included"], "cta": "Book a visit", "highlighted": False}, {"name": "Specialist", "price": 95, "unit": "flat", "tagline": "Focused expertise", "features": ["Specialist consultation", "Care plan", "Follow-up included", "Referrals handled"], "cta": "Book specialist", "highlighted": True}, {"name": "Care Plan", "price": None, "unit": "", "tagline": "Ongoing support", "features": ["Chronic care management", "Priority scheduling", "Annual health check", "Direct messaging"], "cta": "Ask about care", "highlighted": False}],
        "faqs": [{"q": "Do you accept insurance?", "a": "We work with all major providers and bill directly where possible - bring your card to the first visit and we will confirm coverage on the spot."}, {"q": "How fast can I be seen?", "a": "Same-day slots are held every morning for urgent needs; routine visits are usually available within the week."}, {"q": "Do you see children?", "a": "Yes - our pediatric team covers everything from newborn checks to teenage sports physicals."}, {"q": "Where do I park?", "a": "Patient parking is free behind the building, and the entrance is step-free from there."}],
        "cta_h2": "Ready when you are.",
        "cta_sub": "Book online in two minutes or call — our care team responds the same day.",
        "cta_button": "Book an appointment",
        "cta_note": "Same-week appointments · Insurance friendly · Emergency walk-ins",
    },
    "fashion": {
        "title_suffix": "Wear the Extraordinary",
        "meta_description": "{name} crafts clothing that turns heads — curated collections, honest fabrics, timeless cuts.",
        "badge": "New season has landed",
        "hero_h1_line1": "Style that",
        "hero_h1_line2": "speaks first.",
        "hero_sub": "{name} turns honest fabrics into pieces you'll reach for every day — designed to last, made to be noticed.",
        "hero_primary_cta": "Shop the collection",
        "hero_secondary_cta": "View lookbook",
        "proof_number": "40k+",
        "proof_suffix": "happy customers",
        "features_eyebrow": "The {name} difference",
        "features_h2": "Designed with intent.",
        "features_sub": "Four reasons the wardrobe starts here.",
        "features": [
            {"icon": "Scissors", "title": "Cut to last", "body": "Tailored silhouettes and reinforced stitching — pieces that keep their shape for years."},
            {"icon": "Gem", "title": "Honest fabrics", "body": "Organic cotton, linen and recycled fibers — sourced traceably, priced fairly."},
            {"icon": "Shirt", "title": "Every occasion", "body": "From boardroom to weekend — one wardrobe that moves with your calendar."},
            {"icon": "Sparkles", "title": "Small-batch drops", "body": "Limited runs mean you rarely meet someone in your piece. When you do — great taste."},
        ],
        "testimonials_eyebrow": "Worn and loved",
        "pricing_eyebrow": "Membership",
        "pricing_h2": "Join the inside circle.",
        "pricing_sub": "Early drops, free tailoring, members-only collections.",
        "plans": [{"name": "Styling Session", "price": 80, "unit": "/hour", "tagline": "One-on-one with a stylist", "features": ["Wardrobe edit", "Personal styling", "Fit advice", "Lookbook to keep"], "cta": "Book a session", "highlighted": True}, {"name": "Made to Measure", "price": None, "unit": "from", "tagline": "Cut for you alone", "features": ["Private fitting", "Fabric selection", "Two fittings", "Ready in 3 weeks"], "cta": "Start fitting", "highlighted": False}, {"name": "Personal Shopper", "price": 50, "unit": "/hour", "tagline": "Shop with an expert", "features": ["Curated picks", "Private fitting room", "Alterations handled", "No obligation"], "cta": "Reserve a slot", "highlighted": False}],
        "faqs": [{"q": "Do you offer alterations?", "a": "Every purchase includes complimentary basic alterations; made-to-measure pieces are cut for you from the first sketch."}, {"q": "Can I book a private appointment?", "a": "Yes - the boutique opens outside hours for private styling sessions, by appointment only."}, {"q": "Which sizes do you carry?", "a": "Our range runs XXS to 4XL in-store, with the full spectrum available through the made-to-measure atelier."}, {"q": "What is your return policy?", "a": "Unworn pieces return within 30 days for a full refund; sale items exchange or store credit."}],
        "cta_h2": "Your wardrobe is waiting.",
        "cta_sub": "Join the list for early access to the next drop — members shop 48 hours before everyone else.",
        "cta_button": "Shop new arrivals",
        "cta_note": "Free returns · Free tailoring · Ships worldwide",
    },
    "restaurant": {
        "title_suffix": "A Table Worth Booking",
        "meta_description": "{name} serves seasonal plates and warm hospitality — book your table in under a minute.",
        "badge": "Open today until late",
        "hero_h1_line1": "Flavor worth",
        "hero_h1_line2": "gathering for.",
        "hero_sub": "{name} pairs a seasonal menu with warm hospitality — a neighborhood table you'll want to keep coming back to.",
        "hero_primary_cta": "Reserve a table",
        "hero_secondary_cta": "See the menu",
        "proof_number": "4.9",
        "proof_suffix": "average guest rating",
        "features_eyebrow": "From our kitchen",
        "features_h2": "Seasonal. Honest. Delicious.",
        "features_sub": "What makes a meal here different.",
        "features": [
            {"icon": "ChefHat", "title": "Seasonal menu", "body": "The menu changes with the market — plates built around what's best this week."},
            {"icon": "Wine", "title": "Considered pairings", "body": "A short, personal wine and drinks list curated to the menu."},
            {"icon": "UtensilsCrossed", "title": "Made from scratch", "body": "Breads, pastas and desserts made in-house every morning."},
            {"icon": "Clock", "title": "Never rushed", "body": "Book a table and it's yours for the evening. Lingering encouraged."},
        ],
        "testimonials_eyebrow": "Guest book",
        "pricing_eyebrow": "Experiences",
        "pricing_h2": "More than dinner.",
        "pricing_sub": "Tasting menus, chef's tables and private events.",
        "plans": [
            {"name": "La Tavola", "price": 55, "unit": "/guest", "tagline": "The seasonal tasting", "features": ["Five seasonal courses", "Chef's daily selection", "Dietary swaps welcome", "2.5 hour sitting"], "cta": "Reserve tasting", "highlighted": True},
            {"name": "Pizza & Vino", "price": 32, "unit": "/guest", "tagline": "The weeknight table", "features": ["Wood-fired pizza", "House salad to share", "Glass of natural wine", "Walk-ins welcome"], "cta": "Book weeknight", "highlighted": False},
            {"name": "Private Dining", "price": None, "unit": "", "tagline": "Your room, your menu", "features": ["Seats up to 24", "Set menu built with the chef", "Dedicated service team", "Wine pairing optional"], "cta": "Enquire now", "highlighted": False},
        ],
        "faqs": [
            {"q": "Do you take walk-ins?", "a": "Yes — about a third of the room is kept for walk-ins. Weekends fill fast, so booking ahead is the safe bet."},
            {"q": "Can you handle allergies and dietary needs?", "a": "Always. Vegetarian, vegan and gluten-free versions of most dishes are ready, and the kitchen adapts for allergies — just note it when you book."},
            {"q": "Do you offer gift cards?", "a": "We do, for any amount — the perfect excuse for someone to finally try the tasting menu."},
            {"q": "Is there parking nearby?", "a": "Street parking is free after 6pm, and the Market Street garage is a two-minute walk with flat evening rates."},
        ],
        "cta_h2": "Save your table.",
        "cta_sub": "Tell us when and how many — we'll keep the candles lit and the kitchen ready.",
        "cta_button": "Reserve a table",
        "cta_note": "Open Tue–Sun · Private events · Walk-ins welcome at the bar",
    },
    "realestate": {
        "title_suffix": "Find Where You Belong",
        "meta_description": "{name} helps families and investors find, negotiate and close on the right property.",
        "hero_h1_line1": "Keys to",
        "hero_h1_line2": "your next chapter.",
        "hero_sub": "{name} pairs local market mastery with straight-talk guidance — from first viewing to final signature.",
        "hero_primary_cta": "Browse listings",
        "hero_secondary_cta": "Meet the agents",
        "proof_number": "1,200+",
        "proof_suffix": "homes matched",
        "features_h2": "Local experts. Real results.",
        "plans": [{"name": "Buyer Services", "price": None, "unit": "", "tagline": "From search to keys", "features": ["Curated listings", "Offer negotiation", "Inspection coordination", "Closing support"], "cta": "Start searching", "highlighted": True}, {"name": "Seller Services", "price": None, "unit": "", "tagline": "Sell for the right price", "features": ["Home valuation", "Staging advice", "Professional listing", "Marketing package"], "cta": "Get a valuation", "highlighted": False}, {"name": "Investor Program", "price": None, "unit": "", "tagline": "Build the portfolio", "features": ["Yield analysis", "Off-market deals", "Property management", "Portfolio review"], "cta": "Talk investments", "highlighted": False}],
        "faqs": [{"q": "What does a valuation cost?", "a": "Nothing - the first home valuation and market report are free, with no obligation to list."}, {"q": "How long does selling take?", "a": "Most homes in our area go under offer in 3-6 weeks; your agent will give you a realistic timeline with the valuation."}, {"q": "Do you handle rentals too?", "a": "Yes - the rental desk covers lettings and property management for owners who prefer hands-off."}, {"q": "Are viewings by appointment?", "a": "Viewings are scheduled around you, including evenings and weekends."}],
        "cta_h2": "Let's find yours.",
        "cta_sub": "Tell us what home means to you — an agent will curate matches within 24 hours.",
        "cta_button": "Book a viewing",
        "cta_note": "Free valuation · No-pressure viewings · 24h response",
    },
    "fitness": {
        "title_suffix": "Stronger Every Week",
        "meta_description": "{name} is a coaching-first gym — real programs, real accountability, real results.",
        "hero_h1_line1": "Train with",
        "hero_h1_line2": "purpose.",
        "hero_sub": "{name} pairs coached programming with a community that shows up — your first week is on us.",
        "hero_primary_cta": "Start free week",
        "hero_secondary_cta": "See programs",
        "proof_number": "2,400+",
        "proof_suffix": "members stronger",
        "features_eyebrow": "The {name} method",
        "features_h2": "Programs, not workouts.",
        "plans": [{"name": "Group Classes", "price": 39, "unit": "/mo", "tagline": "Train together", "features": ["Unlimited classes", "All levels welcome", "App booking", "No lock-in"], "cta": "Start training", "highlighted": False}, {"name": "Coaching", "price": 89, "unit": "/mo", "tagline": "Programming + accountability", "features": ["Personalized program", "Monthly testing", "Nutrition guidance", "Coach on call"], "cta": "Get a coach", "highlighted": True}, {"name": "1-on-1 Personal", "price": 60, "unit": "/session", "tagline": "Full attention", "features": ["Private sessions", "Technique focus", "Flexible times", "Progress reviews"], "cta": "Book sessions", "highlighted": False}],
        "faqs": [{"q": "I am a complete beginner - is that ok?", "a": "Perfect, actually. Every membership starts with an onboarding session where the coach scales everything to where you are today."}, {"q": "Is there a contract?", "a": "No - memberships are month to month, pause anytime."}, {"q": "What should I bring?", "a": "Trainers and a water bottle; we provide everything else, including the programming."}, {"q": "Do you have showers?", "a": "Yes - changing rooms, showers and lockers are included with every membership."}],
        "cta_h2": "Your first week is free.",
        "cta_sub": "Book a free week of classes — no card, no pressure, just training.",
        "cta_button": "Claim free week",
        "cta_note": "No joining fee · Cancel anytime · All levels",
    },
    "education": {
        "title_suffix": "Learn Without Limits",
        "meta_description": "{name} offers small classes and proven outcomes — enroll for the next term.",
        "hero_h1_line1": "Where bright",
        "hero_h1_line2": "futures begin.",
        "hero_sub": "{name} pairs small classes with dedicated mentors — so every student is known, challenged and celebrated.",
        "hero_primary_cta": "Enroll now",
        "hero_secondary_cta": "Our courses",
        "proof_number": "98%",
        "proof_suffix": "graduate with distinction",
        "features_eyebrow": "Why families choose {name}",
        "features_h2": "Teaching that connects.",
        "plans": [{"name": "Group Courses", "price": 120, "unit": "/course", "tagline": "Learn together", "features": ["8-week terms", "Small groups", "Materials included", "Certificate"], "cta": "Browse courses", "highlighted": True}, {"name": "Private Tutoring", "price": 45, "unit": "/hour", "tagline": "One-on-one focus", "features": ["Personal plan", "Flexible scheduling", "Progress reports", "Exam prep"], "cta": "Find a tutor", "highlighted": False}, {"name": "Full Program", "price": None, "unit": "", "tagline": "The complete path", "features": ["Year-round curriculum", "Mentorship", "Portfolio support", "Career guidance"], "cta": "Apply now", "highlighted": False}],
        "faqs": [{"q": "How do I know which level fits?", "a": "Every enrollment starts with a short assessment - free, informal, and it places you exactly where you will learn fastest."}, {"q": "Are classes online or in person?", "a": "Both - most courses run in person with an online track for the same material."}, {"q": "What if I miss a session?", "a": "Sessions are recorded and the tutor runs a weekly catch-up office hour, so falling behind is a choice."}, {"q": "Do you help with certifications?", "a": "Yes - exam prep is built into the relevant courses, and private students get a customized exam plan."}],
        "cta_h2": "Applications are open.",
        "cta_sub": "Book a campus tour or start an application — the next term begins soon.",
        "cta_button": "Book a tour",
        "cta_note": "Small classes · Scholarships available · Term starts January",
    },
    "art": {
        "title_suffix": "Where Ideas Take Form",
        "meta_description": "{name} is a contemporary gallery and creative studio — exhibitions, collections and commissions.",
        "hero_h1_line1": "Art that",
        "hero_h1_line2": "stops you mid-step.",
        "hero_sub": "{name} exhibits contemporary work worth the pause — rotating shows, open studios and pieces to live with.",
        "hero_primary_cta": "Plan your visit",
        "hero_secondary_cta": "Current exhibition",
        "proof_number": "30+",
        "proof_suffix": "exhibitions a year",
        "features_eyebrow": "At {name}",
        "features_h2": "Always something to see.",
        "plans": [{"name": "Exhibition Visit", "price": 12, "unit": "flat", "tagline": "See the current show", "features": ["Full gallery access", "Artist notes", "Guided tour Sundays", "Kids free"], "cta": "Plan a visit", "highlighted": True}, {"name": "Workshops", "price": 65, "unit": "/session", "tagline": "Make, not just look", "features": ["All materials", "Small groups", "Artist-led", "Take your work home"], "cta": "Join a workshop", "highlighted": False}, {"name": "Collector Circle", "price": None, "unit": "", "tagline": "First look, private view", "features": ["Preview evenings", "Artist studio visits", "Placement advice", "Framing service"], "cta": "Apply to join", "highlighted": False}],
        "faqs": [{"q": "Is the gallery suitable for children?", "a": "Very - Sundays run family tours, and admission for kids is always free."}, {"q": "Can I buy the works on show?", "a": "Most pieces are for sale; the desk can arrange viewings, payment plans and framing."}, {"q": "Do you accept submissions?", "a": "Emerging artists are welcome - the review happens quarterly through the submissions page."}, {"q": "Is photography allowed?", "a": "Yes, without flash - and tag the gallery; the artists love seeing it."}],
        "cta_h2": "Come see for yourself.",
        "cta_sub": "Entry is always free. Current shows run through the season — check what's on the walls today.",
        "cta_button": "Plan your visit",
        "cta_note": "Free entry · Open Tue–Sun · Commissions welcome",
    },
}


def _landing_copy(name: str, brief: dict | None) -> dict:
    """Copy profile for the brief's domain: generic base + domain overrides.

    The library holds a full "generic" profile plus per-domain override
    blocks (hero headline, sections copy, testimonial angles, CTA). Deep
    merging keeps this scalable: adding a domain means adding one override
    dict, not rewriting the whole template. Offerings/CTA the user named
    explicitly always win over profile defaults. Unknown domains get the
    generic profile with the user's name injected (never a placeholder).
    """
    brief = brief or {}
    key = domain_profiles.detect_domain(brief)
    base = json.loads(json.dumps(_LANDING_COPY_LIBRARY["generic"]))
    override = _DOMAIN_COPY_OVERRIDES.get(key)
    if override:
        _deep_merge(base, override)

    # User's explicit asks override profile defaults, verbatim.
    offerings = [o for o in (brief.get("offerings") or [])
                 if o and o not in ("solid ui", "ui")][:4]
    if offerings:
        base["user_offerings"] = offerings
    if brief.get("cta"):
        base["user_cta"] = brief["cta"]

    def fmt(value):
        if isinstance(value, str):
            return value.replace("{name}", name)
        if isinstance(value, list):
            return [fmt(v) for v in value]
        if isinstance(value, dict):
            return {k: fmt(v) for k, v in value.items()}
        return value

    return fmt(base)


def _deep_merge(base: dict, override: dict) -> None:
    """Recursive dict merge: override wins; lists replace; None deletes."""
    for k, v in override.items():
        if v is None:
            base.pop(k, None)
        elif isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v


def _landing_consts_js(copy: dict) -> str:
    """Render the App.jsx data consts (FEATURES/TESTIMONIALS/PLANS/FAQS/LOGOS)
    from the copy profile as valid JS. JSON literals are valid JS, except the
    icon identifiers, which are emitted by name."""
    feat_lines = ",\n".join(
        f"  {{ icon: {f['icon']}, title: {json.dumps(f['title'])}, body: {json.dumps(f['body'])} }}"
        for f in copy["features"]
    )
    return (
        f"const FEATURES = [\n{feat_lines},\n];\n\n"
        f"const TESTIMONIALS = {json.dumps(copy['testimonials'], ensure_ascii=False, indent=2)};\n\n"
        f"const FAQS = {json.dumps(copy['faqs'], ensure_ascii=False, indent=2)};\n\n"
        f"const PLANS = {json.dumps(copy['plans'], ensure_ascii=False, indent=2)};\n\n"
        f"const LOGOS = {json.dumps(copy['logos'], ensure_ascii=False)};"
    )


def _get_landing_scaffold(name: str, primary_color: str, brief: dict | None = None) -> list[dict[str, str]]:
    """Marketing landing page: sticky nav, hero, feature grid, pricing,
    testimonials, FAQ, footer. Copy comes from a domain-aware profile (see
    _LANDING_COPY_LIBRARY) so even this fallback ships the user's business,
    not a generic SaaS template."""
    copy = _landing_copy(name, brief)
    consts_js = _landing_consts_js(copy)
    icon_names = sorted({f["icon"] for f in copy["features"]} | {
        "Zap", "Check", "ChevronDown", "ArrowRight", "Star", "Menu", "X", "Quote", "Sparkles",
    })
    icons_js = ", ".join(icon_names)
    return [
        {
            "path": "package.json",
            "content": """{
  "name": "zenith-landing",
  "private": true,
  "version": "1.0.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "lucide-react": "^0.464.0"
  },
  "devDependencies": {
    "@vitejs/plugin-react": "^4.3.4",
    "vite": "^6.0.1"
  }
}"""
        },
        {
            "path": "index.html",
            "content": f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>{name} — {copy['title_suffix']}</title>
    <meta name="description" content="{copy['meta_description']}" />
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap" rel="stylesheet">
    <style>body {{ font-family: 'Inter', sans-serif; }}</style>
  </head>
  <body class="bg-white text-slate-900 antialiased min-h-screen">
    <div id="root"></div>
    <script type="module" src="/src/main.jsx"></script>
  </body>
</html>"""
        },
        {
            "path": "src/main.jsx",
            "content": """import React from 'react';
import ReactDOM from 'react-dom/client';
import './index.css';
import App from './App';

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);"""
        },
        {
            "path": "src/index.css",
            "content": """@layer base { body { background-color: #ffffff; color: #0f172a; } }
@keyframes fade-up { from { opacity: 0; transform: translateY(16px); } to { opacity: 1; transform: translateY(0); } }
.animate-fade-up { animation: fade-up 0.7s ease-out both; }
@keyframes float-slow { 0%, 100% { transform: translateY(0); } 50% { transform: translateY(-10px); } }
.animate-float-slow { animation: float-slow 5s ease-in-out infinite; }
@keyframes marquee { from { transform: translateX(0); } to { transform: translateX(-50%); } }
.animate-marquee { animation: marquee 30s linear infinite; }
"""
        },
        {
            "path": "src/App.jsx",
            "content": f"""import {{ useState }} from 'react';
import {{ {icons_js} }} from 'lucide-react';

{consts_js}

export default function App() {{
  const [menuOpen, setMenuOpen] = useState(false);
  const [openFaq, setOpenFaq] = useState(0);
  const [email, setEmail] = useState('');
  const [sent, setSent] = useState(false);

  return (
    <div className="min-h-screen bg-white">
      {{/* NAV */}}
      <header className="fixed top-0 inset-x-0 z-50 bg-white/80 backdrop-blur-xl border-b border-slate-200/70">
        <div className="max-w-6xl mx-auto px-6 h-16 flex items-center justify-between">
          <a href="#top" className="flex items-center gap-2">
            <span className="w-8 h-8 rounded-xl bg-gradient-to-br from-indigo-600 to-violet-600 flex items-center justify-center">
              <Zap className="w-4 h-4 text-white" />
            </span>
            <span className="font-extrabold text-lg tracking-tight">{{'{name}'}}</span>
          </a>
          <nav className="hidden md:flex items-center gap-8 text-sm font-medium text-slate-600">
            <a href="#features" className="hover:text-slate-900 transition-colors">Features</a>
            <a href="#pricing" className="hover:text-slate-900 transition-colors">Pricing</a>
            <a href="#faq" className="hover:text-slate-900 transition-colors">FAQ</a>
          </nav>
          <div className="hidden md:flex items-center gap-3">
            <a href="#pricing" className="text-sm font-semibold text-slate-700 hover:text-slate-900">Sign in</a>
            <a href="#cta" className="px-4 py-2 rounded-xl bg-slate-900 text-white text-sm font-semibold hover:bg-slate-700 transition-colors">Get started</a>
          </div>
          <button className="md:hidden p-2" onClick={{() => setMenuOpen(!menuOpen)}} aria-label="Menu">
            {{menuOpen ? <X className="w-5 h-5" /> : <Menu className="w-5 h-5" />}}
          </button>
        </div>
        {{menuOpen && (
          <div className="md:hidden border-t border-slate-200 bg-white px-6 py-4 space-y-3">
            {{['Features', 'Pricing', 'FAQ'].map(item => (
              <a key={{item}} href={{`#${{item.toLowerCase()}}`}} onClick={{() => setMenuOpen(false)}} className="block font-medium text-slate-700">{{item}}</a>
            ))}}
            <a href="#cta" className="block text-center px-4 py-2.5 rounded-xl bg-slate-900 text-white font-semibold">Get started</a>
          </div>
        )}}
      </header>

      {{/* HERO */}}
      <section id="top" className="relative pt-36 pb-24 overflow-hidden">
        <div className="absolute inset-0 -z-10" style={{{{ background: 'radial-gradient(60% 50% at 50% 0%, rgba(99,102,241,0.15), transparent 70%)' }}}} />
        <div className="max-w-6xl mx-auto px-6 text-center">
          <div className="animate-fade-up inline-flex items-center gap-2 px-4 py-1.5 rounded-full bg-indigo-50 border border-indigo-100 text-indigo-700 text-xs font-semibold">
            <Sparkles className="w-3.5 h-3.5" /> {copy['badge']}
            <ArrowRight className="w-3 h-3" />
          </div>
          <h1 className="animate-fade-up mt-6 text-5xl md:text-7xl font-black tracking-tight leading-[1.05]" style={{{{'animation-delay': '80ms'}}}}>
            {copy['hero_h1_line1']}<br />
            <span className="bg-gradient-to-r from-indigo-600 via-violet-600 to-fuchsia-500 bg-clip-text text-transparent">{copy['hero_h1_line2']}</span>
          </h1>
          <p className="animate-fade-up mt-6 text-lg md:text-xl text-slate-600 max-w-2xl mx-auto" style={{{{'animation-delay': '160ms'}}}}>
            {copy['hero_sub']}
          </p>
          <div className="animate-fade-up mt-10 flex flex-col sm:flex-row items-center justify-center gap-4" style={{{{'animation-delay': '240ms'}}}}>
            <a href="#cta" className="w-full sm:w-auto px-8 py-4 rounded-2xl bg-slate-900 text-white font-bold hover:bg-slate-700 transition-all shadow-xl shadow-slate-900/10">
              {copy['hero_primary_cta']}
            </a>
            <a href="#features" className="w-full sm:w-auto px-8 py-4 rounded-2xl border border-slate-300 font-bold text-slate-700 hover:border-slate-400 transition-colors">
              {copy['hero_secondary_cta']}
            </a>
          </div>
          <div className="mt-14 flex items-center justify-center gap-2 text-sm text-slate-500">
            <div className="flex -space-x-2">
              {{['MC', 'DO', 'SM'].map(i => (
                <div key={{i}} className="w-8 h-8 rounded-full bg-gradient-to-br from-indigo-500 to-violet-500 border-2 border-white flex items-center justify-center text-[10px] font-bold text-white">{{i}}</div>
              ))}}
            </div>
            <span>{copy['proof_prefix']} <strong className="text-slate-700">{copy['proof_number']}</strong> {copy['proof_suffix']}</span>
            <span className="flex items-center gap-0.5 ml-2">
              {{[...Array(5)].map((_, i) => <Star key={{i}} className="w-4 h-4 fill-amber-400 text-amber-400" />)}}
            </span>
          </div>
        </div>
      </section>

      {{/* LOGO MARQUEE */}}
      <section className="py-10 border-y border-slate-100 overflow-hidden">
        <div className="flex whitespace-nowrap animate-marquee gap-16 px-8">
          {{[...LOGOS, ...LOGOS].map((logo, i) => (
            <span key={{i}} className="text-xl font-bold text-slate-300 tracking-tight">{{logo}}</span>
          ))}}
        </div>
      </section>

      {{/* FEATURES */}}
      <section id="features" className="py-28">
        <div className="max-w-6xl mx-auto px-6">
          <div className="text-center max-w-2xl mx-auto">
            <p className="text-sm font-bold uppercase tracking-widest text-indigo-600">{copy['features_eyebrow']}</p>
            <h2 className="mt-3 text-4xl md:text-5xl font-black tracking-tight">{copy['features_h2']}</h2>
            <p className="mt-4 text-lg text-slate-600">{copy['features_sub']}</p>
          </div>
          <div className="mt-16 grid md:grid-cols-2 gap-6">
            {{FEATURES.map((f, i) => (
              <div key={{i}} className="group p-8 rounded-3xl border border-slate-200 hover:border-indigo-200 hover:shadow-xl hover:shadow-indigo-100/60 transition-all">
                <div className="w-12 h-12 rounded-2xl bg-gradient-to-br from-indigo-600 to-violet-600 flex items-center justify-center group-hover:scale-110 transition-transform">
                  <f.icon className="w-6 h-6 text-white" />
                </div>
                <h3 className="mt-6 text-xl font-bold">{{f.title}}</h3>
                <p className="mt-2 text-slate-600 leading-relaxed">{{f.body}}</p>
              </div>
            ))}}
          </div>
        </div>
      </section>

      {{/* TESTIMONIALS */}}
      <section className="py-28 bg-slate-950 text-white">
        <div className="max-w-6xl mx-auto px-6">
          <div className="text-center max-w-2xl mx-auto">
            <p className="text-sm font-bold uppercase tracking-widest text-violet-400">{copy['testimonials_eyebrow']}</p>
            <h2 className="mt-3 text-4xl md:text-5xl font-black tracking-tight">Don't take our word for it.</h2>
          </div>
          <div className="mt-16 grid md:grid-cols-3 gap-6">
            {{TESTIMONIALS.map((t, i) => (
              <figure key={{i}} className="p-8 rounded-3xl bg-white/5 border border-white/10 hover:border-violet-500/40 transition-colors">
                <Quote className="w-6 h-6 text-violet-400" />
                <blockquote className="mt-4 text-slate-200 leading-relaxed">{{t.quote}}</blockquote>
                <figcaption className="mt-6 flex items-center gap-3">
                  <div className="w-10 h-10 rounded-full bg-gradient-to-br from-violet-500 to-fuchsia-500 flex items-center justify-center text-xs font-bold">{{t.initials}}</div>
                  <div>
                    <div className="font-semibold text-sm">{{t.name}}</div>
                    <div className="text-xs text-slate-400">{{t.role}}</div>
                  </div>
                </figcaption>
              </figure>
            ))}}
          </div>
        </div>
      </section>

      {{/* PRICING */}}
      <section id="pricing" className="py-28">
        <div className="max-w-6xl mx-auto px-6">
          <div className="text-center max-w-2xl mx-auto">
            <p className="text-sm font-bold uppercase tracking-widest text-indigo-600">{copy['pricing_eyebrow']}</p>
            <h2 className="mt-3 text-4xl md:text-5xl font-black tracking-tight">{copy['pricing_h2']}</h2>
            <p className="mt-4 text-lg text-slate-600">{copy['pricing_sub']}</p>
          </div>
          <div className="mt-16 grid md:grid-cols-3 gap-6 items-start">
            {{PLANS.map((plan, i) => (
              <div key={{i}} className={{`relative p-8 rounded-3xl border transition-all ${{plan.highlighted
                ? 'bg-slate-950 text-white border-slate-900 shadow-2xl md:-translate-y-3'
                : 'bg-white border-slate-200 hover:border-slate-300'}}`}}>
                {{plan.highlighted && (
                  <div className="absolute -top-3 left-1/2 -translate-x-1/2 px-3 py-1 rounded-full bg-gradient-to-r from-indigo-600 to-violet-600 text-white text-[11px] font-bold tracking-wide">MOST POPULAR</div>
                )}}
                <h3 className="text-lg font-bold">{{plan.name}}</h3>
                <p className={{`text-sm mt-1 ${{plan.highlighted ? 'text-slate-400' : 'text-slate-500'}}`}}>{{plan.tagline}}</p>
                <div className="mt-6 flex items-baseline gap-1">
                  {{plan.price === null
                    ? <span className="text-4xl font-black">Custom</span>
                    : <><span className="text-4xl font-black">${{plan.price}}</span><span className="text-slate-500 font-medium">{{plan.unit}}</span></>}}
                </div>
                <ul className="mt-8 space-y-3">
                  {{plan.features.map((feat, j) => (
                    <li key={{j}} className="flex items-start gap-3 text-sm">
                      <Check className={{`w-4 h-4 mt-0.5 flex-shrink-0 ${{plan.highlighted ? 'text-violet-400' : 'text-emerald-500'}}`}} />
                      <span className={{plan.highlighted ? 'text-slate-300' : 'text-slate-600'}}>{{feat}}</span>
                    </li>
                  ))}}
                </ul>
                <a href="#cta" className={{`mt-8 block text-center px-6 py-3.5 rounded-2xl font-bold transition-all ${{plan.highlighted
                  ? 'bg-white text-slate-900 hover:bg-slate-200'
                  : 'bg-slate-900 text-white hover:bg-slate-700'}}`}}>
                  {{plan.cta}}
                </a>
              </div>
            ))}}
          </div>
        </div>
      </section>

      {{/* FAQ */}}
      <section id="faq" className="py-28 bg-slate-50">
        <div className="max-w-3xl mx-auto px-6">
          <div className="text-center">
            <p className="text-sm font-bold uppercase tracking-widest text-indigo-600">FAQ</p>
            <h2 className="mt-3 text-4xl md:text-5xl font-black tracking-tight">Questions, answered.</h2>
          </div>
          <div className="mt-12 space-y-4">
            {{FAQS.map((faq, i) => (
              <div key={{i}} className="bg-white rounded-2xl border border-slate-200 overflow-hidden">
                <button onClick={{() => setOpenFaq(openFaq === i ? -1 : i)}} className="w-full flex items-center justify-between px-6 py-5 text-left font-semibold">
                  {{faq.q}}
                  <ChevronDown className={{`w-5 h-5 text-slate-400 transition-transform ${{openFaq === i ? 'rotate-180' : ''}}`}} />
                </button>
                {{openFaq === i && (
                  <div className="px-6 pb-6 text-slate-600 leading-relaxed">{{faq.a}}</div>
                )}}
              </div>
            ))}}
          </div>
        </div>
      </section>

      {{/* CTA */}}
      <section id="cta" className="py-28">
        <div className="max-w-4xl mx-auto px-6">
          <div className="relative overflow-hidden rounded-[2.5rem] bg-gradient-to-br from-indigo-600 via-violet-600 to-fuchsia-600 px-8 py-16 md:px-16 text-center text-white">
            <div className="absolute -top-24 -right-24 w-72 h-72 rounded-full bg-white/10 blur-2xl animate-float-slow" />
            <h2 className="text-3xl md:text-5xl font-black tracking-tight">{copy['cta_h2']}</h2>
            <p className="mt-4 text-lg text-indigo-100 max-w-xl mx-auto">{copy['cta_sub']}</p>
            {{sent ? (
              <div className="mt-10 inline-flex items-center gap-2 px-6 py-4 rounded-2xl bg-white/15 font-semibold">
                <Check className="w-5 h-5" /> You're on the list — check your inbox!
              </div>
            ) : (
              <form onSubmit={{e => {{ e.preventDefault(); if (email.includes('@')) setSent(true); }}}} className="mt-10 flex flex-col sm:flex-row gap-3 max-w-md mx-auto">
                <input
                  type="email" required value={{email}} onChange={{e => setEmail(e.target.value)}}
                  placeholder="you@company.com"
                  className="flex-1 px-5 py-4 rounded-2xl bg-white/15 backdrop-blur border border-white/30 placeholder-indigo-200 text-white focus:outline-none focus:ring-2 focus:ring-white/60"
                />
                <button type="submit" className="px-8 py-4 rounded-2xl bg-white text-indigo-700 font-bold hover:bg-indigo-50 transition-colors">
                  {copy['cta_button']}
                </button>
              </form>
            )}}
            <p className="mt-6 text-xs text-indigo-200">{copy['cta_note']}</p>
          </div>
        </div>
      </section>

      {{/* FOOTER */}}
      <footer className="border-t border-slate-200 py-12">
        <div className="max-w-6xl mx-auto px-6 flex flex-col md:flex-row items-center justify-between gap-6">
          <div className="flex items-center gap-2">
            <span className="w-7 h-7 rounded-lg bg-gradient-to-br from-indigo-600 to-violet-600 flex items-center justify-center">
              <Zap className="w-3.5 h-3.5 text-white" />
            </span>
            <span className="font-bold">{{'{name}'}}</span>
          </div>
          <div className="flex items-center gap-8 text-sm text-slate-500">
            <a href="#features" className="hover:text-slate-900">Features</a>
            <a href="#pricing" className="hover:text-slate-900">Pricing</a>
            <a href="#faq" className="hover:text-slate-900">FAQ</a>
          </div>
          <p className="text-xs text-slate-400">© 2026 {{'{name}'}}. All rights reserved.</p>
        </div>
      </footer>
    </div>
  );
}}"""
        },
    ]


def _get_ecommerce_scaffold(name: str, primary_color: str) -> list[dict[str, str]]:
    return [
        {
            "path": "package.json",
            "content": """{
  "name": "zenith-ecommerce",
  "private": true,
  "version": "1.0.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "lucide-react": "^0.464.0"
  },
  "devDependencies": {
    "@vitejs/plugin-react": "^4.3.4",
    "vite": "^6.0.1"
  }
}"""
        },
        {
            "path": "index.html",
            "content": f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>{name} — Modern Storefront</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <style>
      body {{ font-family: 'Plus Jakarta Sans', sans-serif; }}
    </style>
  </head>
  <body class="bg-slate-950 text-slate-100 antialiased min-h-screen">
    <div id="root"></div>
    <script type="module" src="/src/main.jsx"></script>
  </body>
</html>"""
        },
        {
            "path": "src/main.jsx",
            "content": """import React from 'react';
import ReactDOM from 'react-dom/client';
import './index.css';
import App from './App';

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);"""
        },
        {
            "path": "src/index.css",
            "content": """/* Tailwind handles all utility styling via CDN */
@layer base {
  body {
    background-color: #030712;
    color: #f8fafc;
  }
}"""
        },
        {
            "path": "src/components/Navbar.jsx",
            "content": f"""import React from 'react';
import {{ ShoppingBag, Search, Sparkles, Heart, Menu, X, SlidersHorizontal }} from 'lucide-react';

export default function Navbar({{
  cartCount,
  onOpenCart,
  searchTerm,
  onSearchChange,
  activeCategory,
  onCategoryChange,
  categories
}}) {{
  return (
    <header className="sticky top-0 z-40 backdrop-blur-xl bg-slate-950/80 border-b border-white/10">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-16 gap-4">
          
          {{/* Brand Logo */}}
          <div className="flex items-center gap-3 cursor-pointer">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-tr from-violet-600 via-fuchsia-600 to-cyan-500 p-0.5 flex items-center justify-center shadow-lg shadow-violet-500/20">
              <div className="w-full h-full bg-slate-950 rounded-[10px] flex items-center justify-center">
                <Sparkles className="w-5 h-5 text-violet-400" />
              </div>
            </div>
            <div>
              <span className="text-xl font-extrabold tracking-tight bg-gradient-to-r from-white via-slate-100 to-slate-400 bg-clip-text text-transparent">
                {name}
              </span>
              <span className="hidden sm:inline-block text-[10px] text-violet-400 font-semibold uppercase tracking-wider ml-2 px-2 py-0.5 rounded-full bg-violet-500/10 border border-violet-500/20">
                Premium Store
              </span>
            </div>
          </div>

          {{/* Search Bar */}}
          <div className="flex-1 max-w-md relative hidden md:block">
            <Search className="w-4 h-4 text-slate-400 absolute left-3.5 top-1/2 -translate-y-1/2 pointer-events-none" />
            <input
              type="text"
              placeholder="Search premium products, gear, accessories..."
              value={{searchTerm}}
              onChange={{(e) => onSearchChange(e.target.value)}}
              className="w-full bg-white/5 border border-white/10 rounded-xl py-2 pl-10 pr-4 text-sm text-slate-100 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-violet-500/50 focus:border-violet-500 transition-all"
            />
          </div>

          {{/* Right Actions */}}
          <div className="flex items-center gap-3">
            <button
              onClick={{onOpenCart}}
              className="relative flex items-center gap-2 px-4 py-2 bg-gradient-to-r from-violet-600 to-cyan-600 hover:from-violet-500 hover:to-cyan-500 rounded-xl text-sm font-semibold text-white shadow-lg shadow-violet-500/20 transition-all hover:scale-[1.02] active:scale-[0.98]"
            >
              <ShoppingBag className="w-4 h-4" />
              <span>Cart</span>
              {{cartCount > 0 && (
                <span className="w-5 h-5 rounded-full bg-white text-slate-950 text-xs font-bold flex items-center justify-center ml-1">
                  {{cartCount}}
                </span>
              )}}
            </button>
          </div>
        </div>

        {{/* Category Nav Pills */}}
        <div className="flex items-center gap-2 py-3 overflow-x-auto no-scrollbar border-t border-white/5">
          {{categories.map((cat) => (
            <button
              key={{cat}}
              onClick={{() => onCategoryChange(cat)}}
              className={{`px-4 py-1.5 rounded-lg text-xs font-semibold whitespace-nowrap transition-all ${{
                activeCategory === cat
                  ? 'bg-violet-600 text-white shadow-md shadow-violet-600/30'
                  : 'bg-white/5 text-slate-400 hover:bg-white/10 hover:text-slate-200'
              }}`}}
            >
              {{cat}}
            </button>
          ))}}
        </div>
      </div>
    </header>
  );
}}"""
        },
        {
            "path": "src/components/ProductCard.jsx",
            "content": """import React from 'react';
import { ShoppingBag, Star, Heart, Check } from 'lucide-react';

export default function ProductCard({ product, onAddToCart, isAdded }) {
  return (
    <div className="group backdrop-blur-xl bg-white/[0.03] border border-white/10 hover:border-violet-500/40 rounded-2xl p-4 transition-all duration-300 hover:scale-[1.02] hover:shadow-2xl hover:shadow-violet-500/10 flex flex-col justify-between">
      
      {/* Image Container */}
      <div className="relative aspect-square rounded-xl overflow-hidden bg-slate-900 mb-4">
        <img
          src={product.image}
          alt={product.name}
          className="w-full h-full object-cover object-center group-hover:scale-105 transition-transform duration-500"
        />
        {product.badge && (
          <span className="absolute top-2.5 left-2.5 px-2.5 py-1 rounded-lg text-[10px] font-extrabold uppercase tracking-wider bg-violet-600/90 backdrop-blur-md text-white shadow-md">
            {product.badge}
          </span>
        )}
        <div className="absolute top-2.5 right-2.5 flex flex-col gap-1.5">
          <button className="p-2 rounded-lg bg-slate-950/70 backdrop-blur-md text-slate-300 hover:text-rose-400 transition-colors">
            <Heart className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Info */}
      <div className="flex-1 flex flex-col justify-between">
        <div>
          <div className="flex items-center justify-between gap-2 mb-1">
            <span className="text-[11px] font-semibold text-violet-400 uppercase tracking-wider">
              {product.category}
            </span>
            <div className="flex items-center gap-1 text-xs text-amber-400">
              <Star className="w-3.5 h-3.5 fill-amber-400" />
              <span>{product.rating}</span>
            </div>
          </div>
          <h3 className="font-bold text-base text-slate-100 group-hover:text-violet-300 transition-colors line-clamp-1 mb-1">
            {product.name}
          </h3>
          <p className="text-xs text-slate-400 line-clamp-2 mb-3">
            {product.description}
          </p>
        </div>

        {/* Price & Action */}
        <div className="flex items-center justify-between pt-3 border-t border-white/5">
          <div>
            <span className="text-[10px] text-slate-500 uppercase block">Price</span>
            <span className="text-lg font-extrabold text-white">${product.price.toFixed(2)}</span>
          </div>
          <button
            onClick={() => onAddToCart(product)}
            className={`flex items-center gap-1.5 px-3.5 py-2 rounded-xl text-xs font-bold transition-all ${
              isAdded
                ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30'
                : 'bg-white/10 hover:bg-violet-600 text-slate-200 hover:text-white'
            }`}
          >
            {isAdded ? (
              <>
                <Check className="w-3.5 h-3.5" /> Added
              </>
            ) : (
              <>
                <ShoppingBag className="w-3.5 h-3.5" /> Add to Cart
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}"""
        },
        {
            "path": "src/components/CartModal.jsx",
            "content": """import React from 'react';
import { X, Trash2, Plus, Minus, ArrowRight, ShieldCheck, ShoppingBag } from 'lucide-react';

export default function CartModal({
  isOpen,
  onClose,
  cartItems,
  onUpdateQuantity,
  onRemoveItem,
  onCheckout
}) {
  if (!isOpen) return null;

  const subtotal = cartItems.reduce((acc, item) => acc + item.price * item.quantity, 0);
  const shipping = subtotal > 150 || subtotal === 0 ? 0 : 15;
  const total = subtotal + shipping;

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/70 backdrop-blur-sm animate-fade-in">
      <div className="w-full max-w-md bg-slate-900 border-l border-white/10 h-full flex flex-col p-6 shadow-2xl overflow-hidden">
        
        {/* Header */}
        <div className="flex items-center justify-between pb-4 border-b border-white/10">
          <div className="flex items-center gap-2">
            <ShoppingBag className="w-5 h-5 text-violet-400" />
            <h2 className="text-lg font-bold text-white">Your Shopping Cart</h2>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-white/10 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Item List */}
        <div className="flex-1 overflow-y-auto py-4 space-y-4">
          {cartItems.length === 0 ? (
            <div className="h-full flex flex-col items-center justify-center text-center p-6 text-slate-500">
              <ShoppingBag className="w-12 h-12 mb-3 text-slate-600" />
              <p className="font-semibold text-slate-300 mb-1">Your cart is empty</p>
              <p className="text-xs">Explore the collection and add products to start shopping.</p>
            </div>
          ) : (
            cartItems.map((item) => (
              <div
                key={item.id}
                className="flex items-center gap-3 p-3 bg-white/[0.02] border border-white/5 rounded-xl"
              >
                <img
                  src={item.image}
                  alt={item.name}
                  className="w-16 h-16 rounded-lg object-cover bg-slate-800 flex-shrink-0"
                />
                <div className="flex-1 min-w-0">
                  <h4 className="text-sm font-semibold text-slate-100 truncate">{item.name}</h4>
                  <p className="text-xs text-violet-400 font-bold mt-0.5">${item.price.toFixed(2)}</p>
                  
                  <div className="flex items-center gap-2 mt-2">
                    <button
                      onClick={() => onUpdateQuantity(item.id, item.quantity - 1)}
                      className="w-6 h-6 rounded bg-white/5 hover:bg-white/10 flex items-center justify-center text-slate-300"
                    >
                      <Minus className="w-3 h-3" />
                    </button>
                    <span className="text-xs font-bold text-white w-5 text-center">{item.quantity}</span>
                    <button
                      onClick={() => onUpdateQuantity(item.id, item.quantity + 1)}
                      className="w-6 h-6 rounded bg-white/5 hover:bg-white/10 flex items-center justify-center text-slate-300"
                    >
                      <Plus className="w-3 h-3" />
                    </button>
                  </div>
                </div>
                <button
                  onClick={() => onRemoveItem(item.id)}
                  className="p-2 text-slate-500 hover:text-rose-400 transition-colors"
                >
                  <Trash2 className="w-4 h-4" />
                </button>
              </div>
            ))
          )}
        </div>

        {/* Footer / Summary */}
        {cartItems.length > 0 && (
          <div className="pt-4 border-t border-white/10 space-y-3">
            <div className="space-y-1.5 text-xs text-slate-400">
              <div className="flex justify-between">
                <span>Subtotal</span>
                <span className="text-slate-200 font-semibold">${subtotal.toFixed(2)}</span>
              </div>
              <div className="flex justify-between">
                <span>Shipping</span>
                <span className="text-slate-200 font-semibold">
                  {shipping === 0 ? <span className="text-emerald-400">Free</span> : `$${shipping.toFixed(2)}`}
                </span>
              </div>
              <div className="flex justify-between text-base font-bold text-white pt-2 border-t border-white/5">
                <span>Total</span>
                <span className="text-violet-400">${total.toFixed(2)}</span>
              </div>
            </div>

            <button
              onClick={onCheckout}
              className="w-full py-3.5 bg-gradient-to-r from-violet-600 via-fuchsia-600 to-cyan-600 hover:from-violet-500 hover:to-cyan-500 rounded-xl font-bold text-sm text-white shadow-xl shadow-violet-500/25 flex items-center justify-center gap-2 transition-all hover:scale-[1.01]"
            >
              <span>Proceed to Checkout</span>
              <ArrowRight className="w-4 h-4" />
            </button>

            <div className="flex items-center justify-center gap-1.5 text-[10px] text-slate-500">
              <ShieldCheck className="w-3.5 h-3.5 text-emerald-400" />
              <span>Guaranteed safe & secure checkout</span>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}"""
        },
        {
            "path": "src/App.jsx",
            "content": f"""import React, {{ useState, useMemo }} from 'react';
import Navbar from './components/Navbar';
import ProductCard from './components/ProductCard';
import CartModal from './components/CartModal';
import {{
  Sparkles,
  TrendingUp,
  ShieldCheck,
  Truck,
  RotateCcw,
  CheckCircle2,
  Package,
  Layers,
  BarChart3
}} from 'lucide-react';

const INITIAL_PRODUCTS = [
  {{
    id: 1,
    name: 'Zenith Quantum Headphones',
    category: 'Audio',
    price: 299.99,
    rating: 4.9,
    badge: 'Best Seller',
    description: 'Active noise-canceling with 40-hour spatial audio playback and titanium acoustic drivers.',
    image: 'https://images.unsplash.com/photo-1505740420928-5e560c06d30e?w=800&q=80'
  }},
  {{
    id: 2,
    name: 'Aura Minimalist Mechanical Keyboard',
    category: 'Keyboards',
    price: 189.00,
    rating: 4.8,
    badge: 'New Arrival',
    description: 'Hot-swappable tactile switches, gasket-mounted aluminum body with per-key RGB backlighting.',
    image: 'https://images.unsplash.com/photo-1587829741301-dc798b83add3?w=800&q=80'
  }},
  {{
    id: 3,
    name: 'Titan Smart Ergonomic Mouse',
    category: 'Accessories',
    price: 119.50,
    rating: 4.7,
    badge: 'Popular',
    description: 'Precision 8K sensor, dual-mode Bluetooth + 2.4GHz wireless with hyper-fast scroll wheel.',
    image: 'https://images.unsplash.com/photo-1527864550417-7fd91fc51a46?w=800&q=80'
  }},
  {{
    id: 4,
    name: 'Nebula 4K UltraWide Studio Display',
    category: 'Displays',
    price: 749.00,
    rating: 5.0,
    badge: 'Staff Pick',
    description: '144Hz refresh rate, 99% DCI-P3 color gamut with 90W USB-C single-cable power delivery.',
    image: 'https://images.unsplash.com/photo-1527443224154-c4a3942d3acf?w=800&q=80'
  }},
  {{
    id: 5,
    name: 'Carbon Fiber MagSafe Stand',
    category: 'Accessories',
    price: 64.99,
    rating: 4.6,
    badge: '',
    description: 'Aerospace-grade carbon weave with dual adjustable pivot angles and 15W Qi2 wireless charging.',
    image: 'https://images.unsplash.com/photo-1586105251261-72a756497a11?w=800&q=80'
  }},
  {{
    id: 6,
    name: 'Zenith Studio Desk Mat Pro',
    category: 'Accessories',
    price: 49.00,
    rating: 4.9,
    badge: 'Essentials',
    description: 'Micro-weave water-resistant surface with non-slip natural rubber base and anti-fray stitching.',
    image: 'https://images.unsplash.com/photo-1616440347437-b1c73416efc2?w=800&q=80'
  }}
];

const CATEGORIES = ['All Products', 'Audio', 'Keyboards', 'Displays', 'Accessories'];

export default function App() {{
  const [products] = useState(INITIAL_PRODUCTS);
  const [searchTerm, setSearchTerm] = useState('');
  const [activeCategory, setActiveCategory] = useState('All Products');
  const [cart, setCart] = useState([]);
  const [isCartOpen, setIsCartOpen] = useState(false);
  const [toastMessage, setToastMessage] = useState(null);
  const [addedItemIds, setAddedItemIds] = useState(new Set());
  const [viewMode, setViewMode] = useState('store'); // 'store' | 'admin'

  const showToast = (msg) => {{
    setToastMessage(msg);
    setTimeout(() => setToastMessage(null), 3000);
  }};

  const handleAddToCart = (product) => {{
    setCart((prev) => {{
      const existing = prev.find((item) => item.id === product.id);
      if (existing) {{
        return prev.map((item) =>
          item.id === product.id ? {{ ...item, quantity: item.quantity + 1 }} : item
        );
      }}
      return [...prev, {{ ...product, quantity: 1 }}];
    }});
    
    setAddedItemIds((prev) => new Set([...prev, product.id]));
    setTimeout(() => {{
      setAddedItemIds((prev) => {{
        const next = new Set(prev);
        next.delete(product.id);
        return next;
      }});
    }}, 1500);

    showToast(`Added ${{product.name}} to cart!`);
  }};

  const handleUpdateQuantity = (id, newQty) => {{
    if (newQty <= 0) {{
      handleRemoveItem(id);
      return;
    }}
    setCart((prev) =>
      prev.map((item) => (item.id === id ? {{ ...item, quantity: newQty }} : item))
    );
  }};

  const handleRemoveItem = (id) => {{
    setCart((prev) => prev.filter((item) => item.id !== id));
  }};

  const handleCheckout = () => {{
    alert('Thank you for your order! Your simulated checkout is complete.');
    setCart([]);
    setIsCartOpen(false);
    showToast('Order confirmed successfully!');
  }};

  const filteredProducts = useMemo(() => {{
    return products.filter((p) => {{
      const matchesCategory =
        activeCategory === 'All Products' || p.category === activeCategory;
      const matchesSearch =
        p.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
        p.description.toLowerCase().includes(searchTerm.toLowerCase());
      return matchesCategory && matchesSearch;
    }});
  }}, [products, activeCategory, searchTerm]);

  const totalCartQuantity = cart.reduce((acc, item) => acc + item.quantity, 0);

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col relative overflow-x-hidden selection:bg-violet-500/30 selection:text-violet-200">
      
      {{/* Ambient Light Glows */}}
      <div className="absolute top-0 left-1/4 w-96 h-96 bg-violet-600/15 rounded-full blur-[140px] pointer-events-none" />
      <div className="absolute top-1/3 right-10 w-96 h-96 bg-cyan-500/10 rounded-full blur-[140px] pointer-events-none" />

      {{/* Toast Notification */}}
      {{toastMessage && (
        <div className="fixed bottom-6 right-6 z-50 animate-bounce">
          <div className="flex items-center gap-2 bg-slate-900/95 border border-emerald-500/40 text-emerald-300 px-4 py-3 rounded-xl shadow-2xl backdrop-blur-xl text-sm font-semibold">
            <CheckCircle2 className="w-4 h-4 text-emerald-400" />
            <span>{{toastMessage}}</span>
          </div>
        </div>
      )}}

      {{/* Navigation */}}
      <Navbar
        cartCount={{totalCartQuantity}}
        onOpenCart={{() => setIsCartOpen(true)}}
        searchTerm={{searchTerm}}
        onSearchChange={{setSearchTerm}}
        activeCategory={{activeCategory}}
        onCategoryChange={{setActiveCategory}}
        categories={{CATEGORIES}}
      />

      {{/* Hero Banner */}}
      <section className="relative py-12 md:py-16 px-4 sm:px-6 lg:px-8 max-w-7xl mx-auto w-full">
        <div className="backdrop-blur-2xl bg-gradient-to-r from-violet-900/20 via-slate-900/40 to-cyan-900/20 border border-white/10 rounded-3xl p-8 md:p-12 relative overflow-hidden shadow-2xl">
          <div className="max-w-2xl relative z-10">
            <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-violet-500/10 border border-violet-500/30 text-violet-300 text-xs font-semibold mb-4">
              <Sparkles className="w-3.5 h-3.5" /> Next-Gen Workspace Gear
            </div>
            <h1 className="text-3xl md:text-5xl font-extrabold tracking-tight text-white mb-4 leading-tight">
              Elevate Your Desk Setup with <span className="bg-gradient-to-r from-violet-400 via-fuchsia-400 to-cyan-400 bg-clip-text text-transparent">{name}</span>
            </h1>
            <p className="text-slate-300 text-sm md:text-base leading-relaxed mb-6">
              Precision-engineered hardware and studio accessories designed for modern creators, developers, and power users.
            </p>
            <div className="flex flex-wrap items-center gap-4">
              <button
                onClick={{() => setActiveCategory('All Products')}}
                className="px-6 py-3 bg-gradient-to-r from-violet-600 via-fuchsia-600 to-cyan-600 rounded-xl font-bold text-sm text-white shadow-xl shadow-violet-500/25 hover:scale-[1.02] transition-all"
              >
                Shop Collection
              </button>
              <div className="flex items-center gap-6 text-xs text-slate-400 pl-2">
                <span className="flex items-center gap-1.5"><Truck className="w-4 h-4 text-cyan-400" /> Free Global Delivery</span>
                <span className="flex items-center gap-1.5"><RotateCcw className="w-4 h-4 text-violet-400" /> 30-Day Guarantee</span>
              </div>
            </div>
          </div>
        </div>
      </section>

      {{/* Main Products Grid */}}
      <main className="flex-1 max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 w-full pb-16">
        <div className="flex items-center justify-between mb-6">
          <div>
            <h2 className="text-xl font-bold text-white tracking-tight">
              {{activeCategory}}
            </h2>
            <p className="text-xs text-slate-400 mt-0.5">
              Showing {{filteredProducts.length}} premium products
            </p>
          </div>
        </div>

        {{filteredProducts.length === 0 ? (
          <div className="text-center py-16 bg-white/[0.02] border border-white/5 rounded-2xl p-8">
            <Package className="w-12 h-12 mx-auto mb-3 text-slate-600" />
            <h3 className="text-base font-bold text-slate-200 mb-1">No products found</h3>
            <p className="text-xs text-slate-400">Try adjusting your search query or filter category.</p>
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">
            {{filteredProducts.map((product) => (
              <ProductCard
                key={{product.id}}
                product={{product}}
                onAddToCart={{handleAddToCart}}
                isAdded={{addedItemIds.has(product.id)}}
              />
            ))}}
          </div>
        )}}
      </main>

      {{/* Cart Modal */}}
      <CartModal
        isOpen={{isCartOpen}}
        onClose={{() => setIsCartOpen(false)}}
        cartItems={{cart}}
        onUpdateQuantity={{handleUpdateQuantity}}
        onRemoveItem={{handleRemoveItem}}
        onCheckout={{handleCheckout}}
      />

      {{/* Footer */}}
      <footer className="border-t border-white/10 bg-slate-950/80 py-8 px-4 sm:px-6 lg:px-8 text-center text-xs text-slate-500">
        <div className="max-w-7xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-4">
          <p>© 2026 {name} Technologies Inc. All rights reserved.</p>
          <div className="flex items-center gap-4">
            <span className="hover:text-slate-300 cursor-pointer">Privacy Policy</span>
            <span className="hover:text-slate-300 cursor-pointer">Terms of Service</span>
            <span className="hover:text-slate-300 cursor-pointer">Support</span>
          </div>
        </div>
      </footer>
    </div>
  );
}}"""
        }
    ]


def _get_crm_scaffold(name: str, primary_color: str) -> list[dict[str, str]]:
    # We can provide a comprehensive CRM scaffold as well
    return [
        {
            "path": "package.json",
            "content": """{
  "name": "zenith-crm",
  "private": true,
  "version": "1.0.0",
  "type": "module",
  "dependencies": {
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "lucide-react": "^0.464.0"
  },
  "devDependencies": {
    "@vitejs/plugin-react": "^4.3.4",
    "vite": "^6.0.1"
  }
}"""
        },
        {
            "path": "index.html",
            "content": f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>{name} — CRM & Lead Engine</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <style>body {{ font-family: 'Plus Jakarta Sans', sans-serif; }}</style>
  </head>
  <body class="bg-slate-950 text-slate-100 antialiased min-h-screen">
    <div id="root"></div>
    <script type="module" src="/src/main.jsx"></script>
  </body>
</html>"""
        },
        {
            "path": "src/main.jsx",
            "content": """import React from 'react';
import ReactDOM from 'react-dom/client';
import './index.css';
import App from './App';

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);"""
        },
        {
            "path": "src/index.css",
            "content": "@layer base { body { background-color: #030712; color: #f8fafc; } }"
        },
        {
            "path": "src/App.jsx",
            "content": f"""import React, {{ useState, useMemo }} from 'react';
import {{
  Users, DollarSign, TrendingUp, Target, Search, Plus, Filter,
  Phone, Mail, CheckCircle2, ChevronRight, Sparkles, X, Award, Clock
}} from 'lucide-react';

const INITIAL_LEADS = [
  {{ id: 1, name: 'Sarah Connor', company: 'Cyberdyne Systems', email: 's.connor@cyberdyne.com', phone: '+1 (555) 019-2834', value: 48000, status: 'Proposal', source: 'Inbound' }},
  {{ id: 2, name: 'Bruce Wayne', company: 'Wayne Enterprises', email: 'bruce@waynecorp.com', phone: '+1 (555) 012-9842', value: 125000, status: 'Won', source: 'Referral' }},
  {{ id: 3, name: 'Tony Stark', company: 'Stark Industries', email: 'tony@stark.com', phone: '+1 (555) 014-4921', value: 95000, status: 'Contacted', source: 'Webinar' }},
  {{ id: 4, name: 'Selina Kyle', company: 'Gotham Jewels Co.', email: 'selina@kyle.net', phone: '+1 (555) 017-8833', value: 18500, status: 'New', source: 'Outreach' }},
  {{ id: 5, name: 'Diana Prince', company: 'Themyscira Antiques', email: 'diana@museum.org', phone: '+1 (555) 011-3000', value: 62000, status: 'Proposal', source: 'Partner' }}
];

export default function App() {{
  const [leads, setLeads] = useState(INITIAL_LEADS);
  const [searchTerm, setSearchTerm] = useState('');
  const [statusFilter, setStatusFilter] = useState('All');
  const [isAddOpen, setIsAddOpen] = useState(false);
  const [newLead, setNewLead] = useState({{ name: '', company: '', email: '', value: '', status: 'New', source: 'Inbound' }});
  const [toast, setToast] = useState(null);

  const showToast = (msg) => {{
    setToast(msg);
    setTimeout(() => setToast(null), 3000);
  }};

  const totalPipeline = useMemo(() => {{
    return leads.reduce((acc, lead) => acc + (lead.status !== 'Lost' ? lead.value : 0), 0);
  }}, [leads]);

  const filteredLeads = useMemo(() => {{
    return leads.filter((l) => {{
      const matchSearch = l.name.toLowerCase().includes(searchTerm.toLowerCase()) || l.company.toLowerCase().includes(searchTerm.toLowerCase());
      const matchStatus = statusFilter === 'All' || l.status === statusFilter;
      return matchSearch && matchStatus;
    }});
  }}, [leads, searchTerm, statusFilter]);

  const handleAddLead = (e) => {{
    e.preventDefault();
    if (!newLead.name || !newLead.company) return;
    const lead = {{
      id: Date.now(),
      name: newLead.name,
      company: newLead.company,
      email: newLead.email || 'contact@company.com',
      phone: '+1 (555) 000-0000',
      value: parseFloat(newLead.value) || 10000,
      status: newLead.status,
      source: newLead.source
    }};
    setLeads([lead, ...leads]);
    setIsAddOpen(false);
    setNewLead({{ name: '', company: '', email: '', value: '', status: 'New', source: 'Inbound' }});
    showToast(`Lead for ${{lead.name}} added!`);
  }};

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 p-6 md:p-10 font-sans selection:bg-indigo-500/30">
      {{toast && (
        <div className="fixed bottom-6 right-6 z-50">
          <div className="bg-slate-900 border border-emerald-500/40 text-emerald-300 px-4 py-3 rounded-xl shadow-2xl flex items-center gap-2 text-sm font-semibold">
            <CheckCircle2 className="w-4 h-4 text-emerald-400" />
            <span>{{toast}}</span>
          </div>
        </div>
      )}}

      <header className="max-w-7xl mx-auto flex items-center justify-between mb-8 pb-4 border-b border-white/10">
        <div className="flex items-center gap-3">
          <div className="p-2.5 rounded-xl bg-gradient-to-tr from-indigo-500 to-purple-600 shadow-lg shadow-indigo-500/20">
            <Sparkles className="w-5 h-5 text-white" />
          </div>
          <div>
            <h1 className="text-xl font-extrabold text-white">{name} CRM</h1>
            <p className="text-xs text-slate-400">Enterprise Pipeline Manager</p>
          </div>
        </div>

        <button
          onClick={{() => setIsAddOpen(true)}}
          className="flex items-center gap-2 px-4 py-2.5 bg-gradient-to-r from-indigo-600 to-purple-600 rounded-xl text-sm font-semibold text-white shadow-lg shadow-indigo-500/20 hover:scale-[1.02] transition-all"
        >
          <Plus className="w-4 h-4" /> Add Lead
        </button>
      </header>

      <main className="max-w-7xl mx-auto space-y-8">
        {{/* KPI Grid */}}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-6">
          <div className="backdrop-blur-xl bg-white/[0.03] border border-white/10 rounded-2xl p-6">
            <span className="text-xs font-semibold text-indigo-400 uppercase tracking-wider">Active Pipeline</span>
            <p className="text-3xl font-extrabold text-white mt-1">${{totalPipeline.toLocaleString()}}</p>
            <span className="text-xs text-emerald-400 flex items-center gap-1 mt-2"><TrendingUp className="w-3 h-3" /> +14.2% this sprint</span>
          </div>
          <div className="backdrop-blur-xl bg-white/[0.03] border border-white/10 rounded-2xl p-6">
            <span className="text-xs font-semibold text-purple-400 uppercase tracking-wider">Active Leads</span>
            <p className="text-3xl font-extrabold text-white mt-1">{{leads.length}}</p>
            <span className="text-xs text-slate-400 flex items-center gap-1 mt-2"><Users className="w-3 h-3" /> 84% qualification rate</span>
          </div>
          <div className="backdrop-blur-xl bg-white/[0.03] border border-white/10 rounded-2xl p-6">
            <span className="text-xs font-semibold text-cyan-400 uppercase tracking-wider">Win Rate</span>
            <p className="text-3xl font-extrabold text-white mt-1">42%</p>
            <span className="text-xs text-emerald-400 flex items-center gap-1 mt-2"><Target className="w-3 h-3" /> +3.5% vs last month</span>
          </div>
        </div>

        {{/* Leads Table */}}
        <div className="backdrop-blur-xl bg-white/[0.03] border border-white/10 rounded-2xl p-6">
          <div className="flex flex-col sm:flex-row items-center justify-between gap-4 mb-6">
            <div className="relative w-full sm:w-80">
              <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
              <input
                type="text"
                placeholder="Search leads or companies..."
                value={{searchTerm}}
                onChange={{(e) => setSearchTerm(e.target.value)}}
                className="w-full bg-white/5 border border-white/10 rounded-xl py-2 pl-9 pr-4 text-xs text-white placeholder-slate-400 focus:outline-none focus:ring-1 focus:ring-indigo-500"
              />
            </div>

            <div className="flex items-center gap-2">
              <Filter className="w-4 h-4 text-slate-400" />
              <select
                value={{statusFilter}}
                onChange={{(e) => setStatusFilter(e.target.value)}}
                className="bg-slate-900 border border-white/10 rounded-xl text-xs py-2 px-3 text-slate-200 focus:outline-none"
              >
                <option value="All">All Statuses</option>
                <option value="New">New</option>
                <option value="Contacted">Contacted</option>
                <option value="Proposal">Proposal</option>
                <option value="Won">Won</option>
              </select>
            </div>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-white/5 text-[11px] font-bold uppercase tracking-wider text-slate-400">
                  <th className="pb-3">Contact</th>
                  <th className="pb-3">Deal Value</th>
                  <th className="pb-3">Status</th>
                  <th className="pb-3">Source</th>
                  <th className="pb-3 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/5">
                {{filteredLeads.map((lead) => (
                  <tr key={{lead.id}} className="hover:bg-white/[0.02] transition-colors">
                    <td className="py-4">
                      <p className="font-bold text-white">{{lead.name}}</p>
                      <p className="text-xs text-slate-400">{{lead.company}}</p>
                    </td>
                    <td className="py-4 font-mono font-bold text-slate-100">${{lead.value.toLocaleString()}}</td>
                    <td className="py-4">
                      <span className={{`px-2.5 py-1 rounded-full text-[10px] font-bold border ${{
                        lead.status === 'Won' ? 'bg-emerald-500/10 text-emerald-300 border-emerald-500/20' :
                        lead.status === 'Proposal' ? 'bg-indigo-500/10 text-indigo-300 border-indigo-500/20' :
                        'bg-slate-500/10 text-slate-300 border-slate-500/20'
                      }}`}}>
                        {{lead.status}}
                      </span>
                    </td>
                    <td className="py-4 text-xs text-slate-400">{{lead.source}}</td>
                    <td className="py-4 text-right">
                      <div className="flex items-center justify-end gap-2">
                        <a href={{`mailto:${{lead.email}}`}} className="p-1.5 rounded-lg bg-white/5 hover:bg-white/10 text-slate-400 hover:text-white">
                          <Mail className="w-3.5 h-3.5" />
                        </a>
                        <a href={{`tel:${{lead.phone}}`}} className="p-1.5 rounded-lg bg-white/5 hover:bg-white/10 text-slate-400 hover:text-white">
                          <Phone className="w-3.5 h-3.5" />
                        </a>
                      </div>
                    </td>
                  </tr>
                ))}}
              </tbody>
            </table>
          </div>
        </div>
      </main>

      {{/* Add Modal */}}
      {{isAddOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
          <div className="bg-slate-900 border border-white/10 rounded-2xl p-6 max-w-md w-full shadow-2xl">
            <div className="flex items-center justify-between mb-4 pb-3 border-b border-white/10">
              <h3 className="font-bold text-white">Create New Lead</h3>
              <button onClick={{() => setIsAddOpen(false)}} className="text-slate-400 hover:text-white"><X className="w-4 h-4" /></button>
            </div>
            <form onSubmit={{handleAddLead}} className="space-y-4 text-xs">
              <div>
                <label className="block text-slate-400 mb-1">Contact Name</label>
                <input
                  type="text"
                  required
                  value={{newLead.name}}
                  onChange={{(e) => setNewLead({{ ...newLead, name: e.target.value }})}}
                  className="w-full bg-white/5 border border-white/10 rounded-xl p-2.5 text-white focus:outline-none focus:border-indigo-500"
                />
              </div>
              <div>
                <label className="block text-slate-400 mb-1">Company</label>
                <input
                  type="text"
                  required
                  value={{newLead.company}}
                  onChange={{(e) => setNewLead({{ ...newLead, company: e.target.value }})}}
                  className="w-full bg-white/5 border border-white/10 rounded-xl p-2.5 text-white focus:outline-none focus:border-indigo-500"
                />
              </div>
              <div>
                <label className="block text-slate-400 mb-1">Deal Value ($)</label>
                <input
                  type="number"
                  value={{newLead.value}}
                  onChange={{(e) => setNewLead({{ ...newLead, value: e.target.value }})}}
                  className="w-full bg-white/5 border border-white/10 rounded-xl p-2.5 text-white focus:outline-none focus:border-indigo-500"
                />
              </div>
              <button
                type="submit"
                className="w-full py-3 bg-indigo-600 hover:bg-indigo-500 rounded-xl font-bold text-white shadow-lg transition-all mt-4"
              >
                Save Lead
              </button>
            </form>
          </div>
        </div>
      )}}
    </div>
  );
}}"""
        }
    ]


def _get_analytics_scaffold(name: str, primary_color: str) -> list[dict[str, str]]:
    """Analytics archetype: KPI-first dashboard with chart focus."""
    files = _get_crm_scaffold(name, primary_color)
    files = [f for f in files if f["path"] in {"package.json", "index.html", "src/main.jsx", "src/index.css"}]
    files.append({
        "path": "src/App.jsx",
        "content": f"""import React, {{ useMemo, useState }} from 'react';
import {{
  TrendingUp, Users, DollarSign, Activity, Target, Zap,
  CheckCircle2, Sparkles, ArrowUpRight, Filter
}} from 'lucide-react';

const KPIS = [
  {{ label: 'Total Revenue', value: '$128,430', delta: '+18.2%', icon: DollarSign, color: 'text-emerald-400', bg: 'bg-emerald-500/10 border-emerald-500/20' }},
  {{ label: 'Active Users', value: '8,412', delta: '+9.4%', icon: Users, color: 'text-violet-400', bg: 'bg-violet-500/10 border-violet-500/20' }},
  {{ label: 'Conversion Rate', value: '4.86%', delta: '+1.2%', icon: Target, color: 'text-cyan-400', bg: 'bg-cyan-500/10 border-cyan-500/20' }},
  {{ label: 'Avg. Session', value: '6m 42s', delta: '+0.8%', icon: Activity, color: 'text-amber-400', bg: 'bg-amber-500/10 border-amber-500/20' }},
];

const SERIES = [
  {{ label: 'Mon', revenue: 12400, users: 820 }},
  {{ label: 'Tue', revenue: 15800, users: 940 }},
  {{ label: 'Wed', revenue: 14200, users: 880 }},
  {{ label: 'Thu', revenue: 18600, users: 1120 }},
  {{ label: 'Fri', revenue: 21400, users: 1290 }},
  {{ label: 'Sat', revenue: 16800, users: 1010 }},
  {{ label: 'Sun', revenue: 23400, users: 1380 }},
];

const CHANNELS = [
  {{ name: 'Organic Search', share: 42, color: '#8b5cf6' }},
  {{ name: 'Direct', share: 26, color: '#06b6d4' }},
  {{ name: 'Referral', share: 18, color: '#f59e0b' }},
  {{ name: 'Social', share: 14, color: '#10b981' }},
];

export default function App() {{
  const [range, setRange] = useState('7d');
  const maxRevenue = Math.max(...SERIES.map(s => s.revenue));
  const total = CHANNELS.reduce((a, c) => a + c.share, 0);
  let acc = 0;
  const arcs = CHANNELS.map(c => {{
    const start = acc; acc += c.share; return {{ ...c, start }};
  }});

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 p-6 md:p-10 selection:bg-cyan-500/30">
      <header className="max-w-7xl mx-auto flex items-center justify-between mb-8 pb-4 border-b border-white/10">
        <div className="flex items-center gap-3">
          <div className="p-2.5 rounded-xl bg-gradient-to-tr from-cyan-500 to-violet-600 shadow-lg shadow-cyan-500/20">
            <Zap className="w-5 h-5 text-white" />
          </div>
          <div>
            <h1 className="text-xl font-extrabold text-white">{name} Analytics</h1>
            <p className="text-xs text-slate-400">Real-time business intelligence</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {{['24h', '7d', '30d', '90d'].map(r => (
            <button key={{r}} onClick={{() => setRange(r)}}
              className={{`px-3.5 py-1.5 rounded-lg text-xs font-bold transition-all ${{
                range === r ? 'bg-cyan-600 text-white shadow-md shadow-cyan-600/30' : 'bg-white/5 text-slate-400 hover:bg-white/10'
              }}`}}>{{r}}</button>
          ))}}
        </div>
      </header>

      <main className="max-w-7xl mx-auto space-y-8">
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5">
          {{KPIS.map(kpi => (
            <div key={{kpi.label}} className="backdrop-blur-xl bg-white/[0.03] border border-white/10 rounded-2xl p-5 hover:border-white/20 transition-colors">
              <div className="flex items-center justify-between">
                <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">{{kpi.label}}</span>
                <div className={{`p-1.5 rounded-lg border {{kpi.bg}}`}}><kpi.icon className={{`w-4 h-4 {{kpi.color}}`}} /></div>
              </div>
              <p className="text-2xl font-extrabold text-white mt-3">{{kpi.value}}</p>
              <span className="text-xs text-emerald-400 flex items-center gap-1 mt-1.5">
                <TrendingUp className="w-3 h-3" /> {{kpi.delta}} vs prev
              </span>
            </div>
          ))}}
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2 backdrop-blur-xl bg-white/[0.03] border border-white/10 rounded-2xl p-6">
            <div className="flex items-center justify-between mb-6">
              <h2 className="font-bold text-white">Revenue Trend ({{range}})</h2>
              <span className="text-xs text-emerald-400 flex items-center gap-1"><ArrowUpRight className="w-3.5 h-3.5" /> +18.2% growth</span>
            </div>
            <div className="flex items-end gap-3 h-48">
              {{SERIES.map(s => (
                <div key={{s.label}} className="flex-1 flex flex-col items-center gap-2 group">
                  <span className="text-[10px] text-slate-500 opacity-0 group-hover:opacity-100 transition-opacity">${{s.revenue.toLocaleString()}}</span>
                  <div className="w-full rounded-t-lg bg-gradient-to-t from-violet-600/60 to-cyan-400/80 hover:from-violet-500 hover:to-cyan-300 transition-all"
                    style={{{{ height: `\\${{Math.round((s.revenue / maxRevenue) * 100)}}%` }}}} />
                  <span className="text-[10px] text-slate-500 font-semibold">{{s.label}}</span>
                </div>
              ))}}
            </div>
          </div>

          <div className="backdrop-blur-xl bg-white/[0.03] border border-white/10 rounded-2xl p-6">
            <h2 className="font-bold text-white mb-6">Traffic Sources</h2>
            <div className="flex justify-center mb-6">
              <svg viewBox="0 0 42 42" className="w-40 h-40 -rotate-90">
                {{arcs.map(a => (
                  <circle key={{a.name}} cx="21" cy="21" r="15.9" fill="none" stroke={{a.color}}
                    strokeWidth="6" strokeDasharray={{`${{a.share / total * 100}} ${{100 - a.share / total * 100}}`}}
                    strokeDashoffset={{`${{-a.start / total * 100}}`}} />
                ))}}
              </svg>
            </div>
            <div className="space-y-2.5">
              {{CHANNELS.map(c => (
                <div key={{c.name}} className="flex items-center justify-between text-xs">
                  <span className="flex items-center gap-2 text-slate-300">
                    <span className="w-2.5 h-2.5 rounded-sm" style={{{{ background: c.color }}}} />{{c.name}}
                  </span>
                  <span className="font-bold text-white">{{c.share}}%</span>
                </div>
              ))}}
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}}"""
    })
    return files


def _get_kanban_scaffold(name: str, primary_color: str) -> list[dict[str, str]]:
    """Kanban archetype: task board with drag-friendly columns."""
    files = _get_crm_scaffold(name, primary_color)
    files = [f for f in files if f["path"] in {"package.json", "index.html", "src/main.jsx", "src/index.css"}]
    files.append({
        "path": "src/App.jsx",
        "content": f"""import React, {{ useState }} from 'react';
import {{ Plus, Search, MoreHorizontal, Clock, Flag, CheckCircle2, X, Sparkles }} from 'lucide-react';

const INITIAL_TASKS = [
  {{ id: 1, title: 'Design onboarding flow', assignee: 'Sarah K.', priority: 'High', status: 'Backlog', due: 'Sep 22' }},
  {{ id: 2, title: 'API rate limiting', assignee: 'Marcus L.', priority: 'Urgent', status: 'In Progress', due: 'Sep 19' }},
  {{ id: 3, title: 'Landing page copy', assignee: 'Elena R.', priority: 'Medium', status: 'In Progress', due: 'Sep 21' }},
  {{ id: 4, title: 'Mobile nav polish', assignee: 'Dev P.', priority: 'Low', status: 'Review', due: 'Sep 18' }},
  {{ id: 5, title: 'Billing webhooks', assignee: 'Sarah K.', priority: 'High', status: 'Done', due: 'Sep 15' }},
];

const COLUMNS = [
  {{ id: 'Backlog', accent: 'bg-slate-500' }},
  {{ id: 'In Progress', accent: 'bg-violet-500' }},
  {{ id: 'Review', accent: 'bg-amber-500' }},
  {{ id: 'Done', accent: 'bg-emerald-500' }},
];

const PRIORITY_STYLES = {{
  Urgent: 'bg-rose-500/10 text-rose-300 border-rose-500/20',
  High: 'bg-amber-500/10 text-amber-300 border-amber-500/20',
  Medium: 'bg-cyan-500/10 text-cyan-300 border-cyan-500/20',
  Low: 'bg-slate-500/10 text-slate-300 border-slate-500/20',
}};

export default function App() {{
  const [tasks, setTasks] = useState(INITIAL_TASKS);
  const [search, setSearch] = useState('');
  const [showAdd, setShowAdd] = useState(false);
  const [newTask, setNewTask] = useState({{ title: '', assignee: '', priority: 'Medium' }});
  const [toast, setToast] = useState(null);

  const showToast = (msg) => {{ setToast(msg); setTimeout(() => setToast(null), 2500); }};

  const moveTask = (id, status) => setTasks(prev => prev.map(t => t.id === id ? {{ ...t, status }} : t));
  const cycleStatus = (task) => {{
    const idx = COLUMNS.findIndex(c => c.id === task.status);
    moveTask(task.id, COLUMNS[(idx + 1) % COLUMNS.length].id);
  }};

  const addTask = (e) => {{
    e.preventDefault();
    if (!newTask.title.trim()) return;
    setTasks([{{ id: Date.now(), ...newTask, status: 'Backlog', due: 'Sep 30' }}, ...tasks]);
    setNewTask({{ title: '', assignee: '', priority: 'Medium' }});
    setShowAdd(false);
    showToast('Task added to backlog');
  }};

  const visible = tasks.filter(t => t.title.toLowerCase().includes(search.toLowerCase()));

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 p-6 md:p-8 selection:bg-violet-500/30">
      {{toast && (
        <div className="fixed bottom-6 right-6 z-50 bg-slate-900 border border-emerald-500/40 text-emerald-300 px-4 py-3 rounded-xl shadow-2xl flex items-center gap-2 text-sm font-semibold">
          <CheckCircle2 className="w-4 h-4" /> {{toast}}
        </div>
      )}}
      <header className="max-w-7xl mx-auto flex flex-wrap items-center justify-between gap-4 mb-8">
        <div className="flex items-center gap-3">
          <div className="p-2.5 rounded-xl bg-gradient-to-tr from-violet-500 to-fuchsia-600 shadow-lg shadow-violet-500/20">
            <Sparkles className="w-5 h-5 text-white" />
          </div>
          <div>
            <h1 className="text-xl font-extrabold text-white">{name} Board</h1>
            <p className="text-xs text-slate-400">{{visible.length}} tasks · sprint 14</p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <div className="relative">
            <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
            <input value={{search}} onChange={{e => setSearch(e.target.value)}} placeholder="Search tasks..."
              className="w-56 bg-white/5 border border-white/10 rounded-xl py-2 pl-9 pr-4 text-xs focus:outline-none focus:ring-1 focus:ring-violet-500" />
          </div>
          <button onClick={{() => setShowAdd(true)}}
            className="flex items-center gap-2 px-4 py-2 bg-gradient-to-r from-violet-600 to-fuchsia-600 rounded-xl text-sm font-semibold shadow-lg shadow-violet-500/20 hover:scale-[1.02] transition-all">
            <Plus className="w-4 h-4" /> New Task
          </button>
        </div>
      </header>

      <main className="max-w-7xl mx-auto grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-5">
        {{COLUMNS.map(col => (
          <div key={{col.id}} className="backdrop-blur-xl bg-white/[0.02] border border-white/10 rounded-2xl p-4">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2">
                <span className={{`w-2 h-2 rounded-full {{col.accent}}`}} />
                <h2 className="text-sm font-bold text-white">{{col.id}}</h2>
                <span className="text-[10px] text-slate-500 bg-white/5 px-2 py-0.5 rounded-full">{{visible.filter(t => t.status === col.id).length}}</span>
              </div>
              <MoreHorizontal className="w-4 h-4 text-slate-500" />
            </div>
            <div className="space-y-3">
              {{visible.filter(t => t.status === col.id).map(task => (
                <div key={{task.id}} onClick={{() => cycleStatus(task)}}
                  className="bg-slate-900/80 border border-white/10 rounded-xl p-3.5 hover:border-violet-500/40 cursor-pointer transition-all hover:shadow-lg hover:shadow-violet-500/10">
                  <div className="flex items-start justify-between gap-2 mb-2">
                    <p className={{`text-sm font-semibold {{task.status === 'Done' ? 'line-through text-slate-500' : 'text-slate-100'}}`}}>{{task.title}}</p>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className={{`px-2 py-0.5 rounded-md text-[10px] font-bold border ${{PRIORITY_STYLES[task.priority]}}`}}>
                      <Flag className="w-2.5 h-2.5 inline mr-1" />{{task.priority}}
                    </span>
                    <span className="flex items-center gap-2">
                      <span className="text-[10px] text-slate-500 flex items-center gap-1"><Clock className="w-3 h-3" />{{task.due}}</span>
                      <span className="w-6 h-6 rounded-full bg-gradient-to-tr from-violet-500 to-cyan-500 flex items-center justify-center text-[9px] font-bold text-white">
                        {{task.assignee.split(' ').map(w => w[0]).join('')}}
                      </span>
                    </span>
                  </div>
                </div>
              ))}}
              <button onClick={{() => setShowAdd(true)}}
                className="w-full py-2 rounded-xl border border-dashed border-white/10 text-xs text-slate-500 hover:text-slate-300 hover:border-white/20 transition-colors">
                + Add task
              </button>
            </div>
          </div>
        ))}}
      </main>

      {{showAdd && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
          <div className="bg-slate-900 border border-white/10 rounded-2xl p-6 max-w-md w-full shadow-2xl">
            <div className="flex items-center justify-between mb-4">
              <h3 className="font-bold text-white">New Task</h3>
              <button onClick={{() => setShowAdd(false)}} className="text-slate-400 hover:text-white"><X className="w-4 h-4" /></button>
            </div>
            <form onSubmit={{addTask}} className="space-y-4 text-xs">
              <input required placeholder="Task title" value={{newTask.title}} onChange={{e => setNewTask({{...newTask, title: e.target.value}})}}
                className="w-full bg-white/5 border border-white/10 rounded-xl p-2.5 text-white focus:outline-none focus:border-violet-500" />
              <input placeholder="Assignee" value={{newTask.assignee}} onChange={{e => setNewTask({{...newTask, assignee: e.target.value}})}}
                className="w-full bg-white/5 border border-white/10 rounded-xl p-2.5 text-white focus:outline-none focus:border-violet-500" />
              <select value={{newTask.priority}} onChange={{e => setNewTask({{...newTask, priority: e.target.value}})}}
                className="w-full bg-slate-800 border border-white/10 rounded-xl p-2.5 text-white focus:outline-none">
                {{['Low', 'Medium', 'High', 'Urgent'].map(p => <option key={{p}}>{{p}}</option>)}}
              </select>
              <button type="submit" className="w-full py-3 bg-violet-600 hover:bg-violet-500 rounded-xl font-bold text-white mt-2">Create Task</button>
            </form>
          </div>
        </div>
      )}}
    </div>
  );
}}"""
    })
    return files


def _get_booking_scaffold(name: str, primary_color: str) -> list[dict[str, str]]:
    """Booking archetype: calendar with slot scheduling."""
    files = _get_crm_scaffold(name, primary_color)
    files = [f for f in files if f["path"] in {"package.json", "index.html", "src/main.jsx", "src/index.css"}]
    files.append({
        "path": "src/App.jsx",
        "content": f"""import React, {{ useMemo, useState }} from 'react';
import {{
  Calendar, Clock, User, CheckCircle2, X, ChevronLeft, ChevronRight,
  Plus, Phone, Mail, Sparkles
}} from 'lucide-react';

const SERVICES = ['Consultation', 'Deep Clean', 'Health Check', 'Strategy Session'];
const SLOTS = ['09:00', '10:00', '11:00', '13:00', '14:00', '15:00', '16:00', '17:00'];

const INITIAL_APPTS = [
  {{ id: 1, client: 'Ava Thompson', service: 'Consultation', date: '2026-09-18', time: '10:00', status: 'Confirmed' }},
  {{ id: 2, client: 'Noah Patel', service: 'Health Check', date: '2026-09-18', time: '14:00', status: 'Pending' }},
  {{ id: 3, client: 'Mia Rodriguez', service: 'Strategy Session', date: '2026-09-19', time: '09:00', status: 'Confirmed' }},
  {{ id: 4, client: 'Liam Chen', service: 'Deep Clean', date: '2026-09-21', time: '15:00', status: 'Confirmed' }},
];

const STATUS_STYLES = {{
  Confirmed: 'bg-emerald-500/10 text-emerald-300 border-emerald-500/20',
  Pending: 'bg-amber-500/10 text-amber-300 border-amber-500/20',
  Cancelled: 'bg-rose-500/10 text-rose-300 border-rose-500/20',
  Completed: 'bg-cyan-500/10 text-cyan-300 border-cyan-500/20',
}};

export default function App() {{
  const [appts, setAppts] = useState(INITIAL_APPTS);
  const [selectedDate, setSelectedDate] = useState('2026-09-18');
  const [showBook, setShowBook] = useState(false);
  const [booking, setBooking] = useState({{ client: '', service: SERVICES[0], time: SLOTS[0] }});
  const [toast, setToast] = useState(null);

  const showToast = (msg) => {{ setToast(msg); setTimeout(() => setToast(null), 2500); }};

  const dayAppts = useMemo(() => appts.filter(a => a.date === selectedDate), [appts, selectedDate]);
  const takenSlots = new Set(dayAppts.map(a => a.time));

  const shiftDate = (days) => {{
    const d = new Date(selectedDate + 'T12:00:00');
    d.setDate(d.getDate() + days);
    setSelectedDate(d.toISOString().slice(0, 10));
  }};

  const confirmBooking = (e) => {{
    e.preventDefault();
    if (!booking.client.trim() || takenSlots.has(booking.time)) return;
    setAppts([...appts, {{ id: Date.now(), ...booking, date: selectedDate, status: 'Confirmed' }}]);
    setShowBook(false);
    setBooking({{ client: '', service: SERVICES[0], time: SLOTS[0] }});
    showToast(`Appointment confirmed for ${{booking.time}}`);
  }};

  const stats = {{
    today: appts.filter(a => a.date === selectedDate).length,
    confirmed: appts.filter(a => a.status === 'Confirmed').length,
    pending: appts.filter(a => a.status === 'Pending').length,
  }};

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 p-6 md:p-10 selection:bg-emerald-500/30">
      {{toast && (
        <div className="fixed bottom-6 right-6 z-50 bg-slate-900 border border-emerald-500/40 text-emerald-300 px-4 py-3 rounded-xl shadow-2xl flex items-center gap-2 text-sm font-semibold">
          <CheckCircle2 className="w-4 h-4" /> {{toast}}
        </div>
      )}}
      <header className="max-w-7xl mx-auto flex items-center justify-between mb-8 pb-4 border-b border-white/10">
        <div className="flex items-center gap-3">
          <div className="p-2.5 rounded-xl bg-gradient-to-tr from-emerald-500 to-cyan-600 shadow-lg shadow-emerald-500/20">
            <Calendar className="w-5 h-5 text-white" />
          </div>
          <div>
            <h1 className="text-xl font-extrabold text-white">{name} Scheduler</h1>
            <p className="text-xs text-slate-400">Appointments & client management</p>
          </div>
        </div>
        <button onClick={{() => setShowBook(true)}}
          className="flex items-center gap-2 px-4 py-2.5 bg-gradient-to-r from-emerald-600 to-cyan-600 rounded-xl text-sm font-semibold text-white shadow-lg shadow-emerald-500/20 hover:scale-[1.02] transition-all">
          <Plus className="w-4 h-4" /> Book Appointment
        </button>
      </header>

      <main className="max-w-7xl mx-auto grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="backdrop-blur-xl bg-white/[0.03] border border-white/10 rounded-2xl p-6">
          <div className="flex items-center justify-between mb-4">
            <h2 className="font-bold text-white">Schedule</h2>
            <div className="flex items-center gap-1">
              <button onClick={{() => shiftDate(-1)}} className="p-1.5 rounded-lg bg-white/5 hover:bg-white/10"><ChevronLeft className="w-4 h-4" /></button>
              <button onClick={{() => shiftDate(1)}} className="p-1.5 rounded-lg bg-white/5 hover:bg-white/10"><ChevronRight className="w-4 h-4" /></button>
            </div>
          </div>
          <p className="text-sm text-slate-300 font-semibold mb-4">{{new Date(selectedDate + 'T12:00:00').toDateString()}}</p>
          <div className="grid grid-cols-2 gap-2">
            {{SLOTS.map(slot => {{
              const taken = takenSlots.has(slot);
              return (
                <button key={{slot}} onClick={{() => !taken && (setBooking({{...booking, time: slot}}), setShowBook(true))}}
                  className={{`py-2 rounded-xl text-xs font-bold border transition-all ${{
                    taken ? 'bg-white/5 border-white/5 text-slate-600 line-through cursor-not-allowed'
                          : 'bg-emerald-500/10 border-emerald-500/20 text-emerald-300 hover:bg-emerald-500/20'
                  }}`}}>{{slot}}</button>
              );
            }})}}
          </div>
          <div className="grid grid-cols-3 gap-3 mt-6 pt-6 border-t border-white/10 text-center">
            <div><p className="text-xl font-extrabold text-white">{{stats.today}}</p><p className="text-[10px] text-slate-500 uppercase">Today</p></div>
            <div><p className="text-xl font-extrabold text-emerald-400">{{stats.confirmed}}</p><p className="text-[10px] text-slate-500 uppercase">Confirmed</p></div>
            <div><p className="text-xl font-extrabold text-amber-400">{{stats.pending}}</p><p className="text-[10px] text-slate-500 uppercase">Pending</p></div>
          </div>
        </div>

        <div className="lg:col-span-2 backdrop-blur-xl bg-white/[0.03] border border-white/10 rounded-2xl p-6">
          <h2 className="font-bold text-white mb-4">Appointments — {{selectedDate}}</h2>
          {{dayAppts.length === 0 ? (
            <div className="text-center py-16 text-slate-500">
              <Calendar className="w-12 h-12 mx-auto mb-3 text-slate-600" />
              <p className="text-sm font-semibold text-slate-300">No appointments this day</p>
              <p className="text-xs mt-1">Pick an open slot to book a client.</p>
            </div>
          ) : (
            <div className="space-y-3">
              {{dayAppts.map(a => (
                <div key={{a.id}} className="flex items-center justify-between bg-slate-900/60 border border-white/10 rounded-xl p-4">
                  <div className="flex items-center gap-4">
                    <div className="text-center">
                      <p className="text-lg font-extrabold text-white">{{a.time}}</p>
                      <p className="text-[10px] text-slate-500">1 hr</p>
                    </div>
                    <div>
                      <p className="font-bold text-sm text-white">{{a.client}}</p>
                      <p className="text-xs text-slate-400">{{a.service}}</p>
                    </div>
                  </div>
                  <span className={{`px-2.5 py-1 rounded-full text-[10px] font-bold border ${{STATUS_STYLES[a.status]}}`}}>{{a.status}}</span>
                </div>
              ))}}
            </div>
          )}}
        </div>
      </main>

      {{showBook && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
          <div className="bg-slate-900 border border-white/10 rounded-2xl p-6 max-w-md w-full shadow-2xl">
            <div className="flex items-center justify-between mb-4">
              <h3 className="font-bold text-white">Book — {{selectedDate}} at {{booking.time}}</h3>
              <button onClick={{() => setShowBook(false)}} className="text-slate-400 hover:text-white"><X className="w-4 h-4" /></button>
            </div>
            <form onSubmit={{confirmBooking}} className="space-y-4 text-xs">
              <input required placeholder="Client name" value={{booking.client}} onChange={{e => setBooking({{...booking, client: e.target.value}})}}
                className="w-full bg-white/5 border border-white/10 rounded-xl p-2.5 text-white focus:outline-none focus:border-emerald-500" />
              <select value={{booking.service}} onChange={{e => setBooking({{...booking, service: e.target.value}})}}
                className="w-full bg-slate-800 border border-white/10 rounded-xl p-2.5 text-white focus:outline-none">
                {{SERVICES.map(s => <option key={{s}}>{{s}}</option>)}}
              </select>
              <button type="submit" className="w-full py-3 bg-emerald-600 hover:bg-emerald-500 rounded-xl font-bold text-white mt-2">Confirm Booking</button>
            </form>
          </div>
        </div>
      )}}
    </div>
  );
}}"""
    })
    return files


def _get_saas_scaffold(name: str, primary_color: str) -> list[dict[str, str]]:
    """Generic SaaS archetype: sidebar dashboard + CRUD data management.

    The former default aliased to the ecommerce storefront, which produced a
    product grid for every non-matching request (a CRM prompt got a shop).
    This is a real neutral dashboard: KPI cards, sidebar navigation, SVG
    chart, and a working CRUD table.
    """
    return [
        {
            "path": "package.json",
            "content": """{
  "name": "zenith-saas",
  "private": true,
  "version": "1.0.0",
  "type": "module",
  "dependencies": {
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "lucide-react": "^0.464.0"
  },
  "devDependencies": {
    "@vitejs/plugin-react": "^4.3.4",
    "vite": "^6.0.1"
  }
}"""
        },
        {
            "path": "index.html",
            "content": f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>{name} — Business OS</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <style>body {{ font-family: 'Plus Jakarta Sans', sans-serif; }}</style>
  </head>
  <body class="bg-slate-950 text-slate-100 antialiased min-h-screen">
    <div id="root"></div>
    <script type="module" src="/src/main.jsx"></script>
  </body>
</html>"""
        },
        {
            "path": "src/main.jsx",
            "content": """import React from 'react';
import ReactDOM from 'react-dom/client';
import './index.css';
import App from './App';

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);"""
        },
        {
            "path": "src/index.css",
            "content": "@layer base { body { background-color: #030712; color: #f8fafc; } }"
        },
        {
            "path": "src/App.jsx",
            "content": f"""import React, {{ useMemo, useState }} from 'react';
import {{
  LayoutDashboard, Database, Settings, Search, Plus, X, Filter,
  TrendingUp, Users, DollarSign, CheckCircle2, Sparkles, Bell
}} from 'lucide-react';

const NAV = [
  {{ id: 'overview', label: 'Overview', icon: LayoutDashboard }},
  {{ id: 'data', label: 'Data', icon: Database }},
  {{ id: 'settings', label: 'Settings', icon: Settings }},
];

const INITIAL_RECORDS = [
  {{ id: 1, title: 'Q3 Marketing Campaign', status: 'Active', value: 24000, owner: 'Sarah K.', updated: '2h ago' }},
  {{ id: 2, title: 'Enterprise Onboarding', status: 'In Progress', value: 58000, owner: 'Marcus L.', updated: '5h ago' }},
  {{ id: 3, title: 'Vendor Contract Renewal', status: 'Pending', value: 12500, owner: 'Elena R.', updated: '1d ago' }},
  {{ id: 4, title: 'Customer Success Program', status: 'Active', value: 31000, owner: 'Dev P.', updated: '2d ago' }},
  {{ id: 5, title: 'Infrastructure Upgrade', status: 'Completed', value: 47500, owner: 'Ava T.', updated: '3d ago' }},
];

const STATUS_STYLES = {{
  Active: 'bg-emerald-500/10 text-emerald-300 border-emerald-500/20',
  'In Progress': 'bg-violet-500/10 text-violet-300 border-violet-500/20',
  Pending: 'bg-amber-500/10 text-amber-300 border-amber-500/20',
  Completed: 'bg-cyan-500/10 text-cyan-300 border-cyan-500/20',
}};

export default function App() {{
  const [view, setView] = useState('overview');
  const [records, setRecords] = useState(INITIAL_RECORDS);
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('All');
  const [showAdd, setShowAdd] = useState(false);
  const [newRec, setNewRec] = useState({{ title: '', status: 'Active', value: '' }});
  const [toast, setToast] = useState(null);

  const showToast = (msg) => {{ setToast(msg); setTimeout(() => setToast(null), 2500); }};

  const filtered = useMemo(() => records.filter(r =>
    (statusFilter === 'All' || r.status === statusFilter) &&
    r.title.toLowerCase().includes(search.toLowerCase())
  ), [records, search, statusFilter]);

  const totals = useMemo(() => ({{
    value: records.reduce((a, r) => a + r.value, 0),
    active: records.filter(r => r.status === 'Active').length,
  }}), [records]);

  const addRecord = (e) => {{
    e.preventDefault();
    if (!newRec.title.trim()) return;
    setRecords([{{ id: Date.now(), ...newRec, value: parseInt(newRec.value) || 0, owner: 'You', updated: 'Just now' }}, ...records]);
    setShowAdd(false);
    setNewRec({{ title: '', status: 'Active', value: '' }});
    showToast('Record created');
  }};

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex selection:bg-violet-500/30">
      <aside className="hidden md:flex w-60 flex-col border-r border-white/10 bg-slate-950/60 p-5 gap-1">
        <div className="flex items-center gap-2.5 mb-8 px-2">
          <div className="p-2 rounded-xl bg-gradient-to-tr from-violet-600 to-cyan-500 shadow-lg shadow-violet-500/20">
            <Sparkles className="w-4 h-4 text-white" />
          </div>
          <span className="font-extrabold text-white">{name}</span>
        </div>
        {{NAV.map(item => (
          <button key={{item.id}} onClick={{() => setView(item.id)}}
            className={{`flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-semibold transition-all ${{
              view === item.id ? 'bg-violet-600/20 text-violet-300 border border-violet-500/20' : 'text-slate-400 hover:bg-white/5 hover:text-slate-200'
            }}`}}>
            <item.icon className="w-4 h-4" /> {{item.label}}
          </button>
        ))}}
        <div className="mt-auto p-3 rounded-xl bg-white/[0.02] border border-white/5 text-xs text-slate-500">
          <p className="font-bold text-slate-300 mb-0.5">{{records.length}} records</p>
          Synced locally · v1.0
        </div>
      </aside>

      <div className="flex-1 min-w-0">
        <header className="sticky top-0 z-40 backdrop-blur-xl bg-slate-950/80 border-b border-white/10 px-6 py-4 flex items-center justify-between">
          <div>
            <h1 className="text-lg font-extrabold text-white capitalize">{{view}}</h1>
            <p className="text-xs text-slate-500">Manage everything from one place</p>
          </div>
          <div className="flex items-center gap-3">
            <div className="relative hidden sm:block">
              <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
              <input value={{search}} onChange={{e => setSearch(e.target.value)}} placeholder="Search records..."
                className="w-56 bg-white/5 border border-white/10 rounded-xl py-2 pl-9 pr-4 text-xs focus:outline-none focus:ring-1 focus:ring-violet-500" />
            </div>
            <button className="p-2 rounded-xl bg-white/5 hover:bg-white/10 text-slate-400 relative">
              <Bell className="w-4 h-4" />
              <span className="absolute top-1.5 right-1.5 w-2 h-2 bg-rose-500 rounded-full" />
            </button>
            <button onClick={{() => setShowAdd(true)}}
              className="flex items-center gap-2 px-4 py-2 bg-gradient-to-r from-violet-600 to-cyan-600 rounded-xl text-sm font-semibold shadow-lg shadow-violet-500/20 hover:scale-[1.02] transition-all">
              <Plus className="w-4 h-4" /> New
            </button>
          </div>
        </header>

        <main className="p-6 space-y-6">
          {{view === 'overview' && (
            <>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-5">
                <div className="backdrop-blur-xl bg-white/[0.03] border border-white/10 rounded-2xl p-5">
                  <span className="text-xs font-semibold text-violet-400 uppercase tracking-wider">Total Value</span>
                  <p className="text-2xl font-extrabold text-white mt-1">${{totals.value.toLocaleString()}}</p>
                  <span className="text-xs text-emerald-400 flex items-center gap-1 mt-2"><TrendingUp className="w-3 h-3" /> +12.4% this month</span>
                </div>
                <div className="backdrop-blur-xl bg-white/[0.03] border border-white/10 rounded-2xl p-5">
                  <span className="text-xs font-semibold text-cyan-400 uppercase tracking-wider">Active Records</span>
                  <p className="text-2xl font-extrabold text-white mt-1">{{totals.active}}</p>
                  <span className="text-xs text-slate-400 flex items-center gap-1 mt-2"><Users className="w-3 h-3" /> across {{records.length}} total</span>
                </div>
                <div className="backdrop-blur-xl bg-white/[0.03] border border-white/10 rounded-2xl p-5">
                  <span className="text-xs font-semibold text-amber-400 uppercase tracking-wider">Avg. Deal Size</span>
                  <p className="text-2xl font-extrabold text-white mt-1">${{records.length ? Math.round(totals.value / records.length).toLocaleString() : 0}}</p>
                  <span className="text-xs text-emerald-400 flex items-center gap-1 mt-2"><DollarSign className="w-3 h-3" /> +4.1% vs last</span>
                </div>
              </div>
              <div className="backdrop-blur-xl bg-white/[0.03] border border-white/10 rounded-2xl p-6">
                <h2 className="font-bold text-white mb-4">Activity</h2>
                <div className="flex items-end gap-2 h-32">
                  {{[42, 58, 45, 71, 64, 88, 79, 94, 82, 100, 91, 97].map((h, i) => (
                    <div key={{i}} className="flex-1 rounded-t bg-gradient-to-t from-violet-600/50 to-cyan-400/70"
                      style={{{{ height: `\\${{h}}%` }}}} />
                  ))}}
                </div>
              </div>
            </>
          )}}

          {{view === 'data' && (
            <div className="backdrop-blur-xl bg-white/[0.03] border border-white/10 rounded-2xl p-6">
              <div className="flex items-center justify-between mb-4">
                <h2 className="font-bold text-white">All Records</h2>
                <select value={{statusFilter}} onChange={{e => setStatusFilter(e.target.value)}}
                  className="bg-slate-900 border border-white/10 rounded-xl text-xs py-2 px-3 text-slate-200 focus:outline-none">
                  {{['All', 'Active', 'In Progress', 'Pending', 'Completed'].map(s => <option key={{s}}>{{s}}</option>)}}
                </select>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <thead>
                    <tr className="border-b border-white/5 text-[11px] font-bold uppercase tracking-wider text-slate-400">
                      <th className="pb-3">Title</th><th className="pb-3">Value</th><th className="pb-3">Status</th><th className="pb-3">Owner</th><th className="pb-3">Updated</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-white/5">
                    {{filtered.map(r => (
                      <tr key={{r.id}} className="hover:bg-white/[0.02] transition-colors">
                        <td className="py-3.5 font-semibold text-white">{{r.title}}</td>
                        <td className="py-3.5 font-mono text-slate-200">${{r.value.toLocaleString()}}</td>
                        <td className="py-3.5"><span className={{`px-2.5 py-1 rounded-full text-[10px] font-bold border ${{STATUS_STYLES[r.status]}}`}}>{{r.status}}</span></td>
                        <td className="py-3.5 text-slate-400">{{r.owner}}</td>
                        <td className="py-3.5 text-xs text-slate-500">{{r.updated}}</td>
                      </tr>
                    ))}}
                  </tbody>
                </table>
              </div>
            </div>
          )}}

          {{view === 'settings' && (
            <div className="backdrop-blur-xl bg-white/[0.03] border border-white/10 rounded-2xl p-6 max-w-xl">
              <h2 className="font-bold text-white mb-4">Workspace Settings</h2>
              <div className="space-y-4 text-xs text-slate-400">
                <div className="flex items-center justify-between p-3 rounded-xl bg-white/[0.02] border border-white/5">
                  <span>Workspace name</span><span className="text-slate-200 font-bold">{name}</span>
                </div>
                <div className="flex items-center justify-between p-3 rounded-xl bg-white/[0.02] border border-white/5">
                  <span>Plan</span><span className="text-violet-300 font-bold">Pro (local)</span>
                </div>
                <div className="flex items-center justify-between p-3 rounded-xl bg-white/[0.02] border border-white/5">
                  <span>Data storage</span><span className="text-emerald-300 font-bold">On-device</span>
                </div>
              </div>
            </div>
          )}}
        </main>
      </div>

      {{showAdd && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
          <div className="bg-slate-900 border border-white/10 rounded-2xl p-6 max-w-md w-full shadow-2xl">
            <div className="flex items-center justify-between mb-4">
              <h3 className="font-bold text-white">New Record</h3>
              <button onClick={{() => setShowAdd(false)}} className="text-slate-400 hover:text-white"><X className="w-4 h-4" /></button>
            </div>
            <form onSubmit={{addRecord}} className="space-y-4 text-xs">
              <input required placeholder="Title" value={{newRec.title}} onChange={{e => setNewRec({{...newRec, title: e.target.value}})}}
                className="w-full bg-white/5 border border-white/10 rounded-xl p-2.5 text-white focus:outline-none focus:border-violet-500" />
              <input type="number" placeholder="Value ($)" value={{newRec.value}} onChange={{e => setNewRec({{...newRec, value: e.target.value}})}}
                className="w-full bg-white/5 border border-white/10 rounded-xl p-2.5 text-white focus:outline-none focus:border-violet-500" />
              <select value={{newRec.status}} onChange={{e => setNewRec({{...newRec, status: e.target.value}})}}
                className="w-full bg-slate-800 border border-white/10 rounded-xl p-2.5 text-white focus:outline-none">
                {{['Active', 'In Progress', 'Pending', 'Completed'].map(s => <option key={{s}}>{{s}}</option>)}}
              </select>
              <button type="submit" className="w-full py-3 bg-violet-600 hover:bg-violet-500 rounded-xl font-bold text-white mt-2">Create Record</button>
            </form>
          </div>
        </div>
      )}}
    </div>
  );
}}"""
        },
    ]
