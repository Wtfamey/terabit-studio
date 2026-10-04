"""Deterministic style enforcement: rewrite off-palette Tailwind classes.

The product goal is frontier-grade design on EVERY archetype (landing pages,
websites, full SaaS) without depending on a 7B's style judgment. The design
system already picks the exact palette per domain; this module enforces it on
model output: every color utility class that does not belong to the theme's
families is mapped to the nearest theme family. Style compliance stops being a
prayer and becomes a post-processing step -- instant, guaranteed, testable.

Mapping rules (v2's live failure: indigo/violet/purple/pink everywhere):
  - neon families (indigo/violet/purple/fuchsia/pink) -> theme primary
  - blue -> primary (law's primary IS blue, so it maps to itself)
  - teal/cyan -> accent if the theme accent is teal-ish, else primary
  - rose/orange -> accent
  - yellow/green -> amber/emerald semantics stay (status colors)
  - neutral families (slate/zinc/neutral/stone/gray) map to the theme's own
    neutral family so a stone restaurant never renders slate text
  - dark section backgrounds (bg-*-900/950) on a LIGHT theme collapse to the
    theme's primary/deep tone (kills the half-dark-half-light page bug)
  - light backgrounds (bg-white/bg-*-50/100) on a DARK theme map to surface
  - theme families pass through untouched; white/black/transparent/current
    and semantic status colors (emerald/red/amber) are always kept

The rewriter is idempotent and preserves shade numbers (indigo-500 on a
restaurant becomes amber-500; the design block then forbids further drift).
"""
import re

# Tailwind color families grouped by how they should re-map.
_NEONS = ("indigo", "violet", "purple", "fuchsia", "pink")
_NEUTRALS = ("slate", "zinc", "neutral", "stone", "gray")
_DARKS = ("slate", "zinc", "neutral", "stone", "gray")

_CLASS_RE = re.compile(
    r"\b((?:bg|text|from|via|to|border|ring|fill|stroke|placeholder|decoration|divide|outline|shadow|accent|caret)-)"
    r"([a-z]+)-(\d{2,3})\b"
)
_FLAT_CLASS_RE = re.compile(
    r"\b((?:bg|text|border|ring)-)(white|black)\b"
)


def _theme_families(theme: dict) -> dict:
    """Extract the theme's primary/accent/neutral families from its tokens."""
    tw = theme["tw"]

    def fam(cls: str) -> str:
        m = re.match(r"(?:bg|text|border)-([a-z]+)", cls)
        if m and m.group(1) not in ("white", "black", "transparent", "current"):
            return m.group(1)
        # arbitrary hex (bg-[#faf6f0]) -> neutral-ish marker
        return "#hex"

    primary = fam(tw["primary"])
    accent = fam(tw["accent_text"])
    g = re.search(r"from-([a-z]+)", tw["gradient"])
    t = re.search(r"to-([a-z]+)", tw["gradient"])
    grad_from = g.group(1) if g else primary
    grad_to = t.group(1) if t else accent
    page = fam(tw["page_bg"])
    return {
        "primary": primary, "accent": accent,
        "grad_from": grad_from, "grad_to": grad_to,
        "page": page, "hex": "#hex" in (page + primary),
    }


