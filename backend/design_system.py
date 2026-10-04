"""Per-domain design systems for TerabitStudio.

Why this exists (live evidence, Casa Verde 20260928-172956): FILE_SYSTEM used
to say "Design premium: dark slate background with indigo accents" for EVERY
domain, so a warm Italian restaurant rendered as dark-slate+indigo SaaS with
half-white half-dark sections (each model file invented its own palette:
Hero white+slate+indigo, Menu neon indigo-purple-pink gradients, Reservations
white cards with light text). A 7B does not follow abstract design advice --
it needs the EXACT Tailwind classes, so this module picks them per domain and
the generator injects them into every file ask, the composed shell, index.html
and index.css. Font pairings give each trade its own typographic identity the
way Bolt/Lovable presets do (Playfair restaurants, navy serif law, clinical
sans healthcare, editorial fashion...).

User customization is a first-class feature: extract_design_prefs() parses
explicit design requests from the prompt (brand colors by hex or name, dark
mode, font choices, animation level) and apply_overrides() layers them over
the domain theme -- the user's brand wins over the domain preset. Arbitrary-
value Tailwind classes (bg-[#7c3aed]) make any user hex work exactly under
the CDN compiler.
"""

import re

# Curated themes. Every field is an EXACT class/value the model must reuse.
# tw.* are Tailwind class strings; fonts.* are Google Fonts family names.
THEMES: dict[str, dict] = {
    "restaurant": {
        "mode": "light",
        "vibe": "warm, appetizing, candle-lit trattoria elegance",
        "tw": {
            "page_bg": "bg-[#faf6f0]",
            "surface": "bg-white",
            "surface_2": "bg-[#f3ece2]",
            "heading_text": "text-stone-900",
            "body_text": "text-stone-600",
            "muted_text": "text-stone-500",
            "primary": "bg-amber-800",
            "primary_hover": "hover:bg-amber-900",
            "on_primary": "text-amber-50",
            "border": "border-stone-200",
            "accent_text": "text-amber-800",
            "accent_bg": "bg-amber-100",
            "gradient": "from-amber-700 to-orange-800",
        },
        "fonts": {"heading": "Playfair Display", "body": "Inter"},
        "font_query": "Playfair+Display:wght@500;600;700;800;900&family=Inter:wght@400;500;600;700",
        "heading_css": "font-family: 'Playfair Display', Georgia, serif;",
        "body_css": "font-family: 'Inter', system-ui, sans-serif;",
        "radius": "rounded-2xl",
        "image_words": "restaurant,italian,food",
    },
    "law": {
        "mode": "light",
        "vibe": "authoritative, discreet, white-shoe firm",
        "tw": {
            "page_bg": "bg-slate-50",
            "surface": "bg-white",
            "surface_2": "bg-slate-100",
            "heading_text": "text-slate-900",
            "body_text": "text-slate-600",
            "muted_text": "text-slate-500",
            "primary": "bg-blue-900",
            "primary_hover": "hover:bg-blue-950",
            "on_primary": "text-white",
            "border": "border-slate-200",
            "accent_text": "text-blue-900",
            "accent_bg": "bg-blue-50",
            "gradient": "from-blue-900 to-slate-800",
        },
        "fonts": {"heading": "Libre Baskerville", "body": "Source Sans 3"},
        "font_query": "Libre+Baskerville:wght@400;700&family=Source+Sans+3:wght@400;500;600;700",
        "heading_css": "font-family: 'Libre Baskerville', Georgia, serif;",
        "body_css": "font-family: 'Source Sans 3', system-ui, sans-serif;",
        "radius": "rounded-xl",
        "image_words": "law,office,architecture",
    },
    "hospital": {
        "mode": "light",
        "vibe": "clean, calm, clinical trust",
        "tw": {
            "page_bg": "bg-white",
            "surface": "bg-sky-50",
            "surface_2": "bg-slate-50",
            "heading_text": "text-slate-900",
            "body_text": "text-slate-600",
            "muted_text": "text-slate-500",
            "primary": "bg-teal-600",
            "primary_hover": "hover:bg-teal-700",
            "on_primary": "text-white",
            "border": "border-slate-200",
            "accent_text": "text-teal-700",
            "accent_bg": "bg-teal-50",
            "gradient": "from-teal-500 to-sky-600",
        },
        "fonts": {"heading": "Inter", "body": "Inter"},
        "font_query": "Inter:wght@400;500;600;700;800",
        "heading_css": "font-family: 'Inter', system-ui, sans-serif;",
        "body_css": "font-family: 'Inter', system-ui, sans-serif;",
        "radius": "rounded-2xl",
        "image_words": "hospital,medical,clinic",
    },
    "fashion": {
        "mode": "dark",
        "vibe": "editorial, high-fashion, gallery minimalism",
        "tw": {
            "page_bg": "bg-neutral-950",
            "surface": "bg-neutral-900",
            "surface_2": "bg-neutral-800",
            "heading_text": "text-neutral-50",
            "body_text": "text-neutral-300",
            "muted_text": "text-neutral-500",
            "primary": "bg-neutral-100",
            "primary_hover": "hover:bg-white",
            "on_primary": "text-neutral-900",
            "border": "border-neutral-800",
            "accent_text": "text-rose-300",
            "accent_bg": "bg-rose-950",
            "gradient": "from-neutral-100 to-neutral-400",
        },
        "fonts": {"heading": "Cormorant Garamond", "body": "Montserrat"},
        "font_query": "Cormorant+Garamond:wght@400;500;600;700&family=Montserrat:wght@300;400;500;600",
        "heading_css": "font-family: 'Cormorant Garamond', Georgia, serif;",
        "body_css": "font-family: 'Montserrat', system-ui, sans-serif;",
        "radius": "rounded-none",
        "image_words": "fashion,editorial,model",
    },
    "art": {
        "mode": "light",
        "vibe": "minimal gallery, whitespace as luxury",
        "tw": {
            "page_bg": "bg-white",
            "surface": "bg-neutral-50",
            "surface_2": "bg-neutral-100",
            "heading_text": "text-neutral-900",
            "body_text": "text-neutral-600",
            "muted_text": "text-neutral-400",
            "primary": "bg-neutral-900",
            "primary_hover": "hover:bg-neutral-700",
            "on_primary": "text-white",
            "border": "border-neutral-200",
            "accent_text": "text-orange-600",
            "accent_bg": "bg-orange-50",
            "gradient": "from-neutral-900 to-neutral-600",
        },
        "fonts": {"heading": "Space Grotesk", "body": "Inter"},
        "font_query": "Space+Grotesk:wght@400;500;600;700&family=Inter:wght@400;500;600",
        "heading_css": "font-family: 'Space Grotesk', system-ui, sans-serif;",
        "body_css": "font-family: 'Inter', system-ui, sans-serif;",
        "radius": "rounded-lg",
        "image_words": "art,gallery,exhibition",
    },
    "fitness": {
        "mode": "dark",
        "vibe": "high-energy, athletic, training-floor grit",
        "tw": {
            "page_bg": "bg-zinc-950",
            "surface": "bg-zinc-900",
            "surface_2": "bg-zinc-800",
            "heading_text": "text-zinc-50",
            "body_text": "text-zinc-300",
            "muted_text": "text-zinc-500",
            "primary": "bg-lime-400",
            "primary_hover": "hover:bg-lime-300",
            "on_primary": "text-zinc-950",
            "border": "border-zinc-800",
            "accent_text": "text-lime-400",
            "accent_bg": "bg-lime-950",
            "gradient": "from-lime-400 to-emerald-500",
        },
        "fonts": {"heading": "Oswald", "body": "Inter"},
        "font_query": "Oswald:wght@400;500;600;700&family=Inter:wght@400;500;600",
        "heading_css": "font-family: 'Oswald', system-ui, sans-serif;",
        "body_css": "font-family: 'Inter', system-ui, sans-serif;",
        "radius": "rounded-xl",
        "image_words": "gym,fitness,training",
    },
    "realestate": {
        "mode": "light",
        "vibe": "aspirational, architectural, premium listings",
        "tw": {
            "page_bg": "bg-stone-50",
            "surface": "bg-white",
            "surface_2": "bg-stone-100",
            "heading_text": "text-stone-900",
            "body_text": "text-stone-600",
            "muted_text": "text-stone-500",
            "primary": "bg-emerald-900",
            "primary_hover": "hover:bg-emerald-950",
            "on_primary": "text-white",
            "border": "border-stone-200",
            "accent_text": "text-emerald-800",
            "accent_bg": "bg-emerald-50",
            "gradient": "from-emerald-800 to-stone-800",
        },
        "fonts": {"heading": "Playfair Display", "body": "Inter"},
        "font_query": "Playfair+Display:wght@500;600;700&family=Inter:wght@400;500;600;700",
        "heading_css": "font-family: 'Playfair Display', Georgia, serif;",
        "body_css": "font-family: 'Inter', system-ui, sans-serif;",
        "radius": "rounded-xl",
        "image_words": "house,architecture,interior",
    },
    "education": {
        "mode": "light",
        "vibe": "encouraging, scholarly, modern campus",
        "tw": {
            "page_bg": "bg-white",
            "surface": "bg-indigo-50",
            "surface_2": "bg-slate-50",
            "heading_text": "text-slate-900",
            "body_text": "text-slate-600",
            "muted_text": "text-slate-500",
            "primary": "bg-indigo-600",
            "primary_hover": "hover:bg-indigo-700",
            "on_primary": "text-white",
            "border": "border-slate-200",
            "accent_text": "text-indigo-700",
            "accent_bg": "bg-indigo-50",
            "gradient": "from-indigo-500 to-sky-600",
        },
        "fonts": {"heading": "Merriweather", "body": "Inter"},
        "font_query": "Merriweather:wght@400;700;900&family=Inter:wght@400;500;600;700",
        "heading_css": "font-family: 'Merriweather', Georgia, serif;",
        "body_css": "font-family: 'Inter', system-ui, sans-serif;",
        "radius": "rounded-2xl",
        "image_words": "school,students,campus",
    },
    "portfolio": {
        "mode": "light",
        "vibe": "personal, confident, editorial portfolio",
        "tw": {
            "page_bg": "bg-white",
            "surface": "bg-stone-50",
            "surface_2": "bg-stone-100",
            "heading_text": "text-stone-900",
            "body_text": "text-stone-600",
            "muted_text": "text-stone-500",
            "primary": "bg-stone-900",
            "primary_hover": "hover:bg-stone-700",
            "on_primary": "text-white",
            "border": "border-stone-200",
            "accent_text": "text-orange-600",
            "accent_bg": "bg-orange-50",
            "gradient": "from-stone-900 to-stone-600",
        },
        "fonts": {"heading": "Space Grotesk", "body": "Inter"},
        "font_query": "Space+Grotesk:wght@400;500;600;700&family=Inter:wght@400;500;600",
        "heading_css": "font-family: 'Space Grotesk', system-ui, sans-serif;",
        "body_css": "font-family: 'Inter', system-ui, sans-serif;",
        "radius": "rounded-xl",
        "image_words": "portfolio,design,workspace",
    },
    "product": {
        "mode": "light",
        "vibe": "premium hardware launch, Apple-style restraint",
        "tw": {
            "page_bg": "bg-white",
            "surface": "bg-gray-50",
            "surface_2": "bg-gray-100",
            "heading_text": "text-gray-900",
            "body_text": "text-gray-600",
            "muted_text": "text-gray-500",
            "primary": "bg-gray-900",
            "primary_hover": "hover:bg-gray-700",
            "on_primary": "text-white",
            "border": "border-gray-200",
            "accent_text": "text-blue-600",
            "accent_bg": "bg-blue-50",
            "gradient": "from-gray-900 to-gray-600",
        },
        "fonts": {"heading": "Inter", "body": "Inter"},
        "font_query": "Inter:wght@400;500;600;700;800;900",
        "heading_css": "font-family: 'Inter', system-ui, sans-serif;",
        "body_css": "font-family: 'Inter', system-ui, sans-serif;",
        "radius": "rounded-2xl",
        "image_words": "product,technology,gadget",
    },
    "agency": {
        "mode": "dark",
        "vibe": "bold agency energy, high-contrast statements",
        "tw": {
            "page_bg": "bg-zinc-950",
            "surface": "bg-zinc-900",
            "surface_2": "bg-zinc-800",
            "heading_text": "text-zinc-50",
            "body_text": "text-zinc-300",
            "muted_text": "text-zinc-500",
            "primary": "bg-amber-400",
            "primary_hover": "hover:bg-amber-300",
            "on_primary": "text-zinc-950",
            "border": "border-zinc-800",
            "accent_text": "text-amber-400",
            "accent_bg": "bg-amber-950",
            "gradient": "from-amber-400 to-orange-500",
        },
        "fonts": {"heading": "Space Grotesk", "body": "Inter"},
        "font_query": "Space+Grotesk:wght@400;500;600;700&family=Inter:wght@400;500;600",
        "heading_css": "font-family: 'Space Grotesk', system-ui, sans-serif;",
        "body_css": "font-family: 'Inter', system-ui, sans-serif;",
        "radius": "rounded-xl",
        "image_words": "agency,office,creative,team",
    },
    # saas + generic: modern light product design (Linear/Stripe style), NOT
    # the old dark-indigo-everything default.
    "saas": {
        "mode": "light",
        "vibe": "modern product, crisp, conversion-focused",
        "tw": {
            "page_bg": "bg-white",
            "surface": "bg-slate-50",
            "surface_2": "bg-slate-100",
            "heading_text": "text-slate-900",
            "body_text": "text-slate-600",
            "muted_text": "text-slate-500",
            "primary": "bg-indigo-600",
            "primary_hover": "hover:bg-indigo-700",
            "on_primary": "text-white",
            "border": "border-slate-200",
            "accent_text": "text-indigo-600",
            "accent_bg": "bg-indigo-50",
            "gradient": "from-indigo-500 to-violet-600",
        },
        "fonts": {"heading": "Inter", "body": "Inter"},
        "font_query": "Inter:wght@400;500;600;700;800;900",
        "heading_css": "font-family: 'Inter', system-ui, sans-serif;",
        "body_css": "font-family: 'Inter', system-ui, sans-serif;",
        "radius": "rounded-2xl",
        "image_words": "technology,workspace,team",
    },
}
THEMES["generic"] = THEMES["saas"]


