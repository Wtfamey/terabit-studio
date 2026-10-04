"""
Generates REAL (instruction, code) training examples for fine-tuning your
local Qwen model - using Gemini as a "teacher" model to write actual,
complete, correctly-styled components in exactly the same format/style
rules your local model needs to learn.

Uses Google's Gemini API, which has a genuinely free, no-credit-card tier
(as of 2026: Gemini 2.5 Flash, ~1,500 requests/day, no expiration) - get a
key in about a minute at https://aistudio.google.com/apikey with just a
Google account.

Put the key in backend/.env:
  GEMINI_API_KEY=your-key-here
(.env is now actually loaded - see the load_dotenv() fix in model_service.py)

Usage:
  pip install google-genai python-dotenv
  python generate_training_data.py --count 150

Output: ./training_data.jsonl, one JSON object per line:
  {"instruction": "...", "output": "<path>\\n```jsx\\n...\\n```"}
which is exactly the schema train.py / train_unsloth.py expect.

Each example targets ONE polished page/component (roughly 800-2500 tokens)
rather than a whole multi-file project - this keeps training sequences
short enough for your RTX 3050's 4GB VRAM while still teaching the visual
style comprehensively (training sequence length and inference context
length are independent).
"""
import os
import re
import sys
import json
import time
import random
import argparse
import threading
import traceback
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

from dotenv import load_dotenv

# .env lives at the project root (one level up from backend/), not next to
# this script - load_dotenv() with no path doesn't reliably find it when run
# from backend/, so point it there explicitly.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from google import genai

BUSINESS_TYPES = [
    "CRM", "e-commerce storefront", "real estate listing site", "analytics dashboard",
    "project management tool", "SaaS landing page", "admin panel", "social media analytics",
    "booking system", "help desk portal", "inventory management", "billing system",
    "LMS", "healthcare patient portal", "restaurant ordering system", "fitness tracker",
    "email marketing dashboard", "HR management system", "event management platform",
    "weather dashboard", "survey platform", "crypto portfolio tracker",
    "document management system", "chat application", "task management app",
    "podcast platform", "job board", "recipe sharing site", "music streaming app",
    "car rental service", "hotel booking site", "freelancer marketplace",
    "online course platform", "expense tracker", "meeting scheduler",
    "logistics tracking dashboard", "warehouse management", "point-of-sale system",
    "subscription box service", "legal case management", "veterinary clinic system",
]

COMPONENT_KINDS = [
    "KPI stat-card row (4 cards with values, deltas, icons)",
    "searchable data-table section with column filters",
    "detail card with header, avatar, and metadata rows",
    "settings panel with multiple collapsible form sections",
    "multi-step wizard form (single step component with progress header)",
    "line/bar chart panel with legend and range toggle",
    "kanban column with task cards and quick-add",
    "pricing tier card with feature checklist",
    "login/signup form card with social buttons",
    "notification dropdown panel with unread badges",
    "modal dialog for creating an item (form + validation styling)",
    "activity feed list with timestamps and icon bullets",
    "profile header with stats row and follow button",
    "empty-state card with illustration icon and CTA",
    "horizontal filter-chip bar with active states",
    "toast notification stack component",
]

STYLE_RULES = """Follow these style rules exactly:
- Use gradient backgrounds (e.g. bg-gradient-to-br from-indigo-500 via-purple-500 to-pink-500)
- Use glassmorphism: backdrop-blur-xl bg-white/5 border border-white/10
- Add smooth transitions: transition-all duration-300, hover:scale-[1.02], hover:shadow-xl
- Use lucide-react for every icon (import { X } from 'lucide-react')
- Dark theme: bg-slate-900 or bg-gray-950 background, text-slate-100 text
- Card layouts with rounded-xl or rounded-2xl and generous padding
- Responsive: sm:/md:/lg: breakpoints
- Loading skeletons use animate-pulse
- Professional color palette: indigo/cyan/violet primary, emerald=success, amber=warning, rose=error
- Every component must be FULLY implemented - no "..." or "// TODO"
- Output as exactly one file: a path in backticks on its own line, then a fenced code block
- For every `import X from "./path"` you write, that path must be a file you'd plausibly
  have already created in the project (name components/pages consistently, e.g.
  `src/components/StatCard.jsx`, `src/pages/Dashboard.jsx`)
"""

