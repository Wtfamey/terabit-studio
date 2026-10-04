"""Deterministic imagery enforcement.

Live evidence (Casa Verde v3 run 20260930-145031): the model filled dish-card
galleries with `picsum.photos/...?grayscale&blur=2` URLs -- they load fine but
render as gray blurred rectangles on a warm cream card (the user read them as
"broken images"), and data arrays carried literal empty-string image fields
(`<img src={item.image}>` with `image: ''`) that render as dead image boxes.
This module rewrites those deterministically to curated, curl-verified
Unsplash photos matched to the site's domain, so preview imagery is warm and
on-type without depending on the model's taste.

Scope guards (learned the hard way):
- Attribute-level replacement only -- never removes or restructures JSX, so
  ternary structure cannot break.
- A literal `src=""` attribute is LEFT ALONE: the shell renders it inside a
  `LOGO_URL ? <img/> : <monogram/>` ternary where an empty string is the
  intended falsy value -- filling it would show a random photo as a logo.
- Data-array image FIELDS (image: '') ARE filled: they feed real content imgs.

All pool IDs verified HTTP 200 against images.unsplash.com on 2026-09-30.
"""

from __future__ import annotations

import hashlib
import re

# ── Domain image pools (every id verified 200) ──────────────────────────────
_POOLS: dict[str, list[str]] = {
    "restaurant": [
        "1504674900247-0877df9cc836", "1414235077428-338989a2e8c0",
        "1517248135467-4c7edcad34c4", "1555396273-367ea4eb4db5",
        "1546069901-ba9599a7e63c", "1565299624946-b28f40a0ae38",
        "1551218808-94e220e084d2", "1621996346565-e3dbc646d9a9",
        "1551183053-bf91a1d81141", "1510812431401-41d2bd2722f3",
        "1568213816046-0ee1c42bd559", "1476224203421-9ac39bcb3327",
        "1467003909585-2f8a72700288", "1540189549336-e6e99c3679fe",
        "1565958011703-44f9829ba187", "1482049016688-2d3e1b311543",
    ],
    "office": [
        "1497366216548-37526070297c", "1498050108023-c5249f4df085",
        "1522071820081-009f0129c71c", "1551288049-bebda4e38f71",
        "1467232004584-a241de8bcf5d", "1556905055-8f358a7a47b2",
        "1521587760476-6c12a4b040da", "1505664194779-8beaceb93744",
    ],
    "medical": [
        "1576091160399-112ba8d25d1d", "1579684385127-1ef15d508118",
    ],
    "retail": [
        "1441984904996-e0b6ba687e04", "1483985988355-763728e1935b",
        "1555529669-e69e7aa0ba9a", "1441986300917-64674bd600d8",
    ],
    "gym": [
        "1534438327276-14e5300c3a48", "1571019613454-1cb2f99b2d8b",
    ],
    "home": [
        "1560518883-ce09059eeffa", "1570129477492-45c003edd2be",
    ],
    "education": [
        "1523050854058-8df90110c9f1", "1523240795612-9a054b0db644",
        "1427504494785-3a9ca7044f45", "1571260899304-425eee4c7efc",
    ],
    "gallery": [
        "1541961017774-22349e4a1262", "1513364776144-60967b0f800f",
        "1554907984-15263bfd63bd", "1460661419201-fd4cecdf8a8b",
    ],
}
# design theme key -> pool
_THEME_POOL = {
    "restaurant": "restaurant", "law": "office", "hospital": "medical",
    "fashion": "retail", "art": "gallery", "fitness": "gym",
    "realestate": "home", "education": "education", "portfolio": "gallery",
    "product": "office", "agency": "office", "saas": "office",
    "business": "office", "ecommerce": "retail", "analytics": "office",
}
_GENERIC_POOL = _POOLS["office"]

_IMG_TAG_RE = re.compile(r"<img\b[^>]*>")
_SRC_ATTR_RE = re.compile(r"""src=("[^"]*"|'[^']*'|\{[^{}]*\})""")
_ALT_ATTR_RE = re.compile(r"""alt=("([^"]*)"|'([^']*)')""")

