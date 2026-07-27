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

from unsloth import FastLanguageModel
from datasets import Dataset
from trl import SFTTrainer
from transformers import TrainingArguments

# ─── Configuration - kept in sync with train.py's reasoning ───
# Unsloth's own pre-quantized 4-bit weights - much smaller/faster download
# than pulling the full fp16 model and quantizing it yourself.
BASE_MODEL = "unsloth/Qwen2.5-7B-Instruct-bnb-4bit"
OUTPUT_DIR = "./qwen-finetuned-lora"
GGUF_OUTPUT_DIR = "./qwen2.5-7b-finetuned-gguf"
DATASET_PATH = "./training_data.jsonl"

LORA_R = 8
LORA_ALPHA = 16
LORA_DROPOUT = 0.0  # unsloth recommends 0 for its optimized paths
TARGET_MODULES = ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]

BATCH_SIZE = 1
GRADIENT_ACCUMULATION = 2
TARGET_EPOCHS = 3
LEARNING_RATE = 2e-4
WARMUP_STEPS = 20
# Same reasoning as train.py: training examples target one polished
# component each (~800-2500 tokens), so this comfortably covers the chat
# template overhead without needing whole multi-file mega-examples.
MAX_SEQ_LENGTH = 1024
EVAL_HOLDOUT = 10

# GGUF quantization for the final export - q4_k_m matches what you're
# already running via llama-server, so no downstream config changes needed.
GGUF_QUANT_METHOD = "q4_k_m"


OFFLOAD_LAYERS = 14  # offload 14 of 28 layers to CPU to free ~1.7 GB VRAM for training


def main():
    import torch

    print(f"Loading {BASE_MODEL} (4-bit, unsloth)...")
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=BASE_MODEL,
        max_seq_length=MAX_SEQ_LENGTH,
        dtype=None,  # auto-detect based on your GPU
        load_in_4bit=True,
    )

    # Offload some layers to CPU to free VRAM for training
    free_before = torch.cuda.get_device_properties(0).total_memory - torch.cuda.memory_allocated()
    print(f"GPU free before offload: {free_before/1e9:.2f} GB")
    n_layers = model.config.num_hidden_layers
    n_offload = min(OFFLOAD_LAYERS, n_layers - 4)  # keep at least 4 layers on GPU
    for i in range(n_offload):
        model.model.layers[i] = model.model.layers[i].to("cpu")
    torch.cuda.empty_cache()
    free_after = torch.cuda.get_device_properties(0).total_memory - torch.cuda.memory_allocated()
    print(f"Offloaded {n_offload}/{n_layers} layers to CPU")
    print(f"GPU free after offload: {free_after/1e9:.2f} GB")

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
        max_seq_length=MAX_SEQ_LENGTH,
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
    trainer.train()

    model.save_pretrained(OUTPUT_DIR)
    tokenizer.save_pretrained(OUTPUT_DIR)
    print(f"LoRA adapter saved to {OUTPUT_DIR}")

    print(f"Merging and exporting GGUF ({GGUF_QUANT_METHOD}) to {GGUF_OUTPUT_DIR}...")
    model.save_pretrained_gguf(GGUF_OUTPUT_DIR, tokenizer, quantization_method=GGUF_QUANT_METHOD)

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
