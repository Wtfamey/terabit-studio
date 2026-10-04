"""Agentic per-file generation for Terabit Studio -- the Bolt/Lovable loop.

Why per-file: single-shot whole-app completions from a 7B model run out of
budget mid-file (fence left open -> parse shatters -> tier-2 preview).
Bolt/Lovable-style products instead (1) plan a small file tree, (2) generate
each file in its own completion with full project context, (3) assemble,
repair, and verify with the REAL bundler before returning.

The loop is provider-agnostic (see providers.py): local Qwen 2.5 7B by
default, any OpenAI-compatible / Gemini / Anthropic endpoint on request --
identical quality control flow, different latency/price.

Public API:
  run_agent(req: GenerateRequest, prep: dict, progress=fn) -> dict
      {"files": [...], "full_response": str, "agent_trace": [...]}
"""

import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

import providers
import context_budget
import domain_profiles
import design_system
import imagery
import motion_enricher
import style_enforcer

FRONTEND_ROOT = Path(__file__).resolve().parent.parent / "frontend"
ESBUILD = FRONTEND_ROOT / "node_modules" / "esbuild" / "bin" / "esbuild"
# Verify temp projects MUST live under frontend/ so node resolves `react` etc.
# by walking up to frontend/node_modules (same trick the preview builder uses).
VERIFY_WORK_ROOT = FRONTEND_ROOT / ".preview-work"
HERE = Path(__file__).resolve().parent

CORE_FILES = ["package.json", "index.html", "src/main.jsx", "src/index.css"]

# ---------------------------------------------------------------- planning

PLAN_SYSTEM = """You are the architect of Terabit Studio, an elite full-stack app generator.
Given a user request, plan the APPLICATION-LEVEL files only.

Rules:
- Plan 3 to 6 files: src/App.jsx plus 2-5 supporting components
  (e.g. src/components/Hero.jsx, PricingTable.jsx, DataDashboard.jsx, SideNav.jsx).
- BE AMBITIOUS: split the product into its natural sections/domains (e.g. a
  marketing site gets Hero, Features, Pricing, FAQ; a dashboard gets sidebar,
  KPI row, charts, table). Small plans produce shallow apps.
- Core infrastructure (package.json, index.html, src/main.jsx, src/index.css)
  is provided by the platform -- NEVER plan it.
- Each component must be self-contained and under ~200 lines; App.jsx composes
  them and holds the shared state.

Output ONLY JSON: {"files": [{"path": "src/App.jsx", "purpose": "one line"}]}"""

PLAN_SYSTEM_EDIT = """You modify an existing Vite + React 18 + Tailwind application.
Given the user's change request and the current file list, choose the MINIMAL set of files to write.

Rules:
- 1 to 3 files ONLY. Prefer editing an existing file over creating a new one.
- Include src/App.jsx only when the page shell, layout, or shared state must change.
- New components only when the feature genuinely needs one; existing ones should be edited instead.
- NEVER plan core infrastructure (package.json, index.html, src/main.jsx, src/index.css).

Output ONLY JSON: {"files": [{"path": "src/App.jsx", "purpose": "one line"}]}"""

PLAN_REMINDER = """Output ONLY valid JSON, nothing else:
{"files": [{"path": "src/App.jsx", "purpose": "..."}]}"""


def _implied_features(prompt: str, declared: list[str] | None = None) -> list[str]:
    """Feature phrases the user's own sentence implies, best-effort.

    Used ONLY as a floor for plan breadth: a 7B planner regularly answers a
    three-feature request with a single App.jsx, which then has to hold the
    entire app, hits the response budget, and truncates (observed live:
    'src/App.jsx hit the token cap' on a bug-tracker ask whose own sentence
    listed severity badges + assignee filter + sprint columns).
    """
    feats = [f.strip() for f in (declared or []) if f and f.strip()]
    if feats:
        return feats[:3]
    text = re.sub(r"^(build|create|make|design|add)\b", "", prompt.strip().lower())
    # Only look at what FOLLOWS the feature clause ("... with X, Y and Z"):
    # everything before it is the app's own description, not a feature.
    m = re.search(r"\bwith\b", text)
    if m:
        text = text[m.end():]
    elif re.search(r"[,;:]", text):
        text = re.split(r"[,;:]", text, maxsplit=1)[1]
    else:
        return []
    parts: list[str] = []
    for chunk in re.split(r"\band\b|,|;|:", text):
        words = chunk.strip().split()
        if not words:
            continue
        if words[0] in ("a", "an", "the", "some"):
            words = words[1:]
        # A feature phrase is short and not the app's own name/first clause.
        if 1 < len(words) <= 5:
            parts.append(" ".join(words))
    out: list[str] = []
    for p in parts:
        if p not in out:
            out.append(p)
    return out[:2]


def _component_path(name: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", name.title().replace("-", " "))
    return "src/components/" + ("".join(words)[:28] or "Feature") + ".jsx"


def _landing_sections(brief: dict | None) -> list[dict]:
    """Domain-appropriate landing section slots (see domain_profiles)."""
    return domain_profiles.get_profile(brief)["sections"]


def _plan_files_admin(messages: list, brief: dict | None) -> list[dict]:
    """Canonical plan for a back-office system.

    Same reasoning as the landing plan: a 7B asked to plan a hospital
    management system either answers with one giant App.jsx (which token-caps)
    or invents marketing sections. The view split is deterministic, and each
    view is a self-contained component the shell then composes.
    """
    views = domain_profiles.admin_views(brief)
    plan = [{
        "path": "src/App.jsx",
        "purpose": "Admin shell: sidebar navigation, topbar, active-view state",
    }]
    for v in views:
        plan.append({
            "path": f"src/components/{v['stem']}.jsx",
            "purpose": f"{v['label']} view -- {v['spec']}",
        })
    return plan


def plan_files(messages: list, provider: str, model: str, edit: bool = False,
               existing_paths: list[str] | None = None,
               features: list[str] | None = None, archetype: str = "saas",
               brief: dict | None = None) -> list[dict]:
    """Plan APPLICATION files only; core infra is always platform-provided.

    In edit mode the planner sees the current file list and returns the
    minimal change set (1-3 files) instead of a whole new app plan. In create
    mode the plan is held to >=2 files whenever the request implies several
    features (see _implied_features), so a multi-feature app does not collapse
    into one over-budget file. Landing pages allow the widest plans (6 files:
    Hero / Features / Pricing / FAQ / CTA / App) because marketing pages have
    the most independently-usable sections.
    """
    max_files = 3 if edit else (6 if archetype in ("landing", "admin") else 5)
    # Landing creates have a CANONICAL deterministic plan (see below) -- skip
    # the planner LLM call entirely (observed live: the call burns ~20-40s
    # and its answer is discarded in favor of the same deterministic split).
    if not edit and archetype == "landing":
        return _plan_files_landing(messages, brief)
    if not edit and archetype == "admin":
        return _plan_files_admin(messages, brief)
    system = PLAN_SYSTEM_EDIT if edit else PLAN_SYSTEM
    if edit:
        listing = "\n".join(f"- {p}" for p in (existing_paths or [])) or "- (empty project)"
        user = (
            f"Current project files:\n{listing}\n\n"
            f"Change request:\n{messages[1]['content'][:2500]}\n\n"
            f"Plan the minimal set of files to write now."
        )
    else:
        user = f"Project context:\n{messages[0]['content'][:4000]}\n\nPlan the application files now."
    plan_msgs = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    text, _ = providers.chat(plan_msgs, max_tokens=500, temperature=0.2,
                             provider=provider, model=model)
    files: list[dict] = []
    try:
        match = re.search(r"\{[\s\S]*\}", text)
        data = json.loads(match.group(0))
        files = [
            {"path": str(f["path"]).strip(), "purpose": str(f.get("purpose", "")).strip()}
            for f in data.get("files", [])
            if isinstance(f, dict) and f.get("path")
        ]
    except (json.JSONDecodeError, AttributeError, TypeError):
        pass
    # Guardrails: drop any core-infra entries (platform provides them) and
    # enforce a sane count; for creates App.jsx is the guaranteed anchor.
    files = [f for f in files if f["path"] not in CORE_FILES]
    if edit:
        # Never invent a change set: if the planner failed, fall back to the
        # one file every request can be expressed against.
        if not files:
            anchor = "src/App.jsx" if "src/App.jsx" in (existing_paths or []) else (
                (existing_paths or ["src/App.jsx"])[0])
            files = [{"path": anchor, "purpose": "Apply the requested change"}]
        return files[:3]
    if not any(f["path"].endswith(("App.jsx", "App.tsx")) for f in files):
        files.insert(0, {"path": "src/App.jsx", "purpose": "Full application UI and state"})

    # Landing pages have a CANONICAL section structure -- a 7B planner asked
    # for "a landing page" either answers with one giant App.jsx (which then
    # blows the per-file token cap: a full landing page is 4-5k tokens of JSX)
    # or invents app-dashboard sections (observed live: ProfileCard,
    # HelpCenter and Settings on a marketing-site ask). Skip the model here
    # entirely: the split below is deterministic and costs zero planner
    # latency; the section asks are each well under budget, and composing
    # sections in App.jsx is exactly the trained pattern.
    if archetype == "landing":
        return _plan_files_landing(messages, brief)

    implied = _implied_features(messages[1]["content"], features)
    if len(files) == 1 and len(implied) >= 2:
        # One file + several implied features = the planner under-planned.
        # ONE stronger retry (small, cheap), then a deterministic floor.
        retry = plan_msgs + [
            {"role": "assistant", "content": text[:400]},
            {"role": "user", "content": (
                "That is too few files. This request asks for several distinct "
                f"features ({', '.join(implied)}). Reply with 2-4 files: "
                "src/App.jsx (shell + shared state) plus one component per "
                "feature, e.g. src/components/FeatureName.jsx. Output ONLY "
                'JSON: {"files": [{"path": ..., "purpose": ...}]}'
            )},
        ]
        try:
            text2, _ = providers.chat(retry, max_tokens=500, temperature=0.4,
                                      provider=provider, model=model)
            m2 = re.search(r"\{[\s\S]*\}", text2)
            data2 = json.loads(m2.group(0)) if m2 else {}
            wider = [
                {"path": str(f["path"]).strip(), "purpose": str(f.get("purpose", "")).strip()}
                for f in data2.get("files", [])
                if isinstance(f, dict) and f.get("path") and f["path"] not in CORE_FILES
            ]
            if any(f["path"].endswith(("App.jsx", "App.tsx")) for f in wider) and len(wider) > 1:
                files = wider
        except (json.JSONDecodeError, AttributeError, TypeError):
            pass
        if len(files) == 1:
            # Deterministic floor: carve the app's own feature list into
            # component slots so App.jsx composes instead of inlining.
            files += [
                {"path": _component_path(f), "purpose": f"{f} (own component)"}
                for f in implied
                if _component_path(f) != "src/components/App.jsx"
            ]
    return files[:max_files]


# ---------------------------------------------------------------- per-file gen


_EXPORT_DUP_RE = re.compile(r"export\s+(?:default|defaul|defau|defa|def)(?![\w])")


def fix_duplicate_exports(path: str, content: str) -> str:
    """Remove duplicate/truncated `export default` statements deterministically.

    Signature seen live: a 19k-char App.jsx whose tail contains a stray
    `export defaul` fragment (mid-keyword cut) on top of the real export at
    the top. esbuild: 'Multiple exports with the same name "default"'. The
    model-repair loop can't reliably fix it (it re-emits the whole file and
    can re-truncate), and failing it falls through to the curated scaffold --
    losing the personalization. Rule: keep the FIRST occurrence; for each
    later one, excise its statement (balanced-brace scan) or, if it is a
    truncated fragment (`export defaul` / bare `export default` with no body),
    cut to EOF. The regex accepts every prefix of the keyword, because a cut
    mid-word (`defaul`) is exactly as fatal as a full duplicate.
    """
    if not path.endswith((".jsx", ".tsx", ".js")):
        return content
    occurrences = list(_EXPORT_DUP_RE.finditer(content))
    if len(occurrences) <= 1:
        return content

    for m in reversed(occurrences[1:]):
        start, end = m.span()
        full_keyword = m.group(0).rstrip().endswith("default")
        rest = content[end:]
        # Fragment if the keyword itself was cut, or if the full keyword has
        # no statement body following it (bare `export default` at EOF).
        if not full_keyword or ("{" not in rest[:120] and ";" not in rest[:120]):
            content = content[:start].rstrip() + "\n"
            continue
        # Complete statement: remove it via balanced braces starting at its
        # first `{`, or up to the terminating `;`.
        brace = rest.find("{")
        semi = rest.find(";")
        if brace == -1 or (semi != -1 and semi < brace):
            consumed = semi + 1 if semi != -1 else 0
            content = content[:start] + rest[consumed:]
        else:
            depth, pos = 0, brace
            while pos < len(rest):
                if rest[pos] == "{":
                    depth += 1
                elif rest[pos] == "}":
                    depth -= 1
                    if depth == 0:
                        break
                pos += 1
            tail = rest[pos + 1:]
            semi2 = tail.find(";")
            consumed = pos + 1 + (semi2 + 1 if semi2 != -1 else 0)
            content = content[:start] + rest[consumed:]

    if len(list(_EXPORT_DUP_RE.finditer(content))) > 1:
        # Still duplicated (nested braces confused the scan) -- hand it to the
        # model repair loop rather than butchering the file further.
        return content
    return content


FILE_SYSTEM = """You are TerabitStudio, an elite full-stack developer. Write ONE complete
React file for a Vite + React 18 + Tailwind CSS project.

Output the file path on its own line in backticks, then ONE fenced block containing
the COMPLETE file: every import, every JSX tag and brace closed. No placeholders,
no TODOs, no truncation, no "(continued)".
Design quality bar: the page must look like ONE designed product, not
assembled parts. A DESIGN SYSTEM block in the user message gives the exact
palette/font/radius classes for THIS domain -- follow it EXACTLY, do not
invent other colors, and never mix light and dark sections. Cards rounded,
soft shadows, generous spacing, Lucide icons."""


def _file_messages(
    plan: list[dict], purpose: str, path: str, summary: str,
    project_ctx: str, done_files: dict, brand: dict | None,
    current: str | None = None, existing_paths: list[str] | None = None,
    brief_block: str = "", design_block: str = "", reply_language: str = "",
) -> list:
    # Local-import awareness: which files exist to import (planned + present).
    known = [f["path"] for f in plan]
    for p in (existing_paths or []):
        if p not in known:
            known.append(p)
    available = "\n".join(f"- {p}" for p in known[:24])
    brand_line = f"\nBrand name: {brand['name']}" if brand and brand.get("name") else ""
    is_main = path.endswith(("App.jsx", "App.tsx"))
    editing = current is not None
    # The #1 local-model failure mode: App.jsx ignoring its components and
    # inlining everything -> token-cap truncation. Composition is mandatory.
    composition = ""
    if is_main:
        components = [f["path"] for f in plan if not f["path"].endswith(("App.jsx", "App.tsx"))]
        if components:
            imports = "\n".join(
                f"import {{ default as {Path(c).stem.replace('-', '_')} }} from '{'./' + c.split('src/', 1)[-1]}'"
                for c in components
            )
            composition = (
                f"\nMANDATORY COMPOSITION: this file MUST import and render the already-written "
                f"components (they exist, do NOT re-implement them):\n{imports}\n"
                f"App.jsx holds the page shell (header, nav, layout) and shared state, then renders "
                f"each component. Keep inline JSX minimal so the file stays under ~150 lines.\n"
            )
    # Instruction mirrors the fine-tune's trained distribution: a short,
    # directive "Create a React component <path>: <spec>" line.
    # Editing an existing file: the model must see what it's modifying, but a
    # full 12k-char file plus a 4096-token re-emit is what made edits crawl on
    # this hardware (context 16384 spills the 7B model onto the CPU, so every
    # extra prompt token is doubly expensive). Cap the visible window and
    # demand compactness, the same nudge that fixed create-side truncation.
    current_block = ""
    if editing:
        shown = current if len(current) <= 4000 else (
            current[:3200] + "\n// ...(middle of the current file omitted)...\n" + current[-700:]
        )
        current_block = (
            f"\nCURRENT CONTENT of {path} (you are MODIFYING this existing file):\n"
            f"```jsx\n{shown}\n```\n"
            f"Keep everything that already works, apply the requested change, and "
            f"return the COMPLETE updated file in one fenced block. Use compact "
            f"single-line imports and keep the file under ~200 lines so it fits "
            f"the response budget completely.\n"
        )
    # Recency, not capability, is what decides whether the 7B obeys the
    # language. Live 2026-10-02: the same model, asked directly, produced
    # correct Hinglish / Marathi-Devanagari / Hindi-Devanagari hero copy --
    # but a full per-file prompt, where the language rule sat under the
    # design block, the requirements and the project context, came back in
    # English every time. So the rule is restated as the LAST line of the
    # prompt, immediately before the write instruction, and repeated once
    # more in the system message.
    lang_tail = ""
    system_extra = ""
    if reply_language and reply_language != "English":
        lang_tail = (
            f"\nHARD CONSTRAINT - LANGUAGE: every piece of user-facing copy in this "
            f"file (headings, body text, buttons, nav, labels, footer) must be "
            f"written in {reply_language}, in that script. Identifiers, class "
            f"names, file paths and image alt attributes stay in English. Do not "
            f"write English marketing copy.\n"
        )
        system_extra = (
            f"\nThe end user of this app writes and reads {reply_language}. All "
            f"user-facing strings you produce must be in {reply_language}."
        )
    instruction = (
        f"Create a React component {path}: {purpose}. "
        f"It is the {'main application screen' if is_main else 'supporting component'} "
        f"of the app.\n"
        f"Available project files to import from:\n{available}\n"
        f"Other files already written (final; do not repeat them):\n"
        f"{chr(10).join(f'- {p}' for p in done_files) or '- (none)'}"
        f"{brand_line}\n{composition}\n{current_block}\n{brief_block}{design_block}"
        f"Full requirements:\n{summary}\n{project_ctx}\n"
        f"{lang_tail}\n"
        f"Write {path} now -- path in backticks on its own line, then one complete fenced block."
    )
    return [
        {"role": "system", "content": FILE_SYSTEM + system_extra},
        {"role": "user", "content": instruction},
    ]
    return [
        {"role": "system", "content": FILE_SYSTEM},
        {"role": "user", "content": instruction},
    ]


_CODE_FENCE_RE = re.compile(r"```[\w-]*\n([\s\S]*?)```", re.MULTILINE)
_PATH_LINE_RE = re.compile(r"`([\w./\\-]+\.[A-Za-z0-9]+)`")

# ChatML / role-tag drift: the fine-tuned model occasionally emits template
# tokens ("<|im_start|>assistant", "<Assistant>", ...) inside long code
# blocks. esbuild then reads them as JSX tags ("expected closing Assistant
# tag") and the file is dead. They are NEVER legitimate content.
_ROLE_TOKEN_RE = re.compile(
    r"<\|im_(?:start|end)\|>[^\n]*|^\s*<\/?\s*(?:Assistant|User|System|IM)\s*>[^\n]*$",
    re.MULTILINE,
)


def _scrub_role_tokens(content: str) -> str:
    cleaned = _ROLE_TOKEN_RE.sub("", content)
    # Collapse runs of blank lines the scrubbing can leave behind.
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()


_LOCALISE_SYSTEM = (
    "You are a UI copywriter. You translate short website strings into the "
    "language the customer asked in. You never touch code."
)


def localise_copy(path: str, content: str, brief: dict, provider: str = "",
                  model: str = "") -> tuple[str, int]:
    """Rewrite only the user-facing strings of one file, in place.

    Why this exists instead of asking the model to re-emit the file
    -----------------------------------------------------------
    Measured 2026-10-02. Two attempts, 423s and 243s, both zero effect:
    the hero stayed English. Two reasons, both architectural:

    1. The repair reused `REPAIR_SYSTEM`, which says "Fix ONLY what the error
       requires; keep everything else identical" -- a BUNDLER-repair prompt.
       Handed a copy rewrite, it instructs the model not to rewrite the copy.
    2. Re-emitting 5-7k chars of JSX with a translation instruction is simply
       too hard for a 7B. Its fine-tuned prior re-asserts English.

    So the model is asked for the only thing it is good at here -- a short
    list of translated strings -- and Python applies them. That also means
    the file CANNOT break: only string literal contents change, never
    imports, JSX structure or classes. Cost drops from ~4 minutes to ~30
    seconds.

    Returns (new_content, number_of_strings_changed).
    """
    lang = (brief.get("language") or "English").strip()
    if lang == "English":
        return content, 0

    strings = [s for s in _user_facing_strings(content)
               if s.strip() and not _TEMPLATE_SEED_RE.fullmatch(s)]
    # de-dupe, preserve order
    uniq: list[str] = []
    for s in strings:
        if s not in uniq:
            uniq.append(s)
    if not uniq or len(uniq) > 40:
        uniq = uniq[:40]
    if not uniq:
        return content, 0

    name = (brief.get("name") or "").strip()
    facts = "; ".join(brief.get("facts") or [])
    name_tokens = {w.lower() for w in re.split(r"\W+", name) if len(w) > 1}

    def _ask(subset: list[str], retry: bool = False) -> dict[str, str]:
        listing = "\n".join(f"{i + 1}. {s}" for i, s in enumerate(subset))
        # A worked example using THIS customer's actual name. Measured
        # 2026-10-02: with only "keep any proper name exactly as written",
        # the model over-applied that to the entire headline and returned
        # "Rahul Sharma - Full Stack Developer" untranslated -- which is the
        # single most visible string on the page. Naming the boundary
        # ("translate everything AROUND the name") fixes it.
        example = ""
        if name:
            role = (facts.split(";")[0].strip() if facts else "professional")
            example = (
                f"\nWorked example, using this customer's actual strings:\n"
                f'  "{name} - {role}"  ->  "{name} - {role} banaane wale"\n'
                f'  "View Portfolio"     ->  "Portfolio dekhein"\n'
                f'  "Get started"        ->  "Shuru karein"\n'
                f'\nKeep ONLY the name itself ({name}) untranslated. Translate '
                f"EVERY other word around it, including the job title, the "
                f"descriptor and the call to action.\n")
        ask = (
            f"Translate these website strings into {lang}, the language the "
            f"customer asked in. Keep the meaning and the tone of a marketing "
            f"site; do not lengthen a short button label into a sentence.\n"
            + example
            + (f"\nA string that is only technology names (React, Tailwind, "
               f"Node.js, Stripe) must stay exactly as it is. A string that "
               f"contains any other English word MUST be translated.\n"
               if lang != "English" else "")
            + f"\nStrings:\n{listing}\n\n"
            f"Output EXACTLY {len(subset)} lines, one per string, in the same "
            f"order, in the form:\n<index>||| <translated string>\n\n"
            f"Numbering only. No commentary, no markdown fence, no extra lines."
            + ("\n\nIMPORTANT: every line above must be DIFFERENT from its "
               "input unless it is purely a list of technology names. Do not "
               "echo English back." if retry else "")
        )
        try:
            text, _fin = providers.chat(
                [{"role": "system", "content": _LOCALISE_SYSTEM},
                 {"role": "user", "content": ask}],
                max_tokens=1400, temperature=0.3, provider=provider, model=model)
        except Exception:  # noqa: BLE001 - never let localisation break a run
            return {}
        out: dict[str, str] = {}
        for line in (text or "").splitlines():
            m = re.match(r"\s*(\d{1,3})\s*\|{3}\s*(.+?)\s*$", line)
            if not m:
                continue
            idx, val = int(m.group(1)), m.group(2).strip()
            if 1 <= idx <= len(subset) and val and val.lower() not in _JUNK_UI_WORDS:
                out[subset[idx - 1]] = val
        return out

    mapping = _ask(uniq)

    # Second pass over ONLY the strings the model echoed back unchanged. The
    # first pass leaves every "name + job title" string in English; asking
    # again about just those, with an explicit "do not echo English back",
    # recovers them for a fraction of the cost of a full re-emit.
    def _has_english(text_s: str) -> bool:
        words = [w for w in re.findall(r"[A-Za-z]+", text_s.lower())
                 if len(w) > 2 and w not in name_tokens]
        return bool(words)

    stalled = [s for s in uniq
               if s in mapping and mapping[s].strip() == s.strip() and _has_english(s)]
    if stalled:
        mapping.update(_ask(stalled, retry=True))

    if not mapping:
        return content, 0

    new = content
    changed = 0
    for old, val in sorted(mapping.items(), key=lambda kv: -len(kv[0])):
        if val.strip() == old.strip():
            continue
        # Replace only inside string literals. Re-quote with a quote char the
        # value cannot contain, so an apostrophe in the translation is safe.
        for q in ("'", '"', "`"):
            needle = q + old + q
            if needle in new:
                new = new.replace(needle, f"{q}{val}{q}")
                changed += 1
                break
    return new, changed


# Strings a translator must never produce as a UI label.
_JUNK_UI_WORDS = {
    "translation", "translated", "none", "n/a", "todo", "placeholder",
    "lorem ipsum", "your text here", "string", "output", "index",
}


def _recover_fenced(text: str) -> str:
    """Last-resort extraction: the biggest fenced block, whatever path it claims.

    `_parse_single_file` demands a "`path`" line before the fence. A repair
    prompt that ends with "Return the complete updated <path>" often gets a
    perfectly good file back with no path line, and the parse then throws the
    whole 7-minute generation away. Measured 2026-10-02: the hero repair
    produced 423s of work and was discarded for exactly this reason, and the
    repair silently moved on to another file.
    """
    blocks = re.findall(r"```[\w-]*\n([\s\S]*?)```", text)
    blocks = [b.strip() for b in blocks if len(b.strip()) > 200]
    if not blocks:
        return ""
    return max(blocks, key=len)


def _parse_single_file(text: str, wanted_path: str) -> str:
    """Extract the best fenced block from a single-file completion.

    'Best', not 'last': a long generation can close the real file and then
    drift (role tags, a re-emit attempt) in a further block that truncates.
    Candidates are scored: balanced braces + export default + import header
    beat raw length.
    """
    blocks = [_scrub_role_tokens(b) for b in _CODE_FENCE_RE.findall(text)]
    blocks = [b for b in blocks if b]
    if not blocks:
        # Salvage: an opening fence that never closed (finish=length). Only
        # worth returning for non-code files or as a repair-loop seed; callers
        # decide via bundle_check.
        open_match = re.search(r"```[\w-]*\n([\s\S]+)$", text)
        if open_match and not wanted_path.endswith((".jsx", ".tsx", ".js")):
            return _scrub_role_tokens(open_match.group(1))
        return ""

    def score(b: str) -> int:
        s = 0
        if b.count("{") == b.count("}"):
            s += 100
        if "export default" in b:
            s += 50
        if b.lstrip().startswith(("import ", "const ", "export ", "<!doctype", "{")):
            s += 20
        return s + min(len(b) // 500, 20)

    content = max(blocks, key=score).strip()
    # Degenerate-emission guard: the model occasionally emits ONLY the path
    # line (in backticks) inside the fence and stops (live: 25/33-char
    # "files" that were just the path). That is not content -- return empty
    # so the caller's retry/compact/skeleton machinery fires.
    if re.fullmatch(r"`[^`]*`", content):
        return ""
    # Tiny heuristics for json/css sanity
    if wanted_path.endswith(".json") and not content.lstrip().startswith("{"):
        return ""
    return content


# ---------------------------------------------------------------- verify

def bundle_check(files: dict) -> tuple[bool, str]:
    """Fast syntax/import validation with the project's real esbuild.
    Returns (ok, error_tail). No Tailwind here -- that's the preview gate."""
    if not ESBUILD.exists():
        return True, "esbuild missing; skipping verification"
    VERIFY_WORK_ROOT.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=VERIFY_WORK_ROOT, prefix="verify-") as td:
        work = Path(td) / "project"
        (work / "src").mkdir(parents=True)
        for path, content in files.items():
            dest = work / path
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(content, encoding="utf-8")
        entry = next(
            (work / c for c in ("src/main.jsx", "src/main.tsx", "src/index.jsx") if (work / c).exists()),
            None,
        )
        if entry is None:
            return False, "no entry point found"
        try:
            r = subprocess.run(
                ["node", str(ESBUILD), str(entry), "--bundle", "--format=iife",
                 "--platform=browser", "--loader:.js=jsx", "--loader:.jsx=jsx",
                 "--loader:.ts=ts", "--loader:.tsx=tsx", "--log-level=warning",
                 f"--outfile={work / 'bundle.js'}"],
                cwd=work, capture_output=True, text=True, timeout=60,
            )
        except (OSError, subprocess.SubprocessError) as e:
            return False, str(e)
        if r.returncode == 0:
            return True, ""
        return False, r.stderr[-1800:]# Render smoke test: bundle the app with a synthetic entry, then execute it
# with react-dom/server (see render_check below).


def render_check(files: dict) -> tuple[bool, str]:  # noqa: C901
    """Execute the app server-side with react-dom/server after bundling.

    Returns (ok, error). error is the runtime message + the component stack
    so the repair loop can localize the failing file. Requires react and
    react-dom in frontend/node_modules (the platform's own deps).
    """
    if not ESBUILD.exists():
        return True, ""
    VERIFY_WORK_ROOT.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=VERIFY_WORK_ROOT, prefix="render-") as td:
        work = Path(td) / "project"
        (work / "src").mkdir(parents=True)
        for path, content in files.items():
            dest = work / path
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(content, encoding="utf-8")
        # Synthetic entry: render App to string instead of mounting.
        app_import = next(
            ("./" + p for p in ("src/App.jsx", "src/App.tsx") if (work / p).exists()),
            None,
        )
        if app_import is None:
            return True, ""
        (work / "render-entry.jsx").write_text(
            f"import {{ renderToString }} from 'react-dom/server';\n"
            f"import App from '{app_import}';\n"
            f"try {{ const html = renderToString(<App />);\n"
            f"  if (!html || html.length < 40) throw new Error('render produced no markup');\n"
            f"}} catch (e) {{\n"
            f"  console.error('RENDER_ERROR::' + (e && e.message || String(e)));\n"
            f"  console.error('STACK::' + (e && e.stack || '').split('\\n').slice(0, 12).join('\\n'));\n"
            f"  process.exit(1);\n}}\n",
            encoding="utf-8")
        try:
            r = subprocess.run(
                ["node", str(ESBUILD), str(work / "render-entry.jsx"), "--bundle",
                 "--format=cjs", "--platform=node", "--loader:.js=jsx",
                 "--loader:.jsx=jsx", "--loader:.ts=ts", "--loader:.tsx=tsx",
                 "--log-level=warning", f"--outfile={work / 'render-bundle.cjs'}"],
                cwd=work, capture_output=True, text=True, timeout=60,
            )
            if r.returncode != 0:
                return True, ""  # bundling failed -> bundle_check's domain
            r2 = subprocess.run(
                ["node", str(work / "render-bundle.cjs")],
                cwd=work, capture_output=True, text=True, timeout=60,
            )
            if r2.returncode == 0:
                return True, ""
            err = "\n".join(l for l in r2.stderr.splitlines() if "RENDER_ERROR::" in l or "at " in l)
            return False, (err or r2.stderr)[-1800:]
        except (OSError, subprocess.SubprocessError) as e:
            return True, ""  # harness failure must not block generation


