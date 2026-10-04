# Terabit Studio — architecture, why it is this way, and how to get to Bolt/Lovable quality

Written 2026-10-02. Every number below was measured on this machine, not assumed.

---

## 0. The constraint that decides everything

| | measured |
|---|---|
| GPU | **NVIDIA GeForce RTX 3050 Laptop, 6 GB VRAM** |
| RAM | 15.7 GB |
| CPU | i7-13650HX, 14c / 20t |
| Live model | `terabit-finetuned-v3`, 7.6B, Q4_K_M, 4.7 GB — **spills to CPU** (4057 MB in VRAM of 5378 MB) |
| Full generation wall time | **1153 s (19 min) for 11 files** |

This is the single most important fact in this document. The advice floating
around the internet — "run Qwen2.5-Coder-32B on a 24 GB card" — **does not
apply to you.** A 14B Q4 needs ~9 GB and a 32B needs ~20 GB; neither fits in
6 GB, and falling back to CPU inference on 15.7 GB of RAM gives you single-digit
tokens per second, which is unusable for writing 4,000-token React files.

So: **model size is fixed by your hardware. You cannot out-scale Bolt or
Lovable, and neither can they out-scale you on cost.** You win or lose on
*architecture*. That is good news, because architecture is the part you own.

---

## 1. What the architecture actually is

`run_agent()` in `backend/agentic_generator.py` (3,013 lines) is a
**spec-less, single-pass, per-file generator wrapped in a deterministic
repair-and-verify shell.** Six stages:

| # | Stage | Module | Tokens? |
|---|---|---|---|
| 1 | Parse the user's prompt into a brief record | `main.extract_product_brief` | 0 |
| 2 | Pick a section skeleton for the trade | `domain_profiles.get_profile` | 0 |
| 3 | Pick a palette / typography pairing | `design_system.get_design` | 0 |
| 4 | **Ask the 7B for each file, one at a time** | `agentic_generator._file_messages` | all of them |
| 5 | Bundle (esbuild) + render smoke test + repair loop | `bundle_check`, `render_check`, ~20 fixers | a few |
| 6 | Last-resort curated scaffold if the bundle still fails | `scaffolds.py` | 0 |

Stages 1, 2, 3 and 6 are pure Python. **Stage 4 is the only place a model
runs.** That is the correct shape for this hardware — and it is the shape
Bolt and Lovable *also* use, except they put a frontier model in stage 4 and
you put a 7B.

### Why it is built this way (it is not accidental)

The comments in the file are a history of hard-won failures, and they are
worth reading before changing anything:

- `_file_messages` forces `App.jsx` to *import* its sections rather than
  inline them, because inlining blew the token cap and truncated the file.
- `bundle_check` alone is not trusted: esbuild happily accepts files that
  white-screen at runtime, so `render_check` actually executes the app with
  `react-dom/server`.
- ~20 mechanical fixers exist (`fix_duplicate_imports`, `fix_bare_icon_children`,
  `fix_lucide_imports`, `promote_tsx_files`, …) because a 7B gets these wrong
  constantly and it is cheaper to fix them with a regex than with a repair call.
- The fallback scaffolds exist because a beautiful working *generic* app beats
  a broken *specific* one.

**This is good engineering under a 6 GB budget.** The problem is not the
architecture. The problem is stage 1 and stage 4, below.

---

## 2. Root cause: why it "just produces templates"

### 2a. The training data is a template factory

`backend/training_data.jsonl`, measured:

- **88 examples.** That is the entire fine-tuning corpus.
- Average instruction length: **83 characters.** Average completion: **16,896 characters** (~4,200 tokens).
- 38 business types, and they are overwhelmingly dashboards and admin systems
  (CRM, logistics, POS, warehouse, HR, analytics, inventory, billing).
- **45 of 88 outputs contain the literal word "placeholder". 50 contain "Foo".
  56 contain "bar".** Two contain `Sarah Connor` / `Cyberdyne Systems`; two
  contain `John Doe`; two contain `Acme`.

