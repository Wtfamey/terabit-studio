# Engineering Changelog

Chronological record of changes made to the codebase across this set of
sessions, grouped by the problem each one addressed. File paths are relative
to the project root.

## Session 1 — Preview rendering, generation truncation, UI audit

**Problem:** live preview showed a fallback file listing instead of the
rendered app; generated output was frequently broken/truncated.

- `backend/preview_builder.py` — full rewrite of the in-browser bundler.
  Replaced hand-written regex-based `import`/`export` rewriting (which broke
  on multi-line imports, `export * from`, comments in import lines, etc.)
  with Babel Standalone's official `transform-modules-commonjs` plugin,
  paired with a lazy Node-style `require()` implemented in the browser.
  Added: resolution of *any* bare package import via esm.sh at runtime
  (previously only 4 packages were ever registered); image import handling
  (placeholder URLs); CSS Modules support (bundled + identity class map);
  JSON import support; a visible in-iframe error overlay fed by
  `window.onerror`/`unhandledrejection`; best-effort forwarding of the
  project's own `tailwind.config.js` `theme` block into the preview.
- `backend/model_service.py` — added `generate_response_with_status`,
  exposing the completion's `finish_reason` so callers can detect
  truncation (`"length"`) instead of silently accepting cut-off output.
- `backend/main.py` — added `generate_complete_response`, a wrapper that
  detects truncation and automatically requests a continuation instead of
  shipping incomplete code, shrinking the token ask on each continuation
  round to stay inside the context window. Wired into `/api/generate`.
- Reviewed frontend (`Builder.tsx`, `Home.tsx`, `PreviewFrame.tsx`) — found
  already reasonably close to a Bolt/v0-style layout; no changes made this
  session, noted concrete polish items (resizable panes, streaming
  file-tree, display font) for a later UI pass.

## Session 2 — Fine-tuned model not loading; output quality regression

**Problem:** the fine-tuned LoRA never actually got served; generated output
had become minimal/generic rather than the intended "premium SaaS" style.

- `run_local.ps1` — removed hardcoded `$env:MODEL_PATH` / `N_CTX` /
  `N_GPU_LAYERS` overrides. These were set *before* the Python process
  started, and since `python-dotenv` never overrides an already-set
  environment variable, they silently beat whatever `.env` specified on
  every run — this was the actual reason the fine-tune never loaded, and
  `N_CTX` being forced down to 8192 was a likely contributor to the
  "preview works sometimes" intermittency (context overflow on larger
  prompts).
- `backend/model_service.py` — added `LORA_PATH` support to
  `start_server()`'s `llama-server` launch command (`--lora` flag), for the
  case where `llama-server` is run directly rather than via Ollama.
- `.env` (root) — documented and wired `MODEL_NAME` (which Ollama model tag
  to request) and `LORA_PATH` (for the `llama-server` + `--lora` path);
  fixed the precedence story between the root `.env` and `backend/.env`.
- `backend/.env` — removed a broken relative `MODEL_PATH` (resolved to a
  nonexistent `backend/models/...`) and added a comment clarifying that
  `zenith/.env` is authoritative for model selection.
- `models/Modelfile` (new) — an Ollama Modelfile (`FROM` the base GGUF +
  `ADAPTER` the LoRA GGUF) so the fine-tune can actually be attached to the
  base model via `ollama create terabit-finetuned -f Modelfile`, since the
  existing fine-tuned artifact (`qwen2.5-7b-finetuned-lora.gguf`, ~40MB) is
  a LoRA adapter, not a standalone merged model, and can't be loaded on its
  own.
- `backend/main.py` — `/api/health` now reports `model_name`, `model_path`,
  `lora_path`, and `lora_configured`, so the active model configuration can
  be verified directly instead of inferred from logs.
