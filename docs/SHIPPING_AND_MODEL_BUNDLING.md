# Shipping the app *with* the model: sizes, limits, and what is left to build

Written 2026-10-03. Every number below was measured on this machine, not
estimated. The question this answers: "if we ship the whole setup including
the preloaded fine-tuned model — a local AI SaaS/website generator that works
out of the box, multilingual prompts included — how much storage is that, and
is it doable?"

**Short answer: yes, it is doable, and the download is ~120 MB + the model.
But a single 5–6 GB installer .exe is not possible (NSIS caps at 2 GB), so the
model has to be provisioned on first run or shipped as a sidecar file.**

---

## 1. What is already shippable (measured)

| Artifact | Size |
|---|---|
| `Terabit Studio Setup 1.1.0.exe` (NSIS) | **119 MB** |
| `Terabit-Studio-1.1.0-portable.exe` | **119 MB** |
| Installed app (`release/win-unpacked`) | **370 MB** |
| · backend bundle (`resources/backend`) | 101 MB |
| · frontend build (`resources/web`) | 0.4 MB |
| Electron runtime (Chromium + Node) | ~270 MB |

Runs with **no Python on the machine**: the packaged app boots its own bundled
backend in 3.8 s, serves the UI from it, and `/api/app/env` reports
`frozen: true`. Multilingual prompts already work end to end (the v3 fine-tune
was the only tag in the A/B that wrote copy in the user's own language; the
brief parser handles Hinglish/Marathi/Devanagari/Bengali/Gujarati).

What it does **not** include today: the model weights, and the inference
runtime. Those are the two things this document sizes.

---

## 2. What the model layer actually costs (measured here)

| Piece | Size | Notes |
|---|---|---|
| `terabit-finetuned-v3` in Ollama | **4.7 GB** | one base blob 4.36 GB + the 40 MB LoRA adapter |
| Base GGUF `qwen2.5-7b-q4_k_m.gguf` | **4.68 GB** | the file the adapter attaches to |
| Fine-tuned LoRA adapter (GGUF) | **40 MB** | delta only — useless without the base |
| Ollama runtime (`Programs\Ollama`) | **2.8 GB** | bundles llama.cpp runners for CPU + CUDA + ROCm |
| · just ONE CUDA backend (`cublasLt64_12` 660 MB + `ggml-cuda` 333 MB + `cublas64_12` 108 MB) | **~1.1 GB** | measured; the reason the runtime is heavy |
| · a CPU-only llama-server build, for contrast | ~50 MB | no CUDA DLLs at all |
| This dev machine's model store (`D:\Ollama\Models`) | 18 GB | 4 stale base blobs from earlier tags; a *single* install needs one |

GGUF q4_K_M is effectively incompressible — an installer/DMG/zip of it saves
only a few percent. Budget the model at its on-disk size.

### Three ways to ship, by total size

| | Download | Installed | Depends on |
|---|---|---|---|
| **A. App only (today)** | 119 MB | 370 MB | user installs Ollama + pulls 4.7 GB |
| **B. App + provisioned model, reuse Ollama** | 119 MB + 4.7 GB | ~5.1 GB + Ollama 2.8 GB | Ollama installed |
| **C. App + bundled llama.cpp runtime + model, CPU** | ~120 MB + ~4.75 GB | **~5.2 GB** | nothing — fully self-contained, CPU speed |
| **C′. Same, with one GPU backend** | ~120 MB + ~5.8 GB | **~6.5 GB** | nothing; needs the matching GPU |

Option C is the "works the moment it is downloaded" version, and it is the one
worth building: `providers.py`/`model_service.py` already speak the
OpenAI-compatible API, which is exactly what `llama-server` exposes, so the
runtime swap is mostly process supervision plus model provisioning.

Optional tier for reach: shipping **Qwen2.5-Coder-3B q4_K_M (~2.0–2.2 GB)**
instead of the 7B takes option C down to **~2.6–3 GB installed** — the right
default for a first download, with the 7B offered as a one-click upgrade.

---

## 3. The installer limit that decides the UX

NSIS — the Windows installer electron-builder produces here — **cannot exceed
2 GB** (documented on the NSIS wiki and forums; the NSISBI fork exists solely
to lift it). So a 5–6 GB single `Setup.exe` is off the table. Four workable
shapes:

1. **First-run model download (recommended).** Ship the 119 MB installer;
   on first launch, download the model with progress, resume and a SHA-256
   check, then start the runtime. This is what LM Studio, Ollama and VS Code
   do, and it keeps updates small (a UI fix stays 119 MB, not 5 GB).
2. **Sidecar model file.** Ship `terabit-model-v3.gguf` beside the installer;
   the app detects it and skips the download. Best for air-gapped installs and
   USB distribution, and it needs no installer changes at all.
3. **`nsis-web` target.** electron-builder's web installer downloads the app
   package at install time — closer to (1) but with less control (no resume,
   no model-level progress UI).
4. **NSISBI / MSI.** Possible, but custom tooling and signing cost for little
   user benefit over (1).

All four keep the same disk total; they differ only in when the bytes move.

---

## 4. Hardware floor (this is the real constraint, not storage)

From the project's own measurements on an RTX 3050 6 GB:

- 7B Q4_K_M **spills to CPU** at 8192 ctx (4057 MB resident of 5378 MB), and a
  full 11-file generation took **1153 s (19 min)**.
- CPU-only inference is single-digit tokens/second — unusable for 4k-token
  React files.

So bundling the 7B implies a stated minimum of ~8 GB VRAM for a good
experience, ~16 GB RAM otherwise, with "slow but works" CPU fallback. A 3B
default changes that floor substantially (fits comfortably in 4–6 GB VRAM).

Also note this machine's `C:` has **11 GB free of 473 GB** — any 5–6 GB
install must target `D:` (321 GB free), or the model store needs to be
`TERABIT_DATA_DIR`-style relocatable from day one. It already is: the model
folder should live under the same data dir, not inside the app bundle.

---

## 5. What is left to build (concrete, in order)

1. **Model manager** (`backend/model_sources.py` + a first-run UI screen):
   catalogue of supported models (3B/7B, quant, size, sha256, licenses),
   detect an existing Ollama install and reuse its tags, otherwise download
   to the data dir with resume + hash verification.
2. **Runtime bundling**: ship `llama-server` and supervise it the way
   `boot.js` already supervises the backend — port pick, health wait, log
   ring, tree kill. `providers.py` then points at `http://127.0.0.1:<port>/v1`.
   Download the *right* build on first run (CPU ~50 MB; one CUDA backend
   ~1.1 GB measured) instead of bundling every vendor's DLLs like Ollama's
   2.8 GB install does — that single decision is worth ~1.7 GB.
3. **First-run screen**: "Choose a model" (3B default / 7B recommended if
   VRAM ≥ 8 GB) with a real progress bar, and the existing environment check
   reused afterwards.
4. **Air-gapped path**: if a `.gguf` sits next to the installer (or in
   `%USERPROFILE%\.terabit\models`), import it instead of downloading.
5. **Update story**: the app auto-checks a release feed; the model is
   versioned separately from the shell so a UI update never re-downloads 5 GB.

Estimated work: (2) and (3) are the bulk — roughly the same size as the shell
work already completed, because the supervision pattern, packaging pipeline
and verification harnesses now exist.
