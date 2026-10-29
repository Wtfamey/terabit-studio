# Terabit Studio vs Bolt/Lovable — Evidence Report (2026-09-29, updated after v3)

## v3 model — trained and deployed

The v3 LoRA (198 hand-authored gold exemplars × 9 design themes × 2 brands,
all esbuild+render-verified BEFORE training; 3 epochs, 228 steps, ~2.2h on the
RTX 3050) is merged, q4_K_M-quantized and served as `terabit-finetuned-v3`
(4.7GB, num_ctx 16384). Pipeline: train_unsloth.py → merge_lora_to_safetensors
→ convert_hf_to_gguf (b4600) → llama-quantize (b11242) → ollama create.

First live v3 run (20260929-150446, 2497s, tier1-bundled):
- ALL FOUR sections generated at healthy sizes (Hero 17.2k, Menu 12.9k,
  Reservations 10.8k, Faq 3.9k chars) — v2's degenerate 26/33-char outputs
  are gone.
- v3 wrote restaurant-specific design (stone/amber palette) but still drifted
  to slate/indigo in places; the deterministic style enforcer rewrote 171
  classes to the theme (indigo-600→amber-600, etc.) and the shipped page is
  palette-consistent.
- Repair loop broke Menu/Hero further → salvage dropped Hero, recomposed, and
  the page shipped model-written Menu + Reservations + Faq + themed shell.
  In-browser verification: root renders, personalized content visible
  ("Seasonal Italian Cooking & Wood-Fired Pizza", "Diavola with Calabrian
  Pepper", address card).
- Design gate: 0.552 palette adherence (v2 baseline: 0.00-0.25) — improving
  but still FAIL (0.80 bar). Gate fixes shipped after this run: re-enforce
  after every LLM repair (repairs were reintroducing off-palette classes),
  invisible border-white → theme border on light themes, Reveal fallback
  timer (embedded viewports never fired the IntersectionObserver → invisible
  content).

Known v3 issue to watch: generation got SLOWER (2497s vs ~900s) because v3
writes much longer files (17k-char Heros) and more repairs fired. If it
persists, cap num_predict tighter or raise the rescue threshold.

---

# Earlier evidence (v2 era)

All runs below are local Qwen 2.5 7B (terabit-finetuned-v2, q4_k_m, RTX 3050 6GB)
with the same deterministic landing architecture: plan → per-section generation →
compose shell → bundle_check (esbuild) + render_check (react-dom/server) →
repair/salvage → tier1 preview. Artifacts: `backend/comparison/<slug>/<ts>/`.

## Reliability progression (Casa Verde restaurant, identical prompt)

| Run | Wall | Sections shipped | Outcome |
|---|---|---|---|
| 20260928-063910 | 547s | 0 + inline scaffold | compose existed, white-screened at runtime |
| 20260928-071311 | 961s | 0 | Hero truncation ×3 repairs → generic SaaS scaffold (the "why Features/Pricing" bug) |
| 20260928-163827 | 895s | 2 of 4 | iterative salvage shipped shell+Faq; render verified in-browser |
| 20260928-172956 | 705s | 3 of 4 | 6144-token budgets ended the truncation loop; Faq JSX-sibling bug → salvage |
| 20260929-020320 | 994s | 2 of 4 | themed shell + fonts + reveal animations shipped; model produced two degenerate files (26/33 chars) |

Root causes eliminated on the way: App.jsx truncation (deterministic composition),
2048-token section cap (→6144), repair loop burning all attempts on one file
(→2-strike + salvage), missing render verification (render_check), generic fallback
copy (brief-aware scaffold), icon-as-function / bare-icon-children / JSX-ternary-
siblings / duplicate-export failures (deterministic fixers, unit-tested against
live artifacts).

## What ships today (verified in browser, not just bundler)

- Model-written personalized sections (Menu with real dishes/prices, FAQ with
  domain answers, Reservations with working form state) inside a deterministic
  shell: monogram logo, sticky blur nav with domain labels + brief CTA, footer.
- Design system per domain: exact Tailwind palettes (restaurant = warm cream/
  amber + Playfair Display; law = navy serif; hospital = teal; fashion = editorial
  dark; art = gallery minimal; fitness = lime/dark; realestate/education/saas...),
  scroll-reveal animations (IntersectionObserver, prefers-reduced-motion safe),
  Inter/serif font pairings via Google Fonts, branded tab title.
- Salvage chain: broken sections are dropped and the shell recomposes — the page
  ships the model's healthy personalized work instead of falling back wholesale.
- Full artifacts every run (request/trace/files/raw generations) under
  backend/comparison/ for benchmarking.

## The remaining gap = the model, and it is being retrained

The 7B (v2) was fine-tuned on data that HARDCODED dark-indigo glassmorphism
(STYLE_RULES in the old generator) — that's why every domain painted dark
indigo and ignored the design block. v3 fixes the data:

- `backend/gold_exemplars.py` — 9 hand-authored exemplars (Hero, Menu,
  Reservations, Faq, Features, Pricing, StatCards, DataTable, Dashboard) with
  design TOKENS, no known 7B failure patterns.
- `backend/generate_v3_dataset.py` — exemplars × 9 design themes × 2 brands =
  162 examples; instructions replicate the RUNTIME ask format including the
  exact DESIGN SYSTEM block; every pair validated through real esbuild +
  react-dom/server BEFORE training (144+18 Dashboard validated, 0 failures).
- Training: Unsloth QLoRA (r=8, lr 2e-4, 3 epochs, 228 steps, seq ≤3584) on the
  box's RTX 3050 — started 2026-09-29, ~57s/step, ≈3.5h.
- Deploy: `backend/deploy_v3.py` (watcher running) → merge fp16 → `ollama create
  terabit-finetuned-v3 --quantize q4_k_m` → restart backend with MODEL_NAME=v3.

Expected v3 gains: sections that follow the injected design block (warm/serif/
editorial per domain instead of indigo everywhere), fewer degenerate outputs
(training data shows only complete, closed-fence files), dashboard-quality SaaS
screens from the StatCards/DataTable/Dashboard exemplars.

## Design-adherence gate (objective baseline)

`backend/eval_design_gate.py` scores every run's palette/font/brand usage
against the domain theme. v2 baseline: restaurant runs score 0.00-0.25 palette
adherence (up to 68 neon indigo/violet/pink classes per run), law 0.50-0.57 --
all FAIL. Gold exemplars score 1.0 and PASS. Every future run saves its score
to design_score.json next to the artifacts; promoting a retrained model should
require live runs that PASS the gate. Training dataset updated to 198 examples
(Testimonials + Cta added) for the v3.1 top-up after the in-flight run.

## Honest gaps vs Bolt/Lovable after v3

1. Speed: ~10-16 min vs ~2 min (7B on 6GB; inherent, mitigated by fewer retries).
2. Single-shot interactivity: Bolt streams a running app you can click around
   immediately; ours is a static-but-interactive preview bundle (state works:
   menus, filters, forms, accordions).
3. Multi-file app coherence for full SaaS (routing/auth/backends) stays
   template-assisted; the deterministic shell + profiles carry what the model
   cannot yet hold in one 7B pass.

## v3 live validation + deterministic quality pass (2026-09-30)

Casa Verde restaurant prompt, UI path, `20260930-145031/`:
**tier1-bundled, wall_s 1090, design gate PASS (palette 1.0, 0 neon drift),
all 4 model sections shipped — zero salvage drops.** Copy fully on-type
(dishes, reservations, restaurant FAQs; no SaaS plans anywhere). The
duplicate-import + missing-export fixers were not needed by this run (v3
outputs were clean), but they remain in the chain as insurance.

### New deterministic fixer module: `backend/imagery.py`
The visual bugs that remained were purely mechanical, so they are now fixed
without the model:

1. **Placeholder imagery** — the model filled galleries with gray
   `picsum.photos?grayscale&blur=2` URLs and left 4/6 menu items with NO image
   field at all (`src={item.image}` -> undefined -> dead img). Domain-themed,
   curl-verified Unsplash pools now replace/fill these (restaurant, medical,
   retail, gym, home, education, gallery, office). Real URLs pass through.
2. **Hover-hidden content images** — the single `<img>` in the menu card was
   `opacity-0 group-hover:opacity-100`, i.e. blank until hover. object-cover
   content images are forced visible (`opacity-100`).
3. **Gradient-text boxes** — `<span className="bg-gradient-to-br ...">` inside
   a `bg-clip-text text-transparent` h1 painted a solid rectangle over the
   word ("Savor ▮ Flavors"). Inline-text elements now get bg-clip-text +
   text-transparent; decorative chips/glows are excluded.
4. **Shell logo** — composed App.jsx emitted `<img src="">` (dead image box);
   template now uses `src={LOGO_URL}` mirroring the JS guard.

Wired into: gen-loop fixer chain, LLM-repair chain, salvage pre-drop chain,
and both non-agent finalize paths in main.py. Tests: `backend/test_imagery.py`
(all pass, idempotent). Replay on 145031 artifacts: 6/6 dish photos themed +
visible, hero headline fixed. Guard + guard click behavior re-verified in the
rebuilt preview (Reserve-a-Table click scrolls in place, no navigation).

### Breadth run: portfolio (Mara Lindqvist) — `i-need-you-to-build-me-a-portfolio-websi/20260930-174958/`
First portfolio-profile run end-to-end: **tier1-bundled, wall_s 1638, design
gate PASS (palette 1.0, 0 neon)** — portfolio theme resolved correctly
(Space Grotesk + Inter, light stone), 315 off-palette classes mapped
(indigo/purple -> stone), Hero/Work/About shipped with real project imagery
(model chose on-type Unsplash ids itself this run). No SaaS copy anywhere.
One truncation failure: Faq.jsx died on an unterminated string literal (the
export lives at the end; both LLM repairs failed) -> salvage dropped it and
recomposed. Deterministic next step queued: re-append a truncated file's
missing export/closing fence before spending LLM repairs. v3.1 polish
candidate: image-led work cards render flat when the frosted panel is nearly
opaque -- consider capping panel opacity in the style enforcer.

## Generation-integrity fixers (2026-09-30, after the portfolio run)

Three mechanical failures that cost real runs their sections are now repaired
without the model (tests: `backend/test_fixers.py`).

1. **Stray fence backtick** — portfolio Faq began with a single '`' (not a
   proper ``` fence, so the parser kept it) which opened a template literal
   over the whole file -> esbuild 'Unterminated string literal' at EOF -> both
   LLM repairs failed -> section dropped. `fix_stray_fence` removes an
   UNPAIRED leading/trailing backtick (paired template literals untouched).
   Live replay: the artifact is balanced again and **Faq bundles + renders**.
2. **Truncated tail** — generation cut mid-string: `fix_truncated` sheds the
   unterminated literal and its partial line, closes the brackets still open
   at the cut, re-appends a missing default export, and returns the ORIGINAL
   if the result cannot be balanced (never makes a file worse).
3. **`fix_missing_export` wrapper bug** — its shape-2 wrapper concatenated a
   plain `"\n}}\n"` after an f-string, emitting a literal double brace and
   unbalanced output every time it fired. Fixed to `"\n}\n"`.

All three run in the gen-loop fixer chain, the LLM-repair chain, the salvage
pre-drop chain, and a new pre-LLM deterministic attempt in the repair loop
(mechanical repair now happens BEFORE ~1 min of LLM repair that already failed
twice). Style: frosted panels are now translucent (`bg-*` + `backdrop-blur-*`
-> `/70`, `test_style_enforcer.py`), because an opaque fill behind a blur is
self-contradictory and made image-led cards read as flat slabs.

**Full pipeline replay of the portfolio run** (raw model files -> fixers ->
shell -> style -> imagery): theme portfolio/Space Grotesk, **all 4 sections
kept (Faq recovered), zero drops, BUNDLE True, RENDER True.** Remaining known
gap (not mechanical): Work.jsx declares `imageUrl`/`overlayGradient` fields but
never renders them, so project cards are text+gradient with no photo -- a
model/exemplar item for v3.1, not safe to patch by DOM surgery.

## Evidence capture: every run now keeps visual proof (2026-09-30)

Runs used to leave only JSON (`request/result/generated/design_score`), so a
green `bundle_ok` could hide a page that looked wrong. `backend/capture_evidence.py`
now renders each run's real bundled preview with the system Chrome/Edge in
headless mode and saves it as JPEG (Pillow), so the visual result is auditable
long after the server is gone:

    <run>/preview.html                    exact bundled preview (self-contained)
    <run>/screenshots/desktop.jpg         1440w full-height
    <run>/screenshots/mobile.jpg          390w
    <run>/screenshots/manifest.json       prompt, wall_s, tier, gate, palette, files

Usage: `python capture_evidence.py --all` (or `--run latest`, `--force`), and
`--gallery` builds `comparison/gallery.html` -- a single browsable page of every
captured run (newest first, desktop + mobile side by side, gate/palette/theme
metadata per card). The artifact dumper in `main.py` spawns this on a daemon
thread after saving, so future runs capture themselves with no manual step.
19 runs backfilled.

## Motion enrichment: animated output is now guaranteed, not hoped for (2026-09-30)

Two changes close the "static template" gap against Bolt/Lovable.

**1. The default design brief now mandates micro-interactions.** The design
system only described motion when the user explicitly asked for "animations"
(mode `rich`); the default `standard` path had *no* animation guidance at all,
so a 7B shipped dead markup. `standard` now mandates, as literal classes it can
copy: cards `transition-all duration-300 hover:-translate-y-1 hover:shadow-xl`,
buttons/links `transition-all duration-200 active:scale-[0.97]`, card images
`transition-transform duration-500 group-hover:scale-105`, entrance
`animate-fade-up`, staggered `animationDelay`, transform/opacity only.

**2. `backend/motion_enricher.py` enforces a mechanical floor.** A deterministic
pass (same philosophy as the style enforcer) that ADDS transition/hover/active
classes to card-like, button-like and photo elements. It only ever adds and is
idempotent (anything already carrying a `transition` utility is skipped), skips
layout containers (`fixed/absolute/sticky/min-h-screen`) and template-literal
classNames, and honours an explicit "no animations" request. Wired into
`run_agent` after style/imagery enforcement; traced as `motion-enrich`.
Tests: `backend/test_motion_enricher.py` (idempotence, safety on layout/svg/
template cases, and brace/quote-invariance across 6 real generated artifacts).

**3. Sections now stagger as they scroll.** The composed shell wraps each
section in `<Reveal delay={n * 110}>` (previously every section animated on the
same frame). `Reveal` gained a `delay` prop applied as `animationDelay`; the
`both` fill-mode keeps a delayed section hidden until its turn. Covered by the
new `backend/test_shell.py`, which composes the shell from the real law-firm
run (after the repair chain) and asserts the result **bundles AND renders**
(4 sections, delays `[0,110,220,330]`, zero drops).

## Builder UI: rebuilt against Bolt/Lovable conventions (2026-09-30)

Researched what the category leaders actually do (Bolt's chat-tools docs:
element select, @-file tagging, dictation, prompt enhance, the 20-deep prompt
queue with edit/reorder/pause, version history that is locked while processing;
Lovable: single engine with a planning mode and chat-outside-project; Emergent:
visible multi-agent activity) and ported the patterns into `frontend/`.

New components:

- `components/PromptComposer.tsx` -- auto-growing textarea; `@` mention
  autocomplete over real project paths ranked by basename then path length;
  a `+` menu with Enhance prompt / Attach images / Tag a file; dictation via
  the Web Speech API (appends rather than clobbers); the selected-element chip;
  and a send button that becomes Stop while a build is running.
- `components/AgentSteps.tsx` -- parses the agent's raw progress lines into a
  real step timeline (plan -> per-file writes with an "n of m" counter ->
  assemble -> design/motion pass -> verify -> repair), with the active step
  spinning, past steps tinted by kind, and a shimmer strip while running.
- `components/VersionHistory.tsx` -- the previously write-only snapshot list is
  now a timeline with relative times, file counts, restore, and the Bolt-style
  rule that restores are locked while the agent is mid-build.
- `components/PromptComposer` + queue in `Builder.tsx` -- prompts sent during a
  build are queued with drag-to-reorder, inline edit, delete, and Pause/Resume,
  then drained one at a time when the agent goes idle.
- `PreviewFrame.tsx` -- desktop/tablet/mobile device switcher; a Select mode
  that injects a hover-highlight + click-to-report script into the preview and
  posts the picked element back over the existing `terabit-preview` channel, so
  a prompt can be aimed at one element; and a designed empty state.

Backend support for the timeline: `run_agent` now emits progress for the phases
that were previously silent (design/imagery/motion pass, verification, and the
final bundle result), so the UI reflects the real pipeline rather than a
five-line approximation.

## Depth: every profile is now 4 domain sections, not 2 (2026-09-30)

The reported symptom was "our sites aren't at par — normal law-firm or
restaurant sites have at least four sections". The cause was structural:
every domain profile carried exactly **two** section slots, so a page shipped
Hero + 2 + FAQ, and any single drop (see below) left it at three. All twelve
profiles now carry **four** domain sections, each with a written spec:

    law         PracticeAreas, Fees, Attorneys, Testimonials
    hospital    Services, Doctors, Facilities, PatientStories
    restaurant  Menu, Reservations, Story, Testimonials
    fashion     Collections, Lookbook, Craft, Testimonials
    realestate  Listings, Agents, Process, Testimonials
    fitness     Programs, Schedule, Trainers, Testimonials
    education   Courses, Faculty, Admissions, Testimonials
    art         Gallery, Visit, Artists, Testimonials
    portfolio   Work, About, Services, Testimonials
    product     Showcase, Specs, Reviews, Faq
    agency      Services, CaseStudies, Process, Testimonials
    saas        Features, Pricing, Testimonials, Metrics
    generic     Features, Pricing, Testimonials, Process

The shell composer also gained a duplicate-stem guard (the `product` profile
now legitimately uses the shell's own FAQ slot). `test_shell.py` asserts every
one of those profiles composes to >= 4 sections, renders each component
exactly once, and **bundles** — so a thin page is now a test failure rather
than a surprise.

## The recurring section-killer: TypeScript syntax in a `.jsx` file (2026-09-30)

The law-firm run lost its FAQ section (its second drop on the same fault). The
error was esbuild's `Expected ")" but found ":"` on `const toggle = (id: number) => {`
— the model had written a TypeScript parameter annotation into a `.jsx` file.
esbuild's jsx loader rejects it, and because the repair loop is *shown the same
annotated source* the LLM "repair" failed twice more, so salvage dropped the
section. The file was never wrong; only its extension was.

`promote_tsx_files` now detects TS-only syntax (parameter/return annotations,
generics on hooks, `interface`/`type` declarations, `as` casts) and re-tags the
file `.tsx`, letting esbuild's TS loader parse it — no risky annotation
surgery. Explicit `.jsx` import specifiers are rewritten to match; extensionless
imports keep resolving; a rename never clobbers an existing `.tsx` sibling. It
runs before shell composition for creates and after assembly for edits.
`test_fixers.py` proves the promotion is load-bearing: the same content fails
to bundle as `.jsx` and bundles as `.tsx`.

## Back-office archetype: management systems were routed wrong (2026-09-30)

Two live mis-routes found while auditing the untested SaaS path:

  * "a store management system" -> `ecommerce`, i.e. a **storefront with a
    cart**, when the user asked for an internal inventory back office.
  * "a hospital management system" -> `saas`, the marketing scaffold.
  * "a restaurant site" -> `saas`, because only the literal words
    "landing page"/"website" triggered the landing path.

All three are fixed: any `<domain> site|website|homepage` is a landing page,
and a new `admin` archetype (checked before ecommerce) covers management
systems, admin panels, POS and internal tools.

`admin` gets the same treatment `landing` got, for the same reason — the giant
App.jsx ask token-caps a 7B:

  * `domain_profiles.admin_views(brief)` returns the managed entities per
    domain (hospital: Dashboard/Patients/Appointments/Doctors; store:
    Dashboard/Products/Orders/Suppliers; employee:
    Dashboard/Employees/Attendance/LeaveRequests; generic fallback).
  * `_plan_files_admin` is a **deterministic plan** — no planner LLM call.
  * `_compose_admin_shell` composes App.jsx as a real admin chrome: sidebar
    navigation, mobile drawer, topbar with search and notifications, animated
    view switching, and an administrator footer. Each view is a self-contained
    component the model writes, so the shell is never a token-cap casualty.

`test_admin_shell.py` covers routing (12 prompts), the per-domain view sets,
the plan, and compose+bundle+render for all three systems plus the
broken-view-dropped-not-fatal case.

## Full product redesign + brand (2026-09-30)

The Studio's own UI was described as "too basic, no animations, swift icons".
It now has a single dark theme lifted from the Freebuff surface language and a
real brand identity.

**Brand.** A generated mark: a rounded tile with a violet->cyan gradient
holding a white "T" (bar + stem) with a thin orbit ring and a node dot passing
behind it — "tera" (scale) + "bit" (a unit of data in orbit). It ships as
`public/logo.svg` (also the favicon, referenced from `index.html`) and as
`<LogoMark>` / `<Wordmark>` React components, so the same artwork renders at
16px in a tab and at 240px in the hero.

**Tokens.** `src/theme.ts` defines the canvas (`#07070d` near-black with a
violet cast), panel/hairline alphas, the brand ramp, the shared button/input/
panel class strings and the hover-lift sweep. Pages import these instead of
re-inventing class soup, which is what makes the product read as one app.
Tailwind gained `ink`/`brand` ramps and the `swift` easing.

**Motion.** A real animation system in `index.css`: aurora drift (three
slow radial blooms), staggered `slideUpIn` entrances, shimmer, glow pulse,
float, gradient pan, pop-in, marquee, plus a `card-glow` gradient hairline and
a `prompt-glow` focus ring. Every interactive element has a transition and an
`active:scale` press state, and the whole system collapses under
`prefers-reduced-motion`.

**Screens.**
  * `Home` — sticky glass nav, animated gradient headline that rotates through
    real asks ("a law firm site", "a hospital management system"), a
    `prompt-glow` composer with template chips, brand and asset panels, a
    three-step "how it works", a hover-lifting template grid and a closing CTA
    card with the floating logo.
  * `Login` / `Register` — a shared `AuthLayout`: brand story with gradient
    headline and proof points on the left, glass form card on the right,
    aurora behind both. Register shows live password-rule checklists.
  * `Builder` — the wordmark replaces the placeholder icon, the canvas moves to
    the new palette, and the status bar animates.

**Also added:** the three template cards the product never had (Hospital
Management, Store Management, Employee Management), each seeding a prompt
whose words match the new `admin` archetype.

## Stability: model calls are now hard-bounded (2026-10-01)

The hospital validation run sat 22+ minutes inside one repair attempt because
`model_service.get_client()` created its OpenAI client with **no timeout** — a
wedged ollama call hung the repair loop forever. `get_client()` now passes
`timeout=MODEL_REQUEST_TIMEOUT_S` (default 600 s, env-overridable) and
`max_retries=0` (callers already own retry budgets; library retries doubled the
cost of failing calls). Combined with the existing two-fails-per-file cap and
the salvage loop, no generation can spiral anymore: worst case is bounded per
file, and the run always terminates with artifacts + evidence shots.

## Evidence: the gallery now also shows the app's own UI (2026-10-01)

`backend/capture_app_ui.py` registers/logs-in a dedicated evidence account,
then drives headless Chrome through `/login`, `/` and `/builder` with the new
`?token=` auth bootstrap (AuthContext consumes it once and strips it from the
URL). Output: `backend/comparison/ui/<stamp>/{auth_login,home,builder}.jpg` +
manifest. `capture_evidence.py --gallery` appends an "app UI" section to
`comparison/gallery.html`, so one page now proves both sides — what the model
builds and what the product looks like. Served at
`http://127.0.0.1:8765/gallery.html`.

## Personalization: the prompt's own details now reach the output (2026-10-01)

Owner report: "I ask for a portfolio with my details and it still makes a
template; user-provided images never appear." Three root causes, all fixed:

**1. The brief never captured people.** `extract_product_brief` only looked
for "for <Business Name>" and appositives. "my name is Amey Chikane i am a
computer science graduate..." produced `name=""` -> the shipped site was
branded "PortfolioName". The brief now extracts:
  * `name` from "my name is X" / "this is for X" / "portfolio of X",
  * `person: true` for personal sites,
  * `facts[]` -- stated bio clauses ("computer science graduate specializing
    in ai and ml tasks", "ai engineer and consultant"), with lazy captures
    that stop at the next "i am/i have/..." clause and drop artifact
    instructions ("uploaded my image"),
  * `subject` -- "e-commerce store for premium coffee beans" now yields
    `subject="premium coffee beans"` instead of an empty brief (the coffee
    run invented headphone products because nothing said "coffee").
The brief block fed to every per-file prompt now carries the name, the facts
and an explicit ban on placeholder copy ("no 'Your Name', 'PortfolioName',
'John Doe'"), plus "the business is about <subject>" for commercial sites.

**2. Uploaded images were dropped.** `req.assets` reached only the landing
shell's logo slot; every other image was ignored, and the pipeline crashed
outright on pydantic `AssetInfo` objects (`a.get()` -- the whole agent run
died and silently fell through to a 607 s single-shot regeneration). Assets
are normalized once (dict/pydantic), all images are listed in the prompt
("USER IMAGES (must appear in the rendered page)"), and
`inject_user_assets()` is the deterministic backstop: any image not present
in the shipped files replaces the first placeholder `<img src>` in a
hero/about/portfolio section, or is injected into the first section. The
imagery-enforcement pass runs BEFORE this one and already treats
`/uploads/` as good, so curated stock can never overwrite a user photo.

**3. Placeholder names were shipped verbatim.** `fix_placeholder_names()`
replaces PortfolioName / Your Name / John Doe / Company Name / Acme Corp /
... with the brief's real name across jsx/tsx/html/css on every create.

## Server responsiveness: generations no longer freeze the API (2026-10-01)

As-user test caught it: during a generation, `/api/health`, `/api/auth/login`
and `/api/assets` all hung (login timed out at 30 s) -- the app looked broken
while building. Two causes:
  * the legacy single-shot stream iterated the sync `providers.stream()`
    generator directly on the event loop -> the whole server blocked for the
    entire generation. Tokens are now pulled one at a time through
    `asyncio.to_thread`, so the loop keeps serving;
  * a `__ERROR__` payload did not terminate the SSE generator -- it fell
    through into the legacy path, silently re-generating for another 10
    minutes (the 607 s "portfolio" run that was actually a crashed agent
    run). Error payloads now `return`.
Verified live: two concurrent generations running, health 200 in 0.2 s and
login 200 in 0.4 s.

**Also:** `AuthContext` no longer logs the user out when `/api/auth/me` hits
a transient 5xx (a busy backend was wiping the session mid-flow and bouncing
Generate -> /login); only a real 401 clears the token.

## Documentation deliverables: report, deck and IEEE paper (2026-10-02)

The BVDET templates were rewritten end to end from project facts without
touching their design. Everything is driven by scripts under
`backend/docs_build/` so any page number or figure can be regenerated.

* **Report** (`Terabit_Studio_MajorProject_Report.docx`): built by cloning the
  template, so styles, headers, footers, chapter dividers, contents table and
  figure list keep their original formatting. `fix_docx.py` fills Chapter 1.1.1
  with context prose, fills the empty Chapter 3 with the five stage methodology,
  corrects the measured facts (48 backend modules and about 17,000 lines, median
  1,042 s, mean 2,678 s, longest run 29,589 s), strips the doubled `[n]` labels
  from the auto numbered reference list, removes the template's `WRITE HERE`,
  `ITEM` and manual-testing notes, collapses 595 filler paragraphs, and forces
  every chapter onto a fresh page. Result: 34 pages, no blank page, no leftover
  placeholder.
* **Figures**: the screenshots chapter now carries the newest evidence captures
  (Casa Verde restaurant, Hartwell and Sawyer law firm, employee management
  dashboard, portfolio, mobile commerce) plus the trimmed pipeline and
  architecture diagrams, the latest builder and landing page UI, and the two
  IEEE paper pages. Page numbers in the contents and figure list are measured
  from the rendered PDF by `measure_pages.py` and written back by `fix_docx.py`.
* **Deck** (`Terabit_Studio_MajorProject_Presentation.pptx`): `fix_pptx.py` fills
  the guide line and the project member table, renumbers every slide, and
  rewrites the contents table to the real slide numbers; `trim_pptx.py` replaces
  the dense slides with shorter bullets because PowerPoint renders four of them
  past the slide edge. Verified by exporting all 16 slides through PowerPoint.
* **Paper** (`Terabit_Studio_IEEE_Research_Paper.pdf`): the two column IEEEtran
  style manuscript, 8 pages, with the student author block, the guide line and
  the acknowledgment updated, then re-printed with headless Chrome. Its first
  two pages are dropped into the report's research publication chapter.