_PLACEHOLDER_HOSTS = (
    "picsum.photos", "placehold.it", "placehold.co",
    "via.placeholder.com", "dummyimage.com", "source.unsplash.com",
)


# Free-text keywords for non-key inputs (main.py passes the brief's domain
# LABEL, e.g. "Italian Restaurant", not the theme key). Order matters.
_POOL_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("restaurant", ("restaurant", "ristorante", "trattoria", "pizzeria",
                    "pizza", "cafe", "caf\u00e9", "bistro", "bakery", "dining",
                    "food", "wine", "kitchen", "grill", "sushi", "catering",
                    "coffee", "culinary")),
    ("medical", ("hospital", "clinic", "medical", "dental", "dentist",
                 "health", "veterinar", "doctor", "care", "therapy")),
    ("gym", ("fitness", "gym", "yoga", "pilates", "crossfit")),
    ("home", ("real estate", "realty", "property", "homes", "housing",
              "interior", "construction", "roofing", "plumb", "hvac",
              "landscap", "architecture")),
    ("education", ("school", "academy", "education", "tutor", "learning",
                   "college", "university", "courses")),
    ("retail", ("fashion", "boutique", "apparel", "clothing", "salon",
                "store", "shop", "ecommerce", "jewel", "beauty", "spa")),
    ("gallery", ("portfolio", "photograph", "agency", "studio", "creative",
                 "art", "design", "gallery", "film", "media")),
]


def _pool_for(design_key: str | None) -> list[str]:
    k = (design_key or "").strip().lower()
    if k in _THEME_POOL:
        return _POOLS[_THEME_POOL[k]]
    for pool_name, words in _POOL_KEYWORDS:
        if any(w in k for w in words):
            return _POOLS[pool_name]
    return _GENERIC_POOL


def _pick(pool: list[str], seed: str, used: set[str]) -> str:
    """Deterministic id from md5(seed), avoiding ids already used this run."""
    for i in range(64):
        h = hashlib.md5(f"{seed}:{i}".encode()).hexdigest()
        pid = pool[int(h, 16) % len(pool)]
        if pid not in used:
            used.add(pid)
            return pid
    return pool[0]


def _literal_of(src_value: str) -> str | None:
    """Inner string of a src attr IF it is a string literal, else None.

    src="x" / src='x' -> 'x';  src={'x'} -> 'x';  src={EXPR} -> None.
    """
    v = src_value.strip()
    if v.startswith(('"', "'")):
        return v[1:-1]
    if v.startswith("{"):
        inner = v[1:-1].strip()
        if len(inner) >= 2 and inner[0] in "'\"" and inner[-1] == inner[0]:
            return inner[1:-1]
        return None  # expression (e.g. {LOGO_URL}, {item.image}) -- keep
    return None


def _is_bad_url(url: str) -> bool:
    u = url.strip().lower()
    if u in ("", "placeholder", "#"):
        return False  # empty attr: see module docstring -- intentionally kept
    if u.startswith(("http://", "https://")):
        return any(h in u.split("/", 2)[-1][:40] or h in u for h in _PLACEHOLDER_HOSTS)
    if u.startswith(("/images/", "/img/", "/assets/")):
        return True  # scaffold-style local paths that were never shipped
    return False