def get_design(brief: dict | None) -> dict:
    """Pick the theme for a brief and add the derived bits (slug for image
    seeds, mode helpers)."""
    import domain_profiles
    key = domain_profiles.detect_domain(brief)
    theme = dict(THEMES.get(key) or THEMES["generic"])
    theme["key"] = key
    name = ((brief or {}).get("name") or "site").lower()
    theme["seed"] = "".join(ch for ch in name if ch.isalnum()) or key
    return theme


# ---------------------------------------------------------------- overrides

_HEX_RE = re.compile(r"#(?:[0-9a-fA-F]{3}){1,2}\b")
_COLOR_WORDS = {
    "red": "#dc2626", "orange": "#ea580c", "amber": "#d97706",
    "yellow": "#ca8a04", "lime": "#65a30d", "green": "#16a34a",
    "emerald": "#059669", "teal": "#0d9488", "cyan": "#0891b2",
    "sky": "#0284c7", "blue": "#2563eb", "indigo": "#4f46e5",
    "violet": "#7c3aed", "purple": "#9333ea", "fuchsia": "#c026d3",
    "pink": "#db2777", "rose": "#e11d48", "black": "#0a0a0a",
}


def _shade(hex_color: str, factor: float) -> str:
    """Darken (factor<1) or lighten (factor>1) a hex color."""
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    if factor <= 1:
        r, g, b = (int(c * factor) for c in (r, g, b))
    else:
        r, g, b = (min(255, int(c + (255 - c) * (factor - 1))) for c in (r, g, b))
    return f"#{r:02x}{g:02x}{b:02x}"