So the objective the model was trained on is, literally:

> *given an 83-character generic instruction, emit a 4,000-token generic
> dashboard containing "placeholder" and Foo/bar seed data.*

Then it is asked to personalise. It was trained not to. **`bundle_ok` cannot
detect this** — a flawless generic page bundles perfectly. That is the whole
of "personalisation doesn't take place".

### 2b. The fine-tune also competes with your own brief

The 88 examples teach "ignore the brief, emit the archetype". Your stage-1
brief (name, trade, stated facts) is in the prompt, but the fine-tune's
learned prior is stronger than an instruction. Every defence you add at
stage 1 is partly fighting your own fine-tune.

### 2c. Stage 1 was silently empty for every non-English brief

`extract_product_brief` was 100% English regexes. For a Hinglish, romanised
Marathi or Devanagari brief it returned a *completely empty* record — no name,
no domain, no facts. The model was never told who the customer was. Fixed this
session; see §4.

---

## 3. Model selection: v3 was trained and never served

`backend/ab_v2_v3.py` + `backend/rescore_ab.py` A/B every Ollama tag on the
same personalised prompt. Scored by `personalisation_score` (new, §4.3):

| model | name | fact | clean | language | score |
|---|:--:|:--:|:--:|:--:|:--:|
| **`terabit-finetuned-v3`** | ✅ | ✅ | ✅ | **✅** | **1.00** |
| `terabit-finetuned-v2` | ✅ | ✅ | ✅ | ❌ | 0.75 |
| `qwen2.5-finetuned` | ✅ | ✅ | ✅ | ❌ | 0.75 |
| `qwen2.5:7b` (stock base) | ❌ | ❌ | ✅ | ❌ | 0.25 |
| `terabit-finetuned` (v1) | ❌ | ❌ | ✅ | ❌ | 0.25 |

**v3 is the only model that wrote the copy in the user's language** — its raw
output contains `"Mujhe contact karo"` and `"Web apps & APIs ke banaane ka
specialist"`. `.env` was pinned to v2, so v3 had never been served. Now fixed.

Also note: **the stock base model is the worst of the five.** The fine-tune is
doing real work. It just needs better data.

---

## 4. Shipped this session (all verified)

1. **`backend/multilingual.py` (new, ~500 lines).** Zero-token
   normaliser: script detection, register detection (Hinglish / Marathi /
   Hindi in Devanagari / Gujarati / Bengali in Roman script), an
   English "shadow" for the deterministic regexes, name capture, persona-fact
   capture, and business-noun / offering / CTA lexicons. Every substitution is
   gated on `is_multilingual()` so **English prompts travel the exact code
   path they always did.**
2. **`extract_product_brief` now returns `language`**, and fills name / facts /
   domain / offerings / CTA for non-English briefs. 5 non-English cases go from
   an empty record to a full one.
3. **Language hard constraint in the highest-salience position.** The rule was
   buried mid-prompt; the same model that ignored it there obeys it when it is
   the last line before the write instruction *and* in the system message
   (`probe_lang.py` proved capability, the 19-min run proved the burial).
4. **`personalisation_score()` + a personalisation gate** — the actual answer
   to "it just makes a template". Measures whether the user's name, facts and
   language reached the shipped copy, and buys **one bounded copy-only repair
   round (~2 min)** when the real name is missing or the hero is in the wrong
   language, instead of shipping a template after a 19-minute generation.
5. **v3 loaded**; `.env` and `.env.example` updated, and `.env` made
   authoritative so a stale shell cannot pin the model again.
6. **Tests: 58 + 22 checks green**, plus shell / fixers / import-fix /
   admin-shell suites unchanged.

### 4.1 What the real v3 acceptance run revealed

Full generation, Hinglish brief, v3, 19 minutes, tier-1 bundle, no
placeholders, real name 14×, stated fact present, `bundle_ok` true.

v3 **did** write Hinglish in the body:

- "Mera Portfolio", "Mera Profile", "Mere Kaam"
- "Mujhe Kahaan Se Kahaan Kariwale Hoon?"
- "Real-time dashboards aur payment systems ke liye kaam kar raha hoon"

but the **hero — the first thing anyone sees — was plain English**
("Rahul Sharma", "Full Stack Developer", "Get started").

The first version of the gate only checked the language of the page as a
whole, so a page with 7 Hinglish strings among 4,827 characters of mostly
English copy scored a confident, false **1.0**. The gate now requires a
**marker share** (`hits / words >= 0.06`, minimum 2 hits) rather than a
single hit, and it judges the **hero separately**:

```
re-scored with hero check:
  {'name_used': True, 'fact_used': True, 'clean': True,
   'lang_ok': False, 'hero_lang_ok': False, 'score': 0.6}
```

The gate now fires a copy-repair on the English hero instead of reporting
success. That is the difference between a metric that flatters you and one
that can be acted on.

### 4.2 A measurement bug worth naming

Three of the four failures I chased this session were bugs in my *tests*, not
in the product — and each one had the same shape: a filter written with `\w`
silently discarding the very thing it was meant to find.

- the v2/v3 A/B reported `name=False` for all five models while the raw v3
  output plainly said "Rahul Sharma";
- the class-list filter threw away every real sentence;
- the e2e harness judged a **roman-script** register (Hinglish) with a
  **Devanagari-ratio** test, and looked for stated facts in `App.jsx` only
  instead of the whole fileset.

The lesson generalises: a personalisation metric that nobody can produce a
*false negative* on is worthless in the other direction too. Every check now
has a positive control, a negative control and a cross-language control.

### 4.3 Generalising the brief reader (no per-customer rules)

The complaint that started this work: the system had learned one customer.
A worked example naming "Rahul Sharma" does not teach a 7B model how to read
a *brief*; it teaches it that briefs contain "Rahul Sharma". So the example
became `_lang_suffix_example(lang, name, role)`, parameterised per register,
and the harder problem was addressed directly: **there is no list of
professions**, so the brief reader may not enumerate professions.

**Where the placeholder came from.** The "with A, B and C" segmentation in
`extract_product_brief` defaulted to `seg = low` when the brief contained no
`with`. So "I'm an arborist, I need a website to show my tree care" was split
on its own commas and shipped **"i'm an arborist"** as a thing the site
offers. Identity masquerading as inventory. There is now no segment without a
trigger, and a chunk carrying a function word is a clause, not an item.

**How asks are derived instead.** `_derived_offerings` reads grammar, not
domain: structural triggers (`for my X`, `about X`, `featuring X`), then
ranked content n-grams over the whole request, longest and most plural first.
Nothing in it is profession-, customer- or language-specific — it is a
function-word table, an artifact-vocabulary table, and two English suffixes
used for ranking only. Measured over 24 trades that have no profile and never
appeared during development:

```
art major    -> ['art major', 'exhibitions', 'paintings']
arborist     -> ['stump removal', 'tree care', 'arborist']
luthier      -> ['handmade violins', 'guitars', 'luthier']
cartographer -> ['topographic maps', 'cartographer']
beekeeper    -> ['raw honey hives', 'pollination services', 'beekeeper']
```