# ---------------------------------------------------------------- repair

REPAIR_SYSTEM = """You fix a single broken file in a Vite + React project.
You get the file content and the exact bundler error. Return the COMPLETE
corrected file: path on its own line in backticks, then one fenced block.
Fix ONLY what the error requires; keep everything else identical."""


def repair_file(path: str, content: str, error: str, provider: str, model: str,
                project_ctx: str, design_block: str = "") -> str:
    msgs = [
        {"role": "system", "content": REPAIR_SYSTEM},
        {"role": "user", "content": (
            f"File: {path}\n\n```jsx\n{content}\n```\n\nBundler error:\n{error}\n\n"
            f"Project requirements:\n{project_ctx[:2500]}\n\n"
            "Keep the file's existing palette/classes; do not restyle.\n"
            f"{design_block}"
            f"Return the complete corrected {path}."
        )},
    ]
    # The repair must re-emit the WHOLE file: a 2048-token cap truncates
    # anything over ~6k chars, the parse then fails/loses the export, and the
    # guard keeps the broken original. Scale the budget to the file size.
    # Floor 4096: a 6.4k-char Hero needs ~2k tokens of pure re-emit, and the
    # fine-tune's one-import-per-line style burns ~25% extra -- 2048-token
    # repairs were themselves truncating, which is why repairs never
    # converged (live: 3 identical failures on Casa Verde Hero).
    repair_budget = max(4096, min(8192, len(content) // 2))
    text, _ = providers.chat(msgs, max_tokens=repair_budget, temperature=0.1,
                             provider=provider, model=model)
    fixed = _parse_single_file(text, path)
    return fixed or content


# ------------------------------------------------------- lucide import repair
# The model hallucinates lucide-react icon names that don't exist in the
# installed version (e.g. `Bag` instead of `ShoppingBag`,
# `ArrowRightOnRectangle` instead of `LogOut`). esbuild hard-fails on those
# ("No matching export") and the preview drops to tier-2. Deterministic fix:
# validate every named import against the real export list and rewrite.

_LUCIDE_EXPORTS: set | None = None

# Recurring hallucinations, mapped to the real icon.
_LUCIDE_ALIASES = {
    "Bag": "ShoppingBag",
    "ShoppingCartIcon": "ShoppingCart",
    "ArrowRightOnRectangle": "LogOut",
    "ArrowLeftOnRectangle": "LogIn",
    "Logout": "LogOut",
    "Login": "LogIn",
    "Search": "Search",
    "Trash": "Trash2",
    "TrashBin": "Trash2",
    "Delete": "Trash2",
    "Edit": "Pencil",
    "Star": "Star",
    "PlusCircle": "CirclePlus",
    "MinusCircle": "CircleMinus",
    "XCircle": "CircleX",
    "CheckCircle": "CircleCheck",
    "AlertCircle": "CircleAlert",
    "HelpCircle": "CircleHelp",
    "UserCircle": "CircleUser",
    "Dollar": "DollarSign",
    "Calender": "Calendar",
    "CalenderDays": "CalendarDays",
    "ClockIcon": "Clock",
    "Grid": "LayoutGrid",
    "Dashboard": "LayoutDashboard",
    "Chart": "ChartColumn",
    "BarChart": "ChartColumn",
    "PieChart": "ChartPie",
    "LineChart": "ChartLine",
    "Home": "House",
}


def _lucide_exports() -> set:
    global _LUCIDE_EXPORTS
    if _LUCIDE_EXPORTS is None:
        names: set = set()
        cache = HERE / "lucide_exports.json"
        try:
            if cache.exists():
                names = set(json.loads(cache.read_text()))
        except Exception:  # noqa: BLE001
            names = set()
        if not names:
            # Fallback: scrape the installed package's export surface.
            try:
                idx = (FRONTEND_ROOT / "node_modules" / "lucide-react" / "dist" / "esm" / "lucide-react.js")
                if idx.exists():
                    names = set(re.findall(r"\bexport \{([^}]+)\}", idx.read_text(errors="ignore")))
                    names = {n.strip().split(" as ")[-1].strip() for n in names}
            except Exception:  # noqa: BLE001
                names = set()
        if not names:
            names = {"Circle"}  # last-resort safe target
        _LUCIDE_EXPORTS = names
    return _LUCIDE_EXPORTS


def _resolve_icon(name: str, exports: set) -> str | None:
    """Real export for a (possibly hallucinated) icon name; None if unfixable."""
    if name in exports:
        return name
    if name in _LUCIDE_ALIASES and _LUCIDE_ALIASES[name] in exports:
        return _LUCIDE_ALIASES[name]
    # Case-insensitive exact match (e.g. `checkbox` -> `Checkbox`).
    lower = {e.lower(): e for e in exports}
    if name.lower() in lower:
        return lower[name.lower()]
    return None


def fix_lucide_imports(path: str, content: str) -> str:
    """Rewrite nonexistent lucide-react named imports to real exports and
    update every JSX usage accordingly. No-op unless the file imports lucide."""
    if not path.endswith((".jsx", ".tsx", ".js", ".ts")):
        return content
    if "lucide-react" not in content:
        return content
    exports = _lucide_exports()

    m = re.search(r"import\s*\{([^}]*)\}\s*from\s*['\"]lucide-react['\"]", content, re.DOTALL)
    if not m:
        return content
    raw = m.group(1)
    specs = [s.strip() for s in raw.split(",") if s.strip()]
    out_specs: list[str] = []
    seen_locals: set[str] = set()
    changed = False
    for spec in specs:
        if " as " in spec:
            imported, local = [x.strip() for x in spec.split(" as ", 1)]
        else:
            imported = local = spec
        real = _resolve_icon(imported, exports)
        if real is None:
            real = "Circle"  # guaranteed to exist; keeps the bundle green
            changed = True
        if real != imported:
            changed = True
        # Duplicate local bindings hard-fail the bundler ("The symbol X has
        # already been declared") -- the 7B re-emits the same icon twice and
        # this fixer used to preserve both copies, which cost the live run its
        # Hero AND Menu sections (two LLM repairs could not fix it either).
        # Keep the first binding; JSX usages stay valid since the first import
        # already provides the name.
        if local in seen_locals:
            changed = True
            continue
        seen_locals.add(local)
        # Keep the model's original local binding via `as` so every JSX usage
        # (and even a later `import X as Y` chain) stays valid untouched.
        out_specs.append(real if real == local else f"{real} as {local}")

    if not changed:
        return content
    new_import = "import { " + ", ".join(out_specs) + " } from 'lucide-react'"
    return content[:m.start()] + new_import + content[m.end():]


# -------------------------------------------------- missing-import repair
# The sibling of the lucide bug above, but SILENT: a file that renders <Plus />
# without importing it, or calls useState() without importing it, still builds
# cleanly (esbuild treats an unknown identifier as a runtime global -- it is not
# a compile error), so the bundle verifies, the preview reaches tier-1, and the
# app white-screens with `ReferenceError: Plus is not defined`. Observed live on
# a generated bug-tracker. This repairs it deterministically from the real
# export lists, so no extra model call and no repair-loop round trip.

# React's own named exports that JSX/hooks code references by identifier.
_REACT_NAMES = {
    "useState", "useEffect", "useMemo", "useCallback", "useRef", "useContext",
    "useReducer", "useLayoutEffect", "useInsertionEffect", "useTransition",
    "useDeferredValue", "useId", "useSyncExternalStore", "useImperativeHandle",
    "memo", "forwardRef", "lazy", "Suspense", "Fragment", "StrictMode",
    "createContext", "createElement", "cloneElement", "isValidElement",
    "Children", "Component", "PureComponent", "Profiler",
}

_IMPORT_RE = re.compile(r"import\s+([^;\n]+?)\s+from\s+['\"]([^'\"]+)['\"]")


def _jsx_component_tags(content: str) -> set:
    """Capitalized JSX tags -- the identifiers React will resolve at runtime."""
    return set(re.findall(r"<([A-Z][A-Za-z0-9_]*)[\s/>]", content))


def _local_names(content: str) -> set:
    """Names this file already defines: imports, declarations, destructuring.

    Destructuring matters for safety: `const { Icon } = props` followed by
    `<Icon />` must NOT be "repaired" into an import, which would redeclare the
    identifier and turn a working file into a syntax error.
    """
    names: set = set()
    for m in _IMPORT_RE.finditer(content):
        clause = m.group(1)
        default = re.match(r"\s*([A-Za-z_$][\w$]*)", clause)
        if default:
            names.add(default.group(1))
        for group in re.findall(r"\{([^}]*)\}", clause):
            for spec in group.split(","):
                spec = spec.strip()
                if not spec:
                    continue
                names.add(spec.split(" as ")[-1].strip())
    for m in re.finditer(r"\b(?:function|class|const|let|var)\s+([A-Za-z_$][\w$]*)", content):
        names.add(m.group(1))
    # Destructured bindings: const { A, B } = / function X({ A }) { / (props) =>
    for m in re.finditer(r"(?:const|let|var)\s*\{([^}]*)\}\s*=", content):
        for part in m.group(1).split(","):
            part = part.strip()
            if part:
                names.add(part.split(":")[-1].split("=")[0].strip())
    for m in re.finditer(r"\(\s*\{([^}]*)\}\s*\)\s*=>", content):
        for part in m.group(1).split(","):
            part = part.strip()
            if part:
                names.add(part.split(":")[-1].split("=")[0].strip())
    for m in re.finditer(r"function\s*[A-Za-z_$]*\s*\(\s*\{([^}]*)\}", content):
        for part in m.group(1).split(","):
            part = part.strip()
            if part:
                names.add(part.split(":")[-1].split("=")[0].strip())
    return names


def fix_missing_imports(path: str, content: str) -> tuple[str, list[str]]:
    """Add imports for JSX/hook identifiers the file uses but never defines.

    Returns (content, unresolved): `unresolved` lists component names that are
    neither react nor lucide exports -- the caller records them because only
    the model (or the repair loop) can fix those, and they are exactly the
    white-screen class that a bundler check cannot see.
    """
    if not path.endswith((".jsx", ".tsx", ".js", ".ts")):
        return content, []
    # Unimported hooks don't show up as JSX tags (they're calls) but throw the
    # same ReferenceError at render time, so scan for them too.
    candidates = _jsx_component_tags(content) | set(
        re.findall(r"\b(use[A-Z][A-Za-z0-9_]*)\s*\(", content)
    )
    if not candidates:
        return content, []
    defined = _local_names(content)
    missing = sorted(t for t in candidates if t not in defined)
    if not missing:
        return content, []

    exports = _lucide_exports()
    hooks: list[str] = []
    icons: list[tuple[str, str]] = []
    unresolved: list[str] = []
    for name in missing:
        if name in _REACT_NAMES:
            hooks.append(name)
            continue
        real = _resolve_icon(name, exports)
        if real:
            icons.append((real, name))
        else:
            unresolved.append(name)
    if not hooks and not icons:
        return content, unresolved

    # lucide-react: extend an existing import, else add one next to react's.
    lucide_match = re.search(
        r"import\s*\{([^}]*)\}\s*from\s*['\"]lucide-react['\"]", content, re.DOTALL
    )
    if icons:
        specs = []
        for real, local in icons:
            specs.append(real if real == local else f"{real} as {local}")
        if lucide_match:
            existing = [s.strip() for s in lucide_match.group(1).split(",") if s.strip()]
            merged = existing + [s for s in specs if s not in existing]
            content = (content[:lucide_match.start()]
                       + "import { " + ", ".join(merged) + " } from 'lucide-react'"
                       + content[lucide_match.end():])
        else:
            line = "import { " + ", ".join(specs) + " } from 'lucide-react'\n"
            react_match = _IMPORT_RE.search(content)
            if react_match:
                content = content[:react_match.end()] + "\n" + line + content[react_match.end():]
            else:
                content = line + content

    # react: extend an existing named import, else add a second import line
    # (a duplicate `from 'react'` is legal ESM and keeps the default untouched).
    if hooks:
        named = re.search(r"import\s*\{([^}]*)\}\s*from\s*['\"]react['\"]", content)
        if named:
            existing = [s.strip() for s in named.group(1).split(",") if s.strip()]
            merged = existing + [h for h in hooks if h not in existing]
            content = (content[:named.start()]
                       + "import { " + ", ".join(merged) + " } from 'react'"
                       + content[named.end():])
        else:
            line = "import { " + ", ".join(hooks) + " } from 'react'\n"
            m = re.match(r"^\s*['\"]use client['\"];?\n", content)
            at = m.end() if m else 0
            content = content[:at] + line + content[at:]

    return content, unresolved


def fix_imports(path: str, content: str) -> tuple[str, list[str]]:
    """Both import repairs, in order: phantom lucide names first (they hard-fail
    the bundler), then identifiers that are never imported at all (they don't)."""
    return fix_missing_imports(path, fix_lucide_imports(path, content))


def fix_duplicate_imports(path: str, content: str) -> str:
    """Merge duplicate imports from the same module into one statement.

    Live v3 failure (Casa Verde Hero): the model emitted TWO lucide-react
    imports ({Sparkles} from an early edit + a full list later). esbuild:
    'The symbol "Sparkles" has already been declared' -> Hero dropped by
    salvage even though the rest of the section was good. ES modules allow
    repeated imports from one module, but NOT re-declaring the same bound
    name -- so merging by union is always safe for declarations, and the
    phantom-import fixer still runs after to drop names the file never uses.
    """
    if not path.endswith((".jsx", ".tsx", ".js")):
        return content
    stmt_re = re.compile(
        r"^import\s*\{([^}]*)\}\s*from\s*(['\"])([^'\"]+)\2\s*;?\s*$",
        re.M,
    )
    groups: dict[str, list[re.Match]] = {}
    for m in stmt_re.finditer(content):
        groups.setdefault(m.group(3), []).append(m)
    # Collect every edit as (start, end, replacement) against the ORIGINAL
    # content, then apply them in reverse order so earlier spans stay valid
    # (a forward loop with stale offsets fuses adjacent code -- found live).
    edits: list[tuple[int, int, str]] = []
    for _module, matches in groups.items():
        if len(matches) < 2:
            continue
        names: list[str] = []
        seen = set()
        for m in matches:
            for raw in m.group(1).split(","):
                n = raw.strip()
                if n and n not in seen:
                    seen.add(n)
                    names.append(n)
        merged = f"import {{ {', '.join(names)} }} from '{matches[0].group(3)}';"
        for m in matches[:-1]:
            edits.append((m.start(), m.end(), ""))
        last = matches[-1]
        edits.append((last.start(), last.end(), merged))
    for start, end, repl in sorted(edits, key=lambda e: -e[0]):
        content = content[:start] + repl + content[end:]
    return content


_STRAY_FENCE_RE = re.compile(r"^\s*`(?=\s*(?:import|export|const|function|//|/\*))")

# A JSX tag name MUST be an identifier; the model sometimes writes a member or
# index expression where one belongs (live: law run 20260930-182939, Fees.jsx
# `<mockFees[selected - 1].icon className="w-5 h-5" />` -> esbuild 'Expected
# ">" but found "["' -> both LLM repairs failed -> section dropped).
_BAD_JSX_TAG_RE = re.compile(
    r"<((?:[A-Za-z_$][\w$]*)(?:\[[^\[\]]*\]|\.[A-Za-z_$][\w$]*)+)"
    r"((?:\s+[A-Za-z_$][\w$-]*(?:\s*=\s*(?:\"[^\"]*\"|'[^']*'|\{[^{}]*\}))?)*)"
    r"\s*/>",
    re.S,
)
_JSX_ATTR_RE = re.compile(
    r"([A-Za-z_$][\w$-]*)(?:\s*=\s*(\"[^\"]*\"|'[^']*'|\{[^{}]*\}))?"
)


def fix_bad_jsx_tag_names(path: str, content: str) -> str:
    """Rewrite `<expr.some.path attr />` (invalid JSX tag name) into
    React.createElement(...), which is valid in ANY expression position.

    Brackets are added only when the element sits in JSX children position;
    inside an existing `{...}` container (the live case: a ternary) the bare
    call is spliced in. A default React import is added when the file lacks
    one. This can only turn a file that CANNOT bundle into one that can.
    """
    if not path.endswith((".jsx", ".tsx")) or "[" not in content:
        return content
    matches = list(_BAD_JSX_TAG_RE.finditer(content))
    if not matches:
        return content

    def _one(m: re.Match) -> str:
        expr, attrs = m.group(1), m.group(2) or ""
        if "[" not in expr:
            # `<Foo.Bar />` (member-expression component) is VALID JSX -- only
            # an index/property access as the tag name is what esbuild rejects.
            return m.group(0)
        props = []
        for am in _JSX_ATTR_RE.finditer(attrs):
            key, val = am.group(1), am.group(2)
            if val is None:
                val = "true"
            elif val.startswith("{"):
                val = val[1:-1]
            props.append(f"{key}: {val}")
        call = f"React.createElement({expr}, {{{', '.join(props)}}})"
        # Context: inside a `{...}` JSX expression container the bare call is
        # correct; in JSX children position it must be wrapped in braces.
        # Analysis is relative to the ENCLOSING TAG's '>' so the component
        # function's own `{` cannot masquerade as an expression container.
        before = content[:m.start()]
        gt = before.rfind(">")
        tail = before[gt + 1:] if gt >= 0 else before
        in_expr = tail.rfind("{") > tail.rfind("}") or "<" in tail
        return call if in_expr else "{" + call + "}"

    fixed = _BAD_JSX_TAG_RE.sub(_one, content)
    if not re.search(r"^import\s+React\b", fixed, re.M):
        fixed = "import React from 'react';\n" + fixed
    return fixed


def fix_stray_fence(path: str, content: str) -> str:
    """Drop an UNPAIRED fence backtick around a generated file.

    Live (portfolio run 20260930-174958, cost the run its Faq section): the
    raw file BEGAN with a single '`' -- not a proper ``` fence, so the parser
    kept it -- which opened a template literal that swallowed the whole file
    -> esbuild 'Unterminated string literal' at EOF -> both LLM repairs failed
    on the same error -> salvage dropped an otherwise complete component.

    Only acts on files with an odd number of backticks (paired fences are the
    parser's job; a lone backtick inside a string is left alone because the
    balance check passes there anyway)."""
    if not path.endswith((".jsx", ".tsx", ".js")) or content.count("`") % 2 == 0:
        return content
    out = _STRAY_FENCE_RE.sub("", content, count=1)
    if out.count("`") % 2 == 1:
        out = re.sub(r"(?m)^\s*`\s*$", "", out, count=1)
    return out


def _scan_js_state(content: str) -> tuple[list[str], int | None]:
    """Walk JS/JSX text tracking literal state and open brackets.

    Returns (open_brackets_in_order, cut_pos) where cut_pos is the index at
    which the still-open string/template literal begins (None when the file
    ends outside any literal). Comments are skipped; escapes are honored.
    """
    stack: list[str] = []
    i, n = 0, len(content)
    in_str: str | None = None
    in_tmpl = False
    lit_start: int | None = None
    while i < n:
        ch = content[i]
        nxt = content[i + 1] if i + 1 < n else ""
        if in_str:
            if ch == "\\":
                i += 2
                continue
            if ch == in_str:
                in_str = None
            i += 1
            continue
        if in_tmpl:
            if ch == "\\":
                i += 2
                continue
            if ch == "`":
                in_tmpl = False
            i += 1
            continue
        if ch == "/" and nxt == "/":
            j = content.find("\n", i)
            i = n if j < 0 else j + 1
            continue
        if ch == "/" and nxt == "*":
            j = content.find("*/", i + 2)
            i = n if j < 0 else j + 2
            continue
        if ch in "\"'":
            in_str, lit_start = ch, i
            i += 1
            continue
        if ch == "`":
            in_tmpl, lit_start = True, i
            i += 1
            continue
        if ch in "{[(":
            stack.append(ch)
        elif ch in "}])":
            if stack:
                stack.pop()
        i += 1
    return stack, (lit_start if (in_str or in_tmpl) else None)


def fix_truncated(path: str, content: str) -> str:
    """Repair a file whose generation was CUT OFF mid-token.

    Live (portfolio run 20260930-174958): Faq.jsx ended inside a string
    literal -> esbuild 'Unterminated string literal' -> both LLM repairs
    failed on the same error -> salvage dropped the section even though the
    bytes that arrived were a complete component minus its tail. This is
    mechanical, so it is fixed without the model:

      1. drop the unterminated literal (and the partial line it sits on),
      2. close whatever brackets are still open at the cut,
      3. re-append a missing default export,
      4. ship the repair ONLY if it comes back syntactically balanced --
         otherwise return the original (a failed repair must never make a
         file worse: the LLM repair loop / salvage remain the safety net).
    Already-balanced files are left untouched for the other fixers.
    """
    if not path.endswith((".jsx", ".tsx", ".js")):
        return content
    if _balanced_syntax(content):
        return content
    stack, cut = _scan_js_state(content)
    repaired = content
    if cut is not None:
        # Cut back to the start of the line holding the unterminated literal,
        # then shed any dangling `key:` / partial-expression fragment so the
        # closing brackets below attach to a complete statement.
        line_start = repaired.rfind("\n", 0, cut) + 1
        repaired = repaired[:line_start].rstrip()
        while repaired and re.search(r"[\w$\"']+\s*:\s*$", repaired):
            nl = repaired.rfind("\n")
            if nl < 0:
                repaired = ""
                break
            repaired = repaired[:nl].rstrip()
    # Close the structures left open at the cut (brackets only; JSX tags are
    # not counted, so a cut inside JSX still fails verification downstream).
    stack2, _ = _scan_js_state(repaired)
    closers = {"{": "}", "[": "]", "(": ")"}
    repaired = repaired.rstrip() + "".join(closers.get(op, "") for op in reversed(stack2))
    if repaired.strip() and not repaired.endswith("\n"):
        repaired += "\n"
    repaired = fix_missing_export(path, repaired)
    if not _balanced_syntax(repaired) or "export default" not in repaired:
        return content  # repair did not converge -- keep the original
    return repaired


# The 7B sometimes writes TypeScript syntax (parameter/return annotations,
# generics, `as` casts) into a `.jsx` file. esbuild's jsx loader rejects it --
# 'Expected ")" but found ":"' -- and the LLM repair loop is shown the same
# annotated source, so it fails twice and the section is DROPPED. That cost the
# law-firm page its Faq section in two separate runs, on `(id: number) =>`.
#
# The file is not wrong; only its extension is. esbuild parses it happily with
# the tsx loader, and the preview builder already bundles .tsx, so promote the
# file instead of performing risky type-annotation surgery.
_TS_SYNTAX_RES = (
    re.compile(r"\(\s*[A-Za-z_$][\w$]*\s*\??\s*:\s*(?:string|number|boolean|void|any|"
               r"unknown|never|object|symbol|bigint|[A-Z][\w$]*(?:\[\])?|(?:string|number|"
               r"boolean|\w+)\[\])\s*[,)=]"),
    re.compile(r"\)\s*:\s*(?:string|number|boolean|void|any|unknown|never|object|"
               r"[A-Z][\w$]*(?:\[\])?)\s*(?:\{|=>)"),
    re.compile(r"^\s*(?:export\s+)?(?:interface|type|enum)\s+[A-Za-z_$][\w$]*", re.M),
    re.compile(r"\b(?:useState|useRef|useMemo|useCallback|useReducer|useContext|forwardRef)\s*<"),
    re.compile(r"\bas\s+(?:const|[A-Z][\w$]*)\s*[;,)\]}]"),
    re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+[A-Za-z_$][\w$]*\s*:\s*(?:[A-Z]\w*|"
               r"string|number|boolean)", re.M),
)


def has_ts_syntax(content: str) -> bool:
    """True when a .jsx file contains TypeScript-only syntax esbuild's jsx
    loader cannot parse."""
    return any(r.search(content) for r in _TS_SYNTAX_RES)


def promote_tsx_files(files: dict) -> tuple[dict, list[tuple[str, str]]]:
    """Rename `.jsx` files carrying TypeScript syntax to `.tsx`.

    Returns (files, renames). When nothing is renamed the ORIGINAL dict object
    is returned, so callers can cheaply detect a no-op. Extensionless imports
    (`./components/Faq`) keep resolving; explicit `.jsx` specifiers and any
    trace/prose mentions are updated to match.
    """
    renames: list[tuple[str, str]] = []
    for path, content in files.items():
        if not path.endswith(".jsx") or not has_ts_syntax(content):
            continue
        target = path[:-4] + ".tsx"
        if target in files:
            continue  # both exist -- never clobber the sibling
        renames.append((path, target))
    if not renames:
        return files, []

    out = dict(files)
    for old, new in renames:
        out.pop(old, None)
        out[new] = files[old]
    for old, new in renames:
        stem_old = old.rsplit("/", 1)[-1]
        stem_new = new.rsplit("/", 1)[-1]
        for p in list(out):
            if p.endswith((".jsx", ".tsx", ".js", ".ts")) and stem_old in out[p]:
                out[p] = out[p].replace(stem_old, stem_new)
    return out, renames


def fix_missing_export(path: str, content: str) -> str:
    """Rescue a component that is structurally complete but never exports.

    Two live shapes (both cost the run its section):
      1. `function Hero() {...}` with no `export default` -> append it.
      2. hooks + bare JSX at MODULE scope with no function decl at all (the
         7B forgot the wrapper). Balance is checked first -- a truncated
         file cannot be rescued by wrapping, and the shell composer's
         missing-export drop remains the safety net.
    """
    if not path.endswith((".jsx", ".tsx")) or "export default" in content:
        return content
    if content.count("{") != content.count("}"):
        return content
    m = re.search(r"^function ([A-Z]\w*)\s*\(", content, re.M)
    if not m:
        m = re.search(r"^const ([A-Z]\w*)\s*=\s*\(", content, re.M)
    if m:
        return content.rstrip() + f"\n\nexport default {m.group(1)};\n"
    # Shape 2: no top-level component function. Wrap everything after the
    # imports in `export default function <Stem>() { ... }`.
    stem = (path.rsplit("/", 1)[-1].split(".")[0] or "Section")
    stem = stem[0].upper() + stem[1:]
    lines = content.splitlines(keepends=True)
    body_start = 0
    for ln in lines:
        s = ln.lstrip()
        if s.startswith(("import ", "//", "/*", "*", '"use", \'use client\';')):
            body_start += len(ln)
        elif s == "":
            body_start += len(ln)
        else:
            break
    head, body = content[:body_start], content[body_start:]
    if not body.strip():
        return content
    return (head
            + f"\nexport default function {stem}() {{\n"
            + body.rstrip() + "\n}\n")


def fix_gradient_text_quiet(path: str, content: str) -> str:
    """imagery.fix_gradient_text with a safety net: this is a className-string
    edit (cannot break bundling), so any unexpected pattern mismatch must log
    and no-op rather than take down a section."""
    try:
        return imagery.fix_gradient_text(path, content)
    except Exception:  # pragma: no cover - defensive
        return content


def fix_module_scope_hooks(path: str, content: str) -> str:
    """Hoist React hooks (and the handlers that reference them) out of MODULE
    scope into the default-exported component.

    Live v3 failure mode: the model emitted `const [isHovered, setIsHovered] =
    useState(false)` + `const handleHover = () => setIsHovered(...)` between
    the imports and `export default function Hero()`. useState at module scope
    throws "Invalid hook call" at import time -> render_check fails -> the
    LLM repair loop cannot fix it (it rewrote the file twice, still broken)
    -> salvage dropped a Hero the model had otherwise written WELL (5.8k
    chars of good section). Deterministic transform:

      - scan top-level statements before the `export default function` line
      - seed = statements that call useState/useRef/useMemo/...
      - fixpoint: any statement whose initializer references a hoisted
        binding moves too (handlers referencing state; handlers referencing
        handlers). Pure data consts stay at module scope (visible inside the
        component anyway).
      - hoisted block is re-inserted right after the component's opening brace.
    """
    if not path.endswith((".jsx", ".tsx")):
        return content
    m = re.search(r"^export default function (\w+)\s*\([^)]*\)\s*\{", content, re.M)
    if not m:
        return content
    comp_start = m.start()
    prelude = content[:comp_start]

    # Quote-aware top-level statement scan of the prelude.
    stmts: list[tuple[int, int, str]] = []
    depth = 0
    i, start, n = 0, 0, len(prelude)
    quote = ""
    while i < n:
        ch = prelude[i]
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = ""
            i += 1
            continue
        if ch in ("'", '"', "`"):
            quote = ch
        elif ch in "{([":
            depth += 1
        elif ch in "})]":
            depth -= 1
        elif ch == ";" and depth == 0:
            stmts.append((start, i + 1, prelude[start:i + 1]))
            start = i + 1
        i += 1

    hook_decl_re = re.compile(
        r"^\s*const (\[[^\]]+\]|[\w$]+)\s*=\s*"
        r"(useState|useRef|useReducer|useMemo|useCallback|useLayoutEffect)\(")
    hoist_idx: set[int] = set()
    for idx, (_s, _e, t) in enumerate(stmts):
        if hook_decl_re.match(t):
            hoist_idx.add(idx)
    if not hoist_idx:
        return content

    def own_names(t: str) -> set[str]:
        dm = re.match(r"\s*(?:const|let|var)\s+([^=\n(]+)=", t)
        if not dm:
            return set()
        lhs = dm.group(1).strip()
        return set(re.findall(r"[\w$]+", lhs))

    # Fixpoint: hoist any statement referencing an already-hoisted binding.
    while True:
        hoisted_names: set[str] = set()
        for idx in hoist_idx:
            hoisted_names |= own_names(stmts[idx][2])
        grew = False
        for idx, (_s, _e, t) in enumerate(stmts):
            if idx in hoist_idx:
                continue
            refs = set(re.findall(r"[\w$]+", t)) - own_names(t)
            if refs & hoisted_names:
                hoist_idx.add(idx)
                grew = True
        if not grew:
            break

    hoisted_text = "\n".join(stmts[i][2].strip() for i in sorted(hoist_idx))
    if not hoisted_text:
        return content

    # Rebuild prelude without hoisted statements; splice imports etc. intact.
    out_parts, last = [], 0
    for idx, (s, e, _t) in enumerate(stmts):
        if idx in hoist_idx:
            out_parts.append(prelude[last:s])
            last = e
    out_parts.append(prelude[last:])
    new_prelude = "".join(out_parts)

    # Insert after the component's opening brace.
    brace_pos = content.find("{", comp_start)
    if brace_pos < 0:
        return content
    after_brace = brace_pos + 1
    return (new_prelude + content[comp_start:after_brace]
            + "\n" + hoisted_text + "\n" + content[after_brace:])


# ---------------------------------------------------------------- progress

class Trace:
    def __init__(self):
        self.steps: list[dict] = []

    def add(self, phase: str, detail: str, **extra):
        step = {"phase": phase, "detail": detail, **extra}
        self.steps.append(step)
        print(f"[agent] {phase}: {detail}"[:220])


# ---------------------------------------------------------------- main loop

_PLACEHOLDER_NAME_RE = re.compile(
    r"\b(PortfolioName|YourName|Your Name|John Doe|Jane Doe|Company Name|"
    r"Business Name|Brand Name|Example Company|Acme Corp|Acme Inc|MyCompany|"
    r"Your Company|Your Business|Your Brand|Sample Business|Demo Company)\b")


_COPY_FILE_RE = re.compile(
    r"(hero|about|contact|footer|nav|header|testimonial|services|work|"
    r"pricing|faq|cta|intro|profile|bio|summary)", re.IGNORECASE)
# Seeded filler that means "this is a template": the strings the fine-tune
# was taught to emit (45 of its 88 training outputs contain the literal word
# "placeholder", 50 contain "Foo", 56 contain "bar").
_TEMPLATE_SEED_RE = re.compile(
    r"\b(?:foo|bar|baz|lorem ipsum|john doe|jane doe|acme|widget|thingamajig|"
    r"your\s+name\s+here|company\s+name|placeholder\s*\w*|sample\s+text|"
    r"example\s+content|test\s+data|dummy\s+\w+)\b", re.IGNORECASE)

# User-facing copy lives in string literals, and so do class lists and icon
# names -- so the two must be told apart. TWO earlier attempts used a plain
# character-class filter, and \w matches letters, so it silently discarded
# every real sentence (that is why the first v2/v3 A/B scored name=False for
# all five models while the raw v3 output plainly said "Rahul Sharma").
#
# The reliable discriminator is that a Tailwind class is a RUN OF UTILITIES:
# every token is a utility token AND at least one of them actually looks like
# one (contains -, :, / or []). English prose -- even all-lowercase prose like
# "welcome to our platform" -- has plain words and no utility tokens, so it
# survives.
_CLASSLIKE_RE = re.compile(
    r"^(?:[a-z0-9]+(?::[a-z0-9-]+)?(?:/[0-9]+)?"
    r"(?:-(?:[a-z0-9]+|\[[^\]]*\]))*)(?:\s+\S+)*$"
)
_UTILITY_HINT_RE = re.compile(r"[-:/\[\]]")
_IDENTIFIERISH_RE = re.compile(
    r"[{}<>=;]|\$\{|\.\w+\(|\bwindow\.|\bdocument\.|\bexport\b|\bimport\b"
    r"|\bfunction\b|\bconst\b|\breturn\b|\bfrom\b|\bclassName\b|\bkey=\b")


def _user_facing_strings(content: str) -> list[str]:
    """The strings a human would read in ONE file.

    Two syntaxes carry the copy: quoted string literals (props, constants,
    arrays) and bare JSX text nodes between tags. Measuring only the quoted
    ones misses every button label and heading written inline, which is most
    of the hero.
    """
    src = re.sub(r"//[^\n]*", "", content or "")
    src = re.sub(r"/\*[\s\S]*?\*/", "", src)
    found: list[str] = []
    for m in re.finditer(r"""(['"`])((?:[^'"`\\\n]|\\.){2,200}?)\1""", src):
        found.append(m.group(2))
    for m in re.finditer(r">([^<>{}]{2,200}?)<", src):
        found.append(m.group(1))
    keep: list[str] = []
    for raw in found:
        s = re.sub(r"\{[^{}]*\}", " ", raw)          # drop {expr} holes
        s = s.replace("&amp;", "&").strip()
        if not re.search(r"[A-Za-zऀ-ॿ]", s):
            continue
        if _IDENTIFIERISH_RE.search(s):
            continue
        if _CLASSLIKE_RE.match(s) and _UTILITY_HINT_RE.search(s):
            continue
        keep.append(s)
    return keep


def user_facing_copy(files: dict) -> str:
    """Every string a user would read on the page, across all files."""
    chunks: list[str] = []
    for p, content in (files or {}).items():
        if not p.endswith((".jsx", ".tsx", ".js", ".html")):
            continue
        chunks.extend(_user_facing_strings(content))
    return "\n".join(chunks)


def _lang_ok_for(copy: str, lang: str) -> bool:
    """Is this copy in the register the user actually wrote in?

    Split out so the same rule can judge the WHOLE page and the HERO
    separately. That separation matters: measured on a real 19-minute
    v3 generation from a Hinglish brief, the body copy was correctly
    Hinglish ("Mera Profile", "Mujhe Kahaan Se Kahaan Kariwale Hoon?") while
    the hero -- the first thing anyone sees -- was plain English. A single
    page-wide check passed that run; a hero check does not.
    """
    if lang in ("English", ""):
        return True
    if not copy.strip():
        return False
    if "Devanagari" in lang:
        dev = sum(1 for c in copy if "ऀ" <= c <= "ॿ")
        letters = sum(1 for c in copy if c.isalpha())
        return letters > 0 and dev / letters > 0.12
    # Roman-script registers (Hinglish / romanised Marathi) cannot be told
    # apart from English by script, so count the user's own function words.
    # A MARKER SHARE is required, not a single hit: one stray "mujhe" in
    # 4,800 characters of English is not a translated page. "main", "ka" and
    # "ke" are excluded because they are ordinary English words.
    _AMBIGUOUS = {"main", "ka", "ke", "kar", "se", "na", "to", "ha"}
    _MARKS = ("mera", "mere", "maza", "mala", "mujhe", "majhe", "amar",
              "maru", "aapko", "aani", "chahiye", "havi", "banani",
              "banvayacha", "karaycha", "lagbe", "sagle", "kasa", "aap",
              "hoon", "tumhe", "karo", "karte", "banao", "banaane",
              "karna", "karnaa", "shukriya", "dhanyavad", "hai", "hain",
              "kaam", "saal", "karaha", "karenge", "kariwale", "waala",
              "wali", "wale", "karke", "ke", "ki", "mein", "bhi", "kya",
              "acha", "kaisa", "kahan", "kyun", "sab", "bahut", "acha")
    low = copy.lower()
    hits = sum(len(re.findall(rf"\b{w}\b", low)) for w in _MARKS
               if w not in _AMBIGUOUS)
    words = max(1, len(re.findall(r"[A-Za-zऀ-ॿ]+", low)))
    # A hero is SHORT by nature -- a name, a tagline, two CTAs -- so a fully
    # translated one carries few marker words and a high ratio is the wrong
    # test. Measured on the real localised hero: 5 markers in 120 words =
    # 0.042, which a 0.06 threshold wrongly called "English". 0.03 is the
    # floor that still rejects an English hero (0 markers) and a page with one
    # stray marker (< 2 hits).
    return hits >= 2 and hits / words >= 0.03


def personalisation_score(files: dict, brief: dict) -> dict:
    """Did the user's own content actually reach the shipped copy?

    This is the metric the owner keeps reporting as "it just made a
    template", and until now nothing in the pipeline measured it. bundle_ok
    only proves the app RUNS; a perfect generic SaaS page bundles fine.

    Checks, in order of how badly their absence hurts the user:
      name_used    the real name from the brief appears in readable copy
      fact_used    at least one stated detail ("full stack developer") appears
      clean        no seeded template filler
      lang_ok      the PAGE is in the register the user wrote in
      hero_lang_ok the HERO -- the most visible surface -- is too
      score        0..1, the number the gate acts on
    """
    copy = user_facing_copy(files)
    low = copy.lower()
    name = (brief.get("name") or "").strip()
    facts = [f for f in (brief.get("facts") or []) if len(f.split()) >= 2]
    lang = (brief.get("language") or "English").strip()

    hero = next((p for p in files
                 if re.search(r"hero|intro|banner", p, re.IGNORECASE)), "")
    if not hero:
        hero = next((p for p in files
                     if p.endswith(("App.jsx", "App.tsx"))), "")
    hero_copy = user_facing_copy({hero: files[hero]}) if hero else ""

    name_used = bool(name) and name.lower() in low
    fact_used = any(f.lower() in low for f in facts) or any(
        tok in low for f in facts for tok in f.split() if len(tok) > 3)
    clean = not _TEMPLATE_SEED_RE.search(copy)
    lang_ok = _lang_ok_for(copy, lang)
    hero_lang_ok = _lang_ok_for(hero_copy, lang) if hero_copy else lang_ok

    parts = [name_used, fact_used, clean, lang_ok, hero_lang_ok]
    if not name:
        parts.remove(name_used)
    if not facts:
        parts.remove(fact_used)
    score = sum(1 for p in parts if p) / len(parts) if parts else 0.0
    return {"name_used": name_used, "fact_used": fact_used, "clean": clean,
            "lang_ok": lang_ok, "hero_lang_ok": hero_lang_ok,
            "score": round(score, 2), "copy_chars": len(copy)}


def repair_personalisation(files: dict, brief: dict, report: dict,
                           provider: str, model: str,
                           design_block: str = "") -> tuple[dict, int]:
    """One bounded copy-only round: the brief's own words back into the page.

    Deliberately NOT another full regeneration. A generation on this hardware
    is ~19 minutes; this touches at most two copy-bearing files with a
    short, low-temperature, copy-only instruction, so the cost of a failed
    personalisation check drops from 19 minutes to about two.

    Nothing structural changes: classes, imports, layout and the palette are
    all explicitly frozen, so the bundle-verified fileset stays valid.
    """
    name = (brief.get("name") or "").strip()
    lang = (brief.get("language") or "English").strip()
    if not name and lang == "English":
        return files, 0
    facts = "; ".join(brief.get("facts") or [])
    domain = brief.get("domain") or ""

    # Prefer the hero and the section most likely to carry the bio.
    targets = [p for p in files
               if p.endswith((".jsx", ".tsx"))
               and _COPY_FILE_RE.search(p) and p not in ("src/App.jsx", "src/App.tsx")]
    targets.sort(key=lambda p: (0 if "hero" in p.lower() else 1, len(p)))
    targets = targets[:2]
    if not targets:
        return files, 0

    fixed_count = 0
    # Tier 1: string-level localisation. ~30s per file, and it CANNOT break the
    # file because only string literal contents change. Measured 2026-10-02:
    # two full-file re-emit attempts cost 423s and 243s and changed nothing,
    # so the expensive path is now the fallback, not the default.
    for path in targets:
        content = files[path]
        before = personalisation_score({path: content}, brief)
        localised, changed = localise_copy(path, content, brief, provider, model)
        if changed and _balanced_syntax(localised):
            after = personalisation_score({path: localised}, brief)
            if after["score"] > before["score"]:
                files[path] = localised
                fixed_count += 1
                continue

    if fixed_count:
        return files, fixed_count

    # Tier 2: full-file re-emit. Only reached when localisation could not move
    # the needle -- e.g. the copy is English AND structurally wrong.
    for path in targets:
        content = files[path]
        problems = []
        if name and not report.get("name_used"):
            problems.append(
                f'the person it belongs to (named "{name}") is never mentioned')
        if lang != "English" and not report.get("hero_lang_ok"):
            problems.append(f"the copy is in plain English, not {lang}")
        if not problems:
            continue
        msgs = [
            {"role": "system", "content": REPAIR_SYSTEM},
            {"role": "user", "content": (
                f"File: {path}\n\n```jsx\n{content[:7000]}\n```\n\n"
                f"PROBLEM with this file: {'; and '.join(problems)}.\n\n"
                + (f"EXAMPLE of the transformation required -- study it, do not "
                   f"copy it verbatim:\n"
                   f'  "View Portfolio"        -> "Mera Portfolio Dekhein"\n'
                   f'  "Get started"            -> "Shuru karein"\n'
                   f'  "Building real-time dashboards"\n'
                   f'                            -> "Real-time dashboards banaye"\n'
                   f'  "Contact me"             -> "Mujhe contact karein"\n\n'
                   if lang != "English" else "")
                + f"Rewrite ONLY the user-facing copy in this file so it is about "
                f"them:\n"
                + (f"- the person is named \"{name}\"\n" if name else "")
                + (f"- their stated background: {facts}\n" if facts else "")
                + (f"- the site is for a {domain}\n" if domain else "")
                + (f"- EVERY headline, sub-headline, button label, nav item and "
                   f"body string must be written in {lang}, in that script. "
                   f"This is the first thing the visitor reads, so the "
                   f"headline itself must be in {lang} -- do not leave it in "
                   f"English.\n" if lang != "English" else "")
                + "Be specific about what they actually do -- no lorem ipsum, no "
                "'Welcome', no 'Our Services' with nothing under it.\n\n"
                "FROZEN: keep every import, className, component structure, "
                "layout and the palette exactly as they are. Change strings "
                "only. Do not add or remove components.\n\n"
                f"Return the complete updated {path}."
            )},
        ]
        budget = max(4096, min(8192, len(content) // 2))
        try:
            text, _ = providers.chat(msgs, max_tokens=budget, temperature=0.2,
                                     provider=provider, model=model)
        except Exception:  # noqa: BLE001 - never let the gate break a run
            continue
        new = _parse_single_file(text, path) or _recover_fenced(text)
        if not new:
            continue
        if not _balanced_syntax(new) or "export default" not in new:
            continue
        # Accept ONLY if this file actually got better. The old guard was
        # `len(new) > len(content) * 0.5`, which happily accepted a file the
        # model returned word-for-word unchanged -- so the repair could spend
        # seven minutes and move the score by exactly zero, and still report
        # success.
        was = personalisation_score({path: content}, brief)
        now = personalisation_score({path: new}, brief)
        if now["score"] <= was["score"]:
            continue
        files[path] = new
        fixed_count += 1
    return files, fixed_count


def fix_placeholder_names(files: dict, brief: dict) -> tuple[dict, int]:
    """Replace template placeholder names with the real brand/person name.

    Live failure (portfolio 2026-09-30): the shipped site was literally
    branded "PortfolioName" even though the prompt said "my name is Amey
    Chikane". When the brief knows the name, mechanical replacement is
    cheaper and more reliable than another LLM repair round.
    """
    name = (brief.get("name") or "").strip()
    if not name:
        return files, 0
    n = 0
    for p in list(files):
        if not p.endswith((".jsx", ".tsx", ".html", ".css")):
            continue
        new, k = _PLACEHOLDER_NAME_RE.subn(name, files[p])
        if k:
            files[p] = new
            n += k
    return files, n


_IMG_TAG_RE = re.compile(r"<img\b[^>]*?\bsrc=([\"'])([^\"']*)\1", re.IGNORECASE)
_BAD_SRC_RE = re.compile(
    r"(?:picsum\.photos|placehold|via\.placeholder|/images/|dummyimage|^\s*$)", re.IGNORECASE)
_SECTIONISH_RE = re.compile(r"hero|about|profile|portfolio|team|gallery|feature", re.IGNORECASE)


def inject_user_assets(files: dict, user_images: list[dict], logo_url: str = "") -> tuple[dict, list[str]]:
    """Guarantee every uploaded image appears in the shipped files.

    The prompts ask the model to use the user's images; live evidence
    (portfolio 2026-09-30, "i have uploaded my image") shows it forgets. This
    pass is the backstop: for each image not present anywhere, swap the first
    placeholder/stock <img> src in a section-ish file (hero/about/...) for the
    real url; if a file has no <img> at all, inject one styled for hero/about
    use. Never touches srcs that already reference the asset.
    """
    injected: list[str] = []
    jsx_paths = [p for p in files if p.endswith((".jsx", ".tsx")) and "App." not in p]
    if not jsx_paths:
        return files, injected

    def _present(url: str) -> bool:
        return any(url in files[p] for p in files)

    ordered = sorted(jsx_paths, key=lambda p: (not _SECTIONISH_RE.search(p), p))
    used_files: set[str] = set()
    for img in user_images:
        url = img["url"]
        if _present(url):
            continue
        placed = False
        for p in ordered:
            if p in used_files:
                continue
            content = files[p]
            for m in _IMG_TAG_RE.finditer(content):
                if _BAD_SRC_RE.search(m.group(2)) or m.group(2) == "":
                    files[p] = content[:m.start(2)] + url + content[m.end(2):]
                    injected.append(f"{url} -> {p} (replaced placeholder)")
                    used_files.add(p)
                    placed = True
                    break
            if placed:
                break
        if placed:
            continue
        # No placeholder anywhere in this file set: inject the image into the
        # first section-ish file's returned markup.
        for p in ordered:
            if p in used_files:
                continue
            m = re.search(r"return\s*\(\s*<([A-Za-z][\w.]*)", files[p])
            if not m:
                continue
            tag_end = files[p].find(">", m.end())
            if tag_end == -1:
                continue
            is_logo = url == logo_url
            cls = ("h-10 w-auto" if is_logo else
                   "h-64 w-full rounded-2xl object-cover shadow-lg")
            snippet = (
                f'\n      <img src="{url}" alt="{"logo" if is_logo else "photo"}" '
                f'className="{cls}" />'
            )
            files[p] = files[p][:tag_end + 1] + snippet + files[p][tag_end + 1:]
            injected.append(f"{url} -> {p} (injected)")
            used_files.add(p)
            break
    return files, injected


def run_agent(req, prep: dict, progress=None, provider: str = "", model: str = "") -> dict:
    """Per-file agentic generation. `progress(detail)` is called with short
    human-readable strings suitable for SSE progress lines."""
    def emit(msg):
        if progress:
            progress(msg)

    trace = Trace()
    provider = providers.resolve_provider(provider)
    trace.add("provider", provider)

    # Edit mode: the user sent an existing project (Builder's second+ turn).
    # The agent then plans the MINIMAL change set, sees the current content of
    # each touched file, and the result is merged back over the project so the
    # bundle check (and thus the preview) still runs on the whole app.
    operation = "edit" if (
        getattr(req, "operation", "create") == "edit" and getattr(req, "project_files", None)
    ) else "create"
    existing: dict[str, str] = {}
    if operation == "edit":
        for f in req.project_files:
            p, c = f.get("path"), f.get("content")
            if p and isinstance(c, str):
                existing[str(p)] = c
    trace.add("mode", f"{operation} ({len(existing)} existing files)")

    system_prompt = prep["messages"][0]["content"]
    user_prompt = prep["messages"][1]["content"]
    project_ctx = f"{system_prompt}\n\nUser request: {user_prompt}"[:9000]
    brand = getattr(req, "brand", None)

    # 1) Plan -------------------------------------------------------------
    emit("Architecting the application files...")
    brief = prep.get("brief") or {}
    brief_block = ""
    if brief.get("name") or brief.get("domain") or brief.get("subject"):
        ident = brief.get("name") or "the business"
        parts = []
        if brief.get("domain"):
            parts.append(f"it is a {brief['domain']}")
        if brief.get("subject"):
            parts.append(
                f"the business is about {brief['subject']} -- every product, "
                "listing, image and line of copy must relate to this subject"
            )
        if brief.get("offerings"):
            parts.append(f"the user explicitly asked for sections on: {', '.join(brief['offerings'])}")
        if brief.get("cta"):
            parts.append(f"primary conversion goal: {brief['cta']}")
        brief_block = (
            f"\nPRODUCT BRIEF (authoritative): the product is named \"{ident}\". "
            + ("; ".join(parts) + ". " if parts else "")
            + f"Use the name \"{ident}\" verbatim in UI copy (nav, hero, footer, "
            "title). Every heading and paragraph must be about THIS business, "
            "not a generic SaaS template.\n"
        )
        if brief.get("person"):
            # Personal sites: the copy is ABOUT the human. Generic placeholders
            # ("Your Name", "PortfolioName", "I am a developer") are the exact
            # "it just makes a template" failure the owner reported.
            facts = "; ".join(brief.get("facts") or [])
            brief_block += (
                f"This is a PERSONAL site for {ident}. "
                + (f"Stated background: {facts}. " if facts else "")
                + "Write first-person copy that uses these exact details "
                "(role, specialty, skills). NEVER emit placeholder names or "
                "lorem-ipsum bios -- no 'Your Name', 'PortfolioName', "
                "'John Doe', 'I am a developer'. Every section must sound "
                f"like {ident} wrote it.\n"
            )
    # Reply language: a Marathi or Hinglish user who gets English marketing
    # copy has still been handed a template, just in a different language.
    # _reply_language is threaded into every per-file prompt as a hard
    # constraint in the highest-salience position (last line, plus the system
    # message) -- see _file_messages.
    _reply_language = (brief.get("language") or "").strip()
    if _reply_language and _reply_language != "English":
        brief_block += (
            f"REPLY LANGUAGE: the user wrote their brief in {_reply_language}. Write ALL "
            "user-facing copy in that same language and script (headings, "
            "buttons, nav, footer, section body text) -- only code, file "
            "paths, class names and image alt attributes stay in English. Do "
            "NOT translate the brief into English and do not emit English "
            "boilerplate.\n"
        )
    # Domain design system: one curated palette/font pairing per trade,
    # injected into EVERY file ask so the page looks like one product (live:
    # each file invented its own palette -> mixed white/dark sections).
    # USER DESIGN PREFS override the domain preset: explicit color/branding,
    # dark mode, font, and animation requests parsed from the user's words
    # are commitments the output must comply with.
    design = design_system.get_design(brief)
    _prefs = design_system.extract_design_prefs(
        (prep.get("messages", [{}, {}])[1].get("content") or ""))
    if getattr(req, "brand", None) and req.brand.get("color"):
        _prefs["primary"] = req.brand["color"]
    if getattr(req, "brand", None) and req.brand.get("animation"):
        _prefs["animation"] = req.brand["animation"]
    design = design_system.apply_overrides(design, _prefs)
    if _prefs:
        trace.add("design-prefs", json.dumps(_prefs))

    # User-uploaded assets: served from /uploads/<filename>. The logo (or the
    # first image) brands the nav; EVERY image is listed for the model, and a
    # deterministic pass below guarantees each one actually lands in the site
    # (live failure: portfolio run 2026-09-30 shipped with the user's uploaded
    # photo nowhere in the output).
    logo_url = ""
    user_images: list[dict] = []
    if getattr(req, "assets", None):
        # Assets arrive as pydantic AssetInfo objects (API path) or dicts
        # (tests/programmatic calls) -- normalize to dicts once. Live failure:
        # run 20261001-1917 crashed the whole asset pass with "'AssetInfo'
        # object has no attribute 'get'" and the user's upload was lost.
        norm_assets: list[dict] = []
        for a in req.assets:
            if isinstance(a, dict):
                norm_assets.append(a)
            elif hasattr(a, "model_dump"):
                norm_assets.append(a.model_dump())
            else:
                norm_assets.append({
                    "url": getattr(a, "url", ""),
                    "filename": getattr(a, "filename", ""),
                    "original_name": getattr(a, "original_name", ""),
                    "mime_type": getattr(a, "mime_type", ""),
                })
        for a in norm_assets:
            fn = (a.get("filename") or "").lower()
            orig = (a.get("original_name") or a.get("filename") or "").lower()
            mime = (a.get("mime_type") or "").lower()
            if mime.startswith("image/") or fn.endswith((".png", ".jpg", ".jpeg", ".svg", ".webp")):
                user_images.append({
                    "url": a.get("url") or f"/uploads/{a.get('filename')}",
                    # Uploads are stored under uuid names; the user's original
                    # name is what can say "logo" or "portrait".
                    "filename": orig or fn,
                })
        # Explicit logo-named asset wins; else the first image.
        _logos = [u for u in user_images if "logo" in u["filename"].lower()]
        logo_url = (_logos or user_images or [{}])[0].get("url", "")
    if logo_url:
        trace.add("design-prefs", f"logo: {logo_url}")
    dsn_block = "\n" + design_system.design_block(design, brief.get("name") or "") + "\n"
    if logo_url:
        dsn_block += (
            f"- LOGO: the brand logo image is served at '{logo_url}'. Use it as\n"
            f"  the nav brand mark: <img src=\"{logo_url}\" alt=\"{brief.get('name') or 'logo'}\"\n"
            f"  className=\"h-9 w-auto\" /> -- do NOT draw a monogram square.\n")
    if user_images:
        # Every uploaded image is real content the user expects to SEE. The
        # model gets the list; the deterministic pass guarantees delivery.
        _lines = []
        for u in user_images:
            if u["url"] == logo_url:
                _lines.append(f"  - {u['url']} (logo -- nav/footer brand mark)")
            else:
                _lines.append(f"  - {u['url']} (photo -- use as hero/about/gallery image)")
        dsn_block += (
            "- USER IMAGES (must appear in the rendered page; do NOT replace "
            "them with stock URLs or avatars):\n" + "\n".join(_lines) + "\n"
            "  For a personal/portfolio site the photo belongs in the hero "
            "(portrait) or the about section.\n"
        )
    trace.add("design", f"{design['key']} / {design['mode']} / {design['fonts']['heading']}+{design['fonts']['body']}")

    plan = plan_files(prep["messages"], provider, model, edit=operation == "edit",
                      existing_paths=sorted(existing),
                      features=list(getattr(req, "features", []) or []),
                      archetype=prep.get("archetype", "saas"),
                      brief=brief)
    trace.add("plan", json.dumps([f["path"] for f in plan]))

    # 2) Generate application files (core infra is platform-provided later) --
    # Landing creates: App.jsx is NOT a model ask anymore -- it is composed
    # deterministically from the generated sections afterwards (see
    # _compose_landing_shell; live evidence: the model truncated the App.jsx
    # ask in 4/4 runs, then the inline-rendering scaffold replacement threw
    # away 4 healthy personalized sections as dead code).
    # Both landing and back-office creates get a deterministically composed
    # shell -- the giant App.jsx ask token-caps the 7B in both cases.
    compose_shell = operation == "create" and prep.get("archetype") in ("landing", "admin")
    generated: dict[str, str] = {}
    summary = f"App: {prep.get('app_name', 'the app')} ({prep.get('archetype', 'saas')} domain)."
    if brief.get("name") or brief.get("domain") or brief.get("subject"):
        summary = (
            f"App: {brief.get('name') or prep.get('app_name')}"
            f"{', ' + brief['domain'] if brief.get('domain') else ''} "
            f"{'- about ' + brief['subject'] if brief.get('subject') else ''}"
            f"({prep.get('archetype', 'saas')} domain)."
        )

    for i, item in enumerate(plan, 1):
        path = item["path"]
        emit(f"Writing {path} ({i}/{len(plan)})...")
        msgs = _file_messages(
            plan, item["purpose"], path, summary, project_ctx,
            generated, brand,
            current=existing.get(path), existing_paths=sorted(existing),
            brief_block=brief_block, design_block=dsn_block,
            reply_language=_reply_language,
        )
        # App screen gets the big budget; small components less. The fine-tune's
        # verbose one-import-per-line style burns ~25% extra tokens, so the main
        # file needs headroom or it dies before the closing fence.
        is_main = path.endswith(("App.jsx", "App.tsx"))
        if compose_shell and is_main:
            emit("App shell will be composed from the generated sections...")
            trace.add("plan", f"{path}: deterministic composition (model ask skipped)")
            continue
        # Section files get 6144 (was 2048): Hero/Menu sections routinely run
        # 6-13k chars (~2-3k tokens). At a 2048 cap they ALWAYS truncated,
        # triggered the compact retry (double the time), and often truncated
        # again -- 3 of 4 model sections were lost in one live run. The cap is
        # a ceiling, not a cost: clean completions stop at their closing fence.
        max_tokens = 4096 if is_main else 8192
        # Local 7B drifts (never closes the fence) at high temperature on long
        # asks; keep each ask in the trained regime and the decoding tame.
        local_temp = min(req.temperature, 0.65) if provider == "local" else req.temperature
        text, finish = providers.chat(msgs, max_tokens=max_tokens,
                                      temperature=local_temp, provider=provider, model=model)
        content = _parse_single_file(text, path)
        # A 'length' finish with a healthy balanced block in hand is fine:
        # the model just kept drifting after closing its fence. Anything
        # syntactically unbalanced (braces, or a string/template literal cut
        # mid-quote) means a mid-syntax cut -> retry while there's still one
        # compact-retry in the budget.
        balanced = _balanced_syntax(content)
        truncated_but_usable = finish == "length" and balanced and "export default" in content
        # Degenerate EOS retry: the model occasionally emits ONLY the path
        # line and stops (finish=stop, content empty after the parser guard).
        # One immediate retry at a shifted temperature escapes the degenerate
        # mode (live: 2 of 4 sections lost this way in v3 run 165641).
        if not content and finish == "stop":
            emit(f"{path} came back empty (degenerate stop); retrying once...")
            trace.add("gen-empty-retry", path)
            msgs[1]["content"] = (
                "REMINDER: output the path in backticks, then a fenced code block "
                "containing the COMPLETE component. Do not stop after the path line.\n\n"
                + msgs[1]["content"]
            )
            text, finish = providers.chat(msgs, max_tokens=max_tokens,
                                          temperature=min(0.9, local_temp + 0.2),
                                          provider=provider, model=model)
            content = _parse_single_file(text, path)
        if (not content or not balanced) and finish == "length":
            # One retry with an explicit compactness nudge -- a truncated main
            # file is worth one extra call (repair of half-written JSX is not).
            emit(f"{path} hit the token cap; retrying with compact-import instruction...")
            msgs[1]["content"] = (
                "IMPORTANT: write compact single-line imports and keep the file "
                "under 250 lines so it fits the response budget completely.\n\n" + msgs[1]["content"]
            )
            text, finish = providers.chat(msgs, max_tokens=max_tokens + 2048,
                                          temperature=local_temp, provider=provider, model=model)
            content = _parse_single_file(text, path)
        if not content:
            # Escalating fallbacks for the main file: curated archetype scaffold
            # (premium, proven tier-1) beats a bare skeleton every time. In an
            # EDIT the file already exists and works -- never clobber it with a
            # scaffold, keep it and let the rest of the agent (or the user)
            # decide.
            if path in existing:
                trace.add("gen-fail", f"{path}: no fenced block (finish={finish}); keeping existing file")
                content = existing[path]
            else:
                fallback = _scaffold_file_for(path, prep, brand) if is_main else ""
                if fallback:
                    trace.add("gen-fail", f"{path}: model failed twice (finish={finish}); using curated scaffold")
                    content = fallback
                else:
                    trace.add("gen-fail", f"{path}: no fenced block (finish={finish}); using skeleton")
                    content = _skeleton_for(path, prep)
        elif is_main and not _plausible_main(content) and path not in existing:
            # Unbalanced or missing export after both attempts -> ship the
            # curated scaffold rather than a broken main file.
            fallback = _scaffold_file_for(path, prep, brand)
            if fallback:
                trace.add("gen-implausible", f"{path}: unbalanced/no-export; curated scaffold")
                content = fallback
        elif finish == "length" and not truncated_but_usable:
            trace.add("gen-truncated", path)
        else:
            trace.add("gen", f"{path}: {len(content)} chars")
        content = fix_stray_fence(path, content)
        content = fix_truncated(path, content)
        content = fix_bad_jsx_tag_names(path, content)
        content, unresolved = fix_imports(path, content)
        content = fix_duplicate_imports(path, content)
        content = fix_duplicate_exports(path, content)
        content = fix_bare_icon_children(path, content)
        content = fix_icon_call_as_function(content)
        content = fix_jsx_ternary_siblings(content)
        content = fix_gradient_text_quiet(path, content)
        content = fix_self_shadowing_name(path, content)
        content = fix_missing_export(path, content)
        content = fix_module_scope_hooks(path, content)
        if unresolved:
            trace.add("import-missing",
                      f"{path}: uses {', '.join(unresolved)} but never defines it "
                      f"(would white-screen; left to the repair loop)")
        generated[path] = content
        if is_main and len(content) > 400:
            summary += f" Main UI is in {path}: {content[:400]}..."

    # Snapshot of every raw model output BEFORE rescue/drops/composition --
    # without this, degenerate outputs (live: 26-char Hero) were unpoppable
    # from artifacts and each diagnosis needed a re-run.
    raw_generated = dict(generated)

    # 2b) Landing shell composition: build App.jsx from the model's own
    # healthy domain-profile sections. If NO section survived, fall through
    # to the curated scaffold as a whole (brand + brief aware).
    dropped_sections: list[str] = []
    if compose_shell:
        # Rescue pass: the composer silently drops any section that fails
        # the plausibility check, shrinking the page (live: 3 of 4 model
        # sections lost in one run -- Hero truncated, Menu 25 chars,
        # Reservations misjudged). Give each implausible section ONE fresh
        # regeneration with a compactness instruction before dropping it;
        # a new sample is far likelier to be clean than repairing a file
        # that was cut mid-syntax.
        rescue_paths = [f"src/components/{s['stem']}.jsx"
                        for s in domain_profiles.get_profile(brief)["sections"]]
        rescue_paths += ["src/components/Hero.jsx",
                         f"src/components/{_LANDING_FAQ_STEM}.jsx"]
        temp2 = min(req.temperature, 0.65) if provider == "local" else req.temperature
        for spath in rescue_paths:
            if spath not in generated or _plausible_component(generated[spath]):
                continue
            item = next((it for it in plan if it["path"] == spath), None)
            if not item:
                continue
            emit(f"Recreating {spath} (first attempt was incomplete)...")
            msgs2 = _file_messages(
                plan, item["purpose"], spath, summary, project_ctx,
                {}, brand, brief_block=brief_block, design_block=dsn_block,
                reply_language=_reply_language,
            )
            msgs2[1]["content"] = (
                "IMPORTANT: write compact single-line imports and keep the "
                "file under 220 lines so it fits the response budget "
                "completely.\n\n" + msgs2[1]["content"]
            )
            text2, _fin2 = providers.chat(msgs2, max_tokens=8192,
                                          temperature=temp2, provider=provider,
                                          model=model)
            content2 = _parse_single_file(text2, spath)
            if content2:
                content2, _unres2 = fix_imports(spath, content2)
                content2 = fix_duplicate_exports(spath, content2)
                content2 = fix_bare_icon_children(spath, content2)
                content2 = fix_icon_call_as_function(content2)
                content2 = fix_jsx_ternary_siblings(content2)
                content2 = fix_self_shadowing_name(spath, content2)
                content2 = fix_missing_export(spath, content2)
                content2 = fix_module_scope_hooks(spath, content2)
            if content2 and _plausible_component(content2):
                trace.add("rescue", f"{spath}: regenerated {len(content2)} chars "
                          f"(first attempt was {len(generated[spath])})")
                generated[spath] = content2
            else:
                trace.add("rescue-fail",
                          f"{spath}: retry still implausible ({len(content2 or '')} chars); dropping")
        # TypeScript syntax in a .jsx file is an extension bug, not a content
        # bug: promote before composing so the section survives verification.
        generated, _tsx_renames = promote_tsx_files(generated)
        if _tsx_renames:
            trace.add("promote-tsx",
                      "TypeScript syntax in .jsx -> retagged: "
                      + ", ".join(f"{o.split('/')[-1]}->{n.split('/')[-1]}"
                                  for o, n in _tsx_renames))
        if prep.get("archetype") == "admin":
            shell, dropped_sections = _compose_admin_shell(
                generated, prep, brand, brief, trace=trace)
        else:
            shell, dropped_sections = _compose_landing_shell(
                generated, prep, brand, brief, trace=trace, logo_url=logo_url)
        if shell:
            generated["src/App.jsx"] = shell
            _slots = (domain_profiles.admin_views(brief)
                      if prep.get("archetype") == "admin"
                      else domain_profiles.get_profile(brief)["sections"])
            kept = [s["stem"] for s in _slots
                    if any(f"src/components/{s['stem']}{e}" in generated
                           for e in (".jsx", ".tsx"))
                    and s["stem"] not in [d.split('/')[-1][:-4] for d in dropped_sections]]
            trace.add("compose-shell",
                      f"App.jsx composed ({len(shell)} chars) over {len(kept)} healthy "
                      f"sections [{', '.join(kept)}]"
                      + (f"; dropped {dropped_sections}" if dropped_sections else ""))
            for p in dropped_sections:
                generated.pop(p, None)
        else:
            trace.add("compose-shell", "no healthy sections; falling back to curated scaffold")
            generated["src/App.jsx"] = _scaffold_file_for("src/App.jsx", prep, brand)

    # 3) Assemble with the same guarantees as the legacy path ---------------
    # Edits merge over the existing project (unchanged files stay untouched);
    # creates start from just the generated set.
    emit("Assembling project...")
    from main import inject_core_files, inject_images, validate_and_repair_files  # late import: avoids cycle

    merged: dict[str, str] = dict(existing) if operation == "edit" else {}
    merged.update(generated)
    file_list = [{"path": p, "content": c} for p, c in merged.items()]
    file_list = inject_core_files(file_list)
    file_list = inject_images(file_list)
    file_list = validate_and_repair_files(file_list)
    final_files = {f["path"]: f["content"] for f in file_list}

    # Extension-vs-syntax mismatch catches the EDIT path too (a changed file
    # keeps its original extension, so TS syntax can arrive there as well).
    final_files, _tsx2 = promote_tsx_files(final_files)
    if _tsx2:
        trace.add("promote-tsx",
                  "TypeScript syntax in .jsx -> retagged: "
                  + ", ".join(f"{o.split('/')[-1]}->{n.split('/')[-1]}" for o, n in _tsx2))

    # Brand the tab title -- the injected index.html says "Generated App",
    # which looked broken in every comparison screenshot.
    _title = ((brief or {}).get("name") or prep.get("app_name") or "").strip()
    if operation == "create" and _title and "index.html" in final_files:
        final_files["index.html"] = re.sub(
            r"<title>[^<]*</title>", f"<title>{_title}</title>",
            final_files["index.html"], count=1)

    # Landing creates: FORCE the themed index.html (domain font link, body
    # classes matching the design system) and index.css (font-display /
    # font-body helper classes + the animation system). The shell defines
    # its own <style> too; these guarantee correct fonts even if a model
    # section renders first.
    if compose_shell:
        from design_system import font_link
        from main import ANIM_CSS_BLOCK
        twm = design["tw"]
        final_files["index.html"] = (
            "<!doctype html>\n<html lang=\"en\">\n  <head>\n"
            "    <meta charset=\"UTF-8\" />\n"
            "    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\" />\n"
            f"    <title>{_title or 'App'}</title>\n"
            "    <script src=\"https://cdn.tailwindcss.com\"></script>\n"
            f"    <link href=\"{font_link(design)}\" rel=\"stylesheet\">\n"
            "  </head>\n"
            f"  <body class=\"{twm['page_bg']} {twm['heading_text']} antialiased min-h-screen\">\n"
            "    <div id=\"root\"></div>\n"
            "    <script type=\"module\" src=\"/src/main.jsx\"></script>\n"
            "  </body>\n</html>"
        )
        final_files["src/index.css"] = (
            f".font-display {{ {design['heading_css']} }}\n"
            f".font-body {{ {design['body_css']} }}\n"
            f"body {{ {design['body_css']} }}\n\n"
            + ANIM_CSS_BLOCK
        )
    elif operation == "create":
        # Webapp/admin creates keep the model's own index.html + index.css but
        # get the domain font + animation system injected. Live failure
        # (coffee-store 2026-10-01): this path shipped Inter everywhere and
        # zero .font-display rules, so every non-landing run failed the font
        # half of the design gate and the output read as "template".
        from design_system import font_link
        from main import ANIM_CSS_BLOCK, ensure_animations
        idx = final_files.get("index.html")
        if idx and "fonts.googleapis.com" not in idx:
            final_files["index.html"] = idx.replace(
                "</head>",
                f'    <link href="{font_link(design)}" rel="stylesheet">\n  </head>',
                1,
            )
        css = ensure_animations(final_files.get("src/index.css") or "")
        if ".font-display" not in css:
            css = (
                f".font-display {{ {design['heading_css']} }}\n"
                f".font-body {{ {design['body_css']} }}\n"
                f"body {{ {design['body_css']} }}\n\n" + css
            )
        if css:
            final_files["src/index.css"] = css

    # Deterministic style enforcement on EVERY create: map off-palette color
    # classes to the domain theme so style compliance never depends on the
    # model's judgment (v2 live failure: indigo glassmorphism restaurants).
    # User-custom themes pass through untouched -- arbitrary-value classes
    # (bg-[#7c3aed]) don't match named families, by design.
    enforced, enf_stats = style_enforcer.enforce_files(final_files, design)
    if enf_stats["rewritten"]:
        trace.add("style-enforce",
                  f"{enf_stats['rewritten']} classes -> theme: "
                  f"{', '.join(enf_stats['examples'][:4])}")
    final_files = enforced

    # Deterministic imagery enforcement: the model fills galleries with gray
    # `picsum.photos?grayscale&blur=2` URLs and empty-string image fields that
    # read as broken images in the preview (live: Casa Verde menu cards).
    # Domain-themed curated photos replace them; real URLs pass through.
    final_files, img_stats = imagery.enforce_imagery(final_files, design.get("key"))
    if img_stats["rewritten_urls"] or img_stats["filled_fields"]:
        trace.add("imagery-enforce",
                  f"{img_stats['rewritten_urls']} placeholder urls rewritten, "
                  f"{img_stats['filled_fields']} empty image fields filled "
                  f"(theme: {design.get('key')})")

    # Template placeholder names ("PortfolioName", "Your Name") are the
    # difference between "a template" and "my website". Replace them with the
    # brief's real name whenever one exists.
    final_files, _ph_n = fix_placeholder_names(final_files, brief)
    if _ph_n:
        trace.add("name-fix", f"{_ph_n} placeholder name(s) -> {brief.get('name')}")

    # ── PERSONALISATION GATE ────────────────────────────────────────────
    # bundle_ok proves the app RUNS. It does not prove the app is the USER'S.
    # A flawless generic SaaS page bundles perfectly, which is exactly the
    # "it just makes a template" complaint. So measure it, and when the real
    # name is missing, buy one bounded copy-only repair round (~2 min) rather
    # than letting a 19-minute generation ship someone else's page.
    personalisation = personalisation_score(final_files, brief)
    # Fire on either failure the user actually sees: the real name absent
    # anywhere, or the HERO in the wrong language while the body is right.
    _lang_broken = (brief.get("language") or "English") != "English" \
        and not personalisation["hero_lang_ok"]
    _need_repair = operation == "create" and (
        (bool(brief.get("name")) and not personalisation["name_used"])
        or _lang_broken)
    if _need_repair:
        why = []
        if brief.get("name") and not personalisation["name_used"]:
            why.append("the real name never appears")
        if _lang_broken:
            why.append(f"the hero is not in {brief['language']}")
        final_files, _pfix = repair_personalisation(
            final_files, brief, personalisation, provider, model, dsn_block)
        if _pfix:
            after = personalisation_score(final_files, brief)
            trace.add("personalise-gate",
                      f"{'; '.join(why)} -> {_pfix} file(s) copy-rewritten; "
                      f"name {personalisation['name_used']} -> "
                      f"{after['name_used']}, hero_lang "
                      f"{personalisation['hero_lang_ok']} -> "
                      f"{after['hero_lang_ok']}, score "
                      f"{personalisation['score']} -> {after['score']}")
            personalisation = after
        else:
            trace.add("personalise-gate",
                      f"{'; '.join(why)}; no copy file could be repaired")
    trace.add("personalisation", " ".join(
        f"{k}={v}" for k, v in personalisation.items()))

    # User-uploaded images are content the owner expects to SEE. Run AFTER
    # imagery enforcement so the curated-stock pass can never overwrite an
    # injected user url with a pool photo.
    if user_images:
        final_files, _user_injected = inject_user_assets(
            final_files, user_images, logo_url)
        if _user_injected:
            trace.add("assets-inject", "; ".join(_user_injected[:4]))

    # Deterministic motion enrichment: never let a section ship as dead static
    # markup. Adds only (transition/hover/active classes), so it can't break a
    # layout that already worked; honours an explicit "no animations" request.
    # design["animation"] is set by apply_overrides when the user explicitly
    # asked for rich or no motion; otherwise the enriched baseline applies.
    anim_pref = design.get("animation") or "standard"
    final_files, mot_stats = motion_enricher.enrich_files(final_files, anim_pref)
    if mot_stats["total"]:
        trace.add("motion-enrich",
                  f"{mot_stats['cards']} cards, {mot_stats['buttons']} buttons, "
                  f"{mot_stats['images']} images given transitions (mode: {anim_pref})")

    # 4) Verify with the real bundler + render smoke test + repair loop ----
    # Template-owned files are NEVER sent for repair -- if the error points
    # there, the model-owned file importing them is what's actually wrong.
    # bundle_check alone is NOT enough: esbuild accepts files that white-
    # screen at runtime (live: `{p.icon}` children holding a lucide component
    # object; a lucide icon CALLED as a function instead of rendered as an
    # element). render_check actually executes the app with react-dom/server.
    # The loop verifies BOTH after every repair: a repair that fixes the
    # bundler but not the runtime must not ship (live: Casa Verde Faq).
    MODEL_OWNABLE = (".jsx", ".tsx", ".js")

    def _verify_all(files_dict: dict) -> tuple[bool, str, str]:
        ok_b, err_b = bundle_check(files_dict)
        if not ok_b:
            return False, err_b, "bundle"
        ok_r, err_r = render_check(files_dict)
        if not ok_r:
            return False, err_r, "render"
        return True, "", ""

    emit("Applying design system, imagery and animation polish...")
    ok, err, err_kind = _verify_all(final_files)
    if not ok:
        emit(f"Verification found a {err_kind} problem; repairing...")
    attempts = 0
    repair_fails: dict[str, int] = {}
    while not ok and attempts < 3:
        broken = _localize_error(final_files, err)
        if not broken and err_kind == "render":
            # Runtime errors carry no filename. Localize by component stack:
            # 'at Hero (...)' -> src/components/Hero.jsx.
            m_stack = re.search(r"at ([A-Z][A-Za-z0-9]+) \(", err)
            if m_stack:
                comp = m_stack.group(1)
                broken = next((p for p in final_files if f"/{comp}." in p), None) \
                    or next((p for p in final_files if p.endswith(("App.jsx", "App.tsx"))), None)
            if not broken:
                broken = next((p for p in final_files if p.endswith(("App.jsx", "App.tsx"))), None)
        if broken and not broken.endswith(MODEL_OWNABLE):
            # Error localized to a core/template file -> the real culprit is
            # whoever imports it; try the main app file instead.
            broken = next((p for p in final_files if p.endswith(("App.jsx", "App.tsx"))), None)
        if not broken or not broken.endswith(MODEL_OWNABLE):
            trace.add("verify", f"unlocalized {err_kind} error: {err[:120]}")
            break
        # Deterministic first: a stray fence backtick or a truncated tail is
        # mechanically repairable -- try that before spending ~1 min of LLM
        # repair on an error the model already failed twice (live: portfolio
        # Faq 20260930-174958 was dropped after two failed repairs on a single
        # leading '`' that opened a template literal over the whole file).
        det = fix_stray_fence(broken, final_files.get(broken, ""))
        det = fix_truncated(broken, det)
        det = fix_bad_jsx_tag_names(broken, det)
        det = fix_missing_export(broken, det)
        if det and det != final_files.get(broken):
            candidate = dict(final_files)
            candidate[broken] = det
            ok_d, _err_d, _kind_d = _verify_all(candidate)
            if ok_d:
                final_files = candidate
                ok, err, err_kind = True, "", ""
                trace.add("repair-deterministic",
                          f"{broken}: mechanical repair verified (no model call)")
                continue
        if repair_fails.get(broken, 0) >= 2:
            # Live evidence (Casa Verde 071311): a truncated Hero burned all
            # 3 repair attempts on the SAME file -- each LLM repair is ~1 min
            # of wall time and never converged. Stop re-repairing a file that
            # already failed twice; hand off to the salvage loop below.
            trace.add("repair-skip",
                      f"{broken}: failed repair {repair_fails[broken]}x already; trying salvage instead")
            break
        emit(f"Fixing {broken} ({err_kind} reported an error)...")
        trace.add("repair", f"{broken} [{err_kind}]: {err[:140]}")
        original = final_files[broken]
        fixed = repair_file(
            broken, original, err, provider, model, project_ctx,
            design_block=dsn_block,
        )
        fixed = fix_stray_fence(broken, fixed)
        fixed = fix_truncated(broken, fixed)
        fixed = fix_bad_jsx_tag_names(broken, fixed)
        fixed, _unresolved = fix_imports(broken, fixed)
        fixed = fix_duplicate_imports(broken, fixed)
        fixed = fix_bare_icon_children(broken, fixed)
        fixed = fix_icon_call_as_function(fixed)
        fixed = fix_jsx_ternary_siblings(fixed)
        fixed = fix_gradient_text_quiet(broken, fixed)
        fixed = fix_self_shadowing_name(broken, fixed)
        # Guard: a repair that LOSES the default export (or breaks balance
        # that previously held) made things worse -- keep the original.
        had_export = "export default" in original
        lost_export = had_export and "export default" not in fixed
        regressed = (
            original.count("{") == original.count("}")
            and fixed.count("{") != fixed.count("}")
        )
        if lost_export or regressed:
            trace.add("repair-rejected", broken)
        else:
            # Re-enforce the design system: LLM repairs re-emit the whole
            # file and reintroduce off-palette classes (live: a repaired Menu
            # came back slate/indigo after enforcement had cleaned it).
            fixed, _enf = style_enforcer.rewrite(fixed, design)
            final_files[broken] = fixed
        ok, err, err_kind = _verify_all(final_files)
        attempts += 1
        if not ok:
            still = _localize_error(final_files, err)
            if still == broken:
                repair_fails[broken] = repair_fails.get(broken, 0) + 1

    # Landing-specific salvage: one still-broken SECTION must not cost the
    # whole page. Drop it and recompose; the shell simply renders fewer
    # sections (live: Hero truncation, Faq icon misuse). KEEP DROPPING while
    # each recomposition still fails on a localized section -- live bug
    # (071311): Hero was dropped, the recomposed page still failed on the
    # NEXT broken section, and the code shipped the generic SaaS scaffold
    # instead of the model's healthy personalized sections.
    if not ok and compose_shell:
        app_path = next(
            (p for p in final_files if p.endswith(("App.jsx", "App.tsx"))),
            "src/App.jsx",
        )
        # Round 0: a repair can corrupt the composed App.jsx ITSELF. Live bug:
        # the error localized to App.jsx, salvage refused to act ("not
        # localizable to a section") and the generic SaaS scaffold shipped
        # over healthy personalized sections. Rebuild the shell from the raw
        # sections first -- _compose_landing_shell is deterministic, so this
        # erases whatever the repair did to the shell.
        suspect0 = _localize_error(final_files, err)
        if suspect0 == app_path or suspect0 is None:
            shell0, _s0 = _compose_landing_shell(
                {k: v for k, v in final_files.items()
                 if k.startswith("src/components/")},
                prep, brand, brief,
            )
            if shell0:
                final_files[app_path] = shell0
                ok, err, err_kind = _verify_all(final_files)
                if ok:
                    trace.add("render-salvage",
                              "shell recomposed after App.jsx corruption; "
                              "model sections shipped")
        for _round in range(4):
            if ok:
                break
            suspect = _localize_error(final_files, err) \
                or (re.search(r"at ([A-Z][A-Za-z0-9]+) \(", err) and next(
                    (p for p in final_files
                     if f"/{re.search(r'at ([A-Z][A-Za-z0-9]+) \(', err).group(1)}." in p),
                    None))
            if (not suspect or suspect == app_path
                    or not suspect.startswith("src/components/")):
                trace.add("render-salvage",
                          f"{err_kind} error not localizable to a section: {err[:120]}")
                break
            # Try the deterministic fixers first: a duplicate import or a
            # missing export is fully mechanical, and dropping a good section
            # over it wastes the model's best work (live: Hero died on a
            # duplicated `Sparkles` import with 5.8k chars of good JSX).
            fixed_try = fix_stray_fence(suspect, final_files.get(suspect, ""))
            fixed_try = fix_truncated(suspect, fixed_try)
            fixed_try = fix_bad_jsx_tag_names(suspect, fixed_try)
            fixed_try = fix_duplicate_imports(suspect, fixed_try)
            fixed_try, _u = fix_imports(suspect, fixed_try)
            fixed_try = fix_bare_icon_children(suspect, fixed_try)
            fixed_try = fix_icon_call_as_function(fixed_try)
            fixed_try = fix_jsx_ternary_siblings(fixed_try)
            fixed_try = fix_gradient_text_quiet(suspect, fixed_try)
            fixed_try = fix_self_shadowing_name(suspect, fixed_try)
            fixed_try = fix_missing_export(suspect, fixed_try)
            fixed_try = fix_module_scope_hooks(suspect, fixed_try)
            if fixed_try and fixed_try != final_files.get(suspect):
                candidate = dict(final_files)
                candidate[suspect] = fixed_try
                ok_f, err_f, kind_f = _verify_all(candidate)
                if ok_f:
                    final_files = candidate
                    ok, err, err_kind = True, "", ""
                    trace.add("render-salvage",
                              f"{suspect} fixed deterministically (no drop); "
                              "model sections shipped")
                    break
            trace.add("render-salvage", f"dropping broken section {suspect}")
            final_files.pop(suspect, None)
            shell2, _ = _compose_landing_shell(
                {k: v for k, v in final_files.items() if k.startswith("src/components/")},
                prep, brand, brief,
            )
            if not shell2:
                trace.add("render-salvage", "no healthy sections left to compose")
                break  # nothing left -> curated scaffold fallback below
            final_files[app_path] = shell2
            ok, err, err_kind = _verify_all(final_files)
            if ok:
                trace.add("render-salvage",
                          f"recomposed page verified with {suspect} dropped; "
                          "model sections shipped")
                break

    # Last-resort fallback for CREATES: if the model-written fileset still
    # fails the real bundler after the repair loop, ship the curated archetype
    # scaffold (hand-built, tier-1 verified) instead of a broken app. A
    # beautiful working generic app beats a broken specific one — this is the
    # behavior that made every scaffold-fallback generation gate tier-1.
    if not ok and operation == "create":
        scaffold = _scaffold_file_for(
            next((p for p in final_files if p.endswith(("App.jsx", "App.tsx"))), "src/App.jsx"),
            prep, brand,
        )
        if scaffold:
            # Replace the model's app files with the curated scaffold's full
            # fileset (it is self-consistent and tier-1 verified).
            try:
                from scaffolds import get_base_scaffold
                _brand = dict(brand or {})
                if not _brand.get("name") and prep.get("app_name") and prep["app_name"] != "Zenith":
                    _brand["name"] = prep["app_name"]
                scaffold_files = get_base_scaffold(
                    prep.get("archetype", "saas"),
                    app_name=_brand.get("name") or prep.get("app_name", "App"), brand=_brand,
                    brief=brief,  # domain-aware copy even in the last resort
                )
                final_files = {f["path"]: f["content"] for f in scaffold_files}
                ok, err = bundle_check(final_files)
                trace.add("fallback-scaffold",
                          f"model bundle unrepairable after {attempts} repairs -> curated {prep.get('archetype', 'saas')} scaffold ({'bundled OK' if ok else 'STILL failing'})")
            except Exception as e:  # noqa: BLE001
                trace.add("fallback-scaffold", f"unavailable: {e}")

    trace.add("verify", "bundled OK" if ok else f"still failing: {err[:120]}")
    emit("Production bundle verified." if ok else "Bundle still failing after repairs; shipping best effort.")
    files_out = [{"path": p, "content": c} for p, c in sorted(final_files.items())]
    full_response = "\n\n".join(
        f"`{p}`\n```{'json' if p.endswith('.json') else ('css' if p.endswith('.css') else 'jsx')}\n{c}\n```"
        for p, c in generated.items()
    )
    return {
        "files": files_out,
        "full_response": full_response,
        "agent_trace": trace.steps,
        "bundle_ok": ok,
        # Did the user's own content reach the shipped copy? Callers and the
        # eval harness need this separately from bundle_ok: a running app can
        # still be a template.
        "personalisation": personalisation,
        # Stripped by the artifact dumper (main.py); included here so every
        # raw model output survives for offline diagnosis even when the
        # composer drops it.
        "generated_debug": [
            {"path": p, "content": c} for p, c in sorted(raw_generated.items())
        ],
    }


def _balanced_syntax(content: str) -> bool:
    """Cheap syntactic sanity: paired braces/parens/brackets, even backticks
    (template literals), and no line with an odd number of unescaped double
    quotes (JS strings can't span lines -> odd = cut mid-string, which esbuild
    reports as 'Unterminated string literal')."""
    if content.count("{") != content.count("}"):
        return False
    if content.count("(") != content.count(")"):
        return False
    if content.count("[") != content.count("]"):
        return False
    if content.count("`") % 2 != 0:
        return False
    # Odd unescaped double quotes on a line = a string cut mid-line. Skip
    # text inside template literals (backtick-aware) -- multi-line template
    # content legitimately contains any quote pattern (live false positive:
    # a healthy 13.7k-char Reservations section was dropped as "truncated").
    in_template = False
    for line in content.splitlines():
        ticks = line.count("`")
        if in_template:
            if ticks % 2 == 1:  # template literal closes on this line
                line = line[line.rindex("`") + 1:]
                in_template = False
            else:
                continue
        elif ticks % 2 == 1:  # template literal opens on this line
            line = line[:line.index("`")]
            in_template = True
        if line.replace('\\"', "").count('"') % 2 != 0:
            return False
    return True


def _plausible_main(content: str) -> bool:
    return _balanced_syntax(content) and "export default" in content and len(content) > 400


def _skeleton_for(path: str, prep: dict) -> str:
    """Last-resort minimal component when the model produced nothing for a
    NON-main file (main files get the curated scaffold instead). Keeps the
    fileset importable so the bundle check can run over the whole project."""
    stem = Path(path).stem or "Section"
    return (
        f"export default function {stem}() {{\n"
        f"  return (\n"
        f"    <section id=\"{stem.lower()}\" className=\"py-20\">\n"
        f"      <div className=\"max-w-4xl mx-auto px-6 text-slate-700\">\n"
        f"        <h2 className=\"text-3xl font-bold mb-4\">{stem}</h2>\n"
        f"      </div>\n"
        f"    </section>\n"
        f"  );\n"
        f"}}\n"
    )


def _plausible_component(content: str) -> bool:
    """A section file is usable when it is balanced, exports a default, and is
    more than a stub. Used by the landing shell composer to decide which
    model-generated sections get rendered (and which get dropped as dead
    code instead of shipping)."""
    return (
        bool(content)
        and content.count("{") == content.count("}")
        and "export default" in content
        and len(content) > 300
    )


_LANDING_FAQ_STEM = "Faq"

_LUCIDE_IMPORT_RE = re.compile(r"import\s*\{([^}]*)\}\s*from\s*['\"]lucide-react['\"]")
_ICON_DATA_RE = re.compile(r"\bicon\s*:\s*([A-Z][A-Za-z0-9]*)")
_BARE_COMPONENT_RE = re.compile(r"\{\s*([A-Z][A-Za-z0-9]*)\s*\}")
_BARE_ICON_PROP_RE = re.compile(r"\{\s*(\w+)\.icon\s*\}")


def _landing_nav_label(stem: str, profile: dict) -> tuple[str, str]:
    """(nav label, anchor) for a section stem: profile override if known,
    else derived from the CamelCase stem ('PracticeAreas' -> 'Practice Areas')."""
    for s in profile["sections"]:
        if s["stem"] == stem:
            return s["label"], s["anchor"]
    words = re.findall(r"[A-Z][a-z0-9]*", stem) or [stem]
    return " ".join(words), stem.lower()


def _plan_files_landing(messages: list, brief: dict | None) -> list[dict]:
    """Deterministic landing plan from the DOMAIN PROFILE (no model call).

    Known domains (law/hospital/fashion/restaurant/...) get curated,
    domain-appropriate sections -- a law firm gets Practice Areas + Fees,
    a restaurant gets Menu + Reservations. This is what killed the
    "same SaaS template for every business" defect.
    """
    product = (brief or {}).get("name") or "the product"
    domain = (brief or {}).get("domain") or ""
    if product == "the product":
        m = re.search(r"for ([A-Z][\w'-]*(?: [A-Z][\w'-]*)?)", messages[1]["content"])
        if m:
            product = m.group(1).strip()
    subject = f"{product}, {domain}" if domain else str(product)
    profile = domain_profiles.get_profile(brief)
    plan = [
        {"path": "src/App.jsx", "purpose": "Compose the landing sections: nav, Hero, "
         + ", ".join(s["label"] for s in profile["sections"])
         + f", FAQ, CTA, footer; smooth-scroll anchors"},
        {"path": "src/components/Hero.jsx",
         "purpose": f"Hero for {subject}: headline, subheadline about what {product} does"
                    f"{( ' for ' + domain) if domain else ''}, primary + secondary CTA buttons, "
                    f"social-proof row. Use fitting lucide icons such as "
                    f"{', '.join(profile['icons'][:4])} -- never off-domain icons"},
    ]
    plan += [
        {"path": f"src/components/{s['stem']}.jsx",
         "purpose": s["spec"].replace("{subject}", subject)
                    + f" Icons: {', '.join(profile['icons'])}."}
        for s in profile["sections"]
    ]
    plan.append({"path": f"src/components/{_LANDING_FAQ_STEM}.jsx",
                 "purpose": f"FAQ accordion for {subject}: 5 questions with expand/collapse answers"})
    # The product profile carries its own Faq section; appending a second
    # entry for the same path made the plan list Faq.jsx twice (two model
    # calls, one winner). Keep the first. 
    seen_paths: set[str] = set()
    deduped: list[dict] = []
    for item in plan:
        if item["path"] in seen_paths:
            continue
        seen_paths.add(item["path"])
        deduped.append(item)
    return deduped


def fix_bare_icon_children(path: str, content: str) -> str:
    """Fix lucide icons rendered as JSX children instead of elements.

    Live failure (law-firm Hero): the model wrote `<p>{p.icon}</p>` where
    `p.icon` holds a lucide component (keys {$$typeof, render}). esbuild
    accepts it, React white-screens the whole tree at runtime:
    'Objects are not valid as a React child'. Deterministic rewrites:
      {Icon}      -> <Icon />        when Icon is a lucide import
      {x.icon}    -> <x.icon />      when some `icon: <LucideName>` data exists
    Both rewrites are no-ops when the child is already a string or a real
    element, and they never touch attributes ({icon=...} is unaffected
    because the pattern requires the braces to BE the child).
    """
    if not path.endswith((".jsx", ".tsx")):
        return content
    m = _LUCIDE_IMPORT_RE.search(content)
    if not m:
        return content
    icons = {n.strip().split(" as ")[0].strip() for n in m.group(1).split(",")}
    icons.discard("")

    # Direct bare component child: {Shield} -> <Shield />. Always wrong when
    # the name is a lucide import, always safe to fix. Import/export brace
    # lists MUST be excluded ({ Shield, Star } from 'lucide-react' is an
    # import clause, not a JSX child) -- mask them out for the pass.
    import_spans = [
        m.span(1) for m in
        re.finditer(r"(?:\bimport\b|\bexport\b)\s*\{([^}]*)\}(?=[\s\S]{0,60}?\bfrom\b)", content)
    ]
    if import_spans:
        def _mask(s: str) -> tuple[str, list[str]]:
            saved = []
            out = s
            for i, (a, b) in enumerate(import_spans):
                token = f"\x00IMP{i}\x00"
                saved.append((token, out[a:b]))
                out = out[:a] + token + out[b:]
            return out, saved

        masked, saved = _mask(content)
    else:
        masked, saved = content, []

    def _direct(mm):
        name = mm.group(1)
        return f"<{name} />" if name in icons else mm.group(0)

    masked = _BARE_COMPONENT_RE.sub(_direct, masked)
    content = masked
    for token, original in reversed(saved):
        content = content.replace(token, original)

    # Property-child {x.icon}: only when the file's data literals assign a
    # lucide import to an `icon:` key (so .icon really is a component).
    data_icons = {n for n in _ICON_DATA_RE.findall(content) if n in icons}
    if data_icons:
        content = _BARE_ICON_PROP_RE.sub(r"<\1.icon />", content)
    return content


def fix_jsx_ternary_siblings(content: str, _depth: int = 0) -> str:
    """Wrap multi-root JSX ternary branches in a fragment.

    Live failure (Casa Verde Faq 20260928-172956): the model wrote
    `{open ? (<span>Collapse</span> <ChevronUp/> ) : (...)}` -- TWO adjacent
    siblings inside a `? (...)` branch with no fragment. esbuild:
    'Expected ")" but found "className"', and the LLM repair failed twice
    to fix it. Deterministic fix: for every `? (` / `: (` branch whose
    content has 2+ top-level JSX element lines, wrap the branch in
    `<> ... </>`. Wrapping a single-root branch would also be valid JSX, so
    false positives are harmless; we skip them anyway.

    v3 refinement: a branch that is ALREADY a fragment can still contain
    NESTED ternaries (live 20260929-191803: `{busy ? (<>...{open ? (
    <span>A</span> : (<span>B</span>\n <Icon/>)}...</>) : ...}`) -- the flat
    loop's scan jumped past the nested `? (` and shipped the broken branch.
    Already-fragment branches are now RECURSED into (bounded depth).
    """
    if "<" not in content or _depth > 6:
        return content
    pat = re.compile(r"[?:]\s*\(")

    def _wrap(inner: str) -> str:
        stripped = inner.strip()
        if not stripped or stripped.startswith("<>") \
                or stripped.startswith("<React.Fragment"):
            # Recurse: nested ternaries inside an existing fragment are
            # invisible to the flat scan but just as fatal.
            return fix_jsx_ternary_siblings(inner, _depth + 1) \
                if pat.search(inner) else inner
        lines = inner.splitlines()
        tag_idx = [k for k, ln in enumerate(lines)
                   if re.match(r"\s*<[A-Za-z][\w.]*[\s/>]", ln)]
        if len(tag_idx) < 2:
            return fix_jsx_ternary_siblings(inner, _depth + 1) \
                if pat.search(inner) else inner
        first = lines[tag_idx[0]]
        indent = len(first) - len(first.lstrip())
        top = [k for k in tag_idx
               if (len(lines[k]) - len(lines[k].lstrip())) == indent]
        if len(top) < 2:
            return fix_jsx_ternary_siblings(inner, _depth + 1) \
                if pat.search(inner) else inner
        return "\n<>" + inner + "</>"

    out: list[str] = []
    i = 0
    n = len(content)
    while True:
        m = pat.search(content, i)
        if not m:
            out.append(content[i:])
            break
        open_paren = content.index("(", m.start())
        out.append(content[i:open_paren + 1])
        j = open_paren + 1
        depth = 1
        in_str = ""
        while j < n and depth:
            ch = content[j]
            if in_str:
                if ch == "\\":
                    j += 2
                    continue
                if ch == in_str:
                    in_str = ""
            elif ch in ("'", '"', "`"):
                in_str = ch
            elif ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if not depth:
                    break
            j += 1
        if depth:  # unbalanced -- leave the rest untouched
            out.append(content[open_paren + 1:])
            break
        out.append(_wrap(content[open_paren + 1:j]))
        out.append(")")
        i = j + 1
    return "".join(out)


def fix_icon_call_as_function(content: str) -> str:
    """Rewrite `{item.icon({ ...props })}` -> `<item.icon { ...props } />`.

    The 7B sometimes CALLS the icon value like a function (lucide icons are
    components, not factories) -- bundles fine, white-screens at runtime:
    'item.icon is not a function' (live: Casa Verde Faq.jsx line 94, both
    063910 and 071311). The props span multiple lines, so match with a
    string-aware balanced-paren scan, not a flat regex.
    """
    out = []
    i = 0
    n = len(content)
    opener = re.compile(r"\{\s*(\w+)\.icon\s*\(\s*(\{)?")
    while i < n:
        m = opener.search(content, i)
        if not m:
            out.append(content[i:])
            break
        out.append(content[i:m.start()])
        prop_obj = bool(m.group(2))
        # Scan forward for the matching close paren, skipping strings and
        # template literals so quoted parens/braces can't skew the depth.
        j = m.end()
        depth = 1
        in_str = ""
        while j < n and depth:
            ch = content[j]
            if in_str:
                if ch == "\\\\":
                    j += 2
                    continue
                if ch == in_str:
                    in_str = ""
            elif ch in ("'", '"', "`"):
                in_str = ch
            elif ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if not depth:
                    break
            j += 1
        if depth:  # unbalanced -- leave the rest untouched
            out.append(content[m.start():])
            break
        inner = content[m.end():j].strip()
        comp = m.group(1)
        if prop_obj and inner.endswith("}"):
            inner = inner[:-1].rstrip()  # drop the props object's closing brace
            # {...{ props }} is a JSXSpreadAttribute of an object literal:
            # always-valid JSX, unlike a bare object literal attribute.
            out.append(f"<{comp}.icon {{...{{ {inner} }}}} />" if inner
                       else f"<{comp}.icon />")
        elif not inner:
            out.append(f"<{comp}.icon />")
        else:
            # Single non-object argument or multi-arg call: not the pattern;
            # keep as-is (repair loop will handle if it's actually broken).
            out.append(content[m.start():j + 1])
            i = j + 1
            continue
        # The pattern lives in a JSX child: `{item.icon(...)}` -- consume the
        # expression's closing brace so it isn't left dangling after `/>`.
        i = j + 2 if j + 1 < n and content[j + 1] == "}" else j + 1
    return "".join(out)


def fix_self_shadowing_name(path: str, content: str) -> str:
    """Rename a module-level `const <Stem> =` that clashes with the file's
    own `function <Stem>` default export.

    Live failure (Casa Verde Menu.jsx): the model wrote `const Menu = [...]`
    AND `export default function Menu()` in the same file. esbuild: 'The
    symbol "Menu" has already been declared'. Deterministic fix: rename the
    CONST to `<Stem>Data` and rewrite its references (never the function --
    the default export name is what the composed shell imports).
    """
    if not path.endswith((".jsx", ".tsx")):
        return content
    stem = Path(path).stem
    if not re.fullmatch(r"[A-Z][A-Za-z0-9]*", stem):
        return content
    decl = re.search(rf"\bconst\s+{stem}\s*[:=]", content)
    fn = re.search(rf"\bfunction\s+{stem}\b", content)
    if not (decl and fn):
        return content
    renamed = f"{stem}Data"
    content = re.sub(rf"\bconst\s+{stem}\s*[:=]", f"const {renamed} =", content, count=1)
    # References inside the const's own initializer and in JSX expressions:
    # safe word-boundary rewrite EXCLUDING the new declaration and the
    # function/export occurrences.
    content = re.sub(rf"(?<![\w.]){stem}(?![\w])", renamed, content)
    # The function name got renamed too by the blanket rewrite -- restore it.
    content = content.replace(f"function {renamed}", f"function {stem}")
    content = content.replace(f"export default {renamed};", f"export default {stem};")
    content = re.sub(
        rf"export default function {renamed}",
        f"export default function {stem}",
        content,
    )
    return content


def _compose_landing_shell(generated: dict, prep: dict, brand: dict | None,
                           brief: dict | None,
                           trace=None, logo_url: str = "") -> tuple[str, list[str]]:
    """Deterministic App.jsx for landing creates: import the model's HEALTHY
    domain-profile sections in canonical order under a small shell (nav +
    footer). Returns (shell_jsx, dropped_paths).

    Why: the 7B model reliably writes excellent personalized section files
    (live: 10.4k-char law-firm Hero) but virtually never survives the giant
    App.jsx composition ask (token cap in 4/4 runs) -- and the curated
    scaffold that used to replace it renders everything INLINE, so the
    model's sections shipped as dead code and every landing page rendered the
    same generic template with a swapped name. Composing the shell here keeps
    the model's work in the product: personalized sections render; broken
    ones are dropped, never shipped. Nav labels come from the DOMAIN PROFILE
    (law: Practice Areas / Fees; restaurant: Menu / Reservations; ...).
    """
    name = ((brief or {}).get("name") or (brand or {}).get("name")
            or prep.get("app_name") or "Our Firm")
    _words = name.split()
    monogram = "".join(w[0] for w in _words[:2]).upper() or "Z"
    profile = domain_profiles.get_profile(brief)
    cta = ((brief or {}).get("cta") or "").strip()
    cta_label = (cta.title() if cta and len(cta) < 28 else "Get started")
    imports: list[str] = []
    renders: list[str] = []
    dropped: list[str] = []
    links: list[tuple[str, str]] = []

    seen_stems: set[str] = set()

    def _add(stem: str, label: str = "", anchor: str = "") -> None:
        # A profile may already list the shell's own FAQ slot (the product
        # profile does), and `_add` is called again for it below -- without
        # this guard that becomes a duplicate import and a doubled section.
        if stem in seen_stems:
            return
        seen_stems.add(stem)
        for ext in ("jsx", "tsx"):
            path = f"src/components/{stem}.{ext}"
            if path not in generated:
                continue
            if _plausible_component(generated[path]):
                imports.append(f"import {stem} from './components/{stem}';")
                # Stagger sections so they cascade in as the page scrolls
                # instead of all animating on the same frame.
                renders.append(f"      <Reveal delay={{{len(renders) * 110}}}><{stem} /></Reveal>")
                if label:
                    links.append((label, f"#{anchor or stem.lower()}"))
            else:
                # Log WHY so drops are diagnosable (live: a healthy-looking
                # 13.7k section was dropped with no explanation in the trace).
                c = generated[path]
                why = ("unbalanced" if not _balanced_syntax(c)
                       else "missing export" if "export default" not in c
                       else f"stub ({len(c)} chars)")
                if trace is not None:
                    trace.add("shell-drop", f"{path}: {why}")
                dropped.append(path)
            return

    # Hero first (always), then the profile's domain sections, then FAQ.
    _add("Hero")
    for s in profile["sections"]:
        _add(s["stem"], s["label"], s["anchor"])
    _add(_LANDING_FAQ_STEM, "FAQ", "faq")
    if not renders:
        return "", list(generated)
    links_js = chr(10).join(
        f"    {{ label: {json.dumps(label)}, href: {json.dumps(href)} }},"
        for label, href in links
    )
    nl = chr(10)
    dsgn = design_system.get_design(brief)
    tw_js = json.dumps(dsgn["tw"])
    font_css = (f".font-display{{{dsgn['heading_css']}}} "
                f".font-body{{{dsgn['body_css']}}} "
                f"body{{{dsgn['body_css']}}}")
    grad_cls = f"bg-gradient-to-br {dsgn['tw']['gradient']}"
    jsx = f"""import {{ useEffect, useRef, useState }} from 'react';
import {{ Menu as MenuIcon, X }} from 'lucide-react';
{nl.join(imports)}

// Domain design tokens (resolved server-side by the design system).
const tw = {tw_js};
const RADIUS = "{dsgn['radius']}";
const GRAD = "{grad_cls}";
const FONT_CSS = {json.dumps(font_css)};
const LOGO_URL = {json.dumps(logo_url)};

// Scroll-reveal wrapper: sections animate in as they enter the viewport
// (IntersectionObserver; no-ops during server render).
function Reveal({{ children, delay = 0 }}) {{
  const ref = useRef(null);
  const [visible, setVisible] = useState(false);
  useEffect(() => {{
    const el = ref.current;
    if (!el) return undefined;
    const io = new IntersectionObserver((entries) => {{
      if (entries[0].isIntersecting) {{ setVisible(true); io.disconnect(); }}
    }}, {{ threshold: 0.12 }});
    io.observe(el);
    // Fallback: embedded/short viewports may never fire the observer
    // (live: preview iframes without scroll) -- never leave content invisible.
    const t = setTimeout(() => {{ setVisible(true); io.disconnect(); }}, 1200);
    return () => {{ clearTimeout(t); io.disconnect(); }};
  }}, []);
  return (
    <div
      ref={{ref}}
      style={{{{ animationDelay: delay ? `${{delay}}ms` : undefined }}}}
      className={{`reveal ${{visible ? 'reveal-visible' : ''}}`}}
    >{{children}}</div>
  );
}}

export default function App() {{
  const [menuOpen, setMenuOpen] = useState(false);
  const links = [
{links_js}
  ];
  return (
    <div className={{`min-h-screen ${{tw.page_bg}} ${{tw.heading_text}} font-body`}}>
      <style>{{FONT_CSS}}</style>
      <header className={{`sticky top-0 z-50 backdrop-blur-xl border-b ${{tw.page_bg}} ${{tw.border}}`}}>
        <div className="max-w-6xl mx-auto px-6 h-16 flex items-center justify-between">
          <a href="#top" className="flex items-center gap-2">
            {{LOGO_URL ? (
              <img src={{LOGO_URL}} alt="{name}" className="h-9 w-auto" />
            ) : (
              <span className={{`w-9 h-9 ${{GRAD}} flex items-center justify-center ${{tw.on_primary}} font-black text-sm tracking-tight ${{RADIUS}}`}}>{monogram}</span>
            )}}
            <span className="font-display font-extrabold text-lg tracking-tight">{name}</span>
          </a>
          <nav className={{`hidden md:flex items-center gap-8 text-sm font-medium ${{tw.body_text}}`}}>
            {{links.map(l => <a key={{l.href}} href={{l.href}} className="hover:opacity-70 transition-opacity">{{l.label}}</a>)}}
          </nav>
          <div className="hidden md:flex items-center gap-3">
            <a href="#top" className={{`px-4 py-2 ${{tw.primary}} ${{tw.primary_hover}} ${{tw.on_primary}} text-sm font-semibold ${{RADIUS}} transition-colors`}}>{cta_label}</a>
          </div>
          <button className="md:hidden p-2" onClick={{() => setMenuOpen(!menuOpen)}} aria-label="Menu">
            {{menuOpen ? <X className="w-5 h-5" /> : <MenuIcon className="w-5 h-5" />}}
          </button>
        </div>
        {{menuOpen && (
          <div className={{`md:hidden border-t px-6 py-4 space-y-3 ${{tw.surface}} ${{tw.border}}`}}>
            {{links.map(l => <a key={{l.href}} href={{l.href}} onClick={{() => setMenuOpen(false)}} className={{`block font-medium ${{tw.body_text}}`}}>{{l.label}}</a>)}}
            <a href="#top" className={{`block text-center px-4 py-2.5 ${{tw.primary}} ${{tw.on_primary}} font-semibold ${{RADIUS}}`}}>{cta_label}</a>
          </div>
        )}}
      </header>
      <main id="top">
{nl.join(renders)}
      </main>
      <footer className={{`border-t py-10 text-center text-sm ${{tw.border}} ${{tw.muted_text}}`}}>
        <div className="flex items-center justify-center gap-2 mb-2">
          {{LOGO_URL ? (
            <img src={{LOGO_URL}} alt="{name}" className="h-7 w-auto" />
          ) : (
            <span className={{`w-7 h-7 ${{GRAD}} flex items-center justify-center ${{tw.on_primary}} font-black text-[11px] ${{RADIUS}}`}}>{monogram}</span>
          )}}
          <span className="font-display font-bold">{name}</span>
        </div>
        &copy; 2026 {name}. All rights reserved.
      </footer>
    </div>    );
}}
"""
    return jsx, dropped


def _compose_admin_shell(generated: dict, prep: dict, brand: dict | None,
                         brief: dict | None, trace=None) -> tuple[str, list[str]]:
    """Deterministic App.jsx for back-office (admin) creates.

    A management system needs a SHELL the 7B cannot reliably write in one
    response: sidebar navigation, a topbar, active-view state, mobile drawer.
    Asking for it inline token-caps exactly like the landing App.jsx did, so
    the shell is composed here and the model only writes the views -- each of
    which is self-contained (it owns its own sample data and local state).

    Returns (shell_jsx, dropped_paths).
    """
    views = domain_profiles.admin_views(brief)
    imports: list[str] = []
    icons: list[str] = []
    entries: list[str] = []
    dropped: list[str] = []

    for v in views:
        stem = v["stem"]
        found = next((f"src/components/{stem}.{e}" for e in ("jsx", "tsx")
                      if f"src/components/{stem}.{e}" in generated), None)
        if not found:
            continue
        content = generated[found]
        if _plausible_component(content):
            imports.append(f"import {stem} from './components/{stem}';")
            icons.append(v["icon"])
            entries.append(
                f"  {{ id: {json.dumps(stem.lower())}, label: {json.dumps(v['label'])}, "
                f"icon: {v['icon']}, View: {stem} }},"
            )
        else:
            why = ("unbalanced" if not _balanced_syntax(content)
                   else "missing export" if "export default" not in content
                   else f"stub ({len(content)} chars)")
            if trace is not None:
                trace.add("shell-drop", f"{found}: {why}")
            dropped.append(found)

    if not imports:
        return "", list(generated)

    name = (brand or {}).get("name") or prep.get("app_name") or "Console"
    dsgn = design_system.get_design(brief)

    # The template below is one f-string, so `{tw.page_bg}` must be a foreign
    # attribute access. Wrap the token dict so the palette is resolved to real
    # class strings here rather than shipped as a client-side lookup.
    class _Tw:
        def __init__(self, d: dict):
            self.__dict__.update(d)

    tw = _Tw(dsgn["tw"])
    grad = f"bg-gradient-to-br {dsgn['tw']['gradient']}"
    monogram = ("".join(w[0] for w in re.findall(r"[A-Za-z0-9]+", name[:18])[:2]) or "TB").upper()
    email = (re.sub(r"[^a-z0-9]", "", name.lower())[:18] or "console") + ".local"

    # `__GRAD__` is patched in after formatting: an f-string cannot contain a
    # literal brace, and the template needs the class inside a JS template
    # literal on the client.
    jsx = f'''import {{ useMemo, useState }} from 'react';
import {{ {', '.join(icons)}, Menu, X, Search, Bell, ChevronRight }} from 'lucide-react';
{chr(10).join(imports)}

// View registry -- ids/labels/icons resolved server-side from the request.
const VIEWS = [
{chr(10).join(entries)}
];

export default function App() {{
  const [active, setActive] = useState('{views[0]["stem"].lower()}');
  const [navOpen, setNavOpen] = useState(false);
  const [query, setQuery] = useState('');

  const view = useMemo(() => VIEWS.find((v) => v.id === active) || VIEWS[0], [active]);
  const ActiveView = view.View;

  return (
    <div className={{"min-h-screen {tw.page_bg} {tw.body_text} antialiased"}}>
      {{navOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/50 backdrop-blur-sm lg:hidden"
          onClick={{() => setNavOpen(false)}}
        />
      )}}

      <aside
        className={{`fixed inset-y-0 left-0 z-50 w-64 {tw.surface} border-r {tw.border} flex flex-col transition-transform duration-300 ease-out ${{navOpen ? 'translate-x-0' : '-translate-x-full'}} lg:translate-x-0`}}
      >
        <div className={{`h-16 flex items-center gap-2.5 px-5 border-b {tw.border}`}}>
          <span className={{`w-8 h-8 __GRAD__ {tw.on_primary} flex items-center justify-center rounded-xl font-black text-xs shrink-0`}}>
            {monogram}
          </span>
          <span className="font-bold text-sm truncate">{name}</span>
          <button
            className="ml-auto lg:hidden opacity-60 hover:opacity-100 transition-opacity"
            onClick={{() => setNavOpen(false)}}
            aria-label="Close navigation"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <nav className="flex-1 overflow-y-auto p-3 space-y-1">
          {{VIEWS.map((v) => {{
            const Icon = v.icon;
            const on = v.id === active;
            return (
              <button
                key={{v.id}}
                onClick={{() => {{ setActive(v.id); setNavOpen(false); }}}}
                className={{`w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm transition-all duration-200 active:scale-[0.98] ${{on ? '{tw.accent_bg} {tw.accent_text} font-medium' : '{tw.muted_text} hover:bg-current/5'}}`}}
              >
                <Icon className="w-4 h-4 shrink-0" />
                <span className="truncate">{{v.label}}</span>
                {{on && <ChevronRight className="w-3.5 h-3.5 ml-auto opacity-60" />}}
              </button>
            );
          }})}}
        </nav>

        <div className={{`p-3 border-t {tw.border}`}}>
          <div className="flex items-center gap-2.5 px-2 py-2">
            <span className={{`w-8 h-8 rounded-full {tw.accent_bg} {tw.accent_text} flex items-center justify-center text-[11px] font-bold shrink-0`}}>
              AD
            </span>
            <div className="min-w-0">
              <p className="text-xs font-medium truncate">Administrator</p>
              <p className={{`text-[10px] truncate {tw.muted_text}`}}>admin@{email}</p>
            </div>
          </div>
        </div>
      </aside>

      <div className="lg:pl-64">
        <header
          className={{`sticky top-0 z-30 h-16 {tw.page_bg}/85 backdrop-blur-xl border-b {tw.border} flex items-center gap-3 px-4 sm:px-6`}}
        >
          <button
            className="lg:hidden p-2 -ml-2 rounded-lg transition-colors hover:bg-current/5"
            onClick={{() => setNavOpen(true)}}
            aria-label="Open navigation"
          >
            <Menu className="w-5 h-5" />
          </button>
          <h1 className="font-semibold text-base sm:text-lg tracking-tight truncate">{{view.label}}</h1>

          <div className="ml-auto flex items-center gap-2">
            <div className={{`hidden sm:flex items-center gap-2 {tw.surface_2} border {tw.border} rounded-xl px-3 py-2 transition-all duration-200`}}>
              <Search className={{`w-3.5 h-3.5 {tw.muted_text} shrink-0`}} />
              <input
                value={{query}}
                onChange={{(e) => setQuery(e.target.value)}}
                placeholder="Search..."
                className="bg-transparent text-xs outline-none w-36 opacity-80"
              />
            </div>
            <button
              className={{`relative p-2 rounded-xl {tw.surface_2} border {tw.border} transition-all duration-200 hover:opacity-80 active:scale-[0.96]`}}
              aria-label="Notifications"
            >
              <Bell className="w-4 h-4" />
              <span className="absolute top-1.5 right-1.5 w-1.5 h-1.5 rounded-full bg-red-500" />
            </button>
          </div>
        </header>

        <main className="p-4 sm:p-6">
          <div key={{active}} className="animate-fade-up">
            <ActiveView />
          </div>
        </main>
      </div>
    </div>
  );
}}
'''
    return jsx.replace("__GRAD__", f'${{{json.dumps(grad)}}}'), dropped


def _scaffold_file_for(path: str, prep: dict, brand: dict | None = None) -> str:
    """Curated-scaffold fallback for a model-owned file (App.jsx only).
    The scaffolds are hand-built, JSX-verified, tier-1 bundling.
    Personalization guarantee: even when the model fails outright and the
    scaffold ships, it must carry the user's product name -- never a generic
    placeholder (law-firm test lesson)."""
    if not path.endswith(("App.jsx", "App.tsx")):
        return ""
    try:
        from scaffolds import get_base_scaffold
        archetype = prep.get("archetype", "saas")
        brand = dict(brand or {})
        if not brand.get("name") and prep.get("app_name") and prep["app_name"] != "Zenith":
            brand["name"] = prep["app_name"]
        files = get_base_scaffold(
            archetype, app_name=brand.get("name") or prep.get("app_name", "App"),
            brand=brand, brief=prep.get("brief"),
        )
        for f in files:
            if f["path"].endswith(("App.jsx", "App.tsx")):
                return f["content"]
    except Exception as e:  # noqa: BLE001 - fallback must never crash the agent
        print(f"[agent] scaffold fallback unavailable: {e}")
    return ""


def _localize_error(files: dict, error: str) -> str | None:
    """Find which file a bundler error is about; None if unlocalizable."""
    m = re.search(r'[\w./\\-]+\.(?:jsx|tsx|js|ts|css|json)', error)
    if not m:
        return None
    hit = m.group(0).replace("\\", "/")
    if hit.startswith("src/"):
        return hit if hit in files else None
    # esbuild sometimes prints just the basename
    matches = [p for p in files if p.endswith(hit)]
    return matches[0] if len(matches) == 1 else None





