import os
import re
import io
import asyncio
import time
import uuid
import zipfile
import json
from pathlib import Path
from datetime import datetime, timezone

import paths as _paths  # frozen-vs-source locations (DB, uploads, web/)
from fastapi import FastAPI, HTTPException, Depends, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi import Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from typing import Optional

from model_service import (
    generate_response,
    generate_response_stream,
    generate_response_with_status,
    start_server,
    warm_up_model_async,
    get_active_model,
)
from rag_engine import rag_search, generate_business_system_prompt, retrieve_project_context
import context_budget
import agentic_generator
import imagery
import providers
import model_api
from database import get_db, User, ChatSession, ChatMessage, Asset
from auth import verify_password, hash_password, create_token, get_current_user
from preview_builder import build_preview_html, preview_tier
from registry_service import get_registry
from ir_generator import IRGenerator, format_ir_for_prompt
from scaffolds import get_archetype_for_prompt, get_base_scaffold


def dump_generation_artifacts(req, prep: dict, result: dict, wall_s: float, source: str) -> None:
    """Persist every completed generation (files + agent trace + timing + tier)
    under backend/comparison/<slug>/<timestamp>/. These are the raw artifacts
    for benchmarking against Bolt/Lovable -- captured at the source, so a
    browser crash never loses a run again."""
    try:
        import time as _time
        slug = re.sub(r"[^a-z0-9]+", "-", (req.prompt[:40].lower())).strip("-") or "run"
        out = Path(__file__).resolve().parent / "comparison" / slug / _time.strftime("%Y%m%d-%H%M%S")
        out.mkdir(parents=True, exist_ok=True)
        tier = ""
        try:
            tier = preview_tier(build_preview_html(result["files"]))
        except Exception:  # noqa: BLE001
            pass
        (out / "request.json").write_text(json.dumps({
            "prompt": req.prompt,
            "business_type": req.business_type,
            "operation": req.operation,
            "provider": req.provider or "local",
            "brief": prep.get("brief"),
            "app_name": prep.get("app_name"),
            "archetype": prep.get("archetype"),
        }, indent=2), encoding="utf-8")
        (out / "result.json").write_text(json.dumps({
            "wall_s": round(wall_s, 1),
            "bundle_ok": result.get("bundle_ok"),
            "preview_tier": tier,
            "agent_trace": result.get("agent_trace", []),
            "files": result.get("files", []),
        }, indent=2, ensure_ascii=False), encoding="utf-8")
        # Raw model outputs BEFORE composition/drops -- without this, dropped
        # sections were unrecoverable and every diagnosis needed a re-run.
        generated_debug = result.pop("generated_debug", None)
        if generated_debug:
            (out / "generated.json").write_text(
                json.dumps(generated_debug, indent=2, ensure_ascii=False),
                encoding="utf-8")
        # Design-adherence score: turns "does it look like <domain>?" into a
        # number every run carries (the v3 promotion gate reads these).
        try:
            from eval_design_gate import score_files
            brief = prep.get("brief") or {}
            score = score_files(result.get("files", []), brief)
            (out / "design_score.json").write_text(
                json.dumps(score, indent=2), encoding="utf-8")
            print(f"[artifacts] design gate: {score['gate']} "
                  f"(palette={score['palette_adherence']}, theme={score['theme']})")
        except Exception as _e:  # noqa: BLE001
            print(f"[artifacts] design gate skipped: {_e}")
        print(f"[artifacts] saved {source} run -> {out} (tier={tier}, {wall_s:.0f}s)")
        # Durable visual evidence: render the shipped preview in headless
        # Chrome and store desktop+mobile JPEGs beside the run's JSON. Runs in
        # a daemon thread so a slow browser never delays the user's response.
        try:
            import threading as _th
            import capture_evidence as _ev

            def _shots(_out=out):
                try:
                    info = _ev.capture_run(_out, force=True)
                    print(f"[artifacts] evidence shots: {info.get('shots', info.get('skipped'))}")
                except Exception as _ee:  # noqa: BLE001
                    print(f"[artifacts] evidence capture failed: {_ee}")

            _th.Thread(target=_shots, daemon=True).start()
        except Exception as _e:  # noqa: BLE001
            print(f"[artifacts] evidence hook skipped: {_e}")
    except Exception as e:  # noqa: BLE001 - artifacts must never break generation
        print(f"[artifacts] dump failed: {e}")

# Shared singletons: the registry is preloaded at import so the first
# generation request doesn't pay a cold file-scan; the IR generator is
# stateless.
_registry = get_registry()
_ir_generator = IRGenerator()

UPLOAD_DIR = _paths.data_dir() / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)


# ---------------------------------------------------------------- product brief

# Word tokenising for anything a human typed. See multilingual.tokens: the
# \w character class shreds Devanagari at every combining mark, so every
# findall(r"[\w']+") on user text silently produced consonant skeletons for
# non-Latin briefs. Imported here with a plain-\w fallback so a broken
# multilingual import degrades to the old behaviour instead of an exception.
try:
    from multilingual import tokens as _tokens
except Exception:  # noqa: BLE001
    def _tokens(text: str) -> list[str]:
        return re.findall(r"[\w']+", text or "")

# Closed-class English function words. This is a *linguistic* table, not a
# per-customer patch: every entry is a word that carries no topic, so dropping
# it is correct for any profession in any language. A Devanagari or Gujarati
# token is simply absent from it and therefore survives as content, which is
# why this generalises instead of enumerating trades.
_DERIVE_STOP = {
    "i", "me", "my", "mine", "myself", "we", "us", "our", "ours", "you",
    "your", "yours", "he", "him", "his", "she", "her", "hers", "it", "its",
    "they", "them", "their", "theirs", "this", "that", "these", "those",
    "who", "whom", "whose", "which", "what", "where", "when", "why", "how",
    "a", "an", "the", "and", "or", "but", "nor", "so", "if", "then", "than",
    "of", "for", "to", "in", "on", "at", "by", "with", "from", "into",
    "onto", "about", "over", "under", "per", "as", "via", "near", "up", "out",
    "off", "down", "am", "is", "are", "was", "were", "be", "been", "being",
    "do", "does", "did", "doing", "have", "has", "had", "having", "will",
    "would", "can", "could", "should", "may", "might", "must", "shall",
    "let", "get", "got", "please", "just", "also", "very", "too", "only",
    "own", "same", "all", "any", "each", "every", "some", "such", "no",
    "not", "more", "most", "less", "least", "much", "many", "here", "there",
    "now", "here", "one", "two", "three", "first", "second", "new", "own",
    "need", "needs", "needed", "want", "wants", "wanted", "like", "help",
    "make", "made", "build", "built", "create", "created", "generate",
    "give", "give", "take", "see", "know", "think", "let", "should",
    "show", "shows", "showing", "shown", "display", "displays",
    "displaying", "present", "presents", "presenting", "list", "lists",
    "listing", "add", "adds", "adding", "include", "includes",
    "including", "run", "runs", "running", "tune", "tunes", "tuning",
    "sell", "sells", "selling", "sale", "sales", "book", "books", "booking",
    "bookings", "get", "gets", "getting", "getting", "start", "starting",
    "hire", "hiring", "work", "works", "working", "call", "calls", "contact",
    # Romanised Hindi/Marathi/Gujarati function words. A register table, same
    # category as the Devanagari rows above: these carry no topic, so removing
    # them is correct for every customer who writes in this script. Without
    # them the brief "apne photography ke liye" produced the offer "liye main".
    "ka", "ki", "ke", "ko", "se", "aur", "hai", "hain", "hu", "hun", "ho",
    "hoon", "main", "mein", "mera", "meri", "mere", "mujhe", "hamara",
    "apna", "apni", "apne", "uska", "uski", "uske", "unka", "unki", "unke",
    "iska", "iski", "iske", "liye", "waala", "wala", "wali", "wale",
    "karke", "karne", "karna", "kiya", "kiye", "diya", "dene", "dena",
    "sakta", "sakti", "sakte", "raha", "rahi", "rahe", "rahaa", "huu",
    "aap", "tum", "tume", "aapko", "tumko", "yahan", "wahan", "abhi",
    "phir", "bhi", "hi", "to", "tak", "jab", "tab", "phir", "kuch", "sab",
    "my", "myself", "itself", "there", "am", "get", "got", "put", "set",
    "क", "का", "की", "के", "को", "में", "से", "और", "का", "है", "हूँ",
    "लिए", "साथ", "वाले", "वाला", "कर", "करना", "चाहिए", "चाहीए",
    "my", "मेरा", "मेरी", "mujhe", "mera", "meri", "meri", "hamara",
    "banao", "banva", "banaye", "banana", "chahiye", "chahie", "karna",
    # Devanagari function words, same reasoning as the romanised rows: a
    # grammar table for a script, not a customer. "मैं एक चित्रकार हूँ" is
    # the Hindi "I am a painter", and without these the identity clause was
    # mined as an offering -- the model was being told to render the user's
    # own introduction as a section heading.
    "मैं", "मी", "मुझे", "मुझको", "मेरा", "मेरी", "मेरे", "मैंने",
    "हम", "हमने", "हमारा", "हमारी", "हमारे", "हमें",
    "तुम", "तुम्हारा", "तुम्हारी", "तुम्हें", "आप", "आपका", "आपकी", "आपके",
    "एक", "और", "यह", "ये", "वह", "वे", "इस", "उस", "उन",
    "है", "हैं", "हूँ", "हूं", "हूना", "था", "थी", "थे", "हो", "होना", "होती",
    "और", "पर", "भी", "ही", "तो", "फिर", "कुछ", "सब", "बहुत", "अब",
    "बनाओ", "बनाना", "बनवा", "बनवाना", "कर", "करना", "करके", "किया", "की",
    "चाहिए", "चाहीए", "चाहता", "चाहते", "चाहती", "होनी", "दो", "देना", "दी",
    "लगा", "लगाना", "रहा", "रही", "रहे", "सकता", "सकती", "सकते", "सकता",
    "लिए", "लिये", "साथ", "नाम", "हैं।", "में", "से", "का", "की", "के", "को",
    "माझा", "माझी", "माझे", "माझ्या", "तुमचा", "तुमची", "तुमचे", "तुमच्या",
    "हे", "हा", "मला", "तुला", "आम्ही", "आम्हाला", "आमचा", "आमची", "आमचे",
    "आपले", "आपली", "आपला", "माझं", "तुमचं", "एकूण", "सर्व", "जर", "तर",
}
# Vocabulary about the ARTIFACT, not about the business. "modern responsive
# website with dark mode" is four words of chrome and zero words of trade;
# letting those into the section asks is how you get "the business's core
# offerings" back wearing a different hat.
# Nouns that describe a business rather than name a thing it does. Banned as
# one-word asks, allowed inside a phrase.
_DERIVE_GENERIC = {
    "service", "services", "work", "works", "business", "company", "thing",
    "things", "stuff", "quality", "price", "prices", "option", "options",
    "people", "team", "teams", "lot", "lots", "bit", "place", "area",
}
_DERIVE_NOISE = re.compile(
    r"website|web\s?site|\bsite\b|\bapp\b|application|landing|homepage|"
    r"\bpage\b|\bpages\b|single[\s-]?page|template|responsive|modern|"
    r"beautiful|professional|clean|simple|minimal|elegant|attractive|"
    r"\bdark\b|\bmode\b|\blight\b|navbar|footer|header|hero|banner|"
    r"layout|styling|\bstyle\b|\bui\b|\bux\b|animation|animations|"
    r"\bbutton\b|\bbuttons\b|\bimage\b|\bimages\b|\bphoto\b|\bphotos\b|"
    r"\blogo\b|\bsection\b|\bsections\b|colour|color|colours|colors|"
    r"\bfont\b|\bfonts\b|animation|interactive|responsive|works|"
    r"nice|good|great|awesome|stunning|smooth|cool|clean|look|feel|"
    r"fast|loading|seo|\bblog\b|domain|hosting|ssl|seo|"
    r"website|साइट|ऐप|वेबसाइट|पेज",
    re.IGNORECASE,
)


