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
import traceback
from pathlib import Path

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
    "main dashboard/overview page", "data table with filters and search",
    "detail/profile page", "settings page with multiple sections",
    "onboarding/wizard flow (single step shown)", "analytics page with charts",
    "kanban/board view", "pricing section", "landing page hero + features section",
    "login/signup form", "notification center dropdown", "modal/dialog for creating an item",
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

MODEL = "gemini-3.5-flash"

SYSTEM_INSTRUCTION = (
    "You are an elite front-end developer producing polished, production-quality "
    "React + Tailwind CSS components. Output exactly ONE file: its path in backticks "
    "on its own line, immediately followed by a fenced code block with the full code. "
    "No commentary before or after."
)

FILE_PATTERN = re.compile(r"`(.+?\.(?:jsx?|tsx?|css))`\s*\n```[\w]*\n([\s\S]*?)```")

MAX_CONSECUTIVE_FAILURES = 15  # allow some natural failures before stopping


def build_prompt() -> tuple[str, str]:
    business_type = random.choice(BUSINESS_TYPES)
    component_kind = random.choice(COMPONENT_KINDS)
    user_prompt = f"Build the {component_kind} for a {business_type}."
    return business_type, user_prompt


def extract_file(text: str) -> tuple[str, str] | None:
    m = FILE_PATTERN.search(text)
    if not m:
        return None
    path, content = m.group(1).strip(), m.group(2).strip()
    if len(content) < 200:
        return None
    return path, content


def generate_one(client, business_type: str, user_prompt: str) -> tuple[dict | None, str]:
    """Returns (example_or_None, raw_response_text) - raw text is always
    returned so callers can show it on failure instead of guessing blind."""
    resp = client.models.generate_content(
        model=MODEL,
        config={"system_instruction": SYSTEM_INSTRUCTION, "temperature": 0.9},
        contents=f"{user_prompt}\n\n{STYLE_RULES}",
    )
    text = resp.text or ""
    extracted = extract_file(text)
    if extracted is None:
        return None, text
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
    try:
        test_example, test_raw = generate_one(client, "CRM", "Build the main dashboard/overview page for a CRM.")
    except Exception:
        print("\n--- TEST CALL FAILED ---")
        traceback.print_exc()
        print("------------------------")
        print(
            "\nThe API call itself raised an exception (see traceback above) - this is "
            "almost always an invalid/expired API key, no internet access, or the "
            "'google-genai' package not being installed correctly. Fix that and re-run."
        )
        sys.exit(1)

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
    written = 0
    consecutive_failures = 0

    with out_path.open("w", encoding="utf-8") as f:
        # Write the test example too, no need to waste it
        f.write(json.dumps(test_example) + "\n")
        f.flush()
        written += 1

        while written < args.count:
            business_type, user_prompt = build_prompt()
            print(f"[{written + 1}/{args.count}] {user_prompt}")
            try:
                example, raw = generate_one(client, business_type, user_prompt)
            except Exception as e:
                consecutive_failures += 1
                print(f"  error: {e}")
                if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                    print(f"\n{consecutive_failures} failures in a row - stopping instead of "
                          f"grinding silently. Full traceback of the last error:")
                    traceback.print_exc()
                    sys.exit(1)
                is_rate_limit = "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e)
                time.sleep(30 if is_rate_limit else 5)
                continue

            if example is None:
                consecutive_failures += 1
                print(f"  skipped (couldn't parse a file from the response). Raw response:")
                print(f"  {raw[:300]!r}")
                if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                    print(f"\n{consecutive_failures} skips in a row - stopping. See raw "
                          f"responses above to figure out why parsing keeps failing.")
                    sys.exit(1)
                continue

            consecutive_failures = 0
            f.write(json.dumps(example) + "\n")
            f.flush()
            written += 1
            time.sleep(7.0)

    print(f"\nWrote {written} real training examples to {out_path}")


if __name__ == "__main__":
    main()
