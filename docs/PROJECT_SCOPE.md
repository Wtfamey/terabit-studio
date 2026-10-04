# Terabit Studio — Project Scope & Technical Roadmap

*Living document. Last updated: 2026-08-07.*

## 1. Executive summary

Terabit Studio is a **local-first AI application generator**: a fine-tuned small LLM
(Qwen2.5-Coder-7B + LoRA), served entirely on the user's own machine via
llama.cpp/Ollama, generates multi-file React + Vite + Tailwind applications
from a natural-language prompt, with a live in-browser preview, a Monaco-based
code editor, and a file explorer — the same interaction model as Bolt.new,
v0.dev, or Lovable, but with **no cloud dependency for generation**.

The current build is a working prototype with three known reliability gaps
(preview consistency, model-selection wiring, output quality/ambition) that
are being actively fixed. This document defines what the project actually is,
what "done" realistically means for a first real version, and what's
explicitly out of scope so effort stays focused.

## 2. Problem statement & motivation

Cloud-hosted AI app builders (Bolt.new, v0, Lovable, Replit Agent, Emergent)
are excellent but come with three structural costs: every prompt and every
line of generated code goes to a third party; usage is metered/subscription;
and they don't work offline or in data-sensitive environments. A local-first
equivalent trades some raw model quality for privacy, zero marginal cost per
generation, offline capability, and full ownership of the model weights —
a legitimate, differentiated position, not just "the free version of Bolt."

The central engineering challenge this creates: closing the quality gap
between a 7-14B local model and a frontier hosted model (GPT-4/Claude-class)
well enough that the trade-off is worth it. That gap is real and won't fully
close — the goal is "good enough for real prototyping work," not parity.

## 3. Target hardware & users

- **Primary target hardware:** mid-to-high gaming laptops — 8-16GB VRAM
  (RTX 3060/4060/4070 mobile class) up to 16-24GB (RTX 4080/4090 mobile),
  16-32GB system RAM. This is a *design constraint*, not a nice-to-have: it's
  what determines the model tier (Q4_K_M 7B fits comfortably in 8GB; 14B
  needs ~10-12GB; 32B is a stretch goal for the 16GB+ tier only).
- **Users:** indie developers and students prototyping quickly without cloud
  AI spend, small teams wanting an internal tool generator that never sends
  code off-machine, and privacy/compliance-sensitive users who can't use
  cloud AI tools at all.

## 4. Redefining "done" — the current goal is too broad to be achievable

This needs to be said plainly: **"generate a full-fledged SaaS" — literally
interpreted as a working backend, database, multi-tenant auth, and billing —
is not a realistic single-prompt output for any current model, local or
frontier-hosted.** Bolt, v0, and Lovable don't do this either; when they
offer "backend," it's by wiring the generated front-end to a separate,
already-built hosted service (typically Supabase), not by having the LLM
invent a backend from scratch. Chasing the literal version of that goal will
keep the project feeling like it's failing even as the actual generation
pipeline improves, because the target itself is unbounded.

**Redefined v1 target (achievable and still genuinely valuable):**

> Generate a polished, fully-interactive **front-end** for a real business
> application archetype (dashboard, admin panel, CRM-style tool, e-commerce
> storefront + admin, booking/scheduling tool, analytics dashboard, etc.) —
> multi-page or multi-section, styled to a real "funded startup" visual bar,
> driven by realistic client-side state and seeded mock data — from one
> prompt, entirely on local hardware, in under a minute or two.

This is a legitimate, sellable, demo-able product on its own, and it's what
the training data and prompt work already in this repo are actually aimed
at. "Full-fledged SaaS" is the *marketing* framing to aspire to later once a
backend-generation phase (§8, Phase 3) is deliberately scoped — it shouldn't
be the bar v1 is silently judged against.

## 5. Non-goals (explicit, v1)

- Real backend/database code generation with actual persistence
- Multi-tenant auth, billing, payments
- Production deployment/hosting pipeline
- Guaranteed reliability across *arbitrary* app domains — prioritize the
  business-app archetypes above before generalizing further

## 6. System architecture (current)

- **Backend:** FastAPI (Python), SQLite for sessions/auth/uploads
  (`backend/main.py`, `backend/database.py`, `backend/auth.py`)
