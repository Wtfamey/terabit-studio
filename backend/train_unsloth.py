# QLoRA Fine-Tuning for Qwen 2.5 7B via Unsloth
# Recommended path for 4GB VRAM cards (RTX 3050 etc.) - roughly 2x faster and
# meaningfully lower memory than the plain transformers+peft+bitsandbytes
# route in train.py, and includes a one-call merge-to-GGUF export.
#
# Usage:
#   pip install unsloth
#   python generate_training_data.py --count 150   (see that file's docstring)
#   python train_unsloth.py
#
# Output: ./qwen2.5-7b-finetuned-gguf/*.gguf, ready to point MODEL_PATH at.

import json
import os
import random

# Must be set before any unsloth import so TARGET_GB reads it at module init
os.environ["UNSLOTH_CE_LOSS_TARGET_GB"] = "0.3"

from unsloth import FastLanguageModel
from datasets import Dataset
from trl import SFTTrainer
from transformers import TrainingArguments

# Windows + unsloth: transformers checkpoints pickle self.args via torch.save,
# but unsloth re-exports SFTConfig so its class identity no longer matches
# trl.trainer.sft_config.SFTConfig -> PicklingError aborts the run at the first
# checkpoint save (observed live at step 50/87). training_args.bin is
# diagnostic-only, so skip pickling config objects instead of crashing.
import torch as _torch

_orig_torch_save = _torch.save

def _torch_save_skip_configs(obj, *args, **kwargs):
    if obj.__class__.__name__ in ("TrainingArguments", "SFTConfig", "Seq2SeqTrainingArguments"):
        return
    return _orig_torch_save(obj, *args, **kwargs)

_torch.save = _torch_save_skip_configs

# ─── Configuration - kept in sync with train.py's reasoning ───
# Unsloth's own pre-quantized 4-bit weights - much smaller/faster download
# than pulling the full fp16 model and quantizing it yourself.
BASE_MODEL = "unsloth/Qwen2.5-7B-Instruct-bnb-4bit"
# Output paths are env-overridable: the GGUF export transiently writes a
# ~15 GB f16 merge file, which does not fit a nearly-full C: drive -- point
# GGUF_OUTPUT_DIR at a roomier volume (the retrain pipeline does this).
OUTPUT_DIR = os.environ.get("OUTPUT_DIR", "./qwen-finetuned-lora")
GGUF_OUTPUT_DIR = os.environ.get("GGUF_OUTPUT_DIR", "./qwen2.5-7b-finetuned-gguf")
DATASET_PATH = os.environ.get("DATASET_PATH", "./training_data.jsonl")

LORA_R = 8
LORA_ALPHA = 16
LORA_DROPOUT = 0.0  # unsloth recommends 0 for its optimized paths
TARGET_MODULES = ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]

BATCH_SIZE = 1
GRADIENT_ACCUMULATION = 2
TARGET_EPOCHS = int(os.environ.get("TARGET_EPOCHS", "3"))
LEARNING_RATE = 2e-4
WARMUP_STEPS = 20
# Sequence length is derived from the dataset (see main()): with the v3
# single-component teacher strategy, examples fit ~2750 tokens. The historical
# fixed 1024 truncated EVERY example ever trained on mid-code -- the root cause
# of the broken-entry-point pathologies in the v1 LoRA (measured, see
# RESEARCH_DRAFT.md). Cap for 4GB VRAM; override if you have more VRAM.
MAX_SEQ_LENGTH_CAP = int(os.environ.get("MAX_SEQ_LENGTH", "3584"))
EVAL_HOLDOUT = 10

# GGUF quantization for the final export - q4_k_m matches what you're
# already running via llama-server, so no downstream config changes needed.
GGUF_QUANT_METHOD = "q4_k_m"

# EXPORT_GGUF=0 skips unsloth's in-trainer merge+export. That export needs the
# whole 7B model resident (GPU + RAM) and died on this 6 GB / 16 GB laptop
# ("Some modules are dispatched on the CPU or the disk") -- it also only runs
# AFTER hours of training, so a failure there wastes the whole run. The
# retrain pipeline instead saves the adapter here and merges/quantizes with
# merge_lora_to_safetensors.py + llama.cpp, which were verified on this box.
EXPORT_GGUF = os.environ.get("EXPORT_GGUF", "1") not in ("0", "false", "False")


OFFLOAD_LAYERS = 0  # offload 0 layers


