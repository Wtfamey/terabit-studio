"""Offline retrieval and compact prompts for Terabit Studio.

This module deliberately avoids web search and remote embedding downloads.  The
retriever grounds edit requests in the files that already exist in a project,
so a small local model can make focused changes without being asked to recreate
the whole application every time.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any


TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{1,}")
STOP_WORDS = {
    "about", "after", "again", "also", "and", "are", "build", "code",
    "for", "from", "have", "into", "make", "project", "that", "the",
    "this", "use", "with", "your",
}


def _terms(value: str) -> Counter[str]:
    return Counter(
        token.lower()
        for token in TOKEN_RE.findall(value)
        if token.lower() not in STOP_WORDS
    )


def _score(query_terms: Counter[str], document: str) -> float:
    document_terms = _terms(document)
    if not query_terms or not document_terms:
        return 0.0
    dot = sum(query_terms[term] * document_terms[term] for term in query_terms)
    query_norm = math.sqrt(sum(count * count for count in query_terms.values()))
    document_norm = math.sqrt(sum(count * count for count in document_terms.values()))
    return dot / (query_norm * document_norm) if query_norm and document_norm else 0.0


def retrieve_project_context(
    query: str,
    project_files: list[dict[str, Any]] | None = None,
    limit: int = 4,
    max_chars_per_file: int = 3500,
    budget_chars: int | None = None,
) -> tuple[str, list[dict[str, str]]]:
    """Return a small, local, explainable context set from project files.

    This is intentionally lexical rather than embedding based: it has zero
    startup/download cost on an RTX 3050 laptop, is deterministic, and keeps
    private source code on-device.  A path-name boost makes requests such as
    "change dashboard" select ``Dashboard.jsx`` even when the component is
    short.

    When ``budget_chars`` is given (from context_budget), whole files are
    packed in rank order up to the budget instead of returning a fixed count
    of arbitrarily-truncated files.
    """
    files = project_files or []
    query_terms = _terms(query)
    ranked: list[tuple[float, str, str]] = []
    for item in files:
        path = str(item.get("path", "")).replace("\\", "/")
        content = str(item.get("content", ""))
        if not path or not content:
            continue
        score = _score(query_terms, content)
        score += 1.25 * _score(query_terms, path.replace("/", " ").replace(".", " "))
        # Files needed to understand a React app remain useful even if wording
        # does not overlap perfectly with a product request.
        if path.rsplit(".", 1)[-1] in {"jsx", "tsx", "js", "ts", "css"}:
            score += 0.01
        ranked.append((score, path, content))

    ranked.sort(key=lambda entry: (-entry[0], entry[1]))

    if budget_chars is not None:
        from context_budget import fit_retrieval_files
        return fit_retrieval_files(ranked, budget_chars, min_files=limit)

    selected = ranked[:limit]
    sources = [
        {"title": path, "link": f"local://project/{path}", "score": f"{score:.3f}"}
        for score, path, _content in selected
    ]
    context = "\n\n".join(
        f"FILE: {path}\n```\n{content[:max_chars_per_file]}\n```"
        for _score_value, path, content in selected
    )
    return context, sources


def rag_search(query: str, project_files: list[dict[str, Any]] | None = None):
    """Compatibility wrapper for the API's RAG endpoint; always offline."""
    return retrieve_project_context(query, project_files)


