"""Deterministic motion enrichment: give static markup real micro-interactions.

Why this exists: even with strong design-system guidance a 7B still ships
plenty of dead static markup -- cards that don't react to hover, buttons with
no press feedback, images that don't move. That reads as "template" next to
Bolt/Lovable output no matter how good the palette is. Prompting for motion
helps but is not a guarantee, so this pass makes the baseline mechanical.

It only ever ADDS classes (never removes or reorders), so it cannot break a
layout that was already correct, and it is idempotent: anything that already
has a `transition` utility is left untouched.

Rules (plain string `className=` attributes only -- template literals are
skipped, they are where conditional class logic lives and must not be edited):

  cards    rounded + bg + padding, no transition
           -> transition-all duration-300 hover:-translate-y-1 hover:shadow-xl
  buttons  <button>/<a> with bg + rounded, no transition
           -> transition-all duration-200 active:scale-[0.97]
  images   <img object-cover>, no transition
           -> transition-transform duration-500

Skipped: html/body/svg/meta tags and anything positioned or sized as a layout
container (fixed/absolute/sticky/min-h-screen), because a hover lift there is
either invisible or actively wrong.
"""
from __future__ import annotations

import re

# Tags whose className must never be touched.
_SKIP_TAGS = {
    "html", "body", "head", "script", "style", "link", "meta", "title",
    "svg", "path", "defs", "g", "circle", "rect", "line", "polyline", "symbol",
    "use", "clippath", "lineargradient", "stop",
}

# Class tokens that mean "this is a layout container, not a card".
_NEVER_LIFT = re.compile(
    r"\b(min-h-screen|min-h-full|h-screen|fixed|absolute|sticky|inset-0"
    r"|overflow-hidden|overflow-y-auto|overflow-x-auto)\b"
)

_CLASSNAME_RE = re.compile(r"""className=("([^"]*)"|'([^']*)')""")
_TAG_OPEN_RE = re.compile(r"<\s*([A-Za-z][\w.$:]*)")
_HAS_TRANSITION = re.compile(r"\btransition\b|\btransition-")
_HAS_ROUNDED = re.compile(r"\brounded(?:-[a-z0-9\[\]#.,%/-]+)?\b")
_HAS_BG = re.compile(r"\bbg-(?!gradient|clip|none|transparent)[a-z0-9\[\]#(/.,%-]+")
_HAS_PAD = re.compile(r"\bp[xytrbl]?-(?:\d|\[)")
_HAS_HOVER_MOTION = re.compile(r"\bhover:(?:-?translate|-?scale|-?rotate)")

CARD_CLASSES = "transition-all duration-300 hover:-translate-y-1 hover:shadow-xl"
BUTTON_CLASSES = "transition-all duration-200 active:scale-[0.97]"
IMAGE_CLASSES = "transition-transform duration-500"


def _tag_for(content: str, pos: int) -> str:
    """Name of the element whose opening tag contains this className.

    Attributes may precede className (`<div id="x" className="...">`), so
    walk back to the nearest `<` and reject the match if a `>` sits between
    (meaning we are in children/text, not inside a tag).
    """
    lt = content.rfind("<", 0, pos)
    if lt < 0:
        return ""
    if content.rfind(">", lt, pos) > lt:
        return ""
    m = _TAG_OPEN_RE.match(content[lt:pos])
    return m.group(1) if m else ""


def _kind(tag: str, cls: str) -> str | None:
    """Which enhancement (if any) this element should receive."""
    if tag.lower() in _SKIP_TAGS:
        return None
    if _HAS_TRANSITION.search(cls):
        return None
    if _NEVER_LIFT.search(cls):
        # Layout containers may still be buttons worth a press state.
        if tag == "button" and _HAS_BG.search(cls) and _HAS_ROUNDED.search(cls):
            return "button"
        return None
    if tag == "button" and _HAS_BG.search(cls) and _HAS_ROUNDED.search(cls):
        return "button"
    if tag in ("a", "Link", "NavLink") and _HAS_BG.search(cls) and _HAS_ROUNDED.search(cls):
        return "button"
    if tag == "img":
        if re.search(r"\bobject-cover\b", cls):
            return "image"
        return None
    # A card: a real surface (rounded + bg + padding) that doesn't move yet.
    if _HAS_ROUNDED.search(cls) and _HAS_BG.search(cls) and _HAS_PAD.search(cls):
        if _HAS_HOVER_MOTION.search(cls):
            return None  # already reactive in its own way
        return "card"
    return None


_STATS_KEY = {"card": "cards", "button": "buttons", "image": "images"}


def enrich(content: str, level: str = "standard") -> tuple[str, dict]:
    """Return (new_content, stats). Adds only; idempotent when level != 'none'."""
    stats = {"cards": 0, "buttons": 0, "images": 0, "total": 0}
    if level == "none" or "className" not in content:
        return content, stats

    pieces: list[str] = []
    last = 0
    for m in _CLASSNAME_RE.finditer(content):
        quote = m.group(1)[0]
        cls = m.group(2) if quote == '"' else m.group(3)
        if cls is None:
            continue
        tag = _tag_for(content, m.start())
        kind = _kind(tag, cls)
        if kind is None:
            continue
        extra = {"card": CARD_CLASSES, "button": BUTTON_CLASSES, "image": IMAGE_CLASSES}[kind]
        # replace exactly the matched attribute: keep everything before it,
        # emit the enriched attribute, then continue after the match.
        pieces.append(content[last:m.start()])
        new_cls = cls.rstrip() + (" " if cls.strip() else "") + extra
        pieces.append(f"className={quote}{new_cls}{quote}")
        last = m.end()
        stats[_STATS_KEY[kind]] += 1
        stats["total"] += 1

    if not pieces:
        return content, stats
    pieces.append(content[last:])
    return "".join(pieces), stats


def enrich_files(files: dict, level: str = "standard") -> tuple[dict, dict]:
    """Apply the enrichment across every jsx/tsx file. Returns (files, totals)."""
    total = {"cards": 0, "buttons": 0, "images": 0, "total": 0}
    out: dict[str, str] = {}
    for path, content in files.items():
        if path.endswith((".jsx", ".tsx")):
            new, stats = enrich(content, level)
            for k in total:
                total[k] += stats[k]
            out[path] = new
        else:
            out[path] = content
    return out, total