def build_custom_theme(primary_hex: str, mode: str = "light",
                       font_pair: tuple[str, str] | None = None) -> dict:
    """A full theme built FROM the user's color (arbitrary-value Tailwind
    classes, which the CDN compiler handles natively). This is how explicit
    user brand colors are honored exactly rather than approximately."""
    p = primary_hex if primary_hex.startswith("#") else f"#{primary_hex}"
    if mode == "dark":
        tw = {
            "page_bg": f"bg-[{_shade(p, 0.12)}]",
            "surface": f"bg-[{_shade(p, 0.18)}]",
            "surface_2": f"bg-[{_shade(p, 0.24)}]",
            "heading_text": "text-white",
            "body_text": "text-gray-300",
            "muted_text": "text-gray-500",
            "primary": f"bg-[{p}]",
            "primary_hover": f"hover:bg-[{_shade(p, 1.15)}]",
            "on_primary": "text-white",
            "border": f"border-[{_shade(p, 0.30)}]",
            "accent_text": f"text-[{_shade(p, 1.5)}]",
            "accent_bg": f"bg-[{_shade(p, 0.30)}]",
            "gradient": f"from-[{p}] to-[{_shade(p, 0.7)}]",
        }
    else:
        tw = {
            "page_bg": "bg-white",
            "surface": f"bg-[{_shade(p, 8.5)}]",
            "surface_2": f"bg-[{_shade(p, 7)}]",
            "heading_text": "text-gray-900",
            "body_text": "text-gray-600",
            "muted_text": "text-gray-500",
            "primary": f"bg-[{p}]",
            "primary_hover": f"hover:bg-[{_shade(p, 0.85)}]",
            "on_primary": "text-white",
            "border": "border-gray-200",
            "accent_text": f"text-[{p}]",
            "accent_bg": f"bg-[{_shade(p, 9)}]",
            "gradient": f"from-[{p}] to-[{_shade(p, 0.75)}]",
        }
    heading_font, body_font = font_pair or ("Inter", "Inter")
    return {
        "mode": mode, "vibe": "customized to the user's explicit brand",
        "tw": tw, "fonts": {"heading": heading_font, "body": body_font},
        "font_query": (
            f"{heading_font.replace(' ', '+')}:wght@400;500;600;700;800&family="
            f"{body_font.replace(' ', '+')}:wght@400;500;600;700"),
        "heading_css": f"font-family: '{heading_font}', Georgia, serif;",
        "body_css": f"font-family: '{body_font}', system-ui, sans-serif;",
        "radius": "rounded-2xl", "image_words": "",
        "custom": True, "custom_primary": p,
    }