def _derived_offerings(text: str, name: str = "", domain: str = "") -> list[str]:
    """Section asks mined from the user's own words, for any trade.

    The explicit "with A, B and C" segmentation in extract_product_brief only
    fires on a list, so most briefs carried no offerings at all and the
    generic profile fell back to "the business's core offerings" -- a
    placeholder. Measured over 20 professions, four of them (music producer,
    architect, veterinarian, electrician) landed exactly there.

    Adding a profile per trade does not scale: there is no list of trades. So
    this reads the *grammar* instead of the domain. Two passes, both
    language-agnostic:

      1. Structural triggers -- "for my X", "about X", "featuring X". The
         trigger list is grammatical; the payload is the user's own words.
      2. Ranked content n-grams over the whole request, longest first, so
         "art major" outranks "painter" and "paintings" outranks "painting".

    Nothing here is profession-, customer- or language-specific: it is a
    function-word table, an artifact-vocabulary table and two English
    suffixes used for *ranking* only. A token in any script is accepted as
    content unless it is literally in the stop table.
    """
    if not text or not text.strip():
        return []
    low = text.lower()
    found: list[str] = []
    seen_stems: set[str] = set()
    skip_tokens: set[str] = set()
    for extra in (name or "", domain or ""):
        for tok in _tokens(extra.lower()):
            if tok not in _DERIVE_STOP:
                skip_tokens.add(tok)

    def _stem(word: str) -> str:
        # Naive plural/gerund folding. ASCII-only, so it is a no-op on
        # Devanagari, Gujarati or Bengali; used for dedupe, never rejection.
        for suf in ("ings", "ing", "ers", "er", "ies", "es", "s"):
            if len(word) > len(suf) + 3 and word.endswith(suf):
                return word[: -len(suf)]
        return word

    def _add(phrase: str) -> bool:
        phrase = re.sub(r"\s+", " ", phrase).strip(" .!?:;,-—–'\"()[]")
        if not phrase or len(phrase) > 60 or _DERIVE_NOISE.search(phrase):
            return False
        toks = _tokens(phrase.lower())
        if not toks or len(toks) > 5:
            return False
        if any(t in _DERIVE_STOP for t in toks):
            return False
        # A Latin token needs 3+ letters to be a word; a non-Latin token is
        # taken on its own length, which is what lets this work for Marathi
        # or Gujarati copy with no per-script table.
        for t in toks:
            if t.isascii() and (len(t) < 3 or not t.isalpha()):
                return False
            if not t.isascii() and len(t) < 2:
                return False
            if t in skip_tokens:
                return False
        if any(ch.isdigit() for ch in phrase):
            return False
        stems = [_stem(t) for t in toks]
        if any(s in seen_stems for s in stems):
            return False
        seen_stems.update(stems)
        found.append(phrase)
        return True

    # -- pass 1: structural triggers. Grammar, not domain.
    _TRIGGER = (
        r"\b(?:for|about|featuring|showcasing|featuring|highlighting|"
        r"displaying|presenting|containing|holding|starring)\s+"
        r"((?:[\w'’-]+\s*){1,5}?)(?=\s*(?:[,.;!?]|\bwith\b|\band\b\s+(?:a|an|my|our|his|her|their)\b|\bthat\b|\bwhich\b|\bfor\b|\bto\b\s+(?:show|help|contact|book|apply)|\bin\b\s+\w+\s+\w+\b|$))"
    )
    for m in re.finditer(_TRIGGER, low):
        _add(m.group(1))

    # -- pass 2: ranked content n-grams over the whole request.
    toks = _tokens(low)
    scored: list[tuple[int, int, int, str]] = []
    for width in (3, 2, 1):
        for i in range(len(toks) - width + 1):
            span = toks[i:i + width]
            if any(t in _DERIVE_STOP for t in span):
                continue
            # A lone generic noun names nothing: "service" or "work" is what a
            # one-word ask says, but "pollination services" and "restoration
            # work" say exactly what the section is about. So the ban applies
            # to unigrams only -- inside a phrase the word is doing work.
            if width == 1 and span[0] in _DERIVE_GENERIC:
                continue
            phrase = " ".join(span)
            if _DERIVE_NOISE.search(phrase) or any(ch.isdigit() for ch in phrase):
                continue
            ok = all(
                (len(t) >= 3 and t.isalpha()) if t.isascii()
                else (len(t) >= 2 and not any(c.isdigit() for c in t))
                for t in span
            )
            if not ok or any(t in skip_tokens for t in span):
                continue
            # Longer n-grams are more specific; a plural ("paintings") names a
            # thing on the page where a singular role ("painter") names a
            # person. Later position wins ties -- briefs front-load the
            # pleasantries and specify the work at the end.
            plural = 1 if span[-1].endswith("s") and not span[-1].endswith("ss") else 0
            scored.append((width, plural, i, phrase))
    scored.sort(key=lambda r: (-r[0], -r[1], -r[2]))
    for _w, _p, _i, phrase in scored:
        if len(found) >= 6:
            break
        _add(phrase)
    return found[:6]