Two negative controls guard against the opposite failure: a brief that is only
about the artifact ("modern responsive website with dark mode and smooth
animations") derives **nothing**.

**The tokenizer bug that made all of this moot for non-Latin input.**
Python's `\w` matches Devanagari *letters* but not the Mn/Mc **combining
marks** that carry the vowel, so the natural `re.findall(r"[\w']+", ...)`
shreds every Indic script at each matra. `चित्रकार` became three tokens, and
the section asks for a Marathi brief came back as the bare consonants of the
last two words — `"बस इट बन"` is `वेबसाइट` and `बनाओ` with every vowel
deleted. It looks like nonsense because it *is* nonsense, and **no English-only
test could see it**. `multilingual.tokens()` now tokenises with whole Unicode
blocks, which include the combining marks by construction; one code path then
serves Marathi, Bengali, Gujarati, Tamil and accented Latin, and a new script
needs one line rather than new logic. Devanagari asks now come back as
`['प्रदर्शनियों', 'चित्रों', 'चित्रकार']` — exhibitions, paintings, painter.

Tests: `test_personalization.py` 58 -> **97** checks.

### 4.4 Local folder workspace (Cursor-style)

The app is now something you point at a real project, not a page that returns
a blob. `backend/workspace.py` opens a folder and reads/writes inside it;
`frontend/src/pages/Workspace.tsx` is the UI (tree, editor, Ctrl+S, generate,
review the change set, apply).

This is the first code here that writes to a path the user did not create, so
it is written defensively and tested like an attacker:

- every path is rejected for `..`, absolute, UNC, null byte, reserved Windows
  names, trailing dots, and excluded directories (`node_modules`, `.git`, …);
- the containment check runs **after** `os.path.realpath`, so a symlink inside
  the project pointing outside is caught — the classic bug is checking the
  *string* prefix before resolution;
- symlinks are refused on the **unresolved** path. Checking `is_symlink()`
  after `realpath()` is always False, and that bug shipped in the first draft:
  the test suite caught writes silently following `alias.py` into its target;
- writes are atomic (temp sibling + `os.replace`), so a crash cannot truncate
  a file;
- the client sends a workspace id, never a path, so a request cannot name a
  root the user never chose;
- `apply` **does not overwrite by default**. The agent emits React projects and
  the folder the user opened is usually something else, so collisions come
  back as `skipped` and replacements carry a backup.

Suites: `test_workspace.py` **62** checks, `probe_workspace_api.py` **48**
wire-level checks with sentinel files outside the root.

Desktop shell: the native folder picker is the one capability a browser does
not have, and it is the reason the shell earns its keep. Its handler was
fire-and-forget — `dialog.showOpenDialog` was never awaited or returned, so
`chooseFolder()` always resolved `undefined` and the picker could never have
worked. Fixed, modal to the window, returning `{canceled, path}`.

Electron's own postinstall silently failed on this machine (zip downloaded,
`extract-zip` died mid-write, exit 0, one file in `dist/`), so
`app/scripts/ensure-electron.js` verifies the binary and extracts with
7-Zip. `npm install` no longer can ship a broken install.

Smoke-tested end to end: the shell launched, spawned its own backend on a free
port (no collision with the dev server), reported `ok: true` with v3 loaded and
zero issues, and a browser edit round-tripped through the API to disk.

---

## 5. The plan, in priority order

### P0 — finish what is already built (hours, no new hardware)

- **DONE — v3 is now genuinely served.** Switching `.env` was *not* enough.
  Measured: `.env` said v3, `/api/health` still said v2, and a fresh
  `python -c` in the same directory resolved v3 correctly. Cause: the uvicorn
  supervisor (started before the edit) inherited `MODEL_NAME=...v2` in its
  environment, and `load_dotenv` defaults to `override=False`, so `.env` could
  never win — and `--reload` respawns workers that inherit that same stale
  environment. `model_service.py` now loads the root `.env` with
  `override=True`, so `.env` is authoritative and this class of "my model is
  never used" bug cannot recur.
- **Acceptance run** (`e2e_ml.py --inproc`, which bypasses the HTTP server
  entirely and uses the model the current process resolved).

### P0b — brief-parser gaps found by building the corpus

Writing a realistic 22-brief bank exposed name shapes the parser had never
seen. Every one of these shipped a page branded with an archetype name:

| the user wrote | before | after |
|---|---|---|
| "a dental clinic **called** Bright Smile in Nashik" | `name=""` | `Bright Smile` |
| "a small bakery **called** Crumb" | `name=""` | `Crumb` |
| "my tailoring **business, Meera Stitch**" | `name=""` | `Meera Stitch` |
| "**I am** Priya Nair, a freelance product designer" | `name=""` | `Priya Nair` |

