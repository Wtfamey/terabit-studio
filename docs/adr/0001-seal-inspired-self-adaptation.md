# ADR 0001: Adopt a SEAL-*inspired* self-curation loop, not full SEAL

**Status:** Proposed
**Date:** 2026-08-07
**Deciders:** project owner

## Context

SEAL (*Self-Adapting Language Models*, Zweiger et al., MIT, arXiv:2506.10943,
June 2025) is a framework where a model generates its own fine-tuning data
and update directives ("self-edits"), applies them via LoRA SFT, evaluates
the result on a downstream task, and is trained via reinforcement learning
(specifically ReST^EM - rejection sampling + SFT on the samples that improved
performance) to get better at proposing self-edits over time. One of the
paper's two demonstrated domains (knowledge incorporation on SQuAD) used
Qwen2.5-7B — the same base model this project already uses.

The question on the table: should Terabit Studio adopt SEAL so the local
model keeps improving from real usage, and would that be a good research
angle.

**The compute reality, checked against the source:** the official
reference implementation (github.com/Continual-Intelligence/SEAL) states
"all experiments can be run with 2 A100/H100 GPUs" — roughly 160GB of GPU
memory. The paper's own training loop, per outer iteration, samples a
minibatch of 50 contexts × 5 self-edits each = 250 candidate self-edits,
and *each one requires actually running a LoRA fine-tuning pass and an
evaluation* before the RL step can score it. This is the loop being asked
about — not a single fine-tune, but hundreds of fine-tune-and-evaluate
cycles per outer iteration, repeated over multiple iterations.

This is fundamentally mismatched with the project's own stated constraint
(`docs/PROJECT_SCOPE.md` §3): mid-to-high gaming laptops, 8-24GB VRAM.
Running the RL outer loop as published is not a "harder version" of what
this project already does — it's roughly two orders of magnitude more
compute than the hardware target allows for.

## Decision

**Do not implement SEAL's RL outer loop (ReST^EM over sampled self-edits) on
this project's target hardware.** It is not a scoping decision that can be
made smaller by degree — the mechanism itself requires a compute tier this
project has explicitly ruled out as a target.

**Do implement a SEAL-*inspired* self-curation pipeline instead** — keeping
the part of SEAL's idea that transfers (the model participates in producing
its own training signal) and dropping the part that doesn't (RL over
hundreds of trial fine-tunes). Concretely:

1. The model generates a **self-edit** (a rationale + a corrected/rewritten
   example) whenever a real signal is available for free — specifically,
   when a user issues an edit/correction request in the Builder (the
   `operation == "edit"` path already implemented in `rag_engine.py`).
   The correction itself *is* the reward signal - a human already judged
   the first output insufficient - so there is no RL loop to run at
   inference time; the "reward" is implicit in the user having asked for a
   change.
2. Self-edits are written to a queue (a new `backend/self_edits.jsonl`,
   analogous to the existing `training_data.jsonl`), not applied
   immediately - no online/per-request weight updates.
3. Periodically (manually triggered for now, per Phase 1 in
   `docs/PROJECT_SCOPE.md`), the best-formed self-edits are batched into a
   LoRA fine-tuning round using the **existing** `train_unsloth.py`
   pipeline - no new training infrastructure needed, just a new data
   source feeding the one that already exists.
4. A held-out eval set (Phase 1's planned 30-50 fixed prompts) gates
   whether a new checkpoint actually gets promoted to
   `MODEL_NAME=terabit-finetuned` - this substitutes for SEAL's per-edit RL
   reward with a single, cheap, offline batch evaluation instead of
   hundreds of online ones.

This gets the specific thing that matters for this product - the model
gets better from real usage without hand-curating a dataset - without the
part that doesn't fit the hardware target.

## Consequences

- **What this buys:** a genuinely differentiated, defensible feature
  ("your local model improves from your own corrections, entirely on your
  machine") that's actually buildable on the stated hardware, and reuses
  100% of the existing fine-tuning pipeline.
- **What this gives up vs. real SEAL:** no learned policy for *which*
  self-edits are most valuable (SEAL's RL loop is precisely what learns
  that). This pipeline instead uses rejection-sampling-once - keep a
  self-edit if the corrected version scores better on the eval set than
  the batch without it, rather than learning a general self-edit-writing
  policy. This is a reasonable, well-precedented simplification (it's
  structurally the "SFT on the good samples" half of ReST^EM without the RL
  half), but it means the system won't get better at writing self-edits
  over time the way full SEAL's policy does.
- **Research framing this supports:** "how much of SEAL's benefit survives
  when the RL loop is replaced with free, real-usage-driven rejection
  sampling, under a hard consumer-hardware compute budget" is a real,
  answerable, and not-yet-published question — see
  `docs/NOVELTY_AND_IP_ASSESSMENT.md` and
  `docs/SEAL_SELF_ADAPTATION_DESIGN.md`.
- **What would change this decision:** if VRAM/compute targets are
  loosened (e.g., an optional cloud-training mode, decoupled from the
  local-inference promise), revisit running actual SEAL-style RL as an
  opt-in "pro" training mode rather than the default path.

## Alternatives considered

- **Full SEAL as published:** rejected — compute mismatch, see Context.
- **Do nothing (static fine-tune only, as today):** leaves real value on
  the table; the project already collects exactly the signal (user
  corrections) SEAL-style self-editing wants, and it's currently discarded.
- **Full online/per-request weight updates (true test-time adaptation):**
  rejected for now — even a small number of gradient steps per request
  would add real latency to every single generation on hardware that's
  already running inference; revisit only after Phase 0 reliability work
  (`docs/PROJECT_SCOPE.md`) is solid.