def main():
    print(f"Loading {BASE_MODEL} (4-bit, unsloth)...")
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=BASE_MODEL,
        max_seq_length=MAX_SEQ_LENGTH_CAP,  # window for model init; the SFT
        dtype=None,  # trainer uses the dataset-derived max_seq_length below
        load_in_4bit=True,
    )

    model = FastLanguageModel.get_peft_model(
        model,
        r=LORA_R,
        target_modules=TARGET_MODULES,
        lora_alpha=LORA_ALPHA,
        lora_dropout=LORA_DROPOUT,
        bias="none",
        use_gradient_checkpointing="unsloth",  # unsloth's own, more memory-efficient checkpointing
        random_state=3407,
    )

    if not os.path.exists(DATASET_PATH):
        raise SystemExit(
            f"{DATASET_PATH} not found.\n"
            f"Run `python generate_training_data.py --count 150` first to create "
            f"real (instruction, code) training examples."
        )

    data = []
    with open(DATASET_PATH, "r") as f:
        for line in f:
            line = line.strip()
            if line:
                data.append(json.loads(line))

    if len(data) < 20:
        print(f"Warning: only {len(data)} examples found - aim for 100+ to avoid memorization.")

    # Derive MAX_SEQ_LENGTH from the actual data instead of a stale constant:
    # 1 token ~= 4 chars for code. Report coverage so truncation is visible.
    def approx_tokens(example):
        return (len(example["instruction"]) + len(example["output"])) // 4 + 48  # +template

    tok_lengths = [approx_tokens(d) for d in data]
    max_seq_length = min(max(tok_lengths), MAX_SEQ_LENGTH_CAP)
    # Drop over-cap examples instead of truncating them: a truncated example
    # teaches the model to STOP mid-code (the v1 pathology). A smaller set of
    # fully-visible examples beats a larger truncated one.
    trainable = [d for d, t in zip(data, tok_lengths) if t <= MAX_SEQ_LENGTH_CAP]
    dropped = len(data) - len(trainable)
    if dropped:
        print(f"Dropping {dropped}/{len(data)} examples over {MAX_SEQ_LENGTH_CAP} tokens "
              f"(would truncate mid-code and teach premature stopping)")
    data = trainable
    if not data:
        raise SystemExit("No trainable examples remain -- generate more data with "
                         "generate_training_data.py first.")
    tok_lengths = [approx_tokens(d) for d in data]
    print(f"Dataset token lengths: min {min(tok_lengths)}, median {sorted(tok_lengths)[len(tok_lengths)//2]}, "
          f"max {max(tok_lengths)} -> MAX_SEQ_LENGTH={max_seq_length}")

    def format_example(example):
        return {
            "text": f"<|im_start|>system\nYou are TerabitStudio, an elite full-stack developer.\n<|im_end|>\n<|im_start|>user\n{example['instruction']}\n<|im_end|>\n<|im_start|>assistant\n{example['output']}\n<|im_end|>"
        }

    random.shuffle(data)
    holdout = data[:EVAL_HOLDOUT] if len(data) > EVAL_HOLDOUT * 2 else []
    train_data = data[EVAL_HOLDOUT:] if holdout else data

    dataset = Dataset.from_list([format_example(d) for d in train_data])
    eval_dataset = Dataset.from_list([format_example(d) for d in holdout]) if holdout else None

    effective_batch = BATCH_SIZE * GRADIENT_ACCUMULATION
    steps_per_epoch = max(1, len(train_data) // effective_batch)
    max_steps = steps_per_epoch * TARGET_EPOCHS
    print(f"{len(train_data)} training examples, {len(holdout)} held out for eval")
    print(f"{steps_per_epoch} steps/epoch x {TARGET_EPOCHS} epochs = {max_steps} max_steps")

    eval_kwargs = {}
    if eval_dataset is not None:
        eval_kwargs = {
            "eval_strategy": "steps",
            "eval_steps": max(10, steps_per_epoch),
            "per_device_eval_batch_size": BATCH_SIZE,
        }

    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        train_dataset=dataset,
        eval_dataset=eval_dataset,
        dataset_text_field="text",
        max_seq_length=max_seq_length,
        args=TrainingArguments(
            output_dir=OUTPUT_DIR,
            per_device_train_batch_size=BATCH_SIZE,
            gradient_accumulation_steps=GRADIENT_ACCUMULATION,
            max_steps=max_steps,
            learning_rate=LEARNING_RATE,
            fp16=not torch_bf16_supported(),
            bf16=torch_bf16_supported(),
            logging_steps=10,
            save_steps=50,
            warmup_steps=WARMUP_STEPS,
            save_total_limit=2,
            optim="adamw_8bit",
            report_to="none",
            **eval_kwargs,
        ),
    )

    print("Starting training...")
    print("  (out of memory? export MAX_SEQ_LENGTH=3072 and re-run)")
    trainer.train()

    model.save_pretrained(OUTPUT_DIR)
    tokenizer.save_pretrained(OUTPUT_DIR)
    print(f"LoRA adapter saved to {OUTPUT_DIR}")

    if EXPORT_GGUF:
        print(f"Merging and exporting GGUF ({GGUF_QUANT_METHOD}) to {GGUF_OUTPUT_DIR}...")
        model.save_pretrained_gguf(GGUF_OUTPUT_DIR, tokenizer, quantization_method=GGUF_QUANT_METHOD)
    else:
        print("EXPORT_GGUF=0 -> skipping unsloth's in-trainer GGUF export.")
        print("  The retrain pipeline merges + quantizes separately (streaming,")
        print("  fits this laptop): merge_lora_to_safetensors.py ->")
        print("  llama.cpp convert_hf_to_gguf.py -> llama-quantize Q4_K_M.")

    print(f"\n{'='*60}")
    print(f"Done. Point MODEL_PATH in .env / docker-compose.yml at the .gguf file")
    print(f"inside {GGUF_OUTPUT_DIR}, then restart the backend.")
    print(f"Training examples: {len(train_data)} (+{len(holdout)} held out for eval)")
    print(f"{'='*60}")


def torch_bf16_supported() -> bool:
    import torch
    return torch.cuda.is_available() and torch.cuda.is_bf16_supported()


if __name__ == "__main__":
    main()
