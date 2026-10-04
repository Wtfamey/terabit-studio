"""Merge a PEFT LoRA adapter into fp16 base safetensors -- memory-streaming.

Why this exists: merging via unsloth needs the whole 7B model resident in
GPU+CPU RAM (~15 GB) which this box (6 GB VRAM, 16 GB RAM with ~9 GB free)
cannot hold ("Some modules are dispatched on the CPU or the disk"). This
script instead walks the base shards with mmap (safetensors safe_open),
applies delta = B @ A * (alpha/r) per targeted tensor on the fly, and
flushes ~2 GB output shards, keeping peak RAM around 3 GB.

The output is a plain HF-format model directory that llama.cpp's
convert_hf_to_gguf.py accepts directly (--outtype q8_0), which Ollama then
quantizes to q4_k_m via `ollama create --quantize`.

Usage:
  ../train_env/Scripts/python.exe merge_lora_to_safetensors.py \
      --base <snapshot-dir-of-Qwen2.5-7B-Instruct> \
      --adapter <adapter-dir> --out <merged-model-dir>
"""

import argparse
import json
import shutil
from pathlib import Path

import numpy as np
import ml_dtypes  # registers bfloat16 with numpy -- base shards are bf16
from safetensors import safe_open
from safetensors.numpy import save_file

SHARD_TARGET_BYTES = 2_000_000_000  # flush output shards at ~2 GB


def load_adapter(adapter_dir: Path):
    cfg = json.loads((adapter_dir / "adapter_config.json").read_text())
    scale = cfg["lora_alpha"] / cfg["r"]
    deltas = {}  # target_key -> (A, B) both small
    with safe_open(adapter_dir / "adapter_model.safetensors", framework="np") as f:
        for key in f.keys():
            # base_model.model.model.layers.0.mlp.down_proj.lora_A.weight
            #   -> strip the PEFT wrapper, keep "model.layers.N.<module>"
            s = key
            for prefix in ("base_model.model.", "base_model."):
                if s.startswith(prefix):
                    s = s[len(prefix):]
                    break
            parts = s.split(".")
            lora_tag = parts[-2]  # lora_A | lora_B
            target = ".".join(parts[:-2]) + ".weight"  # model.layers.0.mlp.down_proj.weight
            entry = deltas.setdefault(target, {})
            entry[lora_tag] = f.get_tensor(key).astype(np.float32)
    if not deltas:
        raise SystemExit("No LoRA tensors found -- check adapter key format.")
    return scale, deltas


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True, help="HF snapshot dir of the fp16 base model")
    ap.add_argument("--adapter", required=True, help="PEFT adapter dir (adapter_config.json)")
    ap.add_argument("--out", required=True, help="output HF-format model dir")
    args = ap.parse_args()

    base_dir, out_dir = Path(args.base), Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    scale, deltas = load_adapter(Path(args.adapter))
    print(f"[merge] {len(deltas)} target tensors, scale={scale}")

    # Copy config + tokenizer files so the converter sees a complete model dir.
    # The HF base snapshot has no tokenizer files -- take them from the adapter
    # dir (unsloth saved the full tokenizer set alongside the adapter).
    for fname in [
        "config.json", "generation_config.json", "tokenizer.json",
        "tokenizer_config.json", "vocab.json", "merges.txt", "special_tokens_map.json",
        "added_tokens.json", "chat_template.jinja",
    ]:
        for src in (base_dir / fname, Path(args.adapter) / fname):
            if src.exists():
                shutil.copyfile(src, out_dir / fname)
                break

    shard_files = sorted(base_dir.glob("model-*.safetensors"))
    if not shard_files:
        raise SystemExit(f"No model-*.safetensors shards found in {base_dir}")

    weight_map = {}
    total_size = 0
    out_idx = 0
    buf, buf_bytes = {}, 0

    def flush():
        nonlocal out_idx, buf, buf_bytes
        if not buf:
            return
        out_idx += 1
        shard_name = f"model-{out_idx:05d}-of-XXXXX.safetensors"
        save_file(buf, str(out_dir / shard_name))
        for k in buf:
            weight_map[k] = shard_name
        print(f"[merge] wrote {shard_name} ({buf_bytes/1e9:.2f} GB, {len(buf)} tensors)")
        buf, buf_bytes = {}, 0

    applied = set()
    for shard in shard_files:
        with safe_open(str(shard), framework="np") as f:
            for key in f.keys():
                t = f.get_tensor(key)
                if key in deltas:
                    applied.add(key)
                    entry = deltas[key]
                    delta = (entry["lora_B"] @ entry["lora_A"]) * scale
                    merged = (t.astype(np.float32) + delta).astype(np.float16)
                    del delta
                    print(f"[merge] applied delta to {key} {t.shape}")
                else:
                    merged = t
                buf[key] = np.ascontiguousarray(merged)
                buf_bytes += merged.nbytes
                total_size += merged.nbytes
                del merged, t
                if buf_bytes >= SHARD_TARGET_BYTES:
                    flush()
    flush()

    missing = set(deltas) - applied
    if missing:
        raise SystemExit(
            f"{len(missing)} LoRA targets had no matching base tensor "
            f"(e.g. {sorted(missing)[0]}) -- adapter/base mismatch, refusing to ship."
        )
    print(f"[merge] applied {len(applied)}/{len(deltas)} LoRA deltas")

    # Rewrite shard names with the final count and emit the index.
    n_shards = out_idx
    renamed = {}
    for i in range(1, n_shards + 1):
        old = out_dir / f"model-{i:05d}-of-XXXXX.safetensors"
        new = out_dir / f"model-{i:05d}-of-{n_shards:05d}.safetensors"
        old.rename(new)
        renamed[f"model-{i:05d}-of-XXXXX.safetensors"] = new.name

    weight_map = {k: renamed[v] for k, v in weight_map.items()}
    index = {"metadata": {"total_size": total_size}, "weight_map": weight_map}
    (out_dir / "model.safetensors.index.json").write_text(json.dumps(index, indent=2))
    print(f"[merge] DONE: {len(weight_map)} tensors, {total_size/1e9:.2f} GB, "
          f"{n_shards} shards -> {out_dir}")


if __name__ == "__main__":
    main()