def extract_product_brief(prompt: str, business_type: str = "") -> dict:
    """Deterministic product identity from the user's own words (zero tokens).

    Found live in the law-firm landing test: the name fallback grabbed
    "LandingPage" (first two content words) and every per-file prompt plus the
    curated fallback scaffold rendered generic SaaS copy -- "Sterling & Cole,
    a law firm" became "LandingPage turns scattered updates into one calm
    workspace". The brief below is threaded into per-file generation AND the
    scaffold so a personalization failure can never again produce a perfectly
    built, perfectly generic site.

    Fields:
      name          -- best-effort proper name ("Sterling & Cole"), else ""
      domain        -- what the business IS ("law firm")
      subject       -- what the product is about ("premium coffee beans")
      offerings     -- explicit section/feature asks ("practice areas", ...)
      cta           -- conversion action named by the user ("free consultation")
      person/facts  -- is this a personal site, and what did the human say
                      about themselves ("i am an ai engineer")
      language      -- the register the user wrote in, so the shipped copy can
                      come back in the same one (see multilingual.py; the
                      regexes above are English-only, which is why a Hinglish
                      or Devanagari brief used to yield an empty record and
                      therefore a perfectly generic template)
    """
    text = prompt.strip()
    low = text.lower()

    # Capitalised words that are never a business or person name. Without this
    # a sentence-initial "Building" or "Make" gets captured as the brand.
    _NAME_STOP = {
        "a", "an", "the", "me", "us", "my", "our", "your", "their", "it",
        "build", "building", "create", "creating", "make", "making",
        "design", "designing", "develop", "developing", "generate",
        "website", "site", "app", "application", "page", "landing",
        "i", "im", "im", "we", "he", "she", "they", "this", "that",
        "new", "modern", "simple", "responsive", "professional",
        "please", "add", "also", "and", "or", "but", "with", "for", "from",
        "home", "best", "top", "free", "online", "first", "one", "two",
    }

    # -- name: patterns beat stopwords. Handles the observed shapes:
    #   "landing page for Sterling & Cole, a law firm website"
    #   "landing page for Flowboard, an AI tool that ..."
    #   "Build Acme CRM ..."
    name = ""
    # "... for Velvet Thread, a fashion boutique" / "for Sterling & Cole, a law
    # firm" / "for Casa Verde": proper name = capitalized words, optionally
    # chained by & / and / +, stopped by the appositive comma or article.
    _NAME_WORD = r"[A-Z][\w'’-]*"
    m = re.search(
        r"\bfor\s+(" + _NAME_WORD + r"(?:(?:\s*&\s*|\s+and\s+|\s+)" + _NAME_WORD + r"){0,3})"
        r"(?=,|\s+(?:a|an|the)\b|\s+(?:website|site|app|landing)\b"
        r"|\s+(?:with|in|that|specializing|serving)\b|\s+[a-z]|\.|\s*$)",
        text,
    )
    if m:
        name = m.group(1).strip(" ,.\"'")
        # Strip a capitalized business-type tail: "Happy Tails Veterinary
        # Hospital" -> "Happy Tails". The domain field already carries the
        # business type; the brand shouldn't repeat it.
        _TAILS = {"hospital", "clinic", "boutique", "gallery", "studio",
                  "restaurant", "cafe", "caf\u00e9", "gym", "academy", "firm",
                  "salon", "spa", "law", "fashion", "veterinary", "dental",
                  "fitness", "art", "design"}
        _words = name.split()
        while len(_words) > 1 and _words[-1].lower().strip(".,") in _TAILS:
            _words.pop()
        name = " ".join(_words)
    if not name:
        m = re.search(r"\b(?:build|create|make|design)\s+((?:[A-Z][\w'’-]+\s+){0,2}[A-Z][\w'’-]+)", text)
        if m:
            candidate = m.group(1).strip()
            if candidate.lower() not in {"a", "an", "the", "me", "us"}:
                name = candidate
    # "a bakery called Crumb", "a tuition centre called Clear Path", "a
    # dental clinic called Bright Smile" -- by far the most common way a
    # business owner names their own business, and none of the patterns above
    # saw it. Every one of these produced name="" and therefore a template
    # branded with an archetype name.
    if not name:
        m = re.search(
            r"\b(?:called|named|known\s+as|brand(?:ed)?)\s+"
            r"((?:[A-Z][\w'’-]*)(?:\s+(?:&|and|of)\s+[A-Z][\w'’-]*)*"
            r"(?:\s+[A-Z][\w'’-]*)?)",
            text,
        )
        if m:
            candidate = m.group(1).strip()
            if candidate.lower() not in _NAME_STOP:
                name = candidate
    # "a website for my tailoring business, Meera Stitch" -- the business name
    # sits after the trade noun rather than after "for" or "called".
    if not name:
        m = re.search(
            r"\b(?:business|shop|store|firm|studio|centre|center|company|"
            r"brand|academy|school|clinic)\s*,?\s+"
            r"((?:[A-Z][\w'’-]*)(?:\s+(?:&|and|of)\s+[A-Z][\w'’-]*)*"
            r"(?:\s+[A-Z][\w'’-]*)?)",
            text,
        )
        if m and m.group(1).split()[0].lower() not in _NAME_STOP:
            name = m.group(1).strip()

    # -- personal sites: the NAME is the human, stated explicitly. Live
    #    failure (portfolio run 2026-09-30): "...my name is Amey Chikane i am
    #    a computer science graduate..." produced name="" -> the shipped site
    #    was branded "PortfolioName" with generic copy -- the exact
    #    "it just makes a template" complaint.
    person_name = ""
    person_facts: list[str] = []
    m = re.search(
        r"\bmy\s+name\s+is\s+([A-Za-z][\w'’-]*(?:\s+[A-Za-z][\w'’-]*){1,3})"
        r"(?=\s*(?:,|\.|and\b|i\b|i'm\b|im\b|$))",
        text, re.IGNORECASE,
    )
    if m:
        person_name = " ".join(w.capitalize() for w in m.group(1).split())
        # Trim clause tails the greedy window swallowed: "my name is Amey
        # Chikane and i am ..." captured "Amey Chikane And", which then
        # branded the whole site "Amey Chikane And".
        person_name = re.sub(
            r"\s+(?:and|or|but|who|which|aur|aani|ani|pn|pan)\s*$", "",
            person_name, flags=re.IGNORECASE).strip()
        name = person_name
    if not person_name:
        m = re.search(r"\b(?:this\s+is\s+for|it'?s\s+for|portfolio\s+of)\s+([A-Z][\w'’-]*(?:\s+[A-Z][\w'’-]*){1,3})", text)
        if m:
            person_name = m.group(1).strip()
            name = person_name
    # "I am Priya Nair, a freelance product designer in Pune" -- the person
    # introduces themselves without ever saying "my name is". Measured on the
    # self-distillation brief bank: 2 of 22 realistic briefs lost their name
    # to this, which is 2 of 22 shipped pages branded with an archetype name.
    if not person_name:
        m = re.search(
            r"\b(?:i\s+am|i'm|im)\b\s+((?:[A-Z][\w'’-]*)(?:\s+[A-Z][\w'’-]*){0,2})"
            r"(?=\s*(?:,|\.|and\b|who\b|at\b|in\b|;|$))",
            text, re.IGNORECASE,
        )
        if m and m.group(1).split()[0].lower() not in _NAME_STOP:
            person_name = m.group(1).strip()
            name = person_name

            person_name = m.group(1).strip()
            name = person_name

    # -- persona facts: who the human is (bio, role, skills, experience).
    #    Kept verbatim-ish so section copy can be SPECIFIC instead of
    #    generic. Short clauses only; capped to keep prompts compact.
    _CLAUSE_STOP = re.compile(
        r"\s+(?:i\s+(?:am|'m|have|work|speciali[sz]e|focus|build|uploaded|provided|want|need|would|can|will)\b"
        r"|you\s+can\b|please\b|also\b)",
        re.IGNORECASE,
    )
    # Instructions about the artifact (images, logo, uploads) are not bio.
    # Devanagari instruction words are listed too -- a Marathi brief said
    # "mujhe website chahiye" and that clause was landing in the bio facts.
    _NOISE = re.compile(
        r"upload|image|photo|logo|use it|website|web site|वेबसाइट|साइट|"
        r"\bsite\b|\bapp\b|ऐप|prefer|make sure|चाहिए|चाहीए|हवी|इच्छा",
        re.IGNORECASE,
    )
    # Lazy captures that stop at the next first-person clause ("i am an ai
    # engineer" inside "i am a CS graduate ... i am an ai engineer") --
    # greedy windows would swallow the second clause and finditer skips
    # overlapping matches, losing real facts. A comma is a clause boundary
    # too: without it "i am an ai engineer with 3 years experience, build me"
    # ran to the end of the prompt, blew the length cap and was dropped.
    _STOP_LOOKAHEAD = (
        r"(?=\s+i\s+(?:am|'m|have|work|speciali[sz]e|focus|build|uploaded|provided|want|need|would|can|will)\b"
        r"|\s+you\s+can\b|\s+please\b|\s+also\b|[,.;!?]|$)"
    )
    for pat in (
        r"\bi\s+am\s+(?:a|an|the)\s+(.+?)" + _STOP_LOOKAHEAD,
        r"\bi'?m\s+(?:a|an|the)\s+(.+?)" + _STOP_LOOKAHEAD,
        r"\bi\s+(?:specialize|specialise|work|focus)\s+(?:in|on|as)\s+(.+?)" + _STOP_LOOKAHEAD,
        r"\bi\s+have\s+(.+?)" + _STOP_LOOKAHEAD,
        r"\bmy\s+(?:skills|experience|expertise|background)\s+(?:are|is|include[s]?)\s+(.+?)" + _STOP_LOOKAHEAD,
    ):
        for fm in re.finditer(pat, text, re.IGNORECASE):
            fact = fm.group(1).strip(" .,")
            if not fact or len(fact) > 90 or _NOISE.search(fact):
                continue
            if fact.lower() not in {f.lower() for f in person_facts}:
                person_facts.append(fact)
    person_facts = person_facts[:4]

    # -- multilingual fallback -------------------------------------------
    # Live failure (2026-10-02): every regex above is English-only, so a brief
    # typed in Hinglish, romanised Marathi or Devanagari produced an entirely
    # empty record and therefore a perfectly built, perfectly generic site.
    # Zero-token normalisation covers the same shapes in the other registers
    # and adds the business type, offerings, CTA and the reply language.
    language = "English"
    try:
        import multilingual as _ml
        language = _ml.language_label(text)
        if _ml.is_multilingual(text):
            if not person_name:
                person_name = _ml.roman_person_name(text)
                if person_name:
                    name = person_name
            if len(person_facts) < 2:
                _seen = {f.lower() for f in person_facts}
                for _f in _ml.roman_person_facts(text):
                    if _f.lower() in _seen:
                        continue
                    _seen.add(_f.lower())
                    person_facts.append(_f)
                person_facts = person_facts[:4]
    except Exception:  # noqa: BLE001 - never let normalisation break a brief
        pass

    # -- domain: what the thing IS, from the appositive or head noun
    #    ("... , a law firm website" -> "law firm").
    domain = ""
    m = re.search(r",\s*(?:a|an|the)\s+([a-z][a-z\s-]{2,48}?)(?:\s+website|\s+site|\s+app|\s+application|\s+that\b|\s+which\b|\s+with\b|[,.]|$)", low)
    if m:
        domain = m.group(1).strip()
    if not domain:
        m = re.search(r"\b(?:landing page|marketing site)\s+for\s+(?:a|an|the)?\s*([a-z][a-z\s-]{2,40}?)(?:\s+website|\s+site|[,.]|$)", low)
        if m:
            domain = m.group(1).strip()
    # Fallback: the profile keywords know more domains than the regexes
    # (live: "Happy Tails Veterinary Hospital" had no appositive comma ->
    # domain="" -> generic profile -> generic SaaS sections). A non-English
    # brief contributes its business nouns in English, because the profile
    # registry has no Marathi or Devanagari keywords to match against.
    if not domain:
        import domain_profiles as _dp
        _blob = low
        try:
            import multilingual as _ml
            _hint = _ml.domain_hint(text)
            if _hint["keywords"]:
                _blob = low + " " + " ".join(_hint["keywords"])
        except Exception:  # noqa: BLE001
            _hint = {"label": "", "keywords": []}
        _k = _dp.detect_domain({"domain": _blob, "business_type": "", "offerings": []})
        if _k != "generic":
            domain = _hint["label"] or _dp.domain_label(_k)

    # -- offerings: explicit asks after "with" / after dashes-colons. Only
    #    short noun phrases (1-5 words), same discipline as _implied_features.
    # An explicit list only exists if the user signalled one. This block used
    # to default to `seg = low` when no trigger matched, so "I'm an arborist,
    # I need a website to show my tree care" was split on its own commas and
    # shipped "i'm an arborist" as something the site offers -- identity
    # masquerading as inventory. No trigger, no list; the derived pass below
    # reads the user's own words instead.
    offerings: list[str] = []
    seg = ""
    m = re.search(r"\b(?:with|including|featuring|offering|containing)\b", low)
    if m:
        seg = low[m.end():]
    else:
        m = re.search(r"[\u2014\u2013-]\s", low)
        if m:
            seg = low[m.end():]
    for chunk in re.split(r"\band\b|,|;|[\u2014\u2013]|\bwith\b", seg):
        words = chunk.strip().split()
        while words and words[0] in ("a", "an", "the", "some"):
            words = words[1:]
        if 0 < len(words) <= 5:
            phrase = " ".join(words).strip(" .!?:;-")
            toks = _tokens(phrase.lower())
            if (phrase and phrase not in offerings
                    and phrase not in ("solid ui", "ui")
                    and toks
                    and not any(t in _DERIVE_STOP for t in toks)
                    and not _NOISE.search(phrase)
                    and not _DERIVE_NOISE.search(phrase)):
                offerings.append(phrase)
    # Non-English briefs: the English "with ..." segmentation has nothing to
    # bite on, so pull the service nouns out of the multilingual lexicon
    # ("ऑनलाइन ऑर्डर" -> "online ordering", "होम डिलीवरी" -> "home delivery").
    try:
        import multilingual as _ml
        if _ml.is_multilingual(text):
            for hint in _ml.offering_hints(text):
                if hint not in offerings:
                    offerings.append(hint)
    except Exception:  # noqa: BLE001
        pass
    # -- derived asks: read the USER'S OWN WORDS.
    #    The "with ..." segmentation above only fires on an explicit list, so
    #    most briefs produced no offerings at all and the generic profile fell
    #    back to the string "the business's core offerings" -- a placeholder
    #    in the section ask, which is the template failure wearing a hat.
    #    Measured across 20 professions: music producer, architect,
    #    veterinarian and electrician all landed there. Mining the content
    #    words of the request instead generalises to every trade without
    #    adding a profile per profession:
    #      "an art major and painter ... for my paintings and exhibitions"
    #        -> art major / painter / paintings / exhibitions
    if not offerings:
        offerings = _derived_offerings(text, name, domain)
    offerings = offerings[:6]

    # -- conversion ask
    cta = ""
    m = re.search(r"(free\s+\w+|book\s+a?\s*\w+|schedule\s+a?\s*\w+|get\s+started|start\s+\w+|request\s+a?\s*\w+|sign\s?up)", low)
    if m:
        cta = m.group(1).strip()
    if not cta:
        try:
            import multilingual as _ml
            cta = _ml.cta_hint(text)
        except Exception:  # noqa: BLE001
            pass

    # -- subject: WHAT the product is about, when the prompt names it.
    #    Live failure (coffee-store run 2026-10-01): "e-commerce store for
    #    premium coffee beans with ..." produced domain="restaurant", an
    #    empty name, and NO mention of coffee anywhere in the per-file
    #    prompts -- so the model invented headphone products. The subject
    #    noun phrase is the one thing every section must be about.
    subject = ""
    m = re.search(
        r"\b(?:store|shop|site|website|app|application|platform|system|marketplace|brand)\s+for\s+"
        r"(?:a|an|the)?\s*([a-z][\w'’-]*(?:\s+[a-z][\w'’-]*){0,5}?)"
        r"(?=\s+(?:with|that|which|including|featuring|offering|and|in|for)\b|[,.]|$)",
        low,
    )
    if m:
        subject = m.group(1).strip(" .,")
        # "premium coffee beans" is a subject; "modern e-commerce" is a
        # description of the artifact -- reject adjective-only captures.
        _STOP_SUBJECTS = {"modern", "simple", "clean", "beautiful", "new",
                          "professional", "minimal", "responsive", "full",
                          "complete", "custom", "online"}
        words = [w for w in subject.split() if w not in _STOP_SUBJECTS]
        subject = " ".join(words)
        if len(subject.split()) < 1 or subject in ("website", "site", "app"):
            subject = ""

    return {
        "name": name,
        "domain": domain,
        "subject": subject,
        "offerings": offerings,
        "cta": cta,
        "person": bool(person_name),
        "facts": person_facts,
        "business_type": business_type or "",
        # Which register the user wrote in. Threaded into the per-file prompt
        # so the shipped copy comes back in their language, not in English
        # boilerplate -- the other half of "it just made a template".
        "language": language,
    }


app = FastAPI(title="TerabitStudio - AI Business OS Generator")