MODEL = "gemini-3.6-flash"

# Free-tier request quotas are PER MODEL per day (measured 2026-09-17:
# gemini-3.6-flash free tier = 20 req/day; 2.5-flash retired for new users).
# On 429 the generator rotates down this chain, multiplying the daily budget.
MODELS = [
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-3.7-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
]
_current_model = 0
_model_lock = threading.Lock()

SYSTEM_INSTRUCTION = (
    "You are an elite front-end developer producing polished, production-quality "
    "React + Tailwind CSS components. You write dense, compact, information-rich "
    "components and ALWAYS respect the requested size limit. Output exactly ONE file: "
    "its path in backticks on its own line, immediately followed by a fenced code block "
    "with the full code. No commentary before or after."
)

FILE_PATTERN = re.compile(r"`(.+?\.(?:jsx?|tsx?|css))`\s*\n```[\w]*\n([\s\S]*?)```")

MAX_CONSECUTIVE_FAILURES = 15  # allow some natural failures before stopping

# TRAINABLE SIZE STRATEGY (research findings, 2026-09-17):
# Both v1 and v2 teacher runs produced 6-16k-token examples while the trainer
# ran at MAX_SEQ_LENGTH=1024 -- i.e. EVERY example ever trained on was cut
# mid-code (the root cause of the broken-entry-point/artifact pathologies).
# Soft size limits don't work (flash ignores them at 19-24k chars); hard
# max_output_tokens truncates mid-code. What works: SINGLE-COMPONENT SCOPE --
# the teacher's natural floor is ~3.5k chars/component, ceiling ~12k, which
# fits a 3072-token training window (chars/4 + template) on 4GB VRAM.
SCOPE_RULE = (
    "SCOPE: exactly ONE React component (the default export). NOT a full page: "
    "no sidebar, no page shell, no navigation, no multiple screens. The named "
    "component only, with its own small mock-data array inline. Target 80-200 "
    "lines of code."
)
MAX_CODE_CHARS = 13000  # post-generation gate: ~3250 tokens + template fits MAX_SEQ_LENGTH=3584
# (teacher's natural component ceiling measured at ~12.5k chars on modal forms)


def build_prompt() -> tuple[str, str]:
    business_type = random.choice(BUSINESS_TYPES)
    component_kind = random.choice(COMPONENT_KINDS)
    user_prompt = f"Build the {component_kind} for a {business_type}."
    return business_type, user_prompt


def generate_one_rotating(client, user_prompt: str, business_type: str = "",
                          corrective_note: str = "") -> tuple[tuple[dict | None, str], str]:
    """Call generate_one, rotating through MODELS on per-model quota (429)
    or persistent high-demand (503). Returns ((example, raw), model_used).

    Raises RuntimeError when every model in the chain is exhausted."""
    global _current_model
    last_err: Exception | None = None
    tries_on_current = 0
    while 0 <= _current_model < len(MODELS):
        model = MODELS[_current_model]
        try:
            return generate_one(client, model, user_prompt, business_type, corrective_note), model
        except Exception as e:
            s = str(e)
            last_err = e
            if "429" in s or "RESOURCE_EXHAUSTED" in s:
                with _model_lock:
                    if MODELS[_current_model] == model:  # another worker may have rotated first
                        _current_model += 1
                        tries_on_current = 0
                        print(f"[quota] {model} exhausted for today -> rotating to "
                              f"{MODELS[_current_model] if _current_model < len(MODELS) else 'NOTHING LEFT'}")
                continue
            if "503" in s or "UNAVAILABLE" in s:
                tries_on_current += 1
                if tries_on_current >= 3:
                    with _model_lock:
                        if MODELS[_current_model] == model:
                            _current_model += 1
                            tries_on_current = 0
                            print(f"[demand] {model} overloaded -> rotating")
                    continue
                time.sleep(15)
                continue
            raise  # anything else (auth, network) is a real failure
    raise RuntimeError(f"All teacher models exhausted or unavailable. Last error: {last_err}")


