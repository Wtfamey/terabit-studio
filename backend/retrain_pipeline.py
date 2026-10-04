"""Retrain pipeline for Terabit Studio -- the full improvement loop as phases:

  train    QLoRA retrain on the v3 dataset -> merged GGUF (space-safe volume)
  serve    create the Ollama model from the new GGUF (tag: terabit-finetuned-v2)
  eval     run the eval harness live and gate against the pre-retrain baseline
  promote  retag v2 -> terabit-finetuned (old one preserved as -v1)
  status   show where the pipeline currently stands

Usage (from backend/, with the training venv):
  ..\\train_env\\Scripts\\python.exe retrain_pipeline.py train
  python retrain_pipeline.py serve
  python retrain_pipeline.py eval
  python retrain_pipeline.py promote
  python retrain_pipeline.py status

Design notes:
  - train runs with the project venv's python (CUDA torch + unsloth live in
    train_env/, NOT the system python -- that one has no CUDA).
  - Before training, `ollama stop`-equivalent unload is requested: Ollama
    keeps the loaded model's weights (~4.5 GB) in VRAM, which starves a 6 GB
    card during training. We ask the user to quit Ollama; it restarts on the
    next `ollama run/serve` transparently.
  - GGUF export goes to a volume with real free space (the f16 merge
    transiently needs ~15 GB); C: with 12 GB free would die mid-export.
  - eval gates on S6 (tier-1 esbuild pass rate) vs the 25% pre-retrain
    baseline (eval_results_live_pretrain*.json, RESEARCH_DRAFT.md 12.2).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
VENV_PY = PROJECT / "train_env" / "Scripts" / "python.exe"

# Space-safe export volume (C: had 11.6 GB free at plan time; the f16 merge
# transiently needs ~15 GB). Override with RETRAIN_WORK_DIR.
WORK_DIR = Path(os.environ.get("RETRAIN_WORK_DIR", "D:/terabit-retrain"))
GGUF_OUT = WORK_DIR / "qwen2.5-7b-finetuned-gguf"
LORA_OUT = WORK_DIR / "qwen-finetuned-lora"

V2_TAG = "terabit-finetuned-v2"
V1_TAG = "terabit-finetuned-v1"
LIVE_TAG = "terabit-finetuned"

PRETRAIN_BASELINE_S6 = 25.0  # % tier-1, RESEARCH_DRAFT.md 12.2
GATE_MIN_S6 = 50.0           # promote only if clearly better than baseline


def _disk_free_gb(path: Path) -> float:
    try:
        usage = shutil.disk_usage(path)
        return usage.free / 2**30
    except OSError:
        return 0.0


def phase_train() -> None:
    if not VENV_PY.exists():
        raise SystemExit(f"training venv python not found at {VENV_PY}")
    free = _disk_free_gb(WORK_DIR if WORK_DIR.exists() else WORK_DIR.anchor)
    if free < 20:
        raise SystemExit(
            f"{WORK_DIR} has {free:.1f} GB free; the GGUF export transiently "
            f"needs ~20 GB (f16 merge). Free space or set RETRAIN_WORK_DIR."
        )
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    print(f"[train] work dir: {WORK_DIR} ({free:.0f} GB free)")
    print("[train] IMPORTANT: quit Ollama first (tray icon -> Quit) so its")
    print("        loaded model frees the ~4.5 GB of VRAM training needs.")
    input("        Press Enter once Ollama is quit (or Ctrl+C to abort)...")
    env = os.environ.copy()
    env["OUTPUT_DIR"] = str(LORA_OUT)
    env["GGUF_OUTPUT_DIR"] = str(GGUF_OUT)
    cmd = [str(VENV_PY), "train_unsloth.py"]
    print(f"[train] launching: {' '.join(cmd)}")
    proc = subprocess.run(cmd, cwd=HERE, env=env)
    if proc.returncode != 0:
        raise SystemExit(f"[train] FAILED with exit code {proc.returncode}")
    ggufs = list(GGUF_OUT.glob("*.gguf"))
    if not ggufs:
        raise SystemExit("[train] no .gguf produced -- check training log above")
    print(f"[train] OK: {', '.join(g.name + f' ({g.stat().st_size/2**30:.2f} GB)' for g in ggufs)}")


def phase_serve() -> None:
    ggufs = sorted(GGUF_OUT.glob("*.gguf"), key=lambda p: p.stat().st_size, reverse=True)
    if not ggufs:
        raise SystemExit(f"[serve] no GGUF at {GGUF_OUT} -- run `train` first")
    gguf = ggufs[0]
    modelfile = WORK_DIR / "Modelfile.v2"
    modelfile.write_text(
        f"FROM {gguf}\n"
        f"PARAMETER num_ctx 16384\n"
        f"PARAMETER temperature 0.85\n",
        encoding="utf-8",
    )
    print(f"[serve] creating Ollama model {V2_TAG} from {gguf.name} (~4-6 min)")
    subprocess.run(["ollama", "create", V2_TAG, "-f", str(modelfile)], check=True)
    print(f"[serve] OK: `ollama run {V2_TAG}` now works")


def _run_eval(tag_hint: str) -> tuple[float, Path]:
    """Swap the served model tag to v2, run the harness, restore env."""
    env_file = PROJECT / ".env"
    backup = PROJECT / ".env.retrain-backup"
    backup.write_text(env_file.read_text(encoding="utf-8"), encoding="utf-8")
    lines = env_file.read_text(encoding="utf-8").splitlines(keepends=True)
    swapped = False
    with env_file.open("w", encoding="utf-8") as f:
        for line in lines:
            if line.startswith("MODEL_NAME="):
                f.write(f"MODEL_NAME={tag_hint}\n")
                swapped = True
            else:
                f.write(line)
    if not swapped:
        with env_file.open("a", encoding="utf-8") as f:
            f.write(f"\nMODEL_NAME={tag_hint}\n")
    print(f"[eval] .env MODEL_NAME -> {tag_hint}; restart the backend manually")
    print(f"[eval] then run:  python eval_harness.py --mode live --limit 4 "
          f"--base-url http://127.0.0.1:8000 --out eval_results_live_v2.json")
    print("[eval] .env backup at .env.retrain-backup; restore after promoting")
    return -1.0, Path("eval_results_live_v2.json")


def _summary_s6(path: Path) -> float | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("summary", {}).get("s6_tier1_build_pct")
    except (OSError, json.JSONDecodeError):
        return None


def phase_eval() -> None:
    v2_tag = V2_TAG
    print("[eval] phase steps (interactive):")
    print(f"   1. backend/.env MODEL_NAME -> {v2_tag} (backup made)")
    _run_eval(v2_tag)
    print("\n[eval] after the harness finishes, re-run: python retrain_pipeline.py gate")


def phase_gate() -> None:
    candidates = sorted(HERE.glob("eval_results_live_v2*.json"))
    if not candidates:
        raise SystemExit("[gate] no eval_results_live_v2*.json found -- run eval first")
    path = candidates[-1]
    s6 = _summary_s6(path)
    if s6 is None:
        raise SystemExit(f"[gate] could not read s6_tier1_build_pct from {path}")
    print(f"[gate] v2 S6 = {s6}% vs pre-retrain baseline {PRETRAIN_BASELINE_S6}%")
    if s6 >= GATE_MIN_S6:
        print(f"[gate] PASS (>= {GATE_MIN_S6}%). Run: python retrain_pipeline.py promote")
    else:
        print(f"[gate] FAIL -- below {GATE_MIN_S6}%. Investigate before promoting;")
        print("       the old model stays live. Consider: more data, higher LoRA r,")
        print("       or 4 epochs. See RESEARCH_DRAFT.md 12.5.")


def phase_promote() -> None:
    print(f"[promote] keeping old model as {V1_TAG}, promoting {V2_TAG} -> {LIVE_TAG}")
    for src, dst in ((V2_TAG, V1_TAG), (V2_TAG, LIVE_TAG)):
        r = subprocess.run(["ollama", "cp", src, dst], check=True)
        if r.returncode != 0:
            raise SystemExit(f"[promote] ollama cp {src} -> {dst} failed")
    print(f"[promote] done: {LIVE_TAG} is now the v2 weights; {V1_TAG} preserves v1")
    print("[promote] restore .env if you edited it: .env.retrain-backup")
    print("[promote] final check: curl http://127.0.0.1:8000/api/health")


def phase_status() -> None:
    print("== retrain pipeline status ==")
    print(f"venv python:      {VENV_PY.exists()} ({VENV_PY})")
    if GGUF_OUT.exists():
        for g in GGUF_OUT.glob("*.gguf"):
            print(f"gguf:             {g.name} ({g.stat().st_size/2**30:.2f} GB)")
    else:
        print("gguf:             not trained yet (run `train`)")
    r = subprocess.run(["ollama", "list"], capture_output=True, text=True)
    print("ollama models:")
    for line in (r.stdout or "").splitlines():
        if line.strip():
            print(f"  {line}")
    for p in sorted(HERE.glob("eval_results_live*.json")):
        print(f"eval result:      {p.name} (S6={_summary_s6(p)}%)")


def main() -> None:
    phases = {"train": phase_train, "serve": phase_serve, "eval": phase_eval,
              "gate": phase_gate, "promote": phase_promote, "status": phase_status}
    if len(sys.argv) < 2 or sys.argv[1] not in phases:
        raise SystemExit(f"usage: python retrain_pipeline.py [{'|'.join(phases)}]")
    phases[sys.argv[1]]()


if __name__ == "__main__":
    main()
