"""Multilingual brief support for Terabit Studio.

Live failure (2026-10-02): `extract_product_brief` is written entirely in
English regexes, so any brief typed in Hinglish, romanised Marathi or
Devanagari returned a completely empty record -- no name, no domain, no
persona facts. Because that record is threaded into every per-file prompt and
into the fallback scaffold, an empty record is exactly what produces a
perfectly built, perfectly generic template. Personalisation silently did
nothing.

This module closes that gap without spending a single token:

  detect_script()     'devanagari' | 'latin'
  language_label()    which language/register the brief is written in; every
                      other helper stays switched OFF for plain English so
                      English briefs are byte-for-byte unaffected
  english_shadow()    an English-normalised copy of the brief, used ONLY by the
                      deterministic regexes. Devanagari substitution is
                      unambiguous so it is applied wholesale; romanised forms
                      are applied only as whole phrases, because "main" is a
                      common English word and must not become "i".
  roman_person_name() name capture for "mera naam X hai" / "my name X"
  roman_person_facts() persona capture for "main X hu" / "mi ek X hu"
  domain_hint()       business-type nouns in any supported register, mapped to
                      English keywords the domain registry already knows
  offering_hints()    service/offering nouns (online ordering, home delivery)
  cta_hint()          the conversion action (order now, call us)

The user's original text is never mutated and the language model always
receives the user's own words, so generated copy can stay in the language the
user actually wrote in -- which is the whole point of personalisation.

Supported registers (zero cost, lexicon-driven, trivially extensible):
  English, Hinglish, Marathi/Hindi in Roman script, Gujarati and Bengali in
  Roman script, and Marathi/Hindi in Devanagari.
"""
from __future__ import annotations

import re
import unicodedata

DEVANAGARI = re.compile(r"[\u0900-\u097F]")

# Facts/names that carry no information. A one-word capture is fine ("shop",
# "bhojan") but a bare pronoun is not -- it is what a mis-anchored regex
# produces when the shadow substitutes "mi"/"ma" for the subject.
_JUNK_VALUES = {
    # english / roman script
    "i", "me", "my", "mine", "am", "is", "a", "an", "the", "and", "or", "of",
    "for", "to", "in", "on", "it", "we", "us", "our", "you", "he", "she",
    "they", "want", "need", "build", "make", "create", "website", "site",
    "app", "application", "page", "logo", "image", "photo", "picture",
    "upload", "portfolio", "one", "two", "three", "hu", "hoon", "ho", "hain",
    "hai", "hun", "chahiye", "havi", "here", "there", "this", "that", "very",
    "sir", "madam", "please", "also", "khup", "sadh", "not", "with", "that",
    # devanagari
    "मैं", "मी", "मेरा", "मेरी", "मेरे", "माझे", "माझा", "माझी", "मुझे",
    "मला", "हूँ", "हूं", "हू", "है", "हैं", "हो", "और", "आणि", "चाहिए",
    "चाहीए", "वेबसाइट", "साइट", "ऐप", "फोटो", "लोगो", "यह", "वह", "ये",
    "एक", "और",
}

# Noise = instructions about the artifact, not biography.
_NOISE = re.compile(
    r"upload|image|photo|foto|logo|logo|website|websait|webseit|"
    r"वेबसाइट|साइट|\bapp\b|ऐप|prefer|make sure|चाहिए|चाहीए|इच्छा|हवी",
    re.IGNORECASE,
)