# Fine-tuning-as-a-feature: dataset generation + QLoRA training job API.
from finetune_api import router as finetune_router
app.include_router(finetune_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ───────── Request schemas ─────────

class RegisterRequest(BaseModel):
    email: str
    password: str

class LoginRequest(BaseModel):
    email: str
    password: str

class ChatRequest(BaseModel):
    messages: list
    temperature: float = 0.7
    max_tokens: int = 2048
    session_id: Optional[int] = None

class AssetInfo(BaseModel):
    url: str
    filename: str
    mime_type: str
    original_name: str = ""

class GenerateRequest(BaseModel):
    prompt: str
    business_type: str = "general"
    features: list[str] = Field(default_factory=list)
    assets: list[AssetInfo] = Field(default_factory=list)
    project_files: list[dict] = Field(default_factory=list)
    brand: dict = Field(default_factory=dict)
    operation: str = "create"
    temperature: float = 0.85
    session_id: Optional[int] = None
    # Bolt/Lovable-style agentic generation (per-file + bundler verify loop).
    # Default ON: measured strictly better than single-shot for app builds.
    use_agent: bool = True
    # Provider override: "auto" (local-first) | "local" | "openai" | "gemini" | "anthropic"
    provider: str = "auto"
    # Cloud model id when provider != local (e.g. "gpt-4o-mini", "gemini-2.0-flash")
    model: str = ""

class SearchRequest(BaseModel):
    query: str
    mode: str = "chat"
    project_files: list[dict] = Field(default_factory=list)

class DownloadRequest(BaseModel):
    files: list
    project_name: str = "project"

class SessionCreateRequest(BaseModel):
    name: str = "New Chat"

# ───────── Startup ─────────

app.include_router(model_api.router)


@app.on_event("startup")
async def startup():
    start_server()
    warm_up_model_async()

# ───────── Auth endpoints ─────────

@app.post("/api/auth/register")
def register(req: RegisterRequest, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.email == req.email).first()
    if existing:
        raise HTTPException(400, "Email already registered")
    user = User(email=req.email, password_hash=hash_password(req.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    token = create_token({"sub": str(user.id)})
    return {"token": token, "user": {"id": user.id, "email": user.email}}

@app.post("/api/auth/login")
def login(req: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == req.email).first()
    if not user or not verify_password(req.password, user.password_hash):
        raise HTTPException(401, "Invalid email or password")
    token = create_token({"sub": str(user.id)})
    return {"token": token, "user": {"id": user.id, "email": user.email}}

@app.get("/api/auth/me")
def me(user: Optional[User] = Depends(get_current_user)):
    if not user:
        raise HTTPException(401, "Not authenticated")
    return {"id": user.id, "email": user.email}

# ───────── Session endpoints ─────────

@app.get("/api/sessions")
def list_sessions(user: Optional[User] = Depends(get_current_user), db: Session = Depends(get_db)):
    if not user:
        # For anonymous users, return sessions with user_id = 0 (or null)
        sessions = db.query(ChatSession).filter(
            ChatSession.user_id == 0
        ).order_by(ChatSession.updated_at.desc()).all()
    else:
        sessions = db.query(ChatSession).filter(
            ChatSession.user_id == user.id
        ).order_by(ChatSession.updated_at.desc()).all()
    return [
        {"id": s.id, "name": s.name, "created_at": s.created_at.isoformat(), "updated_at": s.updated_at.isoformat()}
        for s in sessions
    ]

@app.post("/api/sessions")
def create_session(req: SessionCreateRequest, user: Optional[User] = Depends(get_current_user), db: Session = Depends(get_db)):
    if not user:
        # Create anonymous session with user_id = 0
        session = ChatSession(user_id=0, name=req.name)
        db.add(session)
        db.commit()
        db.refresh(session)
        return {"id": session.id, "name": session.name, "created_at": session.created_at.isoformat(), "anonymous": True}
    session = ChatSession(user_id=user.id, name=req.name)
    db.add(session)
    db.commit()
    db.refresh(session)
    return {"id": session.id, "name": session.name, "created_at": session.created_at.isoformat()}

@app.delete("/api/sessions/{session_id}")
def delete_session(session_id: int, user: Optional[User] = Depends(get_current_user), db: Session = Depends(get_db)):
    if not user:
        raise HTTPException(401, "Authentication required")
    session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    if not session:
        raise HTTPException(404, "Session not found")
    if session.user_id != user.id:
        raise HTTPException(403, "Forbidden")
    db.query(ChatMessage).filter(ChatMessage.session_id == session_id).delete()
    db.delete(session)
    db.commit()
    return {"ok": True}

# ───────── Message endpoints ─────────

@app.get("/api/sessions/{session_id}/messages")
def get_messages(session_id: int, user: Optional[User] = Depends(get_current_user), db: Session = Depends(get_db)):
    if not user:
        raise HTTPException(401, "Authentication required")
    session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    if not session:
        raise HTTPException(404, "Session not found")
    if session.user_id != user.id:
        raise HTTPException(403, "Forbidden")
    messages = db.query(ChatMessage).filter(
        ChatMessage.session_id == session_id
    ).order_by(ChatMessage.created_at.asc()).all()
    return [
        {"id": m.id, "role": m.role, "content": m.content, "created_at": m.created_at.isoformat()}
        for m in messages
    ]

# ───────── Asset endpoints ─────────

ALLOWED_MIME_TYPES = {
    "image/jpeg", "image/png", "image/gif", "image/webp", "image/svg+xml",
    "application/pdf", "text/plain", "text/csv",
}

@app.post("/api/upload")
async def upload_asset(
    file: UploadFile = File(...),
    user: Optional[User] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not user:
        raise HTTPException(401, "Authentication required to upload assets")
    if file.content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(400, f"Unsupported file type: {file.content_type}")
    ext = file.filename.rsplit(".", 1)[-1] if "." in file.filename else "bin"
    stored_name = f"{uuid.uuid4().hex}.{ext}"
    file_path = UPLOAD_DIR / stored_name
    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(413, "File too large (max 10MB)")
    file_path.write_bytes(content)
    asset = Asset(
        user_id=user.id,
        filename=stored_name,
        original_name=file.filename,
        mime_type=file.content_type or "application/octet-stream",
        size=len(content),
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return {
        "id": asset.id,
        "url": f"/uploads/{stored_name}",
        "filename": stored_name,
        "original_name": file.filename,
        "mime_type": asset.mime_type,
        "size": asset.size,
        "created_at": asset.created_at.isoformat(),
    }


@app.get("/api/assets")
def list_assets(user: Optional[User] = Depends(get_current_user), db: Session = Depends(get_db)):
    if not user:
        raise HTTPException(401, "Authentication required")
    query = db.query(Asset).filter(Asset.user_id == user.id).order_by(Asset.created_at.desc())
    assets = query.all()
    return [
        {
            "id": a.id,
            "url": f"/uploads/{a.filename}",
            "filename": a.filename,
            "original_name": a.original_name,
            "mime_type": a.mime_type,
            "size": a.size,
            "created_at": a.created_at.isoformat(),
        }
        for a in assets
    ]


@app.delete("/api/assets/{asset_id}")
def delete_asset(
    asset_id: int,
    user: Optional[User] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not user:
        raise HTTPException(401, "Authentication required")
    asset = db.query(Asset).filter(Asset.id == asset_id).first()
    if not asset:
        raise HTTPException(404, "Asset not found")
    if asset.user_id != user.id:
        raise HTTPException(403, "Forbidden")
    file_path = UPLOAD_DIR / asset.filename
    if file_path.exists():
        file_path.unlink()
    db.delete(asset)
    db.commit()
    return {"ok": True}


# ───── Core AI endpoints ─────

SYSTEM_PROMPT = """You are TerabitStudio, an AI business systems architect.
You help users design, build, and refine business management systems.
Be concise, practical, and focus on delivering working solutions."""


def generate_complete_response(
    messages: list,
    max_tokens: int = 7000,
    temperature: float = 0.7,
    max_continuations: int = 3,
    provider: str = "",
    model: str = "",
) -> str:
    """Call the model and, if it hit max_tokens before actually finishing
    (the finish_reason the API reports as "length"), ask it to continue
    instead of silently shipping truncated code back to the frontend.

    This matters a lot here specifically because a 7B model asked to emit an
    entire multi-file React project in one completion very commonly runs out
    of budget mid-file - which used to mean an unterminated JSX tag / string
    / code fence, which used to mean parse_generated_files() either dropped
    that file or mangled everything after it, which used to mean the preview
    broke. Continuing until finish_reason == 'stop' (or we hit
    max_continuations, as a safety valve against a runaway loop) fixes that
    at the root instead of trying to patch around it after the fact.

    NOTE ON CONTEXT SIZE: each continuation round resends the entire
    conversation so far (prompt + everything generated up to that point),
    so total tokens in play grow every round. With the default N_CTX=16384
    in .env, keep max_tokens in the 6000-8000 range - if you increase N_CTX
    (recommended: 24576-32768 if you have the VRAM for it), you can safely
    raise this for fewer, larger continuations.
    """
    full_text = ""
    convo = list(messages)
    round_tokens = max_tokens
    for round_num in range(max_continuations + 1):
        # Routed through providers so the request's provider/model override
        # (local-first, or an OpenAI-compatible / Gemini / Anthropic model)
        # applies here exactly as it does on the agent path.
        text, finish_reason = providers.chat(
            convo,
            max_tokens=round_tokens,
            temperature=temperature if round_num == 0 else max(0.2, temperature - 0.3),
            provider=provider,
            model=model,
        )
        if finish_reason == "error":
            # A context-length kill arrives here as a normal error string; it is
            # not model output. Shrink the ask and retry while the context
            # allows it -- running out of window mid-generation is a BUDGET bug,
            # not a model bug (and used to be reported to the user as
            # "the model did not answer ... GPU is not out of memory").
            if context_budget.is_context_error(text) and round_tokens > 1500 and round_num < max_continuations:
                round_tokens = max(1500, round_tokens // 2)
                continue
            raise RuntimeError(
                f"The model did not answer ({str(text)[:300]}). Check that Ollama is "
                "running (`ollama list`), that the tag in .env MODEL_NAME exists, and "
                "that the GPU is not out of memory. Nothing was generated."
            )
        full_text += text
        if finish_reason != "length" or round_num == max_continuations:
            break
        convo = convo + [
            {"role": "assistant", "content": text},
            {"role": "user", "content": (
                "Continue exactly where you left off. Do not repeat any file or "
                "line already written above - resume the last file's code from "
                "the exact point you stopped (mid-line if needed), then continue "
                "to any remaining files. Do not restate the file path header for "
                "a file you already started."
            )},
        ]
        # Each round adds to the running conversation length, so shrink the
        # ask each time to stay within the context window instead of
        # overflowing it on round 2+.
        round_tokens = max(1500, round_tokens // 2)
    return full_text


@app.post("/api/chat")
async def chat(req: ChatRequest, user: Optional[User] = Depends(get_current_user), db: Session = Depends(get_db)):
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + req.messages
    response = generate_response(messages, temperature=req.temperature, max_tokens=req.max_tokens)

    if req.session_id and user:
        db.add(ChatMessage(session_id=req.session_id, role="user", content=req.messages[-1]["content"]))
        db.add(ChatMessage(session_id=req.session_id, role="assistant", content=response))
        db.commit()

    return {"response": response}


@app.post("/api/chat/stream")
async def chat_stream(req: ChatRequest, request: Request):
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + req.messages

    async def event_stream():
        for token in generate_response_stream(messages, temperature=req.temperature, max_tokens=req.max_tokens):
            if await request.is_disconnected():
                break
            yield f"data: {json.dumps({'token': token})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


def prepare_generation(req: GenerateRequest, operation: str) -> dict:
    """Shared prep for /api/generate and /api/generate/stream.

    Builds the full prompt from budgeted sections: retrieval → IR plan →
    registry signatures → instructions, then merges the archetype scaffold.
    This is the seam where the IR generator and component registry finally
    participate in the live generation path (previously both modules were
    built but never wired into /api/generate).
    """
    # Deterministic product identity (name/domain/offerings/cta) -- zero
    # tokens, and the antidote to the "perfectly built generic site" failure:
    # the previous name heuristic grabbed "LandingPage" from "Build a landing
    # page for Sterling & Cole, a law firm ...".
    brief = extract_product_brief(req.prompt, req.business_type)
    app_name = brief["name"] or "Zenith"
    if app_name == "Zenith" and not brief["name"]:
        if req.brand and req.brand.get("name"):
            app_name = req.brand.get("name")
        elif "zenith" in req.prompt.lower():
            app_name = "Zenith"
        else:
            # Name the app from what it IS, not from the verb that asked for
            # it: "Build a bug tracker board" used to name the app "Build".
            _skip = {"build", "create", "make", "design", "generate", "add", "develop",
                     "write", "please", "new", "simple", "basic", "modern", "responsive",
                     "landing", "page", "website", "site", "app",
                     "a", "an", "the", "me", "my", "for", "with", "that", "this"}
            words = [
                w.strip(".,:;!?\"'()")
                for w in req.prompt.split()
                if len(w.strip(".,:;!?\"'()")) > 2 and w.lower().strip(".,:;!?") not in _skip
            ]
            if words:
                app_name = "".join(w[:1].upper() + w[1:] for w in words[:2]).replace("-", "")[:24]

    archetype = get_archetype_for_prompt(req.prompt, req.business_type)
    # Task-level routing: the open-vocabulary classifier reads the brief for
    # WHAT kind of system it is (a back-office console: CRM / HMS / EMS / HR /
    # inventory / ... vs a marketing site vs a store). When it says console, the
    # artifact is a management app -- not a marketing page wearing a dashboard
    # costume. The prompt-keyword pass alone misses phrasings like "an app that
    # manages my clinic's patients and staff", so the brief's own words decide.
    try:
        from task_understanding import infer_spec  # late import: no cycle at module load
        if (infer_spec(brief).get("family") or "") == "console" and archetype in ("saas", "landing"):
            archetype = "admin"
    except Exception:  # noqa: BLE001 - routing must never break a build
        pass

    # 1. Budgeted retrieval of existing project files. Edit mode grounds the
    #    model in the real code; the budget packs whole files by rank instead
    #    of a fixed 4-file/3500-char slice.
    retrieval_budget = context_budget.budget_for("retrieval") if operation == "edit" else 0
    project_context, _sources = retrieve_project_context(
        req.prompt, req.project_files, budget_chars=retrieval_budget or None,
    )

    # 2. Deterministic IR: storyboard + data model derived from the request
    #    (zero tokens/latency; LLM two-stage path remains available for
    #    research comparison via generate_all_irs(use_llm=True)).
    irs = _ir_generator.generate_all_irs(
        user_request=req.prompt,
        business_type=req.business_type or archetype,
        features=req.features,
        registry_components={},
        operation=operation,
    )

    # 3. Registry signatures relevant to this request.
    registry_context = _registry.build_registry_context(
        [req.prompt, req.business_type, *req.features]
    )

    # 4. Assemble the system prompt, each section trimmed to its budget.
    ir_section = context_budget.trim_to_budget(
        format_ir_for_prompt(irs), context_budget.budget_for("ir"), "IR plan"
    )
    registry_section = context_budget.trim_to_budget(
        registry_context, context_budget.budget_for("registry"), "registry"
    )
    project_context = context_budget.trim_to_budget(
        project_context, retrieval_budget, "project context"
    )

    system_prompt = generate_business_system_prompt(
        req.business_type, req.features, req.prompt,
        assets=[a.model_dump() for a in req.assets],
        brand=req.brand,
        project_context=project_context,
        operation=operation,
        ir_context=ir_section,
        registry_context=registry_section,
    )

    asset_context = ""
    if req.assets:
        asset_lines = "\n".join(
            f"- {a.filename} ({a.mime_type}): available at {a.url}"
            for a in req.assets
        )
        asset_context = f"\n\nUser uploaded assets:\n{asset_lines}"

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Build/customize the {req.business_type} system '{app_name}': {req.prompt}{asset_context}"},
    ]

    base_files = get_base_scaffold(archetype, app_name=app_name, brand=req.brand) if operation == "create" else []

    return {
        "messages": messages,
        "base_files": base_files,
        "archetype": archetype,
        "app_name": app_name,
        "brief": brief,
        "irs": irs,
    }


@app.post("/agentic/generate")
async def agentic_generate(req: GenerateRequest, user: Optional[User] = Depends(get_current_user), db: Session = Depends(get_db)):
    """Bolt/Lovable-style per-file generation with bundler-verified output."""
    operation = "edit" if req.operation == "edit" and req.project_files else "create"
    prep = prepare_generation(req, operation)
    result = agentic_generator.run_agent(req, prep, provider=req.provider, model=req.model)
    conversational = (
        f"Built **{prep['app_name']}** as {len(result['files'])} bundler-verified files "
        f"({', '.join(f['path'] for f in result['files'][:4])}...)."
    )
    if req.session_id and user:
        db.add(ChatMessage(session_id=req.session_id, role="user", content=req.prompt))
        db.add(ChatMessage(session_id=req.session_id, role="assistant", content=conversational))
        db.commit()
    return {
        "response": conversational,
        "files": result["files"],
        "full_response": result["full_response"],
        "agent_trace": result["agent_trace"],
        "bundle_ok": result["bundle_ok"],
    }


@app.post("/api/generate")
async def generate(req: GenerateRequest, user: Optional[User] = Depends(get_current_user), db: Session = Depends(get_db)):
    operation = "edit" if req.operation == "edit" and req.project_files else "create"
    # prepare_generation does synchronous RAG/embedding/Ollama calls -- never
    # run it on the event loop or one slow prepare starves every endpoint
    # (health checks included) for the duration.
    prep = await asyncio.to_thread(prepare_generation, req, operation)

    # ── Agentic path (default): per-file plan -> generate -> verify -> repair ──
    # Runs for edits too: the agent then plans the minimal change set, sees the
    # current file contents, and the bundle is verified over the whole project.
    if req.use_agent:
        # Multi-minute generation must not occupy the event loop -- otherwise
        # EVERY endpoint (health, preview, selftest) freezes until it finishes.
        _t0 = time.perf_counter()
        result = await asyncio.to_thread(
            agentic_generator.run_agent, req, prep,
            provider=req.provider, model=req.model,
        )
        dump_generation_artifacts(req, prep, result, time.perf_counter() - _t0, "generate")
        conversational_response = (
            f"Built **{prep['app_name']}** as {len(result['files'])} files with a passing production bundle."
            if result["bundle_ok"] else
            f"Built **{prep['app_name']}** as {len(result['files'])} files (bundle needs attention)."
        )
        if req.session_id and user:
            db.add(ChatMessage(session_id=req.session_id, role="user", content=req.prompt))
            db.add(ChatMessage(session_id=req.session_id, role="assistant", content=conversational_response))
            session = db.query(ChatSession).filter(ChatSession.id == req.session_id).first()
            if session and session.name == "New Chat":
                session.name = f"{prep['app_name']} ({req.prompt[:30]})"
            db.commit()
        # Ensure user assets (logo + background) are injected even on agentic path
        result["files"] = imagery.upload_image_injection(
            result["files"], brand=req.brand,
            assets=[a.model_dump() for a in req.assets])
        return {
            "response": conversational_response,
            "files": result["files"],
            "full_response": result["full_response"],
            "agent_trace": result["agent_trace"],
            "bundle_ok": result["bundle_ok"],
        }

    # ── Legacy single-shot path (edit operations + explicit opt-out) ──
    messages = prep["messages"]
    base_files = prep["base_files"]
    archetype = prep["archetype"]
    app_name = prep["app_name"]
    
    # Generate completion with an output budget derived from N_CTX
    response = generate_complete_response(
        messages,
        max_tokens=context_budget.output_budget(operation),
        temperature=req.temperature,
        max_continuations=1,
        provider=req.provider,
        model=req.model,
    )

    response = scrub_artifacts(response)
    conversational_response = extract_conversational_response(response)
    if not conversational_response or len(conversational_response) < 10:
        conversational_response = f"I've built the {archetype} application for **{app_name}** with interactive state management, custom components, and responsive Tailwind styling."

    parsed_files = parse_generated_files(response)
    if not parsed_files:
        parsed_files = parse_markdown_structure(response)
    if not parsed_files:
        parsed_files = parse_loose_fenced_files(response)

    # Merge base scaffold with parsed files
    file_dict = {f["path"]: f["content"] for f in base_files}
    for f in parsed_files:
        file_dict[f["path"]] = f["content"]
    
    final_files = [{"path": p, "content": c} for p, c in file_dict.items()]
    final_files = inject_core_files(final_files)
    final_files = inject_images(final_files)
    final_files, _img_stats = imagery.enforce_imagery(final_files, _theme_key_for(req))
    final_files = imagery.upload_image_injection(final_files, brand=req.brand,
                                                   assets=[a.model_dump() for a in req.assets])
    final_files = validate_and_repair_files(final_files)

    if req.session_id and user:
        db.add(ChatMessage(session_id=req.session_id, role="user", content=req.prompt))
        db.add(ChatMessage(session_id=req.session_id, role="assistant", content=conversational_response))
        session = db.query(ChatSession).filter(ChatSession.id == req.session_id).first()
        if session and session.name == "New Chat":
            session.name = f"{app_name} ({req.prompt[:30]})"
        db.commit()

    return {"response": conversational_response, "files": final_files, "full_response": response}


@app.post("/api/generate/stream")
async def generate_stream(req: GenerateRequest, request: Request):
    operation = "edit" if req.operation == "edit" and req.project_files else "create"
    prep = None
    prep_error = None

    try:
        # prepare_generation does synchronous RAG/embedding/Ollama calls --
        # run it off the event loop so concurrent prepares can't starve the
        # whole server (this exact starvation wedged the backend during a
        # concurrent gate run).
        prep = await asyncio.to_thread(prepare_generation, req, operation)
    except Exception as e:
        prep_error = str(e)
    
    messages = prep["messages"] if prep else []
    base_files = prep["base_files"] if prep else []
    archetype = prep["archetype"] if prep else "saas"
    app_name = prep["app_name"] if prep else "App"

    async def event_stream():
        if prep_error:
            yield f"data: {json.dumps({'error': f'Preparation failed: {prep_error}'})}\n\n"
            return
            
        # ── Agentic streaming path: real per-file progress over SSE ──
        if req.use_agent:
            queue: asyncio.Queue = asyncio.Queue()

            def progress(msg):
                queue.put_nowait(msg)

            async def run_in_thread():
                try:
                    _t0 = time.perf_counter()
                    result = await asyncio.to_thread(
                        agentic_generator.run_agent, req, prep, progress,
                        provider=req.provider, model=req.model,
                    )
                    dump_generation_artifacts(req, prep, result, time.perf_counter() - _t0, "stream")
                    await queue.put(("__DONE__", result))
                except Exception as e:  # surface agent crashes to the client
                    print(f"[stream] Agent error: {e}")
                    await queue.put(("__ERROR__", str(e)))

            runner = asyncio.create_task(run_in_thread())
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=30.0)
                except asyncio.TimeoutError:
                    if await request.is_disconnected():
                        runner.cancel()
                        break
                    continue
                    
                if isinstance(item, tuple):
                    kind, payload = item
                    break
                if await request.is_disconnected():
                    runner.cancel()
                    break
                yield f"data: {json.dumps({'token': f"{item}\n\n", 'conversational': True})}\n\n"

            if kind == "__ERROR__":
                yield f"data: {json.dumps({'error': payload})}\n\n"
                # Terminate here: falling through re-runs the legacy single-
                # shot path, silently doubling a failed run's wall time and
                # confusing clients with error-then-success payloads (live:
                # portfolio user-test 20261001-1917 spent 607s re-generating
                # after an asset-normalization crash).
                return
            else:
                result = payload
                summary = (
                    f"🎉 **{app_name}** built with {len(result['files'])} files — "
                    f"production bundle {'verified ✓' if result['bundle_ok'] else 'needs attention ⚠'}."
                )
                yield f"data: {json.dumps({'token': f'\n\n{summary}', 'conversational': True})}\n\n"
                # `summary` is the human-readable result: on this path
                # full_response is the generated source, so a client that
                # regex-extracts "prose" from it ends up showing a filename.
                yield f"data: {json.dumps({'done': True, 'files': result['files'], 'summary': summary, 'full_response': result['full_response'], 'agent_trace': result['agent_trace'], 'bundle_ok': result['bundle_ok']})}\n\n"

        # ── Legacy single-shot streaming (edit ops / agent opt-out) ──
        # providers.stream is a SYNC generator doing blocking HTTP. Iterating
        # it directly on the event loop froze the entire server for the whole
        # generation (live: login/health/assets all hung while a 607s run
        # streamed). Pull tokens one at a time through a worker thread so the
        # loop keeps serving everything else.
        buffer = ""
        _it = iter(providers.stream(
            messages,
            temperature=req.temperature,
            max_tokens=context_budget.output_budget(operation),
            provider=req.provider,
            model=req.model,
        ))
        _STREAM_DONE = object()

        def _next_token(it):
            try:
                return next(it)
            except StopIteration:
                return _STREAM_DONE

        while True:
            token = await asyncio.to_thread(_next_token, _it)
            if token is _STREAM_DONE:
                break
            if await request.is_disconnected():
                break
            buffer += token

        # Parse model outputs
        parsed_files = parse_generated_files(scrub_artifacts(buffer))
        if not parsed_files:
            parsed_files = parse_markdown_structure(scrub_artifacts(buffer))
        if not parsed_files:
            parsed_files = parse_loose_fenced_files(scrub_artifacts(buffer))

        # Merge base scaffold with parsed files
        file_dict = {f["path"]: f["content"] for f in base_files}
        for f in parsed_files:
            file_dict[f["path"]] = f["content"]

        final_files = [{"path": p, "content": c} for p, c in file_dict.items()]
        final_files = inject_core_files(final_files)
        final_files = inject_images(final_files)
        final_files, _img_stats = imagery.enforce_imagery(final_files, _theme_key_for(req))
        final_files = imagery.upload_image_injection(final_files, brand=req.brand,
                                                       assets=[a.model_dump() for a in req.assets])
        final_files = validate_and_repair_files(final_files)

        summary = f"🎉 **{app_name}** has been built successfully with {len(final_files)} project files! Live interactive preview is ready."
        yield f"data: {json.dumps({'token': f'\n\n{summary}', 'conversational': True})}\n\n"
        yield f"data: {json.dumps({'done': True, 'files': final_files, 'summary': summary, 'full_response': buffer})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/api/selftest")
async def selftest(full: bool = False):
    """Smoke-test the generation stack so regressions fail loudly.

    Always checks: model server reachable, file parser, lucide fixer, and the
    deterministic esbuild bundle path (the exact stage the asyncio-import
    incident silently broke in the UI while the eval gate stayed green).
    ?full=true additionally runs ONE tiny real agent generation end-to-end
    (plan -> generate -> assemble -> bundle-verify) -- a few minutes on local.
    """
    checks: dict = {}
    try:
        import urllib.request
        host = os.environ.get("LLAMA_SERVER_HOST", "127.0.0.1")
        port = os.environ.get("LLAMA_SERVER_PORT", "11434")
        with urllib.request.urlopen(f"http://{host}:{port}/api/tags", timeout=5) as resp:
            models = json.loads(resp.read()).get("models", [])
        # Resolve through the same alias table the generation path uses, so the
        # check sees the tag Ollama is actually serving (a context-variant id
        # like terabit-v3-ctx8k resolves to its base terabit-finetuned-v3).
        wanted = ""
        try:
            import model_sources
            wanted = model_sources.resolve_ollama_tag(os.environ.get("MODEL_NAME", "")) or ""
        except Exception:  # noqa: BLE001
            wanted = os.environ.get("MODEL_NAME", "")
        names = [m.get("name", "") for m in models]
        checks["model_server"] = (
            True if not wanted or any(n.startswith(wanted) or n.split(":")[0] == wanted.split(":")[0] for n in names)
            else f"fail: {wanted} not in ollama ({names})"
        )
    except Exception as e:  # noqa: BLE001
        checks["model_server"] = f"error: {e}"

    # Parser: the canonical FILE:-fenced format must yield the file.
    sample = "`src/App.jsx`\n```jsx\nexport default function App() {\n  return <div>ok</div>\n}\n```"
    parsed = parse_generated_files(sample)
    checks["file_parser"] = bool(parsed and parsed[0]["path"] == "src/App.jsx")

    # Lucide fixer: hallucinated icon must be rewritten.
    fixed = agentic_generator.fix_lucide_imports(
        "src/App.jsx", "import { Bag } from 'lucide-react'\nexport default function A() { return <Bag /> }"
    )
    checks["lucide_fixer"] = "ShoppingBag as Bag" in fixed

    # Preview path: the SAME builder the UI's preview pane uses must reach
    # tier-1 (real esbuild bundle inlined, not the Babel/CDN or file-listing
    # fallbacks) for a minimal project.
    try:
        html = build_preview_html([
            {"path": "package.json", "content": json.dumps({
                "name": "selftest", "private": True, "version": "0.1.0",
                "type": "module", "scripts": {"dev": "vite"},
                "dependencies": {"react": "^18.2.0", "react-dom": "^18.2.0"},
            })},
            {"path": "index.html", "content": '<!doctype html><html><body><div id="root"></div>'
                                               '<script type="module" src="/src/main.jsx"></script></body></html>'},
            {"path": "src/main.jsx", "content": "import React from 'react'\nimport { createRoot } from 'react-dom/client'\n"
                                               "import App from './App.jsx'\ncreateRoot(document.getElementById('root'))"
                                               ".render(<React.StrictMode><App /></React.StrictMode>)"},
            {"path": "src/index.css", "content": "@tailwind base;\n@tailwind components;\n@tailwind utilities;"},
            {"path": "src/App.jsx", "content": "export default function App() {\n  return <div className=\"p-4\">selftest</div>\n}\n"},
        ])
        tier = preview_tier(html)
        checks["preview_builder"] = (
            True if tier == "tier1-bundled" else f"fail: {tier} (expected tier1-bundled)"
        )
    except Exception as e:  # noqa: BLE001
        checks["preview_builder"] = f"error: {e}"

    # Bundle path: a minimal valid project must pass the real esbuild check.
    try:
        ok, err = agentic_generator.bundle_check({
            "package.json": json.dumps({
                "name": "selftest", "private": True, "version": "0.1.0",
                "type": "module", "scripts": {"dev": "vite"},
                "dependencies": {"react": "^18.2.0", "react-dom": "^18.2.0"},
            }),
            "index.html": '<!doctype html><html><body><div id="root"></div>'
                          '<script type="module" src="/src/main.jsx"></script></body></html>',
            "src/main.jsx": "import React from 'react'\nimport { createRoot } from 'react-dom/client'\n"
                            "import App from './App.jsx'\ncreateRoot(document.getElementById('root'))"
                            ".render(<React.StrictMode><App /></React.StrictMode>)",
            "src/index.css": "@tailwind base;\n@tailwind components;\n@tailwind utilities;",
            "src/App.jsx": "export default function App() {\n  return <div className=\"p-4\">selftest</div>\n}\n",
        })
        checks["bundle_check"] = ok if ok else f"fail: {err[:120]}"
    except Exception as e:  # noqa: BLE001
        checks["bundle_check"] = f"error: {e}"

    if full and all(str(v).startswith(("True", "ok")) or v is True for v in checks.values()):
        class _MiniReq:
            prompt = "one-file counter with a button"
            business_type = "business-app"
            features: list = []
            assets: list = []
            brand: dict = {}
            project_files: list = []
            operation = "create"
            temperature = 0.5
            use_agent = True
        try:
            prep = prepare_generation(_MiniReq(), "create")
            result = await asyncio.to_thread(
                agentic_generator.run_agent, _MiniReq(), prep, None,
            )
            checks["agent_e2e"] = (
                f"ok: {len(result['files'])} files, bundle_ok={result['bundle_ok']}"
                if result["files"] else "fail: no files"
            )
        except Exception as e:  # noqa: BLE001
            checks["agent_e2e"] = f"error: {str(e)[:150]}"

    passed = all(
        v is True or (isinstance(v, str) and (v == "ok" or v.startswith("ok:")))
        for v in checks.values()
    )
    return {"status": "pass" if passed else "fail", "checks": checks}


@app.post("/api/search")
async def search(req: SearchRequest):
    if req.mode == "rag":
        context, sources = rag_search(req.query, req.project_files)
        if context:
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"Answer based on:\n\n{context}\n\nQuestion: {req.query}"},
            ]
            answer = generate_response(messages, max_tokens=1024)
            return {"answer": answer, "sources": sources}
        return {"answer": "No search results found.", "sources": []}

    response = generate_response(
        [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": req.query}],
        max_tokens=1024,
    )
    return {"answer": response, "sources": []}


@app.post("/api/correct")
async def correct_code(payload: dict):
    code = payload.get("code", "")
    language = payload.get("language", "auto")
    messages = [
        {"role": "system", "content": "You are a code review expert. Fix bugs, improve style, and optimize. Return only the corrected code."},
        {"role": "user", "content": f"Language: {language}\n\nCode:\n{code}"},
    ]
    corrected = generate_response(messages, temperature=0.1, max_tokens=4096)
    return {"corrected_code": corrected, "language": language}

# ───────── Preview & Download ─────────

@app.post("/api/preview")
async def generate_preview(payload: dict):
    """Build a self-contained HTML preview from generated project files."""
    files = payload.get("files", [])
    print(f"[preview] Received {len(files)} files for preview")
    for f in files:
        print(f"[preview] File: {f.get('path')} ({len(f.get('content', ''))} chars)")
    html = build_preview_html(files)
    tier = preview_tier(html)
    print(f"[preview] Generated HTML length: {len(html) if html else 0} ({tier})")
    return {"html": html, "tier": tier}


@app.post("/api/download")
async def download_project(req: DownloadRequest):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in req.files:
            path = f.get("path", "")
            content = f.get("content", "")
            zf.writestr(path, content)
    buf.seek(0)
    safe_name = req.project_name.replace(" ", "_").replace("/", "_")
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename={safe_name}.zip"},
    )

# ───────── Status ─────────

@app.get("/api/health")
async def health():
    lora_path = os.environ.get("LORA_PATH", "")
    return {
        "status": "ok",
        "name": "TerabitStudio",
        "version": "1.1.0",
        "model_name": get_active_model(),
        "model_path": os.environ.get("MODEL_PATH", ""),
        "lora_path": lora_path or None,
        "lora_configured": bool(lora_path and os.path.exists(lora_path)),
        "llama_server_host": os.environ.get("LLAMA_SERVER_HOST", "127.0.0.1"),
        "llama_server_port": os.environ.get("LLAMA_SERVER_PORT", "11434"),
        "auth": bool(os.environ.get("JWT_SECRET", False)),
    }

# ───────── File Parsers ─────────

def _clean_path(filepath: str) -> str:
    fp = filepath.strip().strip("`").strip("*").strip("#").strip()
    fp = re.sub(r'^(?:exact/path/to/|path/to/|relative/path/|relative/path\s+|file:\s*)', '', fp, flags=re.IGNORECASE)
    fp = fp.strip('`').strip('*').strip('#').strip('"').strip("'").strip()
    return fp


def parse_generated_files(response: str) -> list:
    """Parse files from model response with multiple strategies.

    Continuation-aware: a header like `path` (continued) means the SAME file
    was split across multiple fenced blocks (a habit the model picked up from
    budget-split project context) -- blocks are concatenated instead of the
    tail being silently dropped, which used to yield mid-JSX truncations.
    """
    # Normalize continuation headers so all strategies see one repeated header:
    # `src/App.jsx` (continued)  ->  `src/App.jsx`
    response = re.sub(
        r"(?m)^(`[a-zA-Z0-9_.\\/-]+\.[A-Za-z0-9]+`)[ \t]*\(continued\)[ \t]*$",
        r"\1",
        response,
    )
    # Section headers like "## src/App.jsx (continued)" / "**src/App.jsx (continued)**"
    response = re.sub(
        r"(?m)^(#{1,6}\s*|\*\*)([a-zA-Z0-9_.\\/-]+\.[A-Za-z0-9]+)(\*\*)?[ \t]*\(continued\)[ \t]*$",
        r"\1\2\3",
        response,
    )
    files: list = []
    contents_by_path: dict = {}
    order: list = []
    consumed_spans: list = []

    def _overlaps(start: int, end: int) -> bool:
        return any(s <= start < e or s < end <= e for s, e in consumed_spans)

    def _add(filepath: str, content: str, start: int, end: int) -> None:
        fp = _clean_path(filepath)
        if not fp or not content.strip() or _overlaps(start, end):
            return
        consumed_spans.append((start, end))
        if fp in contents_by_path:
            # Same file continued in a later block -> concatenate.
            contents_by_path[fp] = contents_by_path[fp].rstrip() + "\n" + content.strip()
        else:
            contents_by_path[fp] = content.strip()
            order.append(fp)

    # Strategy 1: Header / Backtick format (### `filename.ext`, `filename.ext`, ### filename.ext)
    pattern1 = r"(?m)^(?:#{1,6}\s*)?`?([a-zA-Z0-9_.-]+(?:/[a-zA-Z0-9_.-]+)*\.(?:jsx?|tsx?|css|html|json|js|ts|py|env|yml|yaml|md|config\.js|config\.cjs))`?\s*\n```[\w]*\n([\s\S]*?)\n```"
    for m in re.finditer(pattern1, response):
        _add(m.group(1), m.group(2), m.start(), m.end())

    # Strategy 2: Bold or plain header format
    pattern2 = r"(?m)^(?:#{1,6}\s*)?\*\*([a-zA-Z0-9_.-]+(?:/[a-zA-Z0-9_.-]+)*\.(?:jsx?|tsx?|css|html|json|js|ts|py))\*\*\s*\n```[\w]*\n([\s\S]*?)\n```"
    for m in re.finditer(pattern2, response):
        _add(m.group(1), m.group(2), m.start(), m.end())

    # Strategy 3: Loose format with any code block
    pattern3 = r"`([^`]+\.(?:jsx?|tsx?|css|html|json|js|ts))`\s*\n```[\w]*\n([\s\S]*?)```"
    for m in re.finditer(pattern3, response, re.IGNORECASE):
        _add(m.group(1), m.group(2), m.start(), m.end())

    files = [{"path": fp, "content": contents_by_path[fp]} for fp in order]
    # Sort by path for consistent ordering
    files.sort(key=lambda x: x["path"])
    return files


def parse_markdown_structure(response: str) -> list:
    """Tolerate common small-model variations in otherwise valid file output."""
    files, current_content = [], []
    current_path = None
    in_code = False
    path_pattern = re.compile(
        r"((?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]+(?:\.[A-Za-z0-9_.-]+)+)"
    )
    previous_text = ""
    for line in response.splitlines():
        if line.strip().startswith("```"):
            if in_code:
                if current_path and current_content:
                    files.append({"path": current_path, "content": "\n".join(current_content).strip()})
                current_path, current_content, in_code = None, [], False
            else:
                # Qwen sometimes emits "relative/path package.json" rather
                # than backticks.  Extract the actual filename, never the
                # placeholder phrase.
                match = path_pattern.search(previous_text.replace("`", ""))
                current_path = match.group(1) if match else None
                current_content, in_code = [], True
            continue
        if in_code:
            current_content.append(line)
        elif line.strip():
            previous_text = line.strip()
    return parse_generated_files(response) or files


def parse_loose_fenced_files(response: str) -> list:
    """Last-resort parser for Qwen's ``relative/path foo.jsx`` headers."""
    pattern = re.compile(
        r"(?ms)^\s*(?:relative/path\s+)?`?([A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*\.[A-Za-z0-9_.-]+)`?\s*\n```[^\n]*\n(.*?)^```"
    )
    files = []
    seen_paths = set()
    for match in pattern.finditer(response):
        path = match.group(1)
        content = match.group(2).strip()
        fp = path.strip().strip("`").strip("*").strip()
        fp = re.sub(r'^relative/path\s+', '', fp)
        fp = fp.strip('"').strip("'")
        if fp and content and fp not in seen_paths:
            seen_paths.add(fp)
            files.append({"path": fp, "content": content})
    return files


def extract_conversational_response(response: str) -> str:
    """Extract the conversational part before the first code block."""
    # Find the first code block marker
    first_code_block = response.find('```')
    if first_code_block == -1:
        return response.strip()
    
    # Get text before the first code block
    before_code = response[:first_code_block].strip()
    
    # If there's a brief response (1-3 sentences), return it
    if before_code and len(before_code) < 500:
        return before_code
    
    return "I've generated the code for your project."

# ───────── Artifact scrubbing & core-file injection ─────────

# The fine-tune's training data contained roleplay/action tokens (measured
# live: a literal `<clap>` in generated output). These never belong in code
# or chat copy. Extended with common small-model artifacts.
ARTIFACT_TOKEN_RE = re.compile(
    r"</?(?:clap|thinking|thought|reasoning|system|assistant|user|human|tool_call|function_call)>",
    re.IGNORECASE,
)


def scrub_artifacts(text: str) -> str:
    """Remove roleplay/meta tokens the fine-tuned model sometimes emits."""
    return ARTIFACT_TOKEN_RE.sub("", text)


CORE_FILE_CONTENTS = {
    "package.json": '''{
  "name": "zenith-app",
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
}''',
    "src/main.jsx": '''import React from 'react';
import ReactDOM from 'react-dom/client';
import './index.css';
import App from './App';

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);''',
    "index.html": '''<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Generated App</title>
    <script src="https://cdn.tailwindcss.com"></script>
  </head>
  <body class="bg-white text-slate-900 antialiased min-h-screen">
    <div id="root"></div>
    <script type="module" src="/src/main.jsx"></script>
  </body>
</html>''',
    # Landing shells rely on .reveal / .animate-* classes; ship them ALWAYS
    # (also when the model provides its own index.css, via ensure_animations).
    "src/index.css": '''@tailwind base;
@tailwind components;
@tailwind utilities;

@layer base {
  body { background-color: #ffffff; color: #0f172a; }
}

/* Scroll-reveal animation system (used by the landing shell) */
@keyframes reveal-up { from { opacity: 0; transform: translateY(28px); } to { opacity: 1; transform: translateY(0); } }
.reveal { opacity: 0; }
.reveal-visible { animation: reveal-up 0.8s cubic-bezier(0.22, 1, 0.36, 1) both; }
@media (prefers-reduced-motion: reduce) {
  .reveal { opacity: 1; }
  .reveal-visible { animation: none; }
}
@keyframes fade-up { from { opacity: 0; transform: translateY(16px); } to { opacity: 1; transform: translateY(0); } }
.animate-fade-up { animation: fade-up 0.7s ease-out both; }
@keyframes float-slow { 0%, 100% { transform: translateY(0); } 50% { transform: translateY(-10px); } }
.animate-float-slow { animation: float-slow 5s ease-in-out infinite; }
@keyframes marquee { from { transform: translateX(0); } to { transform: translateX(-50%); } }
.animate-marquee { animation: marquee 30s linear infinite; }
''',
}


def inject_core_files(files: list[dict]) -> list[dict]:
    """Guarantee the four files every Vite React app needs to build.

    If the model omitted one (or emitted it in a format the parser missed),
    a canonical version is injected — the preview bundler requires an entry,
    and `npm install && npm run dev` fails without package.json.
    Landing shells use .reveal/.animate-* classes; the animation system is
    merged into any model-provided index.css too (see ensure_animations).
    """
    existing = {f["path"] for f in files}
    for path, content in CORE_FILE_CONTENTS.items():
        if path not in existing:
            files.append({"path": path, "content": content})
            print(f"[repair] injected core file: {path}")
    for f in files:
        if f["path"] == "src/index.css":
            f["content"] = ensure_animations(f["content"])
        if f["path"] == "index.html":
            f["content"] = ensure_inter_font(f["content"])
    return files

_ANIM_MARKER = "@keyframes reveal-up"


def ensure_animations(css: str) -> str:
    """Append the scroll-reveal animation system to a model-provided index.css
    if it doesn't already define it (live: shell renders <Reveal> wrappers but
    the model's index.css had no .reveal rules -> sections stayed invisible)."""
    if _ANIM_MARKER in css:
        return css
    return css.rstrip() + "\n\n/* Scroll-reveal animation system (added by TerabitStudio) */\n" + ANIM_CSS_BLOCK


ANIM_CSS_BLOCK = '''@keyframes reveal-up { from { opacity: 0; transform: translateY(28px); } to { opacity: 1; transform: translateY(0); } }
.reveal { opacity: 0; }
.reveal-visible { animation: reveal-up 0.8s cubic-bezier(0.22, 1, 0.36, 1) both; }
@media (prefers-reduced-motion: reduce) {
  .reveal { opacity: 1; }
  .reveal-visible { animation: none; }
}
@keyframes fade-up { from { opacity: 0; transform: translateY(16px); } to { opacity: 1; transform: translateY(0); } }
.animate-fade-up { animation: fade-up 0.7s ease-out both; }
@keyframes float-slow { 0%, 100% { transform: translateY(0); } 50% { transform: translateY(-10px); } }
.animate-float-slow { animation: float-slow 5s ease-in-out infinite; }
@keyframes marquee { from { transform: translateX(0); } to { transform: translateX(-50%); } }
.animate-marquee { animation: marquee 30s linear infinite; }
'''


def ensure_inter_font(html: str) -> str:
    """Make generated pages use a real display typeface: the Tailwind CDN
    default stack looks cheap; Inter (same as Bolt/Lovable defaults) is one
    <link> away. Idempotent."""
    if "fonts.googleapis.com" in html:
        return html
    link = ('<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap" rel="stylesheet">\n'
            '    <style>body { font-family: \'Inter\', sans-serif; }</style>\n    ')
    return html.replace('</head>', '    ' + link + '</head>', 1)


# ───────── Validation & Repair ─────────

IMPORT_PATTERN = re.compile(r'import\s+(?:\{[^}]*\}|\*\s+as\s+\w+|\w+(?:,\s*(?:\{[^}]*\}|\*\s+as\s+\w+|\w+))?)\s+from\s+[\'"]([^\'"]+)[\'"]')
EXTENSIONS = [".js", ".jsx", ".ts", ".tsx", ".mjs"]

PLACEHOLDER_COMPONENT = """// Auto-generated fallback component
export default function Placeholder({ title, children, ...props }) {
  return (
    <div className="p-4 rounded-xl border border-dashed border-white/10 bg-white/[0.02] text-center text-xs text-gray-400 my-2">
      {children || <span className="opacity-70">{title || "Component"} (Auto-generated module)</span>}
    </div>
  );
}
"""

PLACEHOLDER_MODULE = """// Auto-generated fallback module
const placeholder = {};
export default placeholder;
"""


def _resolve_import_path(importer_path: str, import_spec: str) -> str | None:
    """Resolve a relative import spec to an actual file path."""
    if not import_spec.startswith("."):
        return None  # node_modules import, skip

    base_dir = "/".join(importer_path.split("/")[:-1]) if "/" in importer_path else ""
    if base_dir:
        resolved = base_dir + "/" + import_spec
    else:
        resolved = import_spec

    resolved = resolved.replace("./", "")

    # Normalize ../
    parts = resolved.split("/")
    normalized = []
    for p in parts:
        if p == ".." and normalized:
            normalized.pop()
        elif p != "." and p != "..":
            normalized.append(p)
    resolved = "/".join(normalized)

    return resolved


def _find_file(exact_path: str, existing_paths: set) -> str | None:
    """Find a file with various extension attempts."""
    if exact_path in existing_paths:
        return exact_path
    base, _ = os.path.splitext(exact_path)
    for ext in EXTENSIONS:
        candidate = base + ext
        if candidate in existing_paths:
            return candidate
    # Try index files
    for ext in EXTENSIONS:
        candidate = exact_path.rstrip("/") + f"/index{ext}"
        if candidate in existing_paths:
            return candidate
    return None


def validate_and_repair_files(files: list[dict]) -> list[dict]:
    """Scan all generated files for unresolved imports and create placeholders."""
    # Deterministic import repairs first: hallucinated lucide-react exports
    # (e.g. `Bag`) hard-fail the tier-1 bundle; identifiers that are used but
    # never imported (e.g. `<Plus />`, `useState()`) instead white-screen the
    # running app, which no bundler check can see. See agentic_generator.
    files = [
        {**f, "content": agentic_generator.fix_imports(f["path"], f["content"])[0]}
        for f in files
    ]
    existing_paths = {f["path"] for f in files}
    missing = set()

    for f in files:
        path = f["path"]
        content = f["content"]
        if not any(path.endswith(ext) for ext in EXTENSIONS):
            continue

        for match in IMPORT_PATTERN.finditer(content):
            import_spec = match.group(1)
            resolved = _resolve_import_path(path, import_spec)
            if resolved is None:
                continue
            found = _find_file(resolved, existing_paths)
            if found is None:
                missing.add(resolved)

    new_files = []
    for m in sorted(missing):
        if m in existing_paths:
            continue
        is_component = m.endswith("x") or m.split("/")[-1][0].isupper()
        placeholder = PLACEHOLDER_COMPONENT if is_component else PLACEHOLDER_MODULE
        # Pick best extension
        if not any(m.endswith(e) for e in EXTENSIONS):
            m += ".jsx" if is_component else ".js"
        new_files.append({"path": m, "content": placeholder})
        print(f"[repair] Created missing file: {m}")

    return files + new_files


# ───────── Image Injection ─────────

UNSPLASH_IDS = [
    "1506744038136-46273834b3fb", "1517694712202-14dd9538aa97",
    "1551288049-bebda4e38f71", "1497366216548-37526070297c",
    "1556761175-b413da4baf72", "1504384308090-c894fdcc538d",
    "1522071820081-009f3b6b01b1", "1519389950473-47ba0277781c",
    "1454165804606-c3d57bc86b40", "1507003212552-3f11eab7bf6d",
    "1504639725590-34d0984388bd", "1498050108023-c5249f4df085",
    "1552664732117-c8a0b9b7c5e0", "1517245386807-bb43f82c33c4",
    "1553877522-43269d4ea984", "1507003212552-3f11eab7bf6d",
    "1517245386807-bb43f82c33c4", "1553877522-43269d4ea984",
    "1522202176988-66273c2e55e9", "1486312338219-ce68d2c6f44d",
]
import random


def _theme_key_for(req) -> str:
    """Design theme key for imagery enforcement (domain of the request)."""
    try:
        brief = extract_product_brief(req.prompt or "", getattr(req, "business_type", "") or "")
        return (brief.get("domain") or "")
    except Exception:
        return ""


def inject_images(files: list[dict]) -> list[dict]:
    """Replace placeholder image sources with real Unsplash URLs."""
    placeholder_patterns = [
        r'src=["\'](?:placeholder|https?://placehold\.(?:it|co)|#|data:image/[^;]+;base64,)["\']',
        r'src=["\'](?:/images/[^"\']+\.(?:jpg|png|svg))["\']',
    ]
    for f in files:
        if not f["path"].endswith((".html", ".jsx", ".tsx")):
            continue
        content = f["content"]
        replaced = False
        for pattern in placeholder_patterns:
            def replacer(m):
                nonlocal replaced
                replaced = True
                img_id = random.choice(UNSPLASH_IDS)
                return f'src="https://images.unsplash.com/photo-{img_id}?w=800&q=80"'
            content = re.sub(pattern, replacer, content)
        if replaced:
            f["content"] = content
    return files


# ──────────────────────────────────────────────────────── local folder workspace
#
# Registered here, ABOVE the static mount, on purpose: a Mount at "/" matches
# every path and Starlette does not fall through, so anything defined below it
# is unreachable. That was a real 404 on /builder once; do not move these.

import workspace as _workspace
from workspace import WorkspaceError as _WorkspaceError


def _ws_or_400(workspace_id: str):
    """Turn a refusal into a 400 that says what was refused and why.

    WorkspaceError messages are written for humans ("../ is not allowed"),
    which is the right thing to show, so they pass through unchanged.
    """
    try:
        return _workspace.get(workspace_id)
    except _WorkspaceError as exc:
        raise HTTPException(400, str(exc))


class WorkspaceOpenRequest(BaseModel):
    path: str


class WorkspaceFileRequest(BaseModel):
    path: str
    content: str = ""


class WorkspaceApplyRequest(BaseModel):
    files: list[dict] = Field(default_factory=list)
    overwrite: bool = False


class WorkspaceGenerateRequest(BaseModel):
    prompt: str
    business_type: str = "general"
    provider: str = "auto"
    model: str = ""
    use_agent: bool = True
    # Send the folder's current files to the model as project context, so
    # "add a dark mode toggle" means "add it to THIS project".
    use_project_context: bool = True
    max_context_files: int = 40


@app.post("/api/workspace/open")
async def workspace_open(req: WorkspaceOpenRequest):
    """Open a local folder. Returns a workspace id; nothing is written."""
    try:
        ws = _workspace.open_root(req.path)
    except _WorkspaceError as exc:
        raise HTTPException(400, str(exc))
    return ws.tree()


@app.get("/api/workspace/open")
async def workspace_list():
    return {"workspaces": _workspace.list_open()}


@app.get("/api/workspace/{workspace_id}/tree")
async def workspace_tree(workspace_id: str):
    return _ws_or_400(workspace_id).tree()


@app.get("/api/workspace/{workspace_id}/file")
async def workspace_read(workspace_id: str, path: str):
    ws = _ws_or_400(workspace_id)
    try:
        return ws.read(path)
    except _WorkspaceError as exc:
        raise HTTPException(400, str(exc))


@app.put("/api/workspace/{workspace_id}/file")
async def workspace_write(workspace_id: str, req: WorkspaceFileRequest):
    ws = _ws_or_400(workspace_id)
    try:
        return ws.write(req.path, req.content)
    except _WorkspaceError as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/workspace/{workspace_id}/apply")
async def workspace_apply(workspace_id: str, req: WorkspaceApplyRequest):
    """Write a generated file list into the opened folder.

    Defaults to NOT overwriting: the agent emits React projects, and the folder
    the user opened is usually something else. Collisions come back in
    "skipped" so the shell can offer a per-file replace.
    """
    ws = _ws_or_400(workspace_id)
    return ws.apply_files(req.files, overwrite=req.overwrite)


@app.post("/api/workspace/{workspace_id}/export")
async def workspace_export(workspace_id: str, name: str = "terabit-export"):
    ws = _ws_or_400(workspace_id)
    try:
        return {"path": _workspace.copy_out(ws, name)}
    except OSError as exc:
        raise HTTPException(400, f"Export failed: {exc}")


@app.delete("/api/workspace/{workspace_id}")
async def workspace_close(workspace_id: str):
    return {"closed": _workspace.close(workspace_id)}


@app.post("/api/workspace/{workspace_id}/generate")
async def workspace_generate(
    workspace_id: str,
    req: WorkspaceGenerateRequest,
    user: Optional[User] = Depends(get_current_user),
):
    """Generate against an opened folder, without touching the disk.

    Two reasons this returns before writing anything: a full run is ~19
    minutes on a 6 GB card, and the point of the folder workspace is that the
    user sees the diff and decides. The agent already produces the whole file
    list plus its trace, so the shell can render it as a change set and the
    separate /apply call is what actually touches disk.
    """
    ws = _ws_or_400(workspace_id)
    if not req.prompt.strip():
        raise HTTPException(400, "Describe what to build or change.")

    project_files: list[dict] = []
    if req.use_project_context:
        listing = ws.tree()
        # Biggest files first would be wrong; the useful context is the
        # entry points and the manifest, so take the shallowest files and cap
        # the total characters, or the prompt budget goes to a lockfile.
        shallow = sorted(
            listing["files"],
            key=lambda f: (f["path"].count("/"), f["path"]),
        )[: max(1, req.max_context_files)]
        budget = 60_000
        for entry in shallow:
            if budget <= 0:
                break
            try:
                data = ws.read(entry["path"])
            except _WorkspaceError:
                continue
            if data.get("binary") or data.get("too_large") or not data.get("content"):
                continue
            content = data["content"][:8000]
            budget -= len(content)
            project_files.append({"path": entry["path"], "content": content})

    gen_req = GenerateRequest(
        prompt=req.prompt,
        business_type=req.business_type,
        provider=req.provider,
        model=req.model,
        use_agent=req.use_agent,
        operation="edit" if project_files else "create",
        project_files=project_files,
    )
    prep = await asyncio.to_thread(prepare_generation, gen_req, gen_req.operation)
    result = agentic_generator.run_agent(
        gen_req, prep, provider=req.provider, model=req.model
    )

    # Classify each generated path against what is already in the folder, so
    # the shell can show "3 new, 2 replaced" without diffing anything.
    existing = {f["path"] for f in ws.tree()["files"]}
    changed = []
    for f in result["files"]:
        rel = f.get("path") or ""
        changed.append({
            "path": rel,
            "state": "replace" if rel in existing else "new",
            "bytes": len(f.get("content") or ""),
        })
    return {
        "files": result["files"],
        "changes": changed,
        "context_files_sent": len(project_files),
        "bundle_ok": result.get("bundle_ok"),
        "personalisation": result.get("personalisation"),
        "agent_trace": result.get("agent_trace"),
        "app_name": prep.get("app_name"),
        "brief": prep.get("brief"),
    }


@app.get("/api/app/env", include_in_schema=False)
async def app_env():
    """First-run environment report for the desktop app.

    A downloadable build lands on a machine we know nothing about, so the
    shell needs to be able to answer, without guessing: is the model runtime
    there, is the configured model actually pulled, is the UI built, is the
    data directory writable. Everything here is a local filesystem / localhost
    probe -- no network egress.
    """
    import httpx as _httpx

    model_name = os.environ.get("MODEL_NAME", "qwen2.5:7b")
    host = os.environ.get("LLAMA_SERVER_HOST", "127.0.0.1")
    port = os.environ.get("LLAMA_SERVER_PORT", "11434")
    base = f"http://{host}:{port}"

    runtime_ok, models, runtime_error = False, [], None
    try:
        r = _httpx.get(f"{base}/api/tags", timeout=2.0)
        r.raise_for_status()
        data = r.json()
        models = [m.get("name", "") for m in (data.get("models") or [])]
        runtime_ok = True
    except Exception as e:  # noqa: BLE001 - this endpoint reports failure
        runtime_error = type(e).__name__

    loaded, loaded_ctx = [], None
    if runtime_ok:
        try:
            r = _httpx.get(f"{base}/api/ps", timeout=2.0)
            if r.status_code == 200:
                rows = r.json().get("models") or []
                loaded = [m.get("name", "") for m in rows]
                # The CONTEXT actually in use, which is not the same thing as
                # the context the app asked for. Measured 2026-10-03: Ollama's
                # OpenAI-compatible endpoint ignores a per-request
                # options.num_ctx, so the model's Modelfile wins -- a 16384
                # context on a 6 GB card silently spills to CPU (27% CPU) and
                # doubles every build, with nothing in any HTTP response
                # saying why. Reporting both values is the fix.
                for m in rows:
                    value = m.get("context_length") or m.get("context")
                    if isinstance(value, int) and value > 0:
                        loaded_ctx = value
                        break
        except Exception:  # noqa: BLE001
            loaded = []

    def _has(name: str) -> bool:
        # Compare base tags so a context-variant id (terabit-v3-ctx8k) matches
        # the base tag (terabit-finetuned-v3) it was resolved from.
        base = name.split(":")[0]
        return any(m == name or m.split(":")[0] == base for m in models)

    data_dir = _paths.data_dir()
    try:
        probe = data_dir / ".write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        writable = True
    except Exception:  # noqa: BLE001
        writable = False

    model_ready = _has(model_name)
    issues = []
    if not runtime_ok:
        issues.append(
            f"No local model runtime on {base}. Install Ollama "
            f"(https://ollama.com) or start llama.cpp on that port.")
    elif not model_ready:
        issues.append(
            f'Model "{model_name}" is not pulled. Run: ollama pull {model_name}')
    elif loaded_ctx and loaded_ctx != context_budget.get_num_ctx():
        issues.append(
            f"The model server is running a {loaded_ctx}-token context while "
            f"the app asks for {context_budget.get_num_ctx()}. Ollama ignores "
            "a per-request num_ctx on its OpenAI-compatible endpoint (the "
            "model's Modelfile wins), so on a small GPU this silently spills "
            "to CPU and can double every build. Create a tag with "
            f"PARAMETER num_ctx {context_budget.get_num_ctx()}, or use the "
            "bundled llama.cpp runtime where -c is authoritative.")
    if not frontend_dir.exists():
        issues.append(
            "The interface is not built. Run: npm run build (in frontend/).")
    if not writable:
        issues.append(f"Data directory is not writable: {data_dir}")

    return {
        "ok": not issues,
        "issues": issues,
        "backend": {"status": "ok", "data_dir": str(data_dir),
                    "frozen": _paths.is_frozen(),
                    "build": _paths.build_info()},
        "runtime": {"reachable": runtime_ok, "base_url": base,
                    "error": runtime_error, "models": models,
                    "loaded": loaded, "model": model_name,
                    "model_ready": model_ready,
                    # Performance knobs, so Settings can explain what this
                    # install is actually running with instead of guessing
                    # from a .env the user may never have opened.
                    "num_ctx": context_budget.get_num_ctx(),
                    "loaded_context": loaded_ctx,
                    "n_gpu_layers": os.environ.get("N_GPU_LAYERS", "-1"),
                    "n_threads": os.environ.get(
                        "N_THREADS", str(os.cpu_count() or 8)),
                    "kv_cache_type": os.environ.get("KV_CACHE_TYPE", "f16"),
                    "frozen": _paths.is_frozen()},
        "ui": {"built": frontend_dir.exists(), "dir": str(frontend_dir)},
        "storage": {"writable": writable},
        "first_run": not model_ready or not frontend_dir.exists(),
    }


# ───────── Serve static files ─────────

uploads_dir = UPLOAD_DIR
app.mount("/uploads", StaticFiles(directory=str(uploads_dir)), name="uploads")

frontend_dir = _paths.web_dir()
if frontend_dir and frontend_dir.exists():
    # NOTE: deliberately NOT app.mount("/", StaticFiles(...)). A Mount at "/"
    # matches every path and Starlette does NOT fall through it, so it
    # swallows every route registered afterwards -- which is why /builder
    # 404ed and why the SPA fallback below never ran. Measured 2026-10-02.
    # One explicit catch-all handles both real files and deep links instead.
    _spa_index = (frontend_dir / "index.html").resolve()
    _spa_root = frontend_dir.resolve()

    @app.get("/{full_path:path}", include_in_schema=False)
    async def _spa_fallback(full_path: str):
        if full_path.startswith(("api/", "uploads/")):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        candidate = (frontend_dir / full_path).resolve()
        # Never serve outside the dist directory.
        try:
            candidate.relative_to(_spa_root)
        except ValueError:
            candidate = _spa_index
        if candidate.is_file():
            return FileResponse(candidate)
        # Deep link (/builder, /login, ...) -> the SPA shell.
        return FileResponse(_spa_index)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