def rewrite(content: str, theme: dict) -> tuple[str, dict]:
    """Return (new_content, stats). Idempotent."""
    fams = _theme_families(theme)
    primary = fams["primary"]
    accent = fams["accent"]
    stats = {"rewritten": 0, "examples": []}

    def map_family(fam: str, shade: str, util: str) -> str:
        # theme-aware family mapping
        if fam == primary or fam == accent:
            return fam
        if fam in _NEONS:
            return accent if util.startswith("text") and shade in ("300", "400") else primary
        if fam == "blue":
            return primary
        if fam in ("teal", "cyan"):
            return accent if accent in ("teal", "cyan", "sky") else primary
        if fam in ("rose", "orange"):
            return accent if accent in ("rose", "orange", "amber") else primary
        if fam in ("yellow", "lime", "green"):
            return fam if fam in ("lime",) and primary == "lime" else ("emerald" if fam == "green" else fam)
        if fam in _NEUTRALS:
            theme_neutral = primary if primary in _NEUTRALS else (
                re.match(r"(?:bg|text)-([a-z]+)", theme["tw"]["body_text"]).group(1))
            return theme_neutral if theme_neutral in _NEUTRALS else fam
        return fam  # semantic (emerald/red/amber/sky) and unknowns stay

    # Theme-gradient class strings are protected: the class pass must not
    # rewrite to-orange-800 (part of the restaurant gradient) to amber-800,
    # or the gradient pass then rewrites it back -> infinite oscillation.
    # NOTE: the gradient-normalization pass runs FIRST (below) so neon chains
    # collapse to the theme gradient before the class pass can fragment them
    # (live: indigo/purple/pink chain got class-rewritten to all-amber).
    _grad_re = re.compile(r"((?:from|via|to))-([a-z]+)-(\d{2,3})\b")
    protected = {m.group(0) for m in _grad_re.finditer(theme["tw"]["gradient"])}

    # -- gradient normalization (FIRST) --
    _target_grad = (f"bg-gradient-to-br from-{fams['grad_from']}-700 "
                    f"to-{fams['grad_to']}-800")
    _grad_inner_re = re.compile(r"(?:from|via|to)-([a-z]+)-\d{2,3}")
    def grad_repl(m: re.Match) -> str:
        chain = m.group(0)
        chain_fams = set(_grad_inner_re.findall(chain))
        if chain_fams and chain_fams <= {fams['grad_from'], fams['grad_to']}:
            return chain
        return _target_grad
    _grad_count = [0]
    def _counting_grad(m: re.Match) -> str:
        out = grad_repl(m)
        if out != m.group(0):
            _grad_count[0] += 1
        return out
    content, _n = re.subn(
        r"bg-gradient-to-[a-z]+\s+(?:from|via|to)-[a-z]+-\d{2,3}(?:\s+(?:from|via|to)-[a-z]+-\d{2,3}){1,2}",
        _counting_grad, content)
    if _grad_count[0]:
        stats["rewritten"] += _grad_count[0]
        stats["examples"].append("gradient->theme")

    def cls_repl(m: re.Match) -> str:
        util, fam, shade = m.group(1), m.group(2), m.group(3)
        if m.group(0) in protected:
            return m.group(0)
        new_fam = map_family(fam, shade, util)
        if new_fam != fam:
            stats["rewritten"] += 1
            if len(stats["examples"]) < 6:
                stats["examples"].append(f"{fam}-{shade}->{new_fam}-{shade}")
            return f"{util}{new_fam}-{shade}"
        return m.group(0)

    content = _CLASS_RE.sub(cls_repl, content)

    # White borders/dividers on a light theme are invisible; map them to the
    # theme border family (dark themes keep white/N-alpha hairlines).
    mode = theme["mode"]
    if mode == "light":
        border_fam = re.match(r"border-([a-z]+)", theme["tw"]["border"]).group(1)
        def border_repl(m: re.Match) -> str:
            stats["rewritten"] += 1
            return f"{m.group(1)}-{border_fam}-200"
        content, _ = re.subn(
            r"\b(border|divide)-(white|black)\b(?![/-])", border_repl, content)
        content, _ = re.subn(
            r"\b(border|divide)-white\/\d+\b",
            lambda m: (stats.__setitem__("rewritten", stats["rewritten"] + 1),
                       f"{m.group(1)}-{border_fam}-200")[1], content)
        # White-alpha glass cards (bg-white/5, the v2 dark-glass habit) read
        # as gray veils on a light page -> the theme's real surface class
        # (verbatim token, so arbitrary-value surfaces work too).
        surface_cls = theme["tw"]["surface_2"]
        content, _ = re.subn(
            r"\bbg-white\/\d+\b",
            lambda m: (stats.__setitem__("rewritten", stats["rewritten"] + 1),
                       surface_cls)[1], content)
        # Light text (white, white-alpha, or neutral-100..400) on a light
        # theme is unreadable -> body text color. (Dark themes keep light
        # text.) On-primary white text is safe: bg-*-800/900 implies the
        # theme primary, and amber-50-family is theme-native (kept by the
        # allowed-family pass, not this one).
        body_cls = theme["tw"]["body_text"]
        content, _ = re.subn(
            r"\btext-(?:white\/\d+|slate|zinc|neutral|stone|gray)-(?:100|200|300|400)\b",
            lambda m: (stats.__setitem__("rewritten", stats["rewritten"] + 1),
                       body_cls)[1], content)
        content, _ = re.subn(
            r"\btext-white\b(?![^\"']*(?:font-black|font-bold))",
            lambda m: (stats.__setitem__("rewritten", stats["rewritten"] + 1),
                       body_cls)[1], content)
        # Dark sections on a light theme -> primary deep tone.
        def dark_repl(m: re.Match) -> str:
            stats["rewritten"] += 1
            return f"{m.group(1)}-{primary}-900"
        content, _ = re.subn(
            r"\b(bg)-(?:slate|zinc|neutral|stone|gray)-9[05]0\b", dark_repl, content)
    else:
        def light_repl(m: re.Match) -> str:
            stats["rewritten"] += 1
            return f"{m.group(1)}-{theme['tw']['surface'].split('-')[1]}-900"
        content, _ = re.subn(r"\b(bg)-white\b", light_repl, content)

    # -- frosted-panel translucency (LAST: the passes above can leave an
    # opaque fill behind a backdrop-blur, which is self-contradictory -- the
    # blur is invisible and image-led cards render as flat gray slabs over
    # their photos (live: portfolio work cards 20260930-174958,
    # `bg-stone-100 ... backdrop-blur-xl` hiding every project image). The
    # model's intent is frosted glass, so give the fill an alpha whenever the
    # same className also blurs; an existing alpha is left alone. --
    _FB_BG_RE = re.compile(
        r"\b(bg-(?:white|black|[a-z]+-\d{2,3}))(?![/\w])(?=[^\"']*backdrop-blur)"
    )
    _fh_count = [0]

    def _frost_classname(m: re.Match) -> str:
        blk = m.group(0)
        bm = _FB_BG_RE.search(blk)
        if not bm:
            return blk
        _fh_count[0] += 1
        return blk.replace(bm.group(1), bm.group(1) + "/70", 1)

    content = re.sub(
        r"className=(\"[^\"]*backdrop-blur[^\"]*\"|'[^']*backdrop-blur[^']*')",
        _frost_classname,
        content,
    )
    if _fh_count[0]:
        stats["rewritten"] += _fh_count[0]
        if len(stats["examples"]) < 6:
            stats["examples"].append(f"{_fh_count[0]} frosted panel(s) -> /70")

    # Display-font pass: headings must use the theme's display face. Landing
    # shells get .font-display via composition; model-authored webapp files
    # never did (live: coffee-store gate FAIL, font_used=false, everything
    # rendered in Inter -- part of the "looks like a template" report).
    _fd_count = [0]

    def _add_font_display(m: re.Match) -> str:
        tag, attrs = m.group(1), m.group(2)
        cm = re.search(r"className=(\"([^\"]*)\"|\{`([^`]*)`\}|\{\"([^\"]*)\"\})", attrs)
        if cm:
            cls = cm.group(2) or cm.group(3) or cm.group(4) or ""
            if "font-display" in cls:
                return m.group(0)
            new_attrs = attrs.replace(cm.group(0), cm.group(0).replace(cls, f"font-display {cls}"), 1)
        else:
            new_attrs = attrs + ' className="font-display"'
        _fd_count[0] += 1
        return f"<{tag}{new_attrs}>"

    content = re.sub(r"<(h[1-4])([^>]*)>", _add_font_display, content)
    if _fd_count[0]:
        stats["rewritten"] += _fd_count[0]
        if len(stats["examples"]) < 6:
            stats["examples"].append(f"{_fd_count[0]} heading(s) -> font-display")

    return content, stats


def enforce_files(files: dict, theme: dict) -> tuple[dict, dict]:
    """Rewrite every jsx/tsx file in the fileset. Returns (files, total_stats)."""
    total = {"rewritten": 0, "examples": []}
    out = {}
    for path, content in files.items():
        if path.endswith((".jsx", ".tsx")):
            new, stats = rewrite(content, theme)
            total["rewritten"] += stats["rewritten"]
            total["examples"] += stats["examples"]
            out[path] = new
        else:
            out[path] = content
    return out, total
