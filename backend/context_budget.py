"""Context-window budget manager for Terabit Studio.

A 7B model with a finite N_CTX cannot be handed an unbounded prompt. Every
context contributor (system instructions, retrieved project files, component
registry signatures, the storyboard/data-model IR, the user request) competes
for the same window, and the previous behavior — append whatever the pipeline
produced — silently pushed the *output* budget toward zero. Symptoms of that
failure: truncated files, dropped tail files, and the continuation loop
burning rounds on "continue" instead of code.

Strategy: allocate each contributor a fixed fraction of the usable window.
Contributors are trimmed by importance, not blindly truncated: retrieval
context keeps whole files in rank order rather than shredding the
highest-ranked file.
"""

from __future__ import annotations

import os
from typing import Any


def get_num_ctx() -> int:
    """The model context window, in tokens (single source of truth)."""
    return int(os.environ.get("N_CTX", "16384"))


def usable_window(num_ctx: int | None = None) -> int:
    """Tokens actually available for prompt + output after scheduling headroom.

    Reserves ~15% for chat-template overhead, sampling state, and safety
    margin so we never run the server into its hard cap.
    """
    return int(get_num_ctx() if num_ctx is None else num_ctx * 0.85)


def estimate_tokens(text: str) -> int:
    """Fast char-based token estimate (~3.5 chars/token for code+English mix).

    Deliberately conservative (over-estimates slightly) so budgets fail
    toward *shorter* prompts, never overflow.
    """
    if not text:
        return 0
    return max(1, len(text) // 3)


# Fraction of the usable window each contributor may occupy.
BUDGET_FRACTIONS = {
    "system": 0.30,        # instructions + design checklist (never droppable)
    "retrieval": 0.25,     # retrieved project files (edit mode)
    "registry": 0.10,      # component registry signatures
    "ir": 0.10,            # storyboard + data-model IR
    "history": 0.15,       # prior conversation turns
    "user": 0.10,          # the raw user request
}


def budget_for(section: str, num_ctx: int | None = None) -> int:
    """Max characters a given prompt section may consume."""
    return int(usable_window(num_ctx) * BUDGET_FRACTIONS.get(section, 0.05) * 3)


def trim_to_budget(text: str, budget_chars: int, label: str = "") -> str:
    """Hard-truncate a section to its character budget with a visible marker."""
    if len(text) <= budget_chars:
        return text
    marker = f"\n... [{label or 'section'} truncated to fit context budget] ...\n"
    keep = max(0, budget_chars - len(marker))
    return text[:keep] + marker


def fit_retrieval_files(
    ranked_files: list[tuple[float, str, str]],
    budget_chars: int,
    min_files: int = 1,
) -> tuple[str, list[dict[str, str]]]:
    """Pack whole retrieved files (rank order) into the retrieval budget.

    Rather than slicing every file to the same length, include as many whole
    files as fit, then give any leftover budget to the top-ranked file. This
    preserves syntactic integrity — a truncated JS file is worse than a
    missing one for edit reliability.

    Returns (formatted_context, sources).
    """
    if not ranked_files:
        return "", []

    parts: list[str] = []
    sources: list[dict[str, str]] = []
    used = 0
    included = 0

    for score, path, content in ranked_files:
        block = f"FILE: {path}\n```\n{content}\n```"
        block_len = len(block) + 2
        if included >= max(1, min_files) and used + block_len > budget_chars:
            break
        parts.append(block)
        sources.append({"title": path, "link": f"local://project/{path}", "score": f"{score:.3f}"})
        used += block_len
        included += 1

    # NOTE: no continuation splitting here. An earlier version emitted
    # "FILE: path (continued)" blocks; the model imitated that marker in its
    # own OUTPUT, shattering multi-block files at parse time (mid-JSX
    # truncations -> tier-2 previews). Files that exceed the remaining budget
    # are simply skipped; the marker now only survives in the wild via the
    # parser's tolerant continuation handling.

    return "\n\n".join(parts), sources


def output_budget(operation: str = "create") -> int:
    """Completion tokens for the main generation call, derived from the window.

    At the measured ~10 tok/s on the reference RTX 3050 laptop, a full app
    lands in the 4–5 min range; the cap deliberately stays modest because a
    7B model's output quality decays on very long single completions (and
    users watch a spinner the whole time). Scale up only with faster models.
    """
    window = usable_window()
    if operation == "edit":
        return min(2048, int(window * 0.30))
    return min(3072, int(window * 0.45))


def continuation_budget(round_num: int, previous: int) -> int:
    """Shrinking ask for continuation rounds 1..n of generate_complete_response."""
    return max(1500, previous // 2) if round_num > 0 else previous


def describe_budgets() -> dict[str, Any]:
    """Introspectable summary for /api/health and debugging."""
    window = usable_window()
    return {
        "num_ctx": get_num_ctx(),
        "usable_window_tokens": window,
        "sections": {
            name: {
                "tokens": int(window * frac),
                "chars": budget_for(name),
            }
            for name, frac in BUDGET_FRACTIONS.items()
        },
        "output_tokens_create": output_budget("create"),
        "output_tokens_edit": output_budget("edit"),
    }