Four new patterns, a `_NAME_STOP` guard so a sentence-initial "Build" can
never become a brand, and 6 new checks (52 → **58**). A sentence-initial
capitalised word is now explicitly tested against becoming the name.

### P1 — the self-distillation corpus builder is BUILT

`backend/selfdistill.py`. Run it — it is the single highest-value thing left:

```
python selfdistill.py --count 200 --k 4          # ~200 kept examples, overnight
python selfdistill.py --dry-run                  # preview, generates nothing
```

Design points that make the corpus different from the old one:
- The instruction is the **real per-file prompt** from `_file_messages`, with
  the brief block, design block and the language hard constraint already in
  it. The old 83-character instructions never showed the model the prompt
  shape it actually gets at inference.
- **Nothing is kept unless `personalisation_score >= 0.75`** and the output
  carries no seeded filler. Every example is personalised by construction.
- The brief bank spans the register mix you actually receive: English,
  Hinglish, romanised Marathi, Devanagari Marathi and Devanagari Hindi. The
  old corpus was 100% English.
- It prints a **rejection breakdown** — that table is the filter working, and
  it tells you what the model is still getting wrong.

Then retrain with the larger corpus: `LEARNING_RATE 2e-4 → 1e-4`,
`TARGET_EPOCHS 3 → 2`.

### P1 — rebuild the training set by self-distillation (the big win)

Your 88 examples are the problem, and more scraped examples will not fix it:
random web code has the same template bias, just from a different source.

The method that does fit your constraints is **Simple Self-Distillation**
(Apple, arXiv 2604.01193): sample *N* completions per prompt from your own
model, keep only the ones that pass, fine-tune on the winners. No teacher
model, no verifier, no RL — which matters because you cannot afford any of
those.

Concretely, build a `selfdistill.py` that, per prompt:

1. Runs the **real** pipeline (so the brief block, design block and hard
   language constraint are all in the prompt, exactly as at inference).