def enforce_imagery(files, design_key: str | None = None):
    """Rewrite placeholder/picsum image sources and fill empty image fields.

    Accepts either a list[{'path','content'}] or a dict {path: content};
    mutates in place and returns (files, stats).
    """
    pool = _pool_for(design_key)
    stats = {"rewritten_urls": 0, "filled_fields": 0}
    used: set[str] = set()

    items = files.items() if isinstance(files, dict) else [(f["path"], f["content"]) for f in files]
    for path, content in list(items):
        if not path.endswith((".jsx", ".tsx", ".js", ".html")):
            continue
        if "<img" not in content and "image" not in content:
            continue
        changed = False

        # 1) Bad URLs on <img> tags -> themed photo (keyed by alt text).
        def _fix_tag(m: re.Match) -> str:
            nonlocal changed
            tag = m.group(0)
            am = _ALT_ATTR_RE.search(tag)
            alt = (am.group(2) or am.group(3) or "") if am else ""

            def _src(mm: re.Match) -> str:
                nonlocal changed, stats
                lit = _literal_of(mm.group(1))
                if lit is None or not _is_bad_url(lit):
                    return mm.group(0)
                pid = _pick(pool, f"{path}:{alt or lit}", used)
                stats["rewritten_urls"] += 1
                changed = True
                return f'src="https://images.unsplash.com/photo-{pid}?w=800&q=80"'

            tag = _SRC_ATTR_RE.sub(_src, tag, count=1)

            # 4) Hover-hidden content images: the model sometimes ships dish/
            #    gallery photos as `opacity-0 group-hover:opacity-100`, which
            #    reads as a permanently blank card (live Casa Verde menu: all
            #    6 dish photos invisible until hover). An object-cover <img>
            #    is content imagery, not decoration -- always visible; the
            #    hover rule stays harmless since it also sets full opacity.
            if "object-cover" in tag and "opacity-0" in tag \
                    and "group-hover:opacity-100" in tag:
                tag = tag.replace("opacity-0", "opacity-100", 1)
                stats["unhidden_images"] = stats.get("unhidden_images", 0) + 1
                changed = True
            return tag

        new = _IMG_TAG_RE.sub(_fix_tag, content)

        # 2) Empty OR placeholder-valued image fields in data arrays:
        #    image: '' / imageUrl: "" / image: 'https://picsum.photos/...'.
        def _fix_field(mm: re.Match) -> str:
            nonlocal changed, stats
            val = mm.group(3)
            if val and not _is_bad_url(val):
                return mm.group(0)  # real URL -- keep
            pid = _pick(pool, f"{path}:{mm.group(1)}", used)
            stats["filled_fields"] += 1
            changed = True
            return f"{mm.group(1)}: 'https://images.unsplash.com/photo-{pid}?w=800&q=80'"

        if path.endswith((".jsx", ".tsx", ".js")):
            # field: '' | field: "" | field: 'https://picsum.photos/...' etc.
            # Group 3 is the raw inner value; group 2 the quote char.
            new = re.sub(
                r"\b((?:image|imageUrl|img|photo|thumbnail)[A-Za-z0-9_]*)"
                r":\s*(['\"])([^'\"]*)\2",
                _fix_field, new,
            )

            # 3) Missing image key entirely: the model writes SOME dishes with
            #    image fields and others without (live Casa Verde: items 1-2
            #    had picsum urls, 3-6 had none -> src={item.image} rendered as
            #    undefined -> dead <img>). If any sibling object in an array
            #    literal has an image field, inject one into the others.
            new, n_missing = _fill_missing_image_fields(new, path, pool, used)
            if n_missing:
                stats["filled_missing"] = stats.get("filled_missing", 0) + n_missing
                changed = True

        if changed:
            if isinstance(files, dict):
                files[path] = new
            else:
                for f in files:
                    if f["path"] == path:
                        f["content"] = new
                        break
    return files, stats# ── Missing image-field injection ─────────────────────────────────────────
# Split BETWEEN objects, keeping both braces: lookbehind keeps '}',
# lookahead keeps '{' (a consuming split would drop closing braces and
# corrupt the JS on rejoin).
_OBJ_SPLIT_RE = re.compile(r"(?<=\}),\s*(?=\{)")
_FIELD_PRESENCE_RE = re.compile(r"\b(?:image|imageUrl|img|photo|thumbnail)[A-Za-z0-9_]*\s*:")
_ARR_RE = re.compile(r"\[(\s*\{.*?\}\s*)\]", re.S)


