"""Export a saved QLoRA adapter to GGUF without retraining.

The v2 retrain completed (87/87 steps, adapter saved) but its inline
save_pretrained_gguf died on a transient HF-CDN network error while
fetching the fp16 base shards. This script re-runs ONLY the export:
load base (4-bit) -> attach adapter -> merge -> quantize.

Usage (from backend/, with the training venv):
  OUTPUT_DIR="D:/terabit-retrain/qwen-finetuned-lora" \
  GGUF_OUTPUT_DIR="D:/terabit-retrain/qwen2.5-7b-finetuned-gguf" \
  ../train_env/Scripts/python.exe export_gguf.py
"""

import os
import sys
import time

os.environ.setdefault("UNSLOTH_CE_LOSS_TARGET_GB", "0.3")

from unsloth import FastLanguageModel

OUTPUT_DIR = os.environ.get("OUTPUT_DIR", "./qwen-finetuned-lora")
GGUF_OUTPUT_DIR = os.environ.get("GGUF_OUTPUT_DIR", "./qwen2.5-7b-finetuned-gguf")
QUANT_METHOD = os.environ.get("GGUF_QUANT_METHOD", "q4_k_m")
MAX_SEQ_LENGTH = int(os.environ.get("MAX_SEQ_LENGTH", "3584"))
ATTEMPTS = int(os.environ.get("EXPORT_ATTEMPTS", "4"))


def main():
    if not os.path.exists(os.path.join(OUTPUT_DIR, "adapter_model.safetensors")):
        raise SystemExit(f"No adapter found at {OUTPUT_DIR} -- nothing to export.")

    for attempt in range(1, ATTEMPTS + 1):
        try:
            print(f"[export] attempt {attempt}/{ATTEMPTS}: loading adapter {OUTPUT_DIR}...")
            # Loading the adapter dir directly re-attaches it to the 4-bit base;
            # unsloth resolves the base model from adapter_config.json.
            model, tokenizer = FastLanguageModel.from_pretrained(
                model_name=OUTPUT_DIR,
                max_seq_length=MAX_SEQ_LENGTH,
                dtype=None,
                load_in_4bit=True,
            )
            print(f"[export] merging + quantizing ({QUANT_METHOD}) -> {GGUF_OUTPUT_DIR} ...")
            model.save_pretrained_gguf(GGUF_OUTPUT_DIR, tokenizer, quantization_method=QUANT_METHOD)
            print(f"[export] DONE -> {GGUF_OUTPUT_DIR}")
            return
        except Exception as e:  # noqa: BLE001 - network/CDN failures are heterogeneous
            print(f"[export] attempt {attempt} failed: {type(e).__name__}: {e}")
            if attempt < ATTEMPTS:
                wait = 60 * attempt
                print(f"[export] retrying in {wait}s ...")
                time.sleep(wait)
    raise SystemExit(f"[export] all {ATTEMPTS} attempts failed -- check network and re-run.")


if __name__ == "__main__":
    main()