- `backend/rag_engine.py` — the generation system prompt had been rewritten
  at some point to explicitly cap scope ("small runnable app," "only these
  5 files," "prefer a single-page experience") with `max_tokens` capped at
  4200/2600. Restored a compact visual-quality checklist (Tailwind CDN,
  gradients/glassmorphism, icons, populated seed data, responsive layout)
  and removed the file-count/single-page ceiling, while keeping the
  "finish every file completely" discipline that made the leaner prompt
  more reliable in the first place.
- `backend/main.py` — `max_tokens` raised back up (6000 create / 3200 edit,
  from 4200/2600) with `max_continuations=2`, balanced against the
  restored (now larger) `N_CTX`.
- User completed `ollama create terabit-finetuned -f Modelfile` and set
  `MODEL_NAME=terabit-finetuned` in `.env`.

## Session 3 — Preview still inconsistent after model fix

**Problem:** a generation with 3 files (`package.json`, `index.html`,
`src/main.jsx`) rendered the static file-listing fallback instead of a live
preview.

- Found that `backend/preview_builder.py` had been further modified (by the
  user, between sessions) to add a first-choice **local build tier**
  (`_try_local_bundle`): compiling the generated project with the project's
  own installed `esbuild` and Tailwind CLI via subprocess calls, for higher
  fidelity and offline operation. Good idea, but `build_preview_html` had
  been wired so that if this tier failed *for any reason*, it jumped
  straight to the static file-listing fallback — silently skipping the
  entire CDN/Babel bundler from Session 1, which was still present in the
  file but had become unreachable dead code.
- Confirmed `esbuild` and the Tailwind CLI both exist at the exact paths
  `_try_local_bundle` checks, so the failure is happening inside the actual
  subprocess execution, not a missing-dependency guard. Root cause not yet
  confirmed - see `docs/PROJECT_SCOPE.md` §10 (Known Issues).
- `backend/preview_builder.py` — restructured into an explicit three-tier
  fallback (`build_preview_html` → `_try_local_bundle` →
  `_build_cdn_preview` → `_build_fallback_preview`), each tier a strict
  fallback of the last, so a tier-1 failure degrades to a still-functional
  tier-2 preview instead of a non-functional file listing. Also improved
  the failure log to include the subprocess's `stderr`, to make the next
  debugging pass actionable.

## Session 4 - Code review pass; SEAL self-adaptation scoping

**Problem:** asked whether to implement SEAL (Self-Adapting Language
Models) on the local model, framed as both a capability improvement and a
research angle.

- Researched the actual SEAL paper (arXiv:2506.10943) and reference
  implementation rather than relying on the term alone - confirmed it
  requires an RL outer loop where each iteration fine-tunes and evaluates
  hundreds of candidate "self-edits" (the reference implementation states
  2 A100/H100 GPUs), which is fundamentally incompatible with this
  project's gaming-laptop hardware target, not just a matter of scaling
  down.
- Wrote `docs/adr/0001-seal-inspired-self-adaptation.md` - decided against
  full SEAL, in favor of a scoped-down pipeline that keeps SEAL's core idea
  (the model participates in producing its own training signal) while
  dropping the RL loop, using real user edit/correction requests as a free
  reward signal instead.
- Wrote `docs/SEAL_SELF_ADAPTATION_DESIGN.md` - the build spec for that
  pipeline: capture corrections during the existing edit-operation path,
  batch them into the existing `training_data.jsonl`/`train_unsloth.py`
  pipeline, gate promotion with a new fixed eval harness. Not yet
  implemented - this is a design, not code, pending Phase 1 groundwork
  (`docs/PROJECT_SCOPE.md` §8).
- Did a focused code review of `backend/preview_builder.py` (the most
  recently and heavily modified file) and found a real bug in
  `_try_local_bundle`: the Tailwind CLI's `--content` glob was built from
  an absolute `pathlib.Path` on Windows, producing backslashes
  (`...\**\*.{...}`). Tailwind's glob matcher does not reliably treat that
  as a recursive wildcard, so it was very likely matching zero files -
  meaning this tier could *succeed* (exit 0, no exception, tier-2 fallback
  never triggered) while producing a preview with only Tailwind's unstyled
  preflight CSS and no utility classes at all. This is a plausible direct
  contributor to the "lame, basic-looking" output being reported, on any
  generation where tier 1 succeeded. Fixed by writing a minimal
  `tailwind.config.js` with a relative, forward-slash content glob into the
  temp build directory when the model didn't generate its own, and
  removing the broken `--content` flag in favor of letting Tailwind read
  that config normally.

## Not yet done / carried forward

- Confirm the actual cause of `_try_local_bundle` still failing after the
  Tailwind config fix, if it does (run the backend in a foreground
  terminal, not via `Start-Job`, to see the stderr-inclusive error log).
- Build the Phase 1 eval set described in `docs/PROJECT_SCOPE.md` to
  measure whether the fine-tune and restored prompt are actually producing
  the intended quality bar, rather than judging by spot-checking. This is
  now also a prerequisite for `docs/SEAL_SELF_ADAPTATION_DESIGN.md`.
- Implement `backend/self_edits.py` capture (Session 4 design, not yet
  code).
- UI polish pass (resizable panes, streaming file-tree, error-tier
  indicator in the Preview toolbar) - scoped but not started.