def _fill_missing_image_fields(content: str, path: str, pool, used) -> tuple[str, int]:
    """Inject image fields into array objects whose siblings have them.

    Only array-literal objects are touched (a top-level config object without
    an image key is not evidence of a missing field). The field is inserted
    right after the object's opening brace with a themed URL. Arrays with
    unbalanced braces (nested object/array values confusing the scan) are
    left untouched. Returns (new_content, fields_injected).
    """
    filled = 0
    out: list[str] = []
    last = 0
    for arr_m in _ARR_RE.finditer(content):
        body = arr_m.group(1)
        if body.count("{") != body.count("}"):
            continue  # nested structures confuse the scan -- skip safely
        if not _FIELD_PRESENCE_RE.search(body):
            continue  # no sibling demonstrates an image field
        objs = _OBJ_SPLIT_RE.split(body)
        if len(objs) < 2:
            continue
        arr_changed = False
        new_objs = []
        for obj in objs:
            if not _FIELD_PRESENCE_RE.search(obj):
                om = re.match(r"\s*\{", obj)
                if om:
                    pid = _pick(pool, f"{path}:missing{filled}", used)
                    sep = "\n    " if "\n" in obj else " "
                    ins = f"{om.group(0)}{sep}image: 'https://images.unsplash.com/photo-{pid}?w=800&q=80',"
                    obj = ins + obj[om.end():]
                    filled += 1
                    arr_changed = True
            new_objs.append(obj)
        if arr_changed:
            out.append(content[last:arr_m.start(1)])
            out.append(",".join(new_objs))
            last = arr_m.end(1)
    if filled:
        out.append(content[last:])
        return "".join(out), filled
    return content, 0


# ── Gradient-text fixer ─────────────────────────────────────────────────
# Live (Casa Verde Hero): `<span className="inline bg-gradient-to-br ...">`
# inside a `bg-clip-text text-transparent` h1 painted a solid gradient BOX
# over the wrapped word. A gradient background only reads as text when the
# element itself carries bg-clip-text + text-transparent.
_GRADIENT_CLASS_RE = re.compile(r"\bbg-gradient-to-[trbl]{1,2}\b")
_INLINE_TEXT_TAGS = {"span", "em", "strong", "a", "h1", "h2", "h3", "h4",
                     "h5", "h6", "p", "small", "b", "i", "label", "code"}
# Decorative/glow markers: an element with these is a background chip, not
# gradient text (icon bubbles carry w-/h-/p-; glows carry blur-/opacity-).
_DECOR_RE = re.compile(r"\b(blur-|opacity-|rounded|shadow|border-|\bw-\d|\bh-\d|\bp-\d|backdrop)")


def fix_gradient_text(path: str, content: str) -> str:
    """Add bg-clip-text text-transparent to inline-text elements that set a
    bg-gradient class but don't clip it -- solid gradient boxes over words are
    never intended. className-string edit only; cannot break bundling."""
    if not path.endswith((".jsx", ".tsx")):
        return content
    tag_re = re.compile(r"<(\w+)((?:[^>\"]|\"[^\"]*\"|'[^']*')*)>")

    def _patch(m: re.Match) -> str:
        tag, attrs = m.group(1), m.group(2)
        if tag.lower() not in _INLINE_TEXT_TAGS:
            return m.group(0)
        cm = re.search(
            r'(?:className|class)="([^"]*)"'
            r"|(?:className|class)='([^']*)'"
            r"|(?:className|class)=\{?`([^`]*)`\}?",
            attrs,
        )
        if not cm:
            return m.group(0)
        cls = next((g for g in cm.groups() if g is not None), None)
        if not cls or "bg-clip-text" in cls or not _GRADIENT_CLASS_RE.search(cls):
            return m.group(0)
        if _DECOR_RE.search(cls):
            return m.group(0)
        quoted = cm.group(0)
        new_quoted = quoted.replace(
            cls, f"bg-clip-text text-transparent {cls}", 1,
        )
        return m.group(0).replace(quoted, new_quoted, 1)

    return tag_re.sub(_patch, content)