def generate_business_system_prompt(
    business_type: str,
    features: list[str],
    user_prompt: str = "",
    assets: list[dict[str, Any]] | None = None,
    brand: dict[str, Any] | None = None,
    project_context: str = "",
    operation: str = "create",
    ir_context: str = "",
    registry_context: str = "",
) -> str:
    """Build a concise, repeatable prompt that a 7B local model can follow."""
    feature_list = ", ".join(str(feature) for feature in features[:12]) or "interactive dashboard, data tables, metrics, search/filters"
    brand = brand or {}
    brand_lines = []
    for key, label in (("name", "Brand name"), ("website", "Website"), ("primary_color", "Primary color"), ("logo_url", "Logo URL")):
        value = str(brand.get(key, "")).strip()
        if value:
            brand_lines.append(f"- {label}: {value}")
    asset_lines = [
        f"- {asset.get('original_name') or asset.get('filename')} at {asset.get('url')} ({asset.get('mime_type', 'file')})"
        for asset in (assets or [])[:10]
        if asset.get("url")
    ]
    output_scope = (
        "Generate a complete, fully functional, multi-section Vite React application. "
        "Include: `package.json`, `index.html`, `src/main.jsx`, `src/App.jsx`, `src/index.css`, "
        "and modular components in `src/components/*.jsx`."
        if operation == "create"
        else "Modify only the files required for this request. Preserve public APIs and existing components."
    )
    context_section = f"\nExisting project context (retrieved locally):\n{project_context}\n" if project_context else ""
    # The IR plan and registry signatures slot between the design checklist
    # and the brand profile: they carry the highest signal-per-token of any
    # section (the model should treat them as the spec to implement).
    ir_section = f"\n{ir_context}\n" if ir_context else ""
    registry_section = f"\n{registry_context}\n" if registry_context else ""
    design_checklist = """
VISUAL DESIGN & CODING STANDARDS (MANDATORY):
1. STYLING: Use ONLY Tailwind CSS utility classes on every element. NEVER write plain CSS classes (like .product-card or .hero) and NEVER use raw HTML styles.
2. PALETTE: Dark, modern SaaS theme — background `bg-slate-950` or `bg-gray-950`, surfaces `backdrop-blur-xl bg-white/5 border border-white/10`, accents `from-violet-600 to-cyan-600` or `from-indigo-500 to-purple-600`, text `text-slate-100`.
3. ICONS: Use `lucide-react` icons for every nav item, button, stat card, search input, and table action (`import { Search, Plus, TrendingUp, Users, DollarSign, Filter, Bell, CheckCircle2, ArrowUpRight, Sparkles, X, ChevronRight } from 'lucide-react'`).
4. INTERACTIVITY & STATE:
   - State-driven tab switching (e.g. Overview, Data Management, Analytics, Settings).
   - Search bar filter (`searchTerm`) + Status dropdown filter that actively filter the displayed table rows.
   - Interactive Modal or Drawer for adding/editing items (`isAddOpen`, `newItem` state).
   - Interactive Toast notification when actions succeed (`showToast`).
   - Rich realistic seed records (at least 4-6 detailed records with numbers, badges, tags).
5. SVG CHART / METRICS: Include a sleek custom SVG area/bar chart with gradients or rich KPI stat cards with trend percentages (+14.2%).
6. IMAGES: Use Unsplash URLs (e.g. `https://images.unsplash.com/photo-1522071820081-009f3b6b01b1?w=800&q=80`) for avatars and photography.

OUTPUT FORMAT REQUIREMENTS:
1. Provide a brief 1-2 sentence response acknowledging what you're building.
2. Output every file using a clear filename followed by a fenced code block, for example:
   `package.json`
   ```json
   { ... }
   ```
   `src/App.jsx`
   ```jsx
   // complete App code with Tailwind classes and React state
   ```
3. NEVER truncate files. Ensure all JSX tags, braces, and strings are closed cleanly.
4. Each file gets EXACTLY ONE fenced block. NEVER split a file across multiple
   blocks, and NEVER write "(continued)" -- output each file once, complete.
"""
    return f"""You are Terabit Studio, an elite full-stack engineer who builds premium, production-grade SaaS platforms.

Task: {operation} a modern {business_type} application.
User request: {user_prompt}
Requested features: {feature_list}
{output_scope}
{design_checklist}

Brand profile:
{chr(10).join(brand_lines) or '- Default modern brand styling'}
Uploaded local assets:
{chr(10).join(asset_lines) or '- None'}
{ir_section}{registry_section}{context_section}"""