# Verb/noun residue left behind by the shadow substitution. Trimmed from the
# ENDS of a fact, never from the middle, so "ai engineer" survives while
# "shop build want" collapses to "shop".
_EDGE_JUNK = re.compile(
    r"^(?:a|an|ek|one|the|my|and|or|to|for|in|on)\s+"
    r"|\s+(?:build|website|websait|webseit|site|app|want|need|make|create|"
    r"am|is|hu|hoon|ho|hai|hain|here|not|banvayacha?)\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------- helpers


def _norm_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def _term_re(src: str) -> re.Pattern:
    """Word-boundary match, used for every lexicon entry.

    Boundaries matter twice over: "mi" is a substring of "kam" (fewer) and
    "banv" is a prefix of "banvayacha", which used to leave the rest of the
    word behind. re's \\w covers Devanagari letters and combining marks, so the
    same expression is correct for both scripts.
    """
    return re.compile(r"(?<!\w)" + re.escape(src) + r"(?!\w)", re.IGNORECASE)


def _apply(text: str, pairs) -> str:
    """Substitute every (source -> english) pair, longest source first."""
    out = text
    for src, dst in sorted(pairs, key=lambda p: -len(p[0])):
        out = _term_re(src).sub(lambda _m, d=dst: d, out)
    return out


def _clean_fact(raw: str) -> str:
    """Trim shadow residue off a captured fact, keeping the original script."""
    fact = _norm_ws(raw).strip(" ,.;:!?\"'()[]")
    fact = _EDGE_JUNK.sub("", fact)
    fact = _norm_ws(fact).strip(" ,;:-/|")
    return fact


def _usable_fact(fact: str) -> bool:
    """A fact must be informative: non-empty, not noise, not a bare pronoun."""
    if not fact or len(fact) < 2 or len(fact) > 90:
        return False
    if _NOISE.search(fact):
        return False
    if fact.strip().lower() in _JUNK_VALUES:
        return False
    # A single letter or lone combining mark is residue, not a fact.
    if len(re.sub(r"[\s\W_]", "", fact, flags=re.UNICODE)) < 2:
        return False
    return True


# ---------------------------------------------------------------- script


def tokens(text: str) -> list[str]:
    """Whole-script tokeniser: letters plus the combining marks that carry them.

    Python's `\w` matches the *letters* of Devanagari but not the Mn/Mc
    combining marks, so `re.findall(r"[\w']+", "\u091a\u093f\u0924\u094d\u0930\u0915\u093e\u0930")`
    returns four fragments (`\u091a` | `\u0924` | `\u0930\u0915` | `\u0930`) instead of
    the word. Everything built on that tokeniser -- section asks, offering
    mining, the stop tables -- was silently reading consonant skeletons for
    every Indic brief, which is why the fix is one tokeniser rather than
    per-script patches: a mark attaches to the letter it modifies, so
    Marathi, Hindi, Bengali, Gujarati, Tamil and accented Latin all work
    through the same code path and a new script needs no new logic.

    Case is preserved and returned as typed (`caf\u00e9`, `I`, `don't`); callers
    that need lowercase lower the input. An internal apostrophe or hyphen
    stays inside the token ("don't", "re-do"); anything else separates. Empty
    input is `[]`, never an error.
    """
    out: list[str] = []
    buf: list[str] = []
    _INNER = "'\u2019-"

    def flush() -> None:
        if buf:
            tok = "".join(buf).strip(_INNER)
            if tok:
                out.append(tok)
            buf.clear()

    for ch in text or "":
        if ch.isalpha() or unicodedata.category(ch) in ("Mn", "Mc"):
            buf.append(ch)
        elif ch in _INNER and buf:
            buf.append(ch)
        else:
            flush()
    flush()
    return out


def detect_script(text: str) -> str:
    """Return 'devanagari' or 'latin'."""
    return "devanagari" if DEVANAGARI.search(text or "") else "latin"


# ------------------------------------------------- register identification

_DEV_MARATHI = ("आहे", "आहेत", "माझे", "माझा", "माझी", "मला", "मले",
                "चा", "ची", "चे", "पण", "काय", "आणि", "बनवायचे", "बनवायचा")
_ROMAN_MARATHI = ("maza", "mala", "malha", "aahe", "aahit", "aani", "aane",
                  "dukan", "dukhan", "banvay", "banay", "kirana", "pahijet",
                  "ghar", "vajra", "majha", "aahet")
_HINGLISH = ("mera", "meri", "mere", "mujhe", "muhje", "mujhko", "bhai",
             "chahiye", "hai", "hain", "hoon", "banani", "banayi", "yaar",
             "dost")
_ROMAN_GUJARATI = ("maru", "aavu", "tamaro", "khavo", "joine")
_ROMAN_BENGALI = ("amar", "amr", "tomar", "lagbe", "niye", "hobo")


def language_label(text: str) -> str:
    """Human name for the register the brief is written in.

    Feeds the generator prompt so shipped copy comes back in the user's own
    language instead of English boilerplate.
    """
    t = text or ""
    if detect_script(t) == "devanagari":
        if any(_term_re(w).search(t) for w in _DEV_MARATHI):
            return "Marathi (Devanagari)"
        return "Hindi (Devanagari)"
    low = t.lower()
    for words, label in (
        (_ROMAN_MARATHI, "Marathi in Roman script"),
        (_ROMAN_GUJARATI, "Gujarati in Roman script"),
        (_ROMAN_BENGALI, "Bengali in Roman script"),
        (_HINGLISH, "Hinglish (romanised Hindi)"),
    ):
        if any(_term_re(w).search(low) for w in words):
            return label
    return "English"


def is_multilingual(text: str) -> bool:
    """True when the brief is NOT plain English.

    Every multilingual substitution is gated on this so English prompts keep
    travelling the exact code path they passed before.
    """
    return language_label(text) != "English"


# ------------------------------------------------------- Devanagari lexicon
# Unambiguous, so applied to the whole shadow text.
_DEV_WORDS = [
    # -- identity --------------------------------------------------------
    ("मेरा", "my"), ("मेरी", "my"), ("मेरे", "my"),
    ("माझे", "my"), ("माझी", "my"), ("माझा", "my"),
    ("नाम", "name is"), ("नाव", "name is"),
    ("मुझे", "for me"), ("मुझको", "for me"),
    ("मला", "for me"), ("मले", "for me"),
    ("मैं", "i"), ("मी", "i"),
    ("हूँ", "am"), ("हूं", "am"), ("हू", "am"),
    ("है", ""), ("हैं", ""), ("हो", ""),
    ("आहे", ""), ("आहेत", ""), ("नाही", "not"), ("नाहीत", "not"),
    ("और", "and"), ("आणि", "and"), ("इतर", "other"),
    ("एक", "a"), ("दो", "two"),
    # -- wants / verbs ---------------------------------------------------
    ("चाहिए", "want"), ("चाहीए", "want"), ("चाहतो", "want"),
    ("चाहते", "want"), ("चाहती", "want"), ("हवी", "want"),
    ("हवे", "want"), ("पाहिजे", "want"), ("पाहजे", "want"),
    ("पाहिजेत", "want"), ("इच्छितो", "want"), ("इच्छिते", "want"),
    ("इच्छा", "want"),
    ("बनवायचे", "build"), ("बनवायची", "build"), ("बनवायचा", "build"),
    ("बनवायला", "build"), ("बनवायचं", "build"), ("बनवावे", "build"),
    ("बनवा", "build"), ("बनवू", "build"), ("बनव", "build"),
    ("बनाना", "build"), ("बनानी", "build"),
    ("बनायचा", "build"), ("बनायची", "build"), ("तयार", "build"),
    ("करायचे", "build"), ("करायचा", "build"), ("करायची", "build"),
    ("करावे", "build"), ("करा", "build"), ("करू", "build"),
    ("करूं", "build"), ("करें", "build"), ("करना", "build"),
    ("लागू", "add"), ("जोडा", "add"), ("जोडणे", "add"),
    ("दाखवा", "add"), ("दाखवावे", "add"),
    # -- artifacts -------------------------------------------------------
    ("वेबसाइट", "website"), ("वेबसाईट", "website"), ("वेब साइट", "website"),
    ("साइट", "site"), ("पेज", "page"),
    ("ऐप", "app"), ("एप", "app"), ("एप्लीकेशन", "application"),
    ("पोर्टफोलिओ", "portfolio"), ("पोर्ट्फोलिओ", "portfolio"),
    ("फोटो", "image"), ("तस्वीर", "image"), ("इमेज", "image"),
    ("लोगो", "logo"),
    # -- connectors / filler --------------------------------------------
    ("के लिए", "for"), ("की", ""), ("का", ""),
    ("मध्ये", "in it"), ("जिसमें", "in it"), ("जिसमे", "in it"),
    ("ज्यात", "in it"), ("त्यात", "in it"),
    ("बद्दल", "about"), ("साठी", "for"), ("साठून", "for"),
    ("पण", "but"), ("परंतु", "but"),
    ("काळी", "dark"), ("गडद", "dark"), ("हलका", "light"),
    ("साधी", "simple"), ("सादा", "simple"), ("आधुनिक", "modern"),
    ("व्यावसायिक", "professional"),
]

# ------------------------------------------------- romanised phrase lexicon
# Applied only as whole phrases. Single ambiguous roman words such as "main"
# are handled by the dedicated person patterns below instead.
_ROMAN_PHRASES = [
    # -- identity (Hinglish + Marathi + Gujarati + Bengali) --------------
    ("mera naam", "my name is"), ("meri naam", "my name is"),
    ("mere naam", "my name is"), ("mera name", "my name is"),
    ("mere name", "my name is"), ("maza naav", "my name is"),
    ("maza naam", "my name is"), ("malha naav", "my name is"),
    ("mala naav", "my name is"), ("majha naav", "my name is"),
    ("amar naam", "my name is"), ("amr naam", "my name is"),
    ("amar name", "my name is"), ("maru naam", "my name is"),
    ("my name is", "my name is"),
    # -- pronouns / wants -------------------------------------------------
    ("mujhe", "for me"), ("muhje", "for me"), ("mujhko", "for me"),
    ("majhe", "for me"), ("amar jonno", "for me"), ("amr jonno", "for me"),
    ("maru mate", "for me"), ("mala", "for me"), ("malaa", "for me"),
    ("majhya", "for me"), ("amake", "for me"), ("amar mate", "for me"),
    ("aapko", "for you"), ("tumhe", "for you"), ("ek", "a"),
    ("chahiye", "want"), ("havi", "want"), ("hovi", "want"),
    ("padhjo", "want"), ("lahje", "want"), ("lagbe", "want"),
    ("joine", "want"),
    ("karaycha", "build"), ("karaychi", "build"), ("karayche", "build"),
    ("kasa karaycha", "build"),
    ("banani chahiye", "build"), ("banani hai", "build"),
    ("banani hain", "build"), ("banani thi", "build"),
    ("banani", "build"), ("banayi", "build"), ("bananiye", "build"),
    ("banvayacha", "build"), ("banvayachi", "build"),
    ("banvayche", "build"), ("banvayla", "build"),
    ("banayacha", "build"), ("banayachi", "build"),
    ("banayla", "build"), ("banavu", "build"),
    ("website banavi", "build website"),
    # -- connectors -------------------------------------------------------
    ("aani", "and"), ("aane", "and"), ("ani", "and"),
    ("aur", "and"), ("pan", "and"),
    ("tamaru", "your"), ("tamara", "your"), ("tomar", "your"),
    ("maza", "my"), ("majha", "my"),
    ("aata", "now"), ("sagle", "all"), ("sagla", "all"),
    # -- business nouns ---------------------------------------------------
    ("dukan", "shop"), ("dukhan", "shop"), ("dukana", "shop"),
    ("kirana", "grocery shop"), ("kiranacha", "grocery shop"),
    ("kirane", "grocery shop"), ("vajan", "business"), ("vajra", "business"),
    ("vahyaya", "business"), ("udyog", "business"),
    ("restaurant", "restaurant"), ("restoran", "restaurant"),
    ("dhaba", "restaurant"),
    ("cafe", "cafe"), ("kancha", "food"), ("bhojan", "food"),
    ("shimla", "food"), ("chai", "food cafe"),
    ("biryani", "food restaurant"), ("pizza", "food restaurant"),
    ("kapde", "clothes fashion"), ("kapdeche", "clothes fashion"),
    ("kapdecha", "clothes fashion"), ("kapda", "clothes fashion"),
    ("surti", "clothes fashion"), ("vastram", "clothes fashion"),
    ("beauty parlour", "salon beauty parlour"),
    ("beauty parlor", "salon beauty parlour"),
    ("parlour", "salon"), ("parlor", "salon"), ("salon", "salon"),
    ("barber", "salon"), ("spa", "spa wellness"),
    ("clinic", "clinic"), ("doctor", "clinic doctor"),
    ("hospital", "hospital"), ("pharmacy", "medical pharmacy"),
    ("dawai", "medical pharmacy"), ("daawai", "medical pharmacy"),
    ("school", "school"), ("college", "school college"),
    ("academy", "school academy"), ("coaching", "tutoring"),
    ("gym", "gym fitness"), ("yoga", "fitness"),
    ("hotel", "hotel"), ("guest house", "hotel"),
    ("ghar", "property homes"), ("property", "property real estate"),
    ("flat", "property apartments"), ("villa", "property villa"),
    ("lawyer", "law firm"), ("advocate", "law firm"),
    ("vakil", "law firm"), ("kisan", "farming"),
    ("farmer", "farming"), ("khet", "farming"),
    ("naksha", "map design"), ("drone", "drone photography"),
    ("photographer", "photographer"), ("photography", "photography"),
    ("designer", "designer"), ("artist", "artist"),
    ("music", "music"), ("gitar", "music"),
    ("blog", "blog"), ("vlog", "blog"), ("news", "news"),
    ("portfolio", "portfolio"), ("cv", "resume"),
    # -- artifacts --------------------------------------------------------
    ("websait", "website"), ("webseit", "website"),
    ("upload", "upload"), ("photo", "image"), ("foto", "image"),
    ("pictures", "image"), ("logo", "logo"),
    ("app banavi", "app build"), ("application", "app"),
    # -- design prefs -----------------------------------------------------
    ("kala", "dark"), ("black theme", "dark theme"),
    ("white theme", "light theme"), ("simple", "simple"),
    ("sadhe", "simple"), ("modern", "modern"), ("aadhe", "modern"),
]

# Marathi adjectival endings glued onto a known stem ("kiranacha" =
# "of the grocery shop"). Applied only to known stems, never as a blanket
# suffix rule, so English words ending in -cha/-che are left alone.
_ROMAN_STEM = re.compile(
    r"(?<![\w])((?:kirana|dukan|dukhan|kapde|kapda|bhojan|restoran|"
    r"vajra|shala|gaon))(?:cha|chi|che|chya|chhi|la|li|le)\b",
    re.IGNORECASE,
)

# Copulas / trailing particles that add nothing to a captured fact.
_ROMAN_DROP = [
    r"\bbhai\b", r"\byaar\b", r"\bdost\b",
    r"\bthay\b", r"\baahe\b", r"\bahet\b", r"\baahet\b",
    r"\bhota\b", r"\bhe\b", r"\btho\b",
]

# ------------------------------------------------------------------ shadow


def english_shadow(text: str, lower: bool = True) -> str:
    """Best-effort English rendering used only for deterministic matching.

    Devanagari is deliberately NOT stripped. The person's own name is written
    in Devanagari, so erasing the script before the name capture deleted the
    one token that mattered.
    """
    if not text:
        return ""
    out = text
    if detect_script(out) == "devanagari":
        out = _apply(out, _DEV_WORDS)
    elif is_multilingual(out):
        out = _ROMAN_STEM.sub(lambda m: m.group(1), out)
        out = _apply(out, _ROMAN_PHRASES)
        for pat in _ROMAN_DROP:
            out = re.sub(pat, " ", out, flags=re.IGNORECASE)
    out = _norm_ws(out if lower else out)
    # "kiranacha dukhan" -> "grocery shop shop": collapse an immediately
    # repeated word so a captured fact never stutters.
    return re.sub(r"\b(\w+)\b(?:\s+\1\b)+", r"\1", out)


# ------------------------------------------------------------ person name

# A name token: Latin or Devanagari. Built from real characters rather than
# backslash-u escapes inside a raw string, which re-parses inconsistently.
_NAME_CHARS = "A-Za-z0-9ऀ-ॿ'’-"
_NAME_TOK = re.compile("^[" + _NAME_CHARS + "]+$")

_ROMAN_NAME_PATTERNS = [
    re.compile(r"\bmy\s+name\s+is\s+(.+)", re.I),
    re.compile(r"\bmy\s+name\s*[:\-]\s+(.+)", re.I),
]

_TAIL_WORDS = ("and", "or", "but", "who", "which", "that", "aur", "aani",
               "ani", "hai", "hain", "he", "ho", "aahe")


def _tidy_name(raw: str) -> str:
    raw = _norm_ws(raw).strip(" ,.\"'")
    # Cut at the first clause tail, wherever it appears.
    for w in _TAIL_WORDS:
        raw = re.sub(r"\s+" + re.escape(w) + r"\b.*$", "", raw, flags=re.I)
    raw = _norm_ws(raw).strip(" ,.\"'")
    if not raw:
        return ""
    # Devanagari names keep their script; Latin names are title cased.
    if DEVANAGARI.search(raw):
        return raw
    return " ".join(w[:1].upper() + w[1:] for w in raw.split())


def roman_person_name(text: str) -> str:
    """Best-effort personal name from a romanised or Devanagari brief."""
    if not is_multilingual(text):
        return ""
    # lower=False keeps the user's own capitalisation ("McDonald" survives).
    shadow = english_shadow(text, lower=False)
    for pat in _ROMAN_NAME_PATTERNS:
        m = pat.search(shadow)
        if not m:
            continue
        # Take the leading run of name-shaped tokens rather than relying on a
        # greedy quantifier, which used to swallow the following clause.
        take = []
        for tok in m.group(1).split()[:4]:
            tok = tok.strip(' ,.;:!?\'"')
            if not tok or not _NAME_TOK.match(tok):
                break
            if tok.lower() in _JUNK_VALUES:
                break
            take.append(tok)
        if len(take) >= 2:
            return _tidy_name(" ".join(take))
    return ""


# ---------------------------------------------------------- person facts

_ROMAN_FACT_PATTERNS = [
    # "in it X" -- what the thing contains, keeping the original script so a
    # Devanagari phrase survives as a fact instead of being stripped away.
    # Tried first: it is the richest capture ("जिसमें ऑर्डर करने की सुविधा").
    re.compile(r"\bin\s+it\s+(.{3,70}?)"
               r"(?=\s+(?:and|or|but)\b|[.!?,;]|$)", re.I),
    # "main ek full stack developer hu" / "mi a doctor chu"
    re.compile(r"\b(?:main|mai|mi|mala|majhe|amar|maru|malaa)\s+"
               r"(?:a|an|ek|one)?\s*(.{3,90}?)"
               r"(?=\s+(?:aani|ani|aur|and|pan|pn|but)\b"
               r"|\s+(?:hu|huh|hoon|aahe|aahet|chu|chh|hui|he|thi)\b"
               r"|[,.;!?]|$)", re.I),
    # Devanagari "mala/mujhe ek X" became "for me a X"; there is no surviving
    # first-person pronoun to anchor on, so anchor on the object pronoun.
    re.compile(r"\bfor\s+me\s+(?:a|an|ek|one)?\s*(.{3,90}?)"
               r"(?=\s+(?:and|or|but)\b|[,.;!?]|$)", re.I),
    # "<profession> hu" -- profession stated without a leading pronoun
    re.compile(r"\b(?:main|mai|mi|mala|majhe|amar|maru)\s+"
               r"(?:a|an|ek)?\s*(?:professional|developer|engineer|designer|"
               r"founder|student|teacher|doctor|photographer|artist|"
               r"consultant|freelancer|shopkeeper|businessman|shop|clinic|"
               r"gym|hotel|restaurant|cafe|firm|studio|academy)\b"
               r"\s*(.{3,80}?)"
               r"(?=\s+(?:aani|ani|aur|and)\b|[,.;!?]|$)", re.I),
    # Devanagari, after the shadow turned the first person pronoun into "i"
    re.compile(r"\bi\s+(?:a|an|ek)?\s*(.{3,90}?)"
               r"(?=\s+(?:and|or|but)\b|\s+(?:am|is|not)\b|[.!?,;]|$)", re.I),
]


def _redundant_fact(fact: str, text: str) -> bool:
    """Drop a bare business noun the domain field already carries.

    "माझे नाव X आहे आणि मी एक दुकान बनवू" captured the fact "दुकान" on its
    own, which the brief then stated twice ("it is a retail shop" / "Stated
    background: दुकान"). Only single-token facts that are literally a known
    business noun are dropped; a phrase like "कपड़े विकणे" is kept.
    """
    if " " in fact:
        return False
    for src, _rank, _en, _label in _DOMAIN_LEXICON:
        if fact.lower() == src.lower():
            return True
    return False


def roman_person_facts(text: str) -> list[str]:
    """Persona facts from a romanised or Devanagari multilingual brief."""
    if not is_multilingual(text):
        return []
    shadow = english_shadow(text)
    facts: list[str] = []
    seen: set[str] = set()
    taken: list[tuple[int, int]] = []
    for pat in _ROMAN_FACT_PATTERNS:
        for m in pat.finditer(shadow):
            span = m.span(1)
            # A later, greedier pattern must not re-report text an earlier one
            # already claimed ("किराना दुकान in it ऑर्डर करने सुविधा").
            if any(span[0] < e and span[1] > s for s, e in taken):
                continue
            fact = _clean_fact(m.group(1))
            if not _usable_fact(fact) or _redundant_fact(fact, text):
                continue
            key = fact.lower()
            if key in seen:
                continue
            seen.add(key)
            taken.append(span)
            facts.append(fact)
            if len(facts) >= 4:
                return facts
    return facts


# --------------------------------------------------- business / domain nouns
# (source, rank, english keywords, human label)
# rank 0 = the business type itself; rank 1 = what it stocks or sells. The
# lowest rank that matches wins, so "ek kirana dukan" is a grocery shop, not
# a generic store, while "dukan ... kapde" stays a shop and still lets
# detect_domain see the fashion keywords.
_DOMAIN_LEXICON = [
    # -- Devanagari ------------------------------------------------------
    ("ब्यूटी पार्लर", 0, "salon beauty parlour", "beauty parlour"),
    ("केश सालन", 0, "salon", "hair salon"),
    ("सैलून", 0, "salon", "salon"),
    ("सलून", 0, "salon", "salon"),
    ("ब्यूटी", 0, "salon beauty", "beauty studio"),
    ("स्पा", 0, "spa wellness", "spa and wellness"),
    ("किराना", 0, "grocery shop store", "grocery shop"),
    ("दुकान", 0, "shop store", "retail shop"),
    ("दुकानदार", 0, "shop store", "retail shop"),
    ("कपड़े", 1, "clothes fashion apparel", "clothing store"),
    ("कपडे", 1, "clothes fashion apparel", "clothing store"),
    ("वस्त्र", 1, "garment fashion", "clothing store"),
    ("श्रृंगार", 1, "fashion beauty", "fashion and beauty"),
    ("फॅशन", 0, "fashion", "fashion label"),
    ("रेस्टोरेंट", 0, "restaurant", "restaurant"),
    ("रेस्टोरन्ट", 0, "restaurant", "restaurant"),
    ("भोजनालय", 0, "restaurant", "restaurant"),
    ("होटल", 0, "hotel", "hotel"),
    ("कैफे", 0, "cafe", "cafe"),
    ("कॉफे", 0, "cafe", "cafe"),
    ("क्लिनिक", 0, "clinic", "clinic"),
    ("अस्पताल", 0, "hospital", "hospital"),
    ("हॉस्पिटल", 0, "hospital", "hospital"),
    ("डॉक्टर", 0, "doctor clinic", "clinic"),
    ("दवाई", 1, "pharmacy medical", "pharmacy"),
    ("स्कूल", 0, "school", "school"),
    ("कॉलेज", 0, "school college", "college"),
    ("ट्यूशन", 0, "tutoring", "tuition centre"),
    ("कोचिंग", 0, "tutoring academy", "coaching centre"),
    ("शिक्षा", 1, "education", "education provider"),
    ("जिम", 0, "gym fitness", "gym"),
    ("योग", 0, "yoga fitness", "yoga studio"),
    ("वकील", 0, "lawyer law firm", "law firm"),
    ("अधिवक्ता", 0, "advocate law firm", "law firm"),
    ("पोर्टफोलिओ", 0, "portfolio", "portfolio"),
    ("पोर्ट्फोलिओ", 0, "portfolio", "portfolio"),
    ("फोटोग्राफर", 0, "photographer", "photographer"),
    ("गैलरी", 0, "gallery art", "art gallery"),
    ("किसान", 0, "farming", "farm produce business"),
    ("शेती", 0, "farming", "farm produce business"),
    ("फ्लैट", 0, "property apartments", "apartments"),
    ("सर्व्हर", 0, "automotive", "automotive workshop"),
    ("गॅरेज", 0, "automotive", "garage"),
    # -- Roman script ----------------------------------------------------
    ("beauty parlour", 0, "salon beauty parlour", "beauty parlour"),
    ("beauty parlor", 0, "salon beauty parlour", "beauty parlour"),
    ("parlour", 0, "salon", "salon"),
    ("parlor", 0, "salon", "salon"),
    ("salon", 0, "salon", "salon"),
    ("spa", 0, "spa wellness", "spa and wellness"),
    ("kirana", 0, "grocery shop store", "grocery shop"),
    ("dukan", 0, "shop store", "retail shop"),
    ("dukhan", 0, "shop store", "retail shop"),
    ("kapde", 1, "clothes fashion apparel", "clothing store"),
    ("kapda", 1, "clothes fashion apparel", "clothing store"),
    ("vastra", 1, "garment fashion", "clothing store"),
    ("bhojan", 0, "food restaurant", "food business"),
    ("biryani", 0, "food restaurant", "restaurant"),
    ("dhaba", 0, "restaurant", "restaurant"),
    ("restaurant", 0, "restaurant", "restaurant"),
    ("shimla", 1, "food cafe", "food business"),
    ("chai", 0, "cafe food", "tea and snack cafe"),
    ("hotel", 0, "hotel", "hotel"),
    ("clinic", 0, "clinic", "clinic"),
    ("doctor", 0, "doctor clinic", "clinic"),
    ("pharmacy", 0, "pharmacy medical", "pharmacy"),
    ("dawai", 0, "pharmacy medical", "pharmacy"),
    ("school", 0, "school", "school"),
    ("college", 0, "school college", "college"),
    ("academy", 0, "school academy", "academy"),
    ("coaching", 0, "tutoring academy", "coaching centre"),
    ("gym", 0, "gym fitness", "gym"),
    ("yoga", 0, "yoga fitness", "yoga studio"),
    ("lawyer", 0, "lawyer law firm", "law firm"),
    ("advocate", 0, "advocate law firm", "law firm"),
    ("vakil", 0, "lawyer law firm", "law firm"),
    ("photographer", 0, "photographer", "photographer"),
    ("photography", 0, "photography", "photography studio"),
    ("designer", 0, "designer", "design studio"),
    ("artist", 0, "artist", "artist"),
    ("gallery", 0, "gallery art", "art gallery"),
    ("kisan", 0, "farming", "farm produce business"),
    ("farmer", 0, "farming", "farm produce business"),
    ("khet", 0, "farming", "farm produce business"),
    ("gaon", 0, "farming village", "village enterprise"),
    ("garage", 0, "automotive", "garage"),
    ("naukri", 0, "job employment", "job portal"),
    ("bhasha", 1, "language translation", "language services"),
    ("videshi", 1, "tourism travel", "travel service"),
    ("basti", 1, "property real estate", "real estate"),
    ("jagha", 1, "property real estate", "property"),
    ("ghar", 1, "property homes", "property"),
]

# Service / offering nouns -> short English section asks.
_OFFERING_LEXICON = [
    ("ऑनलाइन ऑर्डर", "online ordering"),
    ("ऑर्डर", "online ordering"),
    ("होम डिलीवरी", "home delivery"),
    ("डिलीवरी", "delivery"),
    ("व्हाट्सएप", "WhatsApp ordering"),
    ("किराना सामान", "groceries and staples"),
    ("मसाले", "spices"),
    ("सब्जी", "vegetables"),
    ("फळे", "fruits"),
    ("स्वादिष्ट", "fresh food"),
    ("मिठाई", "sweets"),
    ("फेसबुक", "social media presence"),
    ("इंस्टाग्राम", "Instagram presence"),
    ("गुगल मैप", "location on Google Maps"),
    ("समय", "opening hours"),
    ("वेळ", "opening hours"),
    ("निवड", "selection"),
    ("ऑफर", "offers"),
    ("online order", "online ordering"),
    ("home delivery", "home delivery"),
    ("delivery", "delivery"),
    ("whatsapp", "WhatsApp ordering"),
    ("timing", "opening hours"),
    ("vat", "GST and billing"),
    ("emi", "EMI and instalments"),
    ("free", "free consultation"),
    ("discount", "seasonal discounts"),
    ("feedback", "customer feedback"),
    ("reviews", "customer reviews"),
    ("contact", "contact details"),
    ("map", "location on Google Maps"),
    ("festival", "festival offers"),
    ("jaldi", "fast service"),
    ("aavad", "fresh stock"),
]


def domain_hint(text: str) -> dict:
    """Business type recognised in a non-English brief.

    Returns {"label": <human phrase>, "keywords": [<english words>]} where
    keywords are the union of every match -- detect_domain needs all of them
    (a clothing shop should reach the fashion profile via "kapde" even when
    the head noun is "shop"), while the label is the single most specific
    business type found.
    """
    out: dict = {"label": "", "keywords": []}
    if not text or not is_multilingual(text):
        return out
    # "kiranacha" -> "kirana" first, or the lexicon never sees the stem.
    low = _ROMAN_STEM.sub(lambda m: m.group(1), text.lower())
    best = None
    keys: list[str] = []
    for src, rank, en, label in _DOMAIN_LEXICON:
        m = _term_re(src).search(low)
        if not m:
            continue
        for w in en.split():
            if w not in keys:
                keys.append(w)
        cand = (rank, m.start(), label)
        if best is None or cand[:2] < best[:2]:
            best = cand
    out["keywords"] = keys
    if best:
        out["label"] = best[2]
    return out


def offering_hints(text: str) -> list[str]:
    """Short English offering phrases found in a non-English brief."""
    if not text or not is_multilingual(text):
        return []
    low = _ROMAN_STEM.sub(lambda m: m.group(1), text.lower())
    out: list[str] = []
    for src, en in _OFFERING_LEXICON:
        if _term_re(src).search(low) and en not in out:
            out.append(en)
        if len(out) >= 6:
            break
    return out


_CTA_LEXICON = [
    ("ऑर्डर", "order now"),
    ("खरीद", "buy now"),
    ("बुकिंग", "book now"),
    ("अपॉइंटमेंट", "book an appointment"),
    ("फोन", "call us"),
    ("कॉल", "call us"),
    ("संपर्क", "contact us"),
    ("व्हाट्सएप", "WhatsApp us"),
    ("दर", "see pricing"),
    ("order", "order now"),
    ("buy", "buy now"),
    ("book", "book now"),
    ("appointment", "book an appointment"),
    ("call", "call us"),
    ("contact", "contact us"),
    ("whatsapp", "WhatsApp us"),
    ("videshi", "call us"),
]


def cta_hint(text: str) -> str:
    """The conversion action named in a non-English brief, else ""."""
    if not text or not is_multilingual(text):
        return ""
    low = _ROMAN_STEM.sub(lambda m: m.group(1), text.lower())
    for src, en in _CTA_LEXICON:
        if _term_re(src).search(low):
            return en
    return ""