def extract_design_prefs(prompt: str) -> dict:
    """Parse EXPLICIT design requests from the user's own words.

    These are commitments, not hints: when the user says "use purple" or
    "no animations" the output must comply. Returns {} when nothing
    design-specific was asked.
    """
    low = prompt.lower()
    prefs: dict = {}
    m = _HEX_RE.search(prompt)
    if m:
        prefs["primary"] = m.group(0)
    else:
        m = re.search(
            r"\b(?:use|make|with|in|brand(?:ed)?(?:\s+color)?|color|theme)\s+"
            r"(red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|"
            r"indigo|violet|purple|fuchsia|pink|rose|black)\b", low)
        if not m:
            # "make it purple", "go green", "everything should be blue"
            m = re.search(
                r"\b(?:make|go|turn|paint)\s+(?:it|them|everything|the site|"
                r"the website|the theme|it all)\s+"
                r"(red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|"
                r"blue|indigo|violet|purple|fuchsia|pink|rose|black)\b", low)
        if not m:
            m = re.search(
                r"\b(red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|"
                r"blue|indigo|violet|purple|fuchsia|pink|rose|black)\s+"
                r"(?:color scheme|color palette|theme|color|palette)\b", low)
        if m:
            prefs["primary"] = _COLOR_WORDS[m.group(1)]
            prefs["primary_word"] = m.group(1)
    if re.search(r"\b(dark ?mode|dark theme|make it dark|dark website)\b", low):
        prefs["mode"] = "dark"
    elif re.search(r"\b(light ?mode|light theme|make it light)\b", low):
        prefs["mode"] = "light"
    if re.search(r"\b(no|without|disable|remove)\s+(animations?|motion|scroll\s+effects?)\b", low):
        prefs["animation"] = "none"
    elif re.search(r"\b(add|with|some|little|bit of)\s+animations?\b", low) \
            or re.search(r"\b(very|really|highly|super|lots of|rich|heavy)\s+"
                         r"(animated|animations?)\b", low):
        prefs["animation"] = "rich"
    for font in ("Playfair Display", "Montserrat", "Inter", "Space Grotesk",
                 "Oswald", "Merriweather", "Poppins", "Roboto"):
        if font.lower() in low:
            prefs["font"] = font
            break
    return prefs