- **Model serving:** Ollama or llama.cpp/`llama-server`, accessed via an
  OpenAI-compatible client (`backend/model_service.py`); base model
  Qwen2.5-Coder-7B-Instruct (Q4_K_M GGUF), fine-tuned via a LoRA adapter
  trained with Unsloth
- **Generation pipeline:** prompt template (`backend/rag_engine.py`) →
  completion → truncation-aware continuation loop
  (`generate_complete_response` in `main.py`) → tolerant multi-format file
  parser (handles both strict and loosely-fenced model output)
- **Preview pipeline** (`backend/preview_builder.py`), three tiers, each a
  fallback of the last:
  1. Real local build: the project's own `esbuild` + Tailwind CLI
     (offline, highest fidelity, depends on the local Node toolchain being
     reachable from the Python process)
  2. In-browser bundling: Babel Standalone (`transform-modules-commonjs`) +
     a lazy Node-style `require()` + esm.sh for arbitrary npm packages
     (needs internet in the *browser*, not the backend — independent
     failure mode from tier 1, which is why it exists as a safety net)
  3. Static file listing (last resort — no working preview, just shows
     what was generated)
- **Frontend:** React + Vite + Tailwind, Monaco editor, chat-driven
  Build/Plan/Preview/Code UI (`frontend/src/pages/Builder.tsx`)

## 7. Capability matrix

| Capability | Status |
|---|---|
| Multi-file React app generation | Working |
| Live preview - local toolchain (tier 1) | Unreliable - failing silently, root cause not yet confirmed (see Known Issues) |
| Live preview - CDN bundler (tier 2) | Working; just restored as an active fallback (was previously unreachable dead code) |
| Fine-tuned model actually being served | Wiring in place (`MODEL_NAME`/`LORA_PATH`, Ollama `ADAPTER` Modelfile); needs verification via `/api/health` |
| Visual quality ("funded startup" bar) | Prompt restored this session; not yet evaluated against real output |
| Iterative editing with project context (RAG) | Implemented (`retrieve_project_context`); not yet stress-tested |
| Export/download | Present; not audited this session |
| Multi-page navigation (`react-router-dom`) | Supported by prompt; not guaranteed per-generation |
| Backend/auth/billing generation | Out of scope (§5) |

## 8. Roadmap

- **Phase 0 - Reliability (current focus):** preview renders *something*
  functional on every generation; fine-tuned model connection verified, not
  assumed; generation doesn't silently truncate.
- **Phase 1 - Quality:** a small fixed eval set (30-50 prompts spanning the
  business-app archetypes in §4), scored for structural success (does it
  render), visual quality (rubric or LLM-judge), and compared base model vs
  fine-tuned model, to know whether fine-tuning is actually earning its
  keep and where it isn't.
- **Phase 2 - UX polish:** resizable panes, streaming file-tree during
  generation, visible error states (the tier-2/tier-3 fallback distinction
  should be visible in the UI, not just inferred from a blank screen).
- **Phase 3 - Scope expansion (deliberate, not implicit):** optional real
  backend generation against a local SQLite-backed API, a template library,
  multi-model support so users on 16GB+ VRAM can opt into a 14B/32B model.

## 9. Success metrics (for Phase 1 onward)

- % of generations producing a working preview on first try
- Time-to-first-preview
- Visual quality score against a fixed rubric
- Actual VRAM/hardware envelope required per model tier, measured, not
  estimated

## 10. Known issues (as of this session)

- **Preview tier 1** (`_try_local_bundle`) fails on at least the case tested
  this session, for an unconfirmed reason - `esbuild` and the Tailwind CLI
  both exist at the expected paths, so the failure is inside the subprocess
  execution itself (PATH resolution from a background job, a Windows path
  with a space in `super project`, a Tailwind CLI flag mismatch, or a
  timeout). The `except` block now prints `stderr` from the failed
  subprocess - next step is capturing that output with the backend run
  directly in a foreground terminal (not via `Start-Job`) to get the real
  error message.
- **Training data volume:** the current LoRA (`checkpoint-30`) was trained
  on a small dataset for a short run. The sampled example is genuinely
  high quality, but more examples + more steps are needed before expecting
  the fine-tune to meaningfully outperform prompting alone.