def extract_file(text: str) -> tuple[str, str] | None:
    m = FILE_PATTERN.search(text)
    if not m:
        return None
    path, content = m.group(1).strip(), m.group(2).strip()
    if len(content) < 200:
        return None
    return path, content


def generate_one(client, model: str, user_prompt: str, business_type: str = "",
                 corrective_note: str = "") -> tuple[dict | None, str]:
    """Returns (example_or_None, raw_response_text) - raw text is always
    returned so callers can show it on failure instead of guessing blind."""
    prefix = f"{corrective_note}\n\n" if corrective_note else ""
    resp = client.models.generate_content(
        model=model,
        config={"system_instruction": SYSTEM_INSTRUCTION, "temperature": 0.85},
        contents=f"{prefix}{SCOPE_RULE}\n\n{user_prompt}\n\n{STYLE_RULES}",
    )
    text = resp.text or ""
    extracted = extract_file(text)
    if extracted is None:
        return None, text
    path, content = extracted
    if len(content) > MAX_CODE_CHARS:
        return None, f"OVERSIZE (gate: >{MAX_CODE_CHARS} chars, got {len(content)})\n{text[:300]}"
    path, content = extracted
    example = {
        "instruction": f"Build the {user_prompt[9:]}",
        "output": f"`{path}`\n```jsx\n{content}\n```",
        "business_type": business_type,
    }
    return example, text


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=150)
    parser.add_argument("--out", default="./training_data.jsonl")
    parser.add_argument("--workers", type=int, default=1,
                        help="parallel Gemini calls (3 keeps well under free-tier RPM)")
    args = parser.parse_args()

    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        env_path = Path(__file__).resolve().parent.parent / ".env"
        raise SystemExit(
            f"GEMINI_API_KEY not found (checked {env_path} and the environment).\n"
            f"Get a free key (no credit card) at https://aistudio.google.com/apikey\n"
            f"then open {env_path} in a text editor and add this line to it:\n"
            f"  GEMINI_API_KEY=your-key-here\n"
            f"(this is a line to add INSIDE the .env file, not a command to run in the terminal)"
        )

    print(f"Using API key ending in ...{api_key[-4:]}")
    client = genai.Client(api_key=api_key)

    # One sanity-check call before the real loop, with the FULL error and raw
    # response shown if it fails - this is the step that was silently
    # failing 150+ times before with nothing printed. If this one call
    # doesn't work, nothing else will either, so we stop here instead of
    # burning through retries.
    print("Running a single test generation to verify everything works...")
    test_example = test_raw = None
    for attempt in range(1, 4):  # transient 503s ("high demand") happen; retry
        try:
            (test_example, test_raw), _m = generate_one_rotating(
                client, "Build the create-new-lead modal dialog for a CRM: form fields, validation styling, cancel/save buttons.", "CRM",
                "" if attempt == 1 else "Your previous response exceeded the size limit and was rejected. Be compact.")
            if test_example is not None:
                break
            # Gate rejection (oversize/unparseable) falls through to the retry below
        except Exception:
            if attempt == 3:
                print("\n--- TEST CALL FAILED (3 attempts) ---")
                traceback.print_exc()
                print("------------------------")
                print(
                    "\nThe API call itself raised an exception - this is "
                    "almost always an invalid/expired API key, no internet access, or the "
                    "'google-genai' package not being installed correctly. Fix that and re-run."
                )
                sys.exit(1)
            print(f"  attempt {attempt} failed (likely transient), retrying in 20s...")
            time.sleep(20)
    if test_example is None:
        print("\n--- TEST CALL SUCCEEDED BUT PARSING FAILED ---")
        print("Raw response from Gemini:\n")
        print(test_raw[:2000])
        print("\n-----------------------------------------------")
        print(
            "The API call worked, but the response didn't match the expected "
            "`path`\\n```code``` format, so no file could be extracted. If the raw "
            "response above looks reasonable but the code fence style differs, adjust "
            "FILE_PATTERN in this script to match what you're actually seeing."
        )
        sys.exit(1)

    print(f"Test generation succeeded: {test_example['output'].splitlines()[0]}")
    print("Proceeding with full run...\n")

    out_path = Path(args.out)
    # Preserve any existing examples (the 20-example v1 set): the generator
    # opens in "w" mode, which would silently discard them. Seed the new file
    # with everything already there, then dedupe at write time on the exact
    # instruction text so re-runs can't create duplicates.
    existing = []
    if out_path.exists():
        with out_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    existing.append(json.loads(line))
                except json.JSONDecodeError:
                    print(f"  warning: skipped corrupt line in existing {out_path}")
    if existing:
        print(f"Preserving {len(existing)} existing examples from {out_path}")
    seen_instructions = {ex.get("instruction", "") for ex in existing}

    written = len(existing)
    consecutive_failures = 0
    stop = threading.Event()
    lock = threading.Lock()  # guards written, seen_instructions, file handle, failures

    with out_path.open("w", encoding="utf-8") as f:
        for ex in existing:
            f.write(json.dumps(ex) + "\n")
        f.flush()

        def worker(worker_id: int) -> None:
            nonlocal written, consecutive_failures
            while not stop.is_set():
                with lock:
                    if written >= args.count:
                        return
                try:
                    business_type, user_prompt = build_prompt()
                    (example, raw), _used = generate_one_rotating(client, user_prompt, business_type)
                    # Corrective retry: the teacher ignoring the size limit is the
                    # dominant failure; one reinforced retry recovers most of them.
                    if example is None and raw.startswith("OVERSIZE"):
                        print(f"[w{worker_id}] oversize, retrying with correction...")
                        (example, raw), _used = generate_one_rotating(
                            client, user_prompt, business_type,
                            "REMINDER: your previous version was far too long and was rejected. "
                            "Output ONE screen section only - omit extra pages, side routes, "
                            "and duplicated sections. Stay under the size limit.")
                except Exception as e:
                    with lock:
                        consecutive_failures += 1
                        n = consecutive_failures
                        print(f"[w{worker_id}] error: {e}")
                        if n >= MAX_CONSECUTIVE_FAILURES:
                            stop.set()
                            print(f"\n{n} consecutive failures - stopping.")
                            traceback.print_exc()
                    time.sleep(30 if ("429" in str(e) or "RESOURCE_EXHAUSTED" in str(e)) else 5)
                    continue

                if example is None:
                    with lock:
                        consecutive_failures += 1
                        n = consecutive_failures
                        print(f"[w{worker_id}] skipped (unparseable). raw: {raw[:200]!r}")
                        if n >= MAX_CONSECUTIVE_FAILURES:
                            stop.set()
                            print(f"\n{n} consecutive skips - stopping.")
                    continue

                with lock:
                    consecutive_failures = 0
                    if example["instruction"] in seen_instructions:
                        print("  duplicate instruction, skipping")
                        continue
                    if written >= args.count:
                        return
                    seen_instructions.add(example["instruction"])
                    f.write(json.dumps(example) + "\n")
                    f.flush()
                    written += 1
                    print(f"[{written}/{args.count}] {example['instruction'][:80]}")
                time.sleep(3.0)  # spacing on top of ~100s call time; 3 workers ~2 RPM

        if args.workers <= 1:
            worker(0)
        else:
            with ThreadPoolExecutor(max_workers=args.workers) as pool:
                list(pool.map(worker, range(args.workers)))

    print(f"\nWrote {written} real training examples to {out_path}")


if __name__ == "__main__":
    main()