def apply_overrides(design: dict, prefs: dict) -> dict:
    """Apply user design prefs over the domain theme (user wins)."""
    if not prefs:
        return design
    out = dict(design)
    if prefs.get("primary"):
        custom = build_custom_theme(
            prefs["primary"], prefs.get("mode", design["mode"]),
            (prefs["font"], prefs.get("font", design["fonts"]["body"]))
            if prefs.get("font") else None)
        custom["key"] = design["key"]
        custom["seed"] = design["seed"]
        out = custom
    elif prefs.get("font"):
        out = dict(design)
        out["fonts"] = {"heading": prefs["font"], "body": design["fonts"]["body"]}
        out["font_query"] = (
            f"{prefs['font'].replace(' ', '+')}:wght@400;500;600;700;800&family="
            f"{design['fonts']['body'].replace(' ', '+')}:wght@400;500;600;700")
        out["heading_css"] = f"font-family: '{prefs['font']}', Georgia, serif;"
    if prefs.get("mode") and "custom" not in out:
        out = dict(out)
        out["mode"] = prefs["mode"]
    out["user_prefs"] = prefs
    if prefs.get("animation") is not None:
        out["animation"] = prefs["animation"]
    return out


def design_block(design: dict, name: str = "") -> str:
    """The exact-class DESIGN SYSTEM text injected into every file ask.

    A 7B follows literal class mandates far better than vibes ("design
    premium"), and every file receiving the SAME mandates is what unifies
    the page -- the live failure was each file inventing its own palette.
    """
    tw = design["tw"]
    slug = design["seed"]
    words = design["image_words"]
    lines = [
        "DESIGN SYSTEM -- follow EXACTLY. Use ONLY these colors/classes for",
        "backgrounds, text, buttons and borders. Do NOT invent other colors",
        "and do NOT mix light and dark sections:",
        f"- Page background: {tw['page_bg']} | Cards: {tw['surface']} with",
        f"  {tw['border']} and {design['radius']} and soft shadow-md/shadow-xl.",
        f"- Headings: {tw['heading_text']} (use the font-display CSS class).",
        f"- Body text: {tw['body_text']} | Muted: {tw['muted_text']}.",
        f"- Primary buttons: {tw['primary']} {tw['primary_hover']}",
        f"  {tw['on_primary']} {design['radius']}.",
        f"- Accents: {tw['accent_text']} on {tw['accent_bg']}.",
        f"- One gradient allowed (sparingly, hero/CTA only): bg-gradient-to-br",
        f"  {tw['gradient']}.",
        "- Icons: lucide-react only, same stroke style throughout",
        "  (strokeWidth={1.75}, className='w-5 h-5').",
        "- Typography rhythm: sections py-20 or more, max-w-6xl mx-auto px-6",
        "  containers, large bold headings (text-4xl/5xl), generous spacing.",
        "- Taste rules: no neon colors, no purple-pink gradients (unless they",
        "  are THE gradient above), no dark sections on a light page, no",
        "  global * { margin: 0 } resets.",
        f"- Imagery: for photo areas use <img src=\"https://picsum.photos/seed/{slug}/1600/900\"",
        f"  /> (real photography) with a colored overlay -- never empty boxes.",
        f"- Mood: {design['vibe']}.",
    ]
    if name:
        lines.append(f"- Brand: use the name \"{name}\" verbatim in nav/hero/footer.")
    prefs = design.get("user_prefs") or {}
    anim = design.get("animation", "standard")
    if anim == "none":
        lines.append("- Animations: the user asked for NO animations. Do not add"
                     " reveal/animate classes or transitions beyond hover colors.")
    elif anim == "rich":
        lines.append("- Animations: the user asked for RICH animation. Use the"
                     " .reveal/.reveal-visible scroll-reveal on every section,"
                     " staggered animate-fade-up on cards (animation-delay per"
                     " index), hover:-translate-y-1 + shadow growth on cards,")
        lines.append("  and one ambient float/marquee element. Keep it smooth"
                     " (transform/opacity only, duration-300/700).")
    else:
        # The default path. Without explicit class mandates a 7B ships dead
        # static markup, which is what makes the output read as "template"
        # next to Bolt/Lovable. These are the same micro-interactions every
        # polished site has, stated as literal classes it can copy.
        lines.append("- Motion (REQUIRED, even if the user didn't ask): every"
                     " interactive element animates.")
        lines.append("  * Cards and tiles: 'transition-all duration-300"
                     " hover:-translate-y-1 hover:shadow-xl'.")
        lines.append("  * Buttons and links: 'transition-all duration-200"
                     " active:scale-[0.97]' plus a hover color/shadow change.")
        lines.append("  * Images inside a card: wrap in 'overflow-hidden' and give"
                     " the img 'transition-transform duration-500"
                     " group-hover:scale-105' (add 'group' to the card).")
        lines.append("  * Entrance: wrap each section's inner container in the"
                     " Reveal component if it is available; otherwise add"
                     " 'animate-fade-up' to the section heading.")
        lines.append("  * Lists/grids: stagger with style={{ animationDelay:"
                     " `${i * 80}ms` }} on each item.")
        lines.append("  * Animate transform and opacity ONLY (never width/height/"
                     "top/left); durations 200-700ms; ease-out.")
    if prefs.get("primary_word"):
        lines.append(f"- USER REQUIREMENT: the brand color is"
                     f" {prefs['primary_word']} ({prefs['primary']}) -- the"
                     " primary button and accents MUST use it.")
    elif prefs.get("primary"):
        lines.append(f"- USER REQUIREMENT: the brand color is {prefs['primary']}"
                     " (use bg-[...] / text-[...] arbitrary classes exactly).")
    if prefs.get("font"):
        lines.append(f"- USER REQUIREMENT: headings use the '{prefs['font']}'"
                     " font (the .font-display class already loads it).")
    if prefs.get("mode"):
        lines.append(f"- USER REQUIREMENT: the site is {prefs['mode']}-mode;"
                     " every section follows that mode.")
    return "\n".join(lines)


def font_link(design: dict) -> str:
    return (f"https://fonts.googleapis.com/css2?family={design['font_query']}"
            "&display=swap")