2. Samples K=4 completions at temperature 0.9.
3. Keeps a completion only if it passes **all** of:
   - `personalisation_score() >= 0.75` (name used, stated fact used, no
     seeded filler, copy in the user's language),
   - balanced syntax, a real default export, and an actual `return (`,
   - no `_TEMPLATE_SEED_RE` hit — explicitly rejects "placeholder", Foo, bar,
     John Doe, Acme.
4. Writes `(real prompt, winning file)` rows in the same schema
   `train_unsloth.format_example` already consumes.

That yields an unlimited, perfectly on-distribution corpus where **every
example is personalised by construction**, and it is free. Budget 3–4 hours of
generation overnight, not GPU time.

### P2 — the web-data question (yes, but filtered)

You asked for web data. Take it, but **filter at the door** with the same
gate. Accept a scraped file only if it contains a *specific, non-generic*
domain noun and no seeded placeholder tokens. Reject on `personalisation_score`
principles. Unfiltered scraping is how you get 88 examples that teach
templating in the first place.

The higher-value use of the web is not training data — it is a **retrieval
corpus of real component patterns** (there is already `rag_engine.py` and an
18-component registry). Feeding two or three genuinely well-built component
examples into each per-file prompt is worth more than ten thousand scraped
files, and costs no training.

### P3 — the planner stage (this is where Sim earns its place)

`plan_files` currently asks the 7B for a file list and per-file purposes in one
shot. That is the weakest link: a 7B asked to plan 11 files will return a
generic plan. The research is unambiguous — spec-driven development converts a
raw request into a specification precise enough for one agent to build and
another to verify, with **error reductions up to 50%** (arXiv 2602.00180).

Split the run into **plan → build → verify**:
- Stage A (planner): produce a *structured brief spec* — sections, per-section
  intent, the actual finished copy, the palette, the CTA. This is ~2,000
  tokens, not 4,200 × 11.
- Stage B (builder): each file ask *receives the spec section*, not a vague
  purpose string.
- Stage C: `personalisation_score` is the verifier.

Stage A is cheap enough to be worth running on a bigger model than the builder
if you ever want to, and it is exactly what your Sim agent already does.

### P4 — speed, so iteration is possible at all (19 min/run is the tax)

- **n-gram speculative decoding in llama.cpp** — `--spec-type ngram`, no draft
  model needed, 1.5–2.5× on generation-heavy code. Cheapest win available.
- **Keep the preview cache** — the e2e run logged `[preview] cache hit`, so it
  works. Extend it to the generator, keyed on the brief, so tweaking a
  *deterministic* stage (design, profile, scaffold) never re-runs the model.
- **Per-file parallelism is not available** on 6 GB; do not try.

### P5 — the honest gap

Bolt and Lovable run GPT-4o-class models. On a 6 GB card you will not match
their raw code fluency, and no amount of prompt work changes that. What you
*can* match is the thing users actually complain about — **"it gave me a
template"** — and you are now structurally better positioned than they are,
because your stage 1/2/3/6 are deterministic and measured. Close that gap
first and the product is competitive for the actual target user: a
non-technical, non-English-speaking business owner. That is a market Bolt and
Lovable serve badly.

---

## 6. Sim: keep the prompt, discard the deployment

**Verdict: do not discard the thinking, do not keep the integration.**

What Sim is today:
- A workflow on sim.ai, model `claude-sonnet-5-5`, that turns a request into a
  `terabit-build-spec.md`. Version 7, ~$0.51 of 1,000 free credits spent.
- **It is not wired into the product.** `grep` for `sim.ai` across the repo
  returns **0 matches**. It cannot be "running the show".
- Its deployment cannot interpolate cross-block references into a file block
  (`<uuid.field>`, `{{uuid.field}}`, `<uuid.content>` all pass through
  literally). We worked around it by giving the agent a `file_write` tool.

So it is currently a **spec-authoring console for you and me**, useful for
design work, useless at runtime — and it breaks the "fully local" promise,
because shipping a user's description to a hosted service is the opposite of
local-first.

What to do:
1. **Keep `prompt.txt`.** That 3.2 KB system prompt is the best
   spec-first planner prompt in this project — rules 1–10 ("never emit a
   generic template", "infer and commit, never ask", "the content field must
   be final text") are exactly the contract the builder stage is missing.
2. **Port rules 1–10 into a local planner stage** (P3 above). Run it on the
   local model as stage A.
3. **Let the sim.ai deployment drift.** Nothing depends on it. If you want the
   console later, it is one `npx sim@2` command away.

Optionally fold the 3,200 prompt chars into `FILE_SYSTEM` for the planner.

---

## 7. Files touched

| file | change |
|---|---|
| `backend/multilingual.py` | **new** — zero-token multilingual normalisation layer |
| `backend/main.py` | `extract_product_brief`: language field, multilingual fallback, noise filters, comma clause boundary |
| `backend/agentic_generator.py` | `user_facing_copy`, `personalisation_score`, `repair_personalisation`, language hard constraint, `personalisation` in the result |
| `backend/domain_profiles.py` | new `beauty` profile; `photography` keyword |
| `backend/test_personalization.py` | 18 → **52 checks** (5 non-English briefs) |
| `backend/test_personalisation_gate.py` | **new** — 18 checks on the gate |
| `backend/model_service.py` | root `.env` loaded with `override=True` so a stale shell cannot pin the model again |
| `backend/selfdistill.py` | **new** — P1 self-distillation corpus builder |
| `backend/ab_v2_v3.py`, `backend/rescore_ab.py` | **new** — model A/B + offline re-scoring |
| `backend/probe_lang.py`, `backend/probe_salience.py` | **new** — capability vs salience probes |
| `backend/e2e_ml.py`, `backend/ml_matrix.py` | **new** — end-to-end and matrix harnesses |
| `.env`, `.env.example` | `MODEL_NAME=terabit-finetuned-v3` |

---

## 8. Session 2026-10-03 — open-vocabulary task understanding, and two missing modules

### 8a. The hardcoding, named

The complaint "you are hardcoding things into the system" was correct, and it
had an exact address. Stage 2 of the pipeline (`domain_profiles`) decided what
the deliverable looks like by looking the user's *trade* up in a keyword table
(`_KEYWORDS`) and reading a skeleton off a second table (`_PROFILE_OVERRIDES`,
13 trades; `_ADMIN_VIEW_SETS`, 3 back-office trades). Everything else fell
through to one generic SaaS skeleton. Adding a profile per trade cannot fix
this: there is a list of *trades* nobody has, and the trade was never the
thing that determines structure anyway.

### 8b. The fix: infer the SHAPE from function, not the market from identity

`backend/task_understanding.py` (new). Four artifact families (site,
showcase, storefront, back-office console) and fourteen section *roles*
(showcase, offering list, catalogue, ordering, pricing, booking, events,
roster, story, process, credentials, location, proof, FAQ). Roles are selected
by the user's own function words -- "book an appointment", "prices", "my
paintings", "records" -- and filled with the user's own nouns. No profession,
industry or country appears in the file; extending it means adding a *shape*
the product supports, not a *customer* it serves. `model_hint()` can ask the
local model to choose from this registry when the deterministic pass is
unsure, and discards anything outside it (tested with a fake chat function, so
the registry bound is enforced even offline).

Integrated at the two fallbacks that used to be generic: `get_profile()` for
unknown trades, `admin_views()` for unknown back-office entity sets (entities
come from the user's own nouns, so "manage students, batches and fees" gets
Students and Batches views). Curated profiles stay as quality boosts for the
trades they cover; they are no longer the gate to being understood.

Measured (`test_task_understanding.py`, **263 checks**): a lawyer whose brief
never says "law" gets Practice Areas + Fees from "practice areas" and
"fees"; a business student gets Work + Testimonials; a beekeeper gets a
catalogue + pricing; a luthier gets a Portfolio whose copy names "handmade
violins"; an artifact-only brief ("dark mode and smooth animations") derives
**no** roles and invents nothing; and identical function words from three
different trades produce identical structure.

### 8c. Two modules the checkout was missing (restored, verified)

Documentation described both of these as shipped; neither was present, and
`main.py` imports both at module level, so **the backend could not start**.

- `backend/workspace.py` — the local-folder workspace (open / tree / read /
  write / apply / export). Rebuilt against the contracts already in the tree:
  the 48-check wire probe and the Workspace UI. Containment is checked after
  `realpath`, symlinks are refused on the unresolved path, writes are atomic,
  overwrites carry byte-faithful backups, a hostile path in a generated file
  list fails one file instead of the batch. `probe_workspace_api.py`: **48/48
  pass**; `test_workspace.py` (new): **55 checks** including symlink escape,
  reserved names, binary/large reads and export contents.
- `backend/multilingual.py::tokens()` — the whole-script tokeniser. `\w`
  matches Devanagari letters but not combining marks, so every
  `re.findall(r"[\w']+")` shredded Indic text (`चित्रकार` -> 4 fragments).
  `test_personalization.py` goes from an import-time failure to **97 checks
  pass**.

### 8d. The desktop shell (restored, booting verified end to end)

`app/package.json` described the shell while its entry files were missing, so
the app could not be built or launched. Rebuilt as four pieces with one rule:
**the shell is wiring, `boot.js` is behaviour, and behaviour is testable
without Electron.**

- `app/boot.js` -- port choice, health wait, backend discovery (bundled exe,
  packaged resources, or the source tree + a Python that can import
  uvicorn/fastapi), spawn/stop (process-tree kill on Windows), env probe.
- `app/main.js` -- windows, IPC, menu, single-instance, `--smoke` mode. It
  reuses a healthy backend instead of spawning a second one; in dev it keeps
the :8000 contract the Vite UI hard-codes, and a packaged build loads the UI
  from the backend origin (any free port works, nothing is hard-coded).
- `app/preload.js` -- the `window.terabit` bridge the Workspace UI already
  calls, including the awaited `chooseFolder()` whose first implementation was
  fire-and-forget and could never have worked.
- `app/first-run.html` -- live boot log, and a plain-language environment
  check (Ollama missing, model not pulled, UI not built) instead of a blank
  window; `npm run smoke` exercises the same boot with no window at all.

Measured on this machine: `app/test_boot.js` **22 checks** (real backend
spawned on a free port, health, `/api/app/env`, shutdown, and the failure
paths); `electron . --smoke` ready in **4.1 s** reusing an existing backend and
**8.2 s** spawning its own, with the child shut down on exit; the backend
serves the built SPA at `/` and `/workspace` (200, hashed assets), which is
exactly what the packaged window loads.

Still human-only: the native folder picker and the rendered window cannot be
asserted from a terminal -- they need one click-through.

### 8f. Ship-able: the backend bundle and the installers (done)

The missing `extraResources` payload now exists and is proven. `paths.py` is
the piece that made it possible: frozen builds have no repository above them,
so the DB and uploads resolve to the executable's own folder (`TERABIT_DATA_DIR`
to move them), the UI resolves from `web/` inside the bundle, and `.env` is
read next to the exe. `terabit_main.py` is the entry point the bundle runs
(`--host/--port`, exactly the contract `boot.js` sends), and
`build_backend.py` runs PyInstaller with the dynamic imports uvicorn/anyio/
SQLAlchemy need and with the ML stack excluded -- retrieval is lexical
(`rag_engine.py`), training stays a source-tree feature, and the installer
lands at ~119 MB instead of multiple GB.

Measured on this machine: bundle build **114 s, 104 MB**; frozen bundle
healthy in **4 s**, `/api/app/env` reports `frozen=true` and
`BUILD.json` label `v1.1.0+20261003-022649+ba0eab1`, the bundled UI serves at
`/` (402 KB JS asset, `/workspace` deep link 200); `electron-builder --dir`
packages it; the PACKAGED app smoke-tests in **3.8 s** booting its own bundled
backend (`"reused":false, "env_ok":true`); `npm run dist` produces the NSIS
installer and the portable exe (**~119 MB each**, unsigned -- Windows will
warn).

Still human-only: the first interactive launch of the installed app (the
glass half of "it works").

### 8e. Files in this session

| file | change |
|---|---|
| `backend/task_understanding.py` | **new** — families, roles, bounded model hint |
| `backend/test_task_understanding.py` | **new** — 263 checks, 11 personas |
| `backend/workspace.py` | **restored** — containment, atomic writes, apply/export |
| `backend/test_workspace.py` | **new** — 55 checks incl. symlink escape |
| `backend/multilingual.py` | **restored `tokens()`** — marks stay attached |
| `backend/domain_profiles.py` | generic fallbacks now delegate to `task_understanding` |
| `backend/agentic_generator.py` | landing plan de-duplicates paths (product profile listed Faq twice) |
| `app/boot.js`, `app/test_boot.js` | **new** -- backend lifecycle + 22 checks |
| `app/main.js`, `app/preload.js`, `app/first-run.html` | **restored** -- Electron shell |
| `app/scripts/ensure-electron.js` | **restored** -- verifies/repairs the Electron binary |
| `app/build/icon.ico`, `app/package.json` | icon + smoke/test/package scripts, `boot.js` shipped |
| `backend/paths.py`, `backend/terabit_main.py` | **new** -- frozen-vs-source locations; bundle entry point |
| `backend/build_backend.py` | **new** -- PyInstaller build (104 MB, ML stack excluded) |
| `app/scripts/build-backend.js` | **new** -- builds AND verifies the bundle before packaging |
| `backend/{main,database,model_service}.py` | data dir / web dir / `.env` resolution for frozen builds |
