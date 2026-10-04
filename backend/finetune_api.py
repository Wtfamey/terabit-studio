"""In-house fine-tuning API -- the "train your own coding model" feature.

Exposes the offline pipeline (generate_training_data.py -> train_unsloth.py ->
export GGUF -> ollama serve -> eval gate -> promote) as HTTP endpoints so the
product UI can offer "teach Terabit your patterns" without a human shell.

  POST /api/finetune/dataset       generate teacher examples (Gemini chain)
  POST /api/finetune/train         start a QLoRA run only (background thread)
  POST /api/finetune/retrain       full loop: unload -> train -> serve ->
                                   eval -> gate -> promote (no human needed)
  GET  /api/finetune/status        current job status + log tail
  GET  /api/finetune/pipeline      phase timeline, progress %, gate history
  GET  /api/finetune/dataset/stats dataset size, trainable count, time estimate
  GET  /api/finetune/models        Ollama model zoo + which tag is live
  POST /api/finetune/cancel        request cancellation (kills the phase proc)

Consumer-laptop notes (RTX 3050 6GB / 16GB RAM, measured):
  - 3584-token seq, batch 1 x grad-accum 2 -> ~66-80 s/step, so a 58-example
    dataset is ~40 min/epoch and 3 epochs is ~2 h.
  - Export (merge -> f16 GGUF -> Q4_K_M -> ollama create) is ~10 min and uses
    no GPU at all, so a failure there never costs more than a re-run
    (POST /api/finetune/export).
  - Ollama keeps ~4.5 GB resident while a model is loaded. Training needs that
    VRAM back, so the pipeline starts by unloading the served model
    (`ollama stop <tag>`) instead of asking a human to quit Ollama.
  - The candidate is created under its own tag and evaluated through the LIVE
    backend with a per-request model override, so the served model is never
    swapped mid-run. Promotion is a hot-swap: os.environ + .env, no restart.

Jobs are single-flight (one GPU phase at a time); state is derived from files
on disk so it survives a backend restart.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

HERE = Path(__file__).parent
PROJECT = HERE.parent
VENV_PY = PROJECT / "train_env" / "Scripts" / "python.exe"

WORK_DIR = Path(os.environ.get("RETRAIN_WORK_DIR", "D:/terabit-retrain"))
DATASET = HERE / "training_data.jsonl"
HISTORY_FILE = HERE / "eval_gate_history.json"

# llama.cpp toolchain used for the export chain (verified on this box).
LLAMA_CPP_DIR = Path(os.environ.get("LLAMA_CPP_DIR", "D:/terabit-retrain/llama.cpp"))
LLAMA_BIN_DIR = Path(os.environ.get("LLAMA_BIN_DIR", "D:/terabit-retrain/llama-bin"))
QUANT = os.environ.get("GGUF_QUANT", "Q4_K_M")

# Measured on this box (see module docstring); override if you retrain on
# different hardware so the UI's time estimate stays honest.
SEC_PER_STEP = float(os.environ.get("TERABIT_SEC_PER_STEP", "75"))
EFFECTIVE_BATCH = 2  # BATCH_SIZE(1) x GRADIENT_ACCUMULATION(2) in train_unsloth.py
# merge -> convert -> quantize -> ollama create, measured on this box: 15.2 GB
# merge ~4 min, f16 GGUF ~1 min, Q4_K_M ~2 min, create ~0.5 min. Disk-bound and
# GPU-free, but long enough that the UI has to budget for it.
EXPORT_MINUTES = float(os.environ.get("TERABIT_EXPORT_MINUTES", "10"))
EVAL_MINUTES_PER_PROMPT = float(os.environ.get("TERABIT_EVAL_MIN_PER_PROMPT", "9"))

GATE_FLOOR = 75.0          # absolute S6 (tier-1 build %) a candidate must clear
LIVE_TAG_FALLBACK = "terabit-finetuned-v2"

router = APIRouter(prefix="/api/finetune", tags=["finetune"])

_job_lock = threading.Lock()
_job: dict = {}
_proc: subprocess.Popen | None = None
_cancel = threading.Event()
_pipeline: dict = {"running": False, "phases": [], "candidate": "", "results": {}}


# ───────────────────────────── process plumbing ─────────────────────────────

def _popen(cmd: list, log_path: Path, cwd: Path | None = None,
           env: dict | None = None) -> subprocess.Popen:
    global _proc
    with open(log_path, "ab") as log:
        _proc = subprocess.Popen(cmd, stdout=log, stderr=log, cwd=cwd, env=env)
    _job["pid"] = _proc.pid
    return _proc


def _run(cmd: list, log_path: Path, cwd: Path | None = None,
         env: dict | None = None) -> int:
    return _popen(cmd, log_path, cwd=cwd, env=env).wait()


def _start(kind: str, cmd: list, env: dict | None = None):
    if not _job_lock.acquire(blocking=False):
        raise HTTPException(409, "A fine-tuning job is already running")
    _cancel.clear()

    def runner():
        _job.update({"kind": kind, "status": "running", "started": time.time()})
        try:
            code = _run(cmd, HERE / f"finetune_{kind}.log", env=env)
            _job["status"] = "done" if code == 0 else "failed"
        except Exception as e:  # noqa: BLE001
            _job["status"] = "failed"
            _job["error"] = str(e)
        finally:
            _job["finished"] = time.time()
            _job_lock.release()

    threading.Thread(target=runner, daemon=True).start()


def _tail(path: Path, lines: int = 12) -> list[str]:
    if not path.exists():
        return []
    try:
        return path.read_text(errors="replace").strip().splitlines()[-lines:]
    except OSError:
        return []


# ───────────────────────────── helpers ─────────────────────────────

def _vram_free_mb() -> float | None:
    """Free VRAM in MB, or None when nvidia-smi is unavailable (non-NVIDIA)."""
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.free,memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=20,
        )
        if r.returncode == 0 and r.stdout.strip():
            free, _total = (float(x) for x in r.stdout.strip().splitlines()[0].split(","))
            return free
    except (OSError, subprocess.SubprocessError, ValueError):
        pass
    return None


def _ollama_models() -> list[dict]:
    try:
        r = subprocess.run(["ollama", "list"], capture_output=True, text=True,
                           timeout=30)
    except (OSError, subprocess.SubprocessError):
        return []
    out = []
    for line in (r.stdout or "").splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 3 and parts[0] != "NAME":
            out.append({"name": parts[0], "size": parts[2] + (parts[3] if len(parts) > 3 and not parts[3].isdigit() else "")})
    return out


def _load_history() -> dict:
    """Gate history, seeded from the v2 promotion gate (10/10 tier-1, n=10)."""
    default = {
        "live": {"tag": os.environ.get("MODEL_NAME", LIVE_TAG_FALLBACK),
                 "s6": 100.0, "n": 10, "at": "2026-09-26T00:00:00",
                 "note": "v2 + agent pipeline gate: 10/10 tier-1 (eval_agent_*.json)"},
        "candidates": [],
    }
    try:
        data = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        data.setdefault("candidates", [])
        data.setdefault("live", default["live"])
        return data
    except (OSError, json.JSONDecodeError):
        return default


def _save_history(data: dict) -> None:
    HISTORY_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _dataset_examples() -> list[dict]:
    out = []
    if not DATASET.exists():
        return out
    for line in DATASET.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _approx_tokens(example: dict) -> int:
    """Same estimator train_unsloth.py uses (1 token ~= 4 chars of code + 48
    for the ChatML template) so the UI's numbers match the trainer's."""
    return (len(example.get("instruction", "")) + len(example.get("output", ""))) // 4 + 48


def _hf_base_snapshot() -> Path | None:
    """fp16 HF snapshot of the base model to merge the LoRA into.

    The merge MUST run against full-precision weights: applying the deltas to
    the 4-bit base the trainer loaded gives wrong weights. Autodiscovers the
    HF cache entry (with an env override); returns None when missing.
    """
    override = os.environ.get("HF_BASE_DIR", "")
    if override and Path(override).exists():
        return Path(override)
    hub = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface")) / "hub"
    for snap in sorted(hub.glob("models--Qwen--Qwen2.5-7B-Instruct/snapshots/*/")):
        if list(snap.glob("model-*.safetensors")):
            return snap
    return None


def _export_quantized_gguf(kind: str, lora_dir: Path, merged_out: Path,
                           entry: dict | None = None) -> Path:
    """Adapter -> merged fp16 HF -> f16 GGUF -> q4_K_M GGUF (streaming).

    Split into three logged subprocesses because each was a real failure
    point on this laptop: the merge is RAM-bound (mmap, ~3 GB peak), the
    convert writes a ~15 GB transient f16 GGUF, and llama-quantize is the
    only step that needs the bin/ toolchain. Progress is mirrored into
    `entry["detail"]` so the UI timeline shows which sub-step is running.
    """
    if not VENV_PY.exists():
        raise RuntimeError("training venv python missing (train_env/)")
    base = _hf_base_snapshot()
    if base is None:
        raise RuntimeError(
            "no fp16 base snapshot for Qwen2.5-7B-Instruct; set HF_BASE_DIR"
        )
    convert_script = LLAMA_CPP_DIR / "convert_hf_to_gguf.py"
    quantize_bin = LLAMA_BIN_DIR / f"llama-quantize{'.exe' if os.name == 'nt' else ''}"
    if not convert_script.exists():
        raise RuntimeError(f"llama.cpp convert script not found at {convert_script}")
    if not quantize_bin.exists():
        raise RuntimeError(f"llama-quantize not found at {quantize_bin}")

    if entry is not None:
        entry["detail"] = "merging LoRA into fp16 base (streaming mmap)"
    # -u matters: without unbuffered stdout these logs only land on disk when
    # the step EXITS, so the dashboard's log tail is blank for the whole
    # 10-20 minute merge/convert and a user can't tell progress from a hang.
    code = _run([str(VENV_PY), "-u", str(HERE / "merge_lora_to_safetensors.py"),
                 "--base", str(base), "--adapter", str(lora_dir),
                 "--out", str(merged_out)], HERE / f"finetune_merge_{kind}.log")
    if code != 0:
        raise RuntimeError(f"merge failed (exit {code}) -- see finetune_merge_{kind}.log")

    if entry is not None:
        entry["detail"] = "converting merged model to f16 GGUF"
    f16 = WORK_DIR / f"{kind}-f16.gguf"
    code = _run([str(VENV_PY), "-u", str(convert_script), str(merged_out),
                 "--outfile", str(f16), "--outtype", "f16"],
                HERE / f"finetune_convert_{kind}.log")
    if code != 0 or not f16.exists():
        raise RuntimeError(f"convert failed (exit {code}) -- see finetune_convert_{kind}.log")

    if entry is not None:
        entry["detail"] = f"quantizing to {QUANT}"
    out = WORK_DIR / f"{kind}-{QUANT.lower()}.gguf"
    code = _run([str(quantize_bin), str(f16), str(out), QUANT],
                HERE / f"finetune_quantize_{kind}.log")

    # (llama-quantize streams its own progress to stderr, which is unbuffered.)
    if code != 0 or not out.exists():
        raise RuntimeError(f"quantize failed (exit {code}) -- see finetune_quantize_{kind}.log")

    # Reclaim the ~15 GB transient f16 + merged shards; the q4 artifact is all
    # the serving path needs and this box's C: drive is tight.
    try:
        f16.unlink()
        shutil.rmtree(merged_out, ignore_errors=True)
    except OSError:
        pass
    return out


def _next_candidate_tag() -> str:
    """terabit-finetuned-v<N> where N = highest existing version + 1."""
    highest = 1
    for m in _ollama_models():
        mt = re.match(r"^terabit-finetuned-v(\d+)(:latest)?$", m["name"])
        if mt:
            highest = max(highest, int(mt.group(1)))
    live = os.environ.get("MODEL_NAME", "")
    mt = re.match(r"^terabit-finetuned-v(\d+)$", live)
    if mt:
        highest = max(highest, int(mt.group(1)))
    return f"terabit-finetuned-v{highest + 1}"


def _set_live_model(tag: str) -> None:
    """Hot-swap the served model: in-process env (no restart) + .env for the
    next boot. .env is backed up once per session before the first edit."""
    os.environ["MODEL_NAME"] = tag
    env_file = PROJECT / ".env"
    if not env_file.exists():
        return
    backup = PROJECT / ".env.retrain-backup"
    if not backup.exists():
        shutil.copyfile(env_file, backup)
    text = env_file.read_text(encoding="utf-8")
    if re.search(r"^MODEL_NAME=.*$", text, flags=re.MULTILINE):
        text = re.sub(r"^MODEL_NAME=.*$", f"MODEL_NAME={tag}", text,
                      count=1, flags=re.MULTILINE)
    else:
        text = text.rstrip("\n") + f"\nMODEL_NAME={tag}\n"
    env_file.write_text(text, encoding="utf-8")


# ───────────────────────────── request schemas ─────────────────────────────

class DatasetRequest(BaseModel):
    count: int = 25
    business_types: list[str] | None = None


class TrainRequest(BaseModel):
    max_seq_length: int = 3584
    epochs: int = 3


class RetrainRequest(BaseModel):
    max_seq_length: int = 3584
    epochs: int = 3
    eval_limit: int = 4          # prompts graded; 10 = full gate (~1 h extra)
    gate_margin: float = 0.0     # allowed S6 drop vs the live model
    auto_promote: bool = True
    tag: str = ""                # override candidate tag (default: next v<N>)


# ───────────────────────────── simple jobs ─────────────────────────────

@router.post("/dataset")
def build_dataset(req: DatasetRequest):
    """Generate new teacher examples (uses GEMINI_API_KEY; quota-rotating)."""
    if not os.environ.get("GEMINI_API_KEY"):
        raise HTTPException(400, "GEMINI_API_KEY not configured")
    (HERE / "finetune_dataset.log").write_bytes(b"")
    _start("dataset", [
        sys.executable, str(HERE / "generate_training_data.py"),
        "--count", str(req.count),
    ])
    return {"status": _job.get("status"), "kind": "dataset"}


@router.post("/train")
def start_train(req: TrainRequest):
    """Start a QLoRA training run (requires the CUDA training venv)."""
    if not VENV_PY.exists():
        raise HTTPException(400, "Training venv not found (train_env/)")
    if _vram_free_mb() is not None:
        live = os.environ.get("MODEL_NAME", LIVE_TAG_FALLBACK)
        subprocess.run(["ollama", "stop", live], capture_output=True, text=True,
                       timeout=60)
    (HERE / "finetune_train.log").write_bytes(b"")
    env = {
        **os.environ,
        "MAX_SEQ_LENGTH": str(req.max_seq_length),
        "TARGET_EPOCHS": str(req.epochs),
        "OUTPUT_DIR": str(WORK_DIR / "qwen-finetuned-lora"),
        "GGUF_OUTPUT_DIR": str(WORK_DIR / "qwen2.5-7b-finetuned-gguf"),
    }
    _start("train", [str(VENV_PY), str(HERE / "train_unsloth.py")], env=env)
    return {"status": _job.get("status"), "kind": "train"}


# ───────────────────────────── full retrain loop ─────────────────────────────

def _phase(name: str, label: str) -> dict:
    entry = {"name": name, "label": label, "status": "running", "detail": "",
             "started": time.time()}
    _pipeline["phases"].append(entry)
    return entry


def _train_progress() -> dict | None:
    """Parse the last tqdm line of the training log -> {step, total, pct}."""
    log = HERE / "finetune_train.log"
    if not log.exists():
        return None
    try:
        text = log.read_text(errors="replace")
    except OSError:
        return None
    matches = re.findall(r"(\d+)/(\d+) \[", text)
    if not matches:
        return None
    step, total = int(matches[-1][0]), int(matches[-1][1])
    return {"step": step, "total": total,
            "pct": round(100 * step / total, 1) if total else None}


def _retrain_runner(cfg: RetrainRequest) -> None:
    def cancel_requested() -> bool:
        return _cancel.is_set()

    candidate = cfg.tag.strip() or _next_candidate_tag()
    lora_dir = WORK_DIR / f"lora-{candidate}"
    merged_dir = WORK_DIR / f"merged-{candidate}"
    eval_out = HERE / f"eval_gate_{candidate}.json"

    _pipeline.update({
        "running": True, "candidate": candidate, "started": time.time(),
        "phases": [], "results": {}, "error": "",
    })

    def fail(entry: dict, msg: str) -> None:
        entry.update({"status": "failed", "detail": msg, "finished": time.time()})
        _pipeline["error"] = msg

    # 1) Free the VRAM the served model is holding -------------------------
    entry = _phase("unload", "Free VRAM (unload served model)")
    live_tag = os.environ.get("MODEL_NAME", LIVE_TAG_FALLBACK)
    try:
        subprocess.run(["ollama", "stop", live_tag], capture_output=True,
                       text=True, timeout=90)
        free = _vram_free_mb()
        entry.update({"status": "done", "finished": time.time(),
                      "detail": f"unloaded {live_tag}; {free:.0f} MB VRAM free"
                                if free else f"unloaded {live_tag}"})
    except (OSError, subprocess.SubprocessError) as e:
        entry.update({"status": "done", "detail": f"best-effort: {e}",
                      "finished": time.time()})

    if cancel_requested():
        return
    if not VENV_PY.exists():
        fail(_phase("train", "QLoRA training"), "training venv missing (train_env/)")
        return
    if not DATASET.exists():
        fail(_phase("train", "QLoRA training"),
             "no training_data.jsonl -- generate the dataset first")
        return

    # 2) Train ------------------------------------------------------------
    entry = _phase("train", "QLoRA training (unsloth)")
    _job.update({"kind": "retrain", "pid": None})
    (HERE / "finetune_train.log").write_bytes(b"")
    env = {
        **os.environ,
        "MAX_SEQ_LENGTH": str(cfg.max_seq_length),
        "TARGET_EPOCHS": str(cfg.epochs),
        "OUTPUT_DIR": str(lora_dir),
        # skip unsloth's in-trainer merge+export: it needs the whole 7B model
        # resident and dies on a 6 GB card AFTER hours of training. The
        # export phase below does it streaming instead.
        "EXPORT_GGUF": "0",
    }
    code = _run([str(VENV_PY), "-u", str(HERE / "train_unsloth.py")],
                HERE / "finetune_train.log", env=env)
    if cancel_requested() or code != 0:
        fail(entry, f"exit code {code}" if code != 0 else "cancelled")
        return
    adapters = list(lora_dir.glob("adapter_model.safetensors"))
    if not adapters:
        fail(entry, f"no LoRA adapter produced in {lora_dir}")
        return
    entry.update({"status": "done", "finished": time.time(),
                  "detail": f"adapter saved to {lora_dir.name}"})

    if cancel_requested():
        return

    # 3) Export: merge -> convert -> quantize (streaming, laptop-sized) -----
    entry = _phase("export", f"Export GGUF ({QUANT})")
    _job["pid"] = None
    try:
        gguf = _export_quantized_gguf(candidate, lora_dir, merged_dir, entry)
    except RuntimeError as e:
        fail(entry, str(e))
        return
    if cancel_requested():
        return
    entry.update({"status": "done", "finished": time.time(),
                  "detail": f"{gguf.name} ({gguf.stat().st_size / 2**30:.2f} GB)"})

    # 4) Serve the candidate under its own tag (live model untouched) -----
    entry = _phase("serve", f"Create Ollama model {candidate}")
    _job["pid"] = None
    modelfile = WORK_DIR / f"Modelfile.{candidate}"
    # Bare FROM on purpose: the promoted v2 model (`ollama show ... --modelfile`)
    # carries no TEMPLATE/PARAMETER lines, so it serves with the GGUF's own
    # ChatML template and per-request options only. Adding params here would
    # make the candidate serve differently from the incumbent and bias the
    # gate comparison.
    modelfile.write_text(f"FROM {gguf}\n", encoding="utf-8")
    (HERE / "finetune_serve.log").write_bytes(b"")
    code = _run(["ollama", "create", candidate, "-f", str(modelfile)],
                HERE / "finetune_serve.log")
    if cancel_requested() or code != 0:
        fail(entry, f"ollama create exit {code}" if code != 0 else "cancelled")
        return
    created = next(iter(_tail(HERE / "finetune_serve.log", 1)), "")
    entry.update({"status": "done", "finished": time.time(),
                  "detail": f"{candidate} ready. {created[:120]}"})

    if cancel_requested():
        return

    # 5) Eval the candidate through the LIVE backend (per-request model) ---
    entry = _phase("eval", f"Eval {cfg.eval_limit} prompts (candidate only)")
    _job["pid"] = None
    port = os.environ.get("LLAMA_API_PORT", "8000")
    base_url = f"http://127.0.0.1:{port}"
    (HERE / "finetune_eval.log").write_bytes(b"")
    cmd = [sys.executable, str(HERE / "eval_harness.py"), "--mode", "live",
           "--limit", str(cfg.eval_limit), "--base-url", base_url,
           "--out", str(eval_out), "--model", candidate]
    code = _run(cmd, HERE / "finetune_eval.log")
    s6 = None
    if eval_out.exists():
        try:
            s6 = json.loads(eval_out.read_text(encoding="utf-8")).get(
                "summary", {}).get("s6_tier1_build_pct")
        except (OSError, json.JSONDecodeError):
            s6 = None
    if cancel_requested() or code != 0 or s6 is None:
        fail(entry, f"eval failed (exit {code})" if code != 0 else
             ("cancelled" if cancel_requested() else "no S6 in eval output"))
        return
    entry.update({"status": "done", "finished": time.time(),
                  "detail": f"S6 tier-1 build = {s6}% over {cfg.eval_limit} prompts"})
    _pipeline["results"]["s6"] = s6
    _pipeline["results"]["eval_file"] = eval_out.name

    # 6) Gate against the recorded live baseline --------------------------
    entry = _phase("gate", "Gate vs live baseline")
    history = _load_history()
    live_s6 = float(history.get("live", {}).get("s6") or 0.0)
    threshold = max(GATE_FLOOR, live_s6 - cfg.gate_margin)
    passed = s6 >= threshold
    detail = (f"candidate {s6}% vs live {live_s6}% (threshold {threshold}%) -> "
              f"{'PASS' if passed else 'FAIL'}")
    entry.update({"status": "done", "finished": time.time(), "detail": detail})
    _pipeline["results"]["gate_pass"] = passed
    history.setdefault("candidates", []).append({
        "tag": candidate, "s6": s6, "n": cfg.eval_limit,
        "at": datetime.now().isoformat(timespec="seconds"),
        "gate_pass": passed, "eval_file": eval_out.name,
    })
    _save_history(history)

    if not passed or not cfg.auto_promote:
        reason = ("gate failed -- live model stays put"
                  if not passed else "auto_promote disabled -- promote manually")
        _phase("promote", "Promote candidate").update(
            {"status": "skipped", "finished": time.time(), "detail": reason})
        if not passed:
            _pipeline["error"] = detail
        return

    # 7) Promote: hot-swap the served tag (no restart), warm it up ---------
    entry = _phase("promote", f"Promote {candidate} to live")
    _set_live_model(candidate)
    try:
        subprocess.run(["ollama", "stop", live_tag], capture_output=True,
                       text=True, timeout=60)
        from model_service import warm_up_model_async
        warm_up_model_async()
        detail = f"live model is now {candidate} (.env updated; backup .env.retrain-backup)"
    except Exception as e:  # noqa: BLE001
        detail = f"swapped to {candidate}, warm-up skipped: {e}"
    history["live"] = {"tag": candidate, "s6": s6, "n": cfg.eval_limit,
                       "at": datetime.now().isoformat(timespec="seconds")}
    _save_history(history)
    entry.update({"status": "done", "finished": time.time(), "detail": detail})


@router.post("/retrain")
def start_retrain(req: RetrainRequest):
    """One-click loop: train -> serve -> eval -> gate -> promote.

    Runs detached; poll /api/finetune/pipeline for the phase timeline.
    """
    if not _job_lock.acquire(blocking=False):
        raise HTTPException(409, "A fine-tuning job is already running")
    _cancel.clear()

    def runner():
        try:
            _retrain_runner(req)
        except Exception as e:  # noqa: BLE001
            _pipeline["error"] = str(e)
            for p in _pipeline["phases"]:
                if p["status"] == "running":
                    p.update({"status": "failed", "detail": str(e),
                              "finished": time.time()})
        finally:
            _pipeline["running"] = False
            _pipeline["finished"] = time.time()
            _job.update({"kind": "retrain", "status": "done"})
            _job_lock.release()

    threading.Thread(target=runner, daemon=True).start()
    return {
        "status": "running",
        "candidate": req.tag.strip() or _next_candidate_tag(),
        "phases": ["unload", "train", "serve", "eval", "gate", "promote"],
    }


# ───────────────────────────── status / inspect ─────────────────────────────

class ExportRequest(BaseModel):
    adapter_dir: str = ""     # default: latest lora-* with an adapter in WORK_DIR
    tag: str = ""             # candidate tag to create from the export
    create_model: bool = True  # also `ollama create` the tag after exporting


@router.post("/export")
def start_export(req: ExportRequest):
    """Recover path: merge + quantize an EXISTING adapter without retraining.

    Training and export are separate failure domains (a merge that dies on
    RAM or a missing llama.cpp binary used to mean re-running hours of
    training), so the export is independently re-runnable here.
    """
    adapters = [Path(req.adapter_dir)] if req.adapter_dir else sorted(
        (d for d in WORK_DIR.glob("lora-*") if (d / "adapter_model.safetensors").exists()),
        key=lambda p: p.stat().st_mtime, reverse=True,
    )
    adapter = adapters[0] if adapters else None
    if not adapter or not (adapter / "adapter_model.safetensors").exists():
        raise HTTPException(404, "No LoRA adapter found to export")
    tag = req.tag.strip() or f"{adapter.name.removeprefix('lora-')}-reexport"
    if not _job_lock.acquire(blocking=False):
        raise HTTPException(409, "A fine-tuning job is already running")
    _cancel.clear()

    def runner():
        _job.update({"kind": "export", "status": "running", "started": time.time()})
        entry = _phase("export", f"Export {adapter.name}")
        try:
            gguf = _export_quantized_gguf(tag, adapter, WORK_DIR / f"merged-{tag}", entry)
            entry.update({"status": "done", "finished": time.time(),
                          "detail": f"{gguf.name} ({gguf.stat().st_size / 2**30:.2f} GB)"})
            _pipeline.update({"running": True, "candidate": tag,
                              "phases": [entry], "results": {}})
            modelfile = WORK_DIR / f"Modelfile.{tag}"
            modelfile.parent.mkdir(parents=True, exist_ok=True)
            # Bare FROM: same serving config as the incumbent (see retrain).
            modelfile.write_text(f"FROM {gguf}\n", encoding="utf-8")
            entry = _phase("serve", f"Create Ollama model {tag}")
            code = _run(["ollama", "create", tag, "-f", str(modelfile)],
                        HERE / "finetune_serve.log")
            entry.update({"status": "done" if code == 0 else "failed",
                          "finished": time.time(), "detail": f"ollama create exit {code}"})
            _job["status"] = "done" if code == 0 else "failed"
        except Exception as e:  # noqa: BLE001
            entry.update({"status": "failed", "detail": str(e), "finished": time.time()})
            _job.update({"status": "failed", "error": str(e)})
        finally:
            _pipeline["running"] = False
            _job["finished"] = time.time()
            _job_lock.release()

    threading.Thread(target=runner, daemon=True).start()
    return {"status": "running", "adapter": str(adapter), "tag": tag}


@router.get("/status")
def job_status():
    kind = _job.get("kind", "train")
    log_name = "finetune_train.log" if kind in ("train", "retrain") else f"finetune_{kind}.log"
    return {
        "job": {k: v for k, v in _job.items() if k != "pid"},
        "running": _job_lock.locked(),
        "log_tail": _tail(HERE / log_name),
    }


@router.get("/pipeline")
def pipeline_status():
    """Phase timeline + live progress + gate history for the UI dashboard."""
    entry_progress = _train_progress() if _pipeline.get("running") else None
    history = _load_history()
    # Export/retrain logs are named after the run tag (a standalone /export
    # uses the tag, a retrain uses the candidate tag) -- read whichever is in
    # flight instead of assuming the retrain naming.
    tail_tag = _pipeline.get("candidate") or "export"
    return {
        "running": _pipeline.get("running", False),
        "candidate": _pipeline.get("candidate", ""),
        "error": _pipeline.get("error", ""),
        "expected": [
            {"name": "unload", "label": "Free VRAM (unload served model)"},
            {"name": "train", "label": "QLoRA training (unsloth)"},
            {"name": "export", "label": f"Export GGUF ({QUANT})"},
            {"name": "serve", "label": "Create Ollama model (candidate tag)"},
            {"name": "eval", "label": "Eval candidate through the live backend"},
            {"name": "gate", "label": "Gate vs live baseline"},
            {"name": "promote", "label": "Promote to live (hot-swap)"},
        ],
        "phases": _pipeline.get("phases", []),
        "results": _pipeline.get("results", {}),
        "train_progress": entry_progress,
        "live": history.get("live", {}),
        "candidates": history.get("candidates", [])[-10:],
        "job_running": _job_lock.locked(),
        "log_tails": {
            "train": _tail(HERE / "finetune_train.log", 6),
            "merge": _tail(HERE / f"finetune_merge_{tail_tag}.log", 3),
            "convert": _tail(HERE / f"finetune_convert_{tail_tag}.log", 3),
            "quantize": _tail(HERE / f"finetune_quantize_{tail_tag}.log", 3),
            "serve": _tail(HERE / "finetune_serve.log", 4),
            "eval": _tail(HERE / "finetune_eval.log", 6),
        },
        "hardware": {"vram_free_mb": _vram_free_mb()},
    }


@router.get("/dataset/stats")
def dataset_stats(max_seq_length: int = 3584, epochs: int = 3):
    examples = _dataset_examples()
    lengths = [_approx_tokens(e) for e in examples]
    trainable = [t for t in lengths if t <= max_seq_length]
    steps_per_epoch = max(1, len(trainable) // EFFECTIVE_BATCH)
    planned = steps_per_epoch * epochs
    train_minutes = planned * SEC_PER_STEP / 60
    return {
        "examples": len(examples),
        "trainable": len(trainable),
        "dropped_over_cap": len(lengths) - len(trainable),
        "median_tokens": sorted(lengths)[len(lengths) // 2] if lengths else None,
        "max_tokens": max(lengths) if lengths else None,
        "planned_steps": planned,
        "est_minutes": round(train_minutes, 1),
        "export_minutes": EXPORT_MINUTES,
        "est_total_minutes": round(train_minutes + EXPORT_MINUTES, 1),
        "sec_per_step": SEC_PER_STEP,
        "dataset_path": str(DATASET),
    }


@router.get("/models")
def list_models():
    return {"models": _ollama_models(), "live": os.environ.get("MODEL_NAME", "")}


@router.get("/history")
def gate_history():
    return _load_history()


@router.post("/cancel")
def cancel():
    _cancel.set()
    pid = _job.get("pid")
    if not pid:
        if _job_lock.locked():
            return {"status": "cancellation requested (between phases)"}
        raise HTTPException(404, "No running job")
    try:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], check=True,
                       capture_output=True)
    except subprocess.CalledProcessError:
        raise HTTPException(500, "Failed to kill the job process")
    _job["status"] = "cancelled"
    return {"status": "cancelled"}
