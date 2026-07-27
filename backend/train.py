# QLoRA Fine-Tuning for Qwen 2.5 7B
# Trains on business app code generation examples
# Runs on RTX 3050 4GB with 4-bit quantization
#
# Usage:
#   1. pip install -r requirements-training.txt
#   2. Generate REAL training data first: python generate_training_data.py --count 150
#      (this file no longer falls back to fake description-only data - see note below)
#   3. python train.py
#   4. Convert LoRA to GGUF: python convert_lora_to_gguf.py ./qwen-finetuned-lora
#   5. Replace the model in model_service.py with your fine-tuned GGUF
#
# NOTE: an earlier version of this script fell back to a bundled
# create_sample_dataset() when training_data.jsonl was missing. That fallback
# data was prose DESCRIBING a UI, not actual code - training on it would
# have taught the model to write more descriptions, not more code. It has
# been removed. Run generate_training_data.py to produce real examples.

import torch
import json
import os
import random
from datasets import Dataset
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    TrainingArguments,
    BitsAndBytesConfig,
)
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
from trl import SFTTrainer

# ─── Configuration ───
BASE_MODEL = "Qwen/Qwen2.5-7B-Instruct"
OUTPUT_DIR = "./qwen-finetuned-lora"
DATASET_PATH = "./training_data.jsonl"
USE_4BIT = True  # 4GB VRAM requires 4-bit

# QLoRA config — lower rank saves memory on 4GB cards
# r=8 uses ~350MB less VRAM than r=16 with minimal quality loss
LORA_R = 8
LORA_ALPHA = 16
LORA_DROPOUT = 0.1
TARGET_MODULES = ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]

# Training params — optimized for RTX 3050 4GB
BATCH_SIZE = 1        # 4GB VRAM can only do batch 1
GRADIENT_ACCUMULATION = 4  # Effective batch size = 4
TARGET_EPOCHS = 3     # passes over the whole dataset - computed into MAX_STEPS below
LEARNING_RATE = 2e-4
WARMUP_STEPS = 20     # Gradual LR warmup for stable training
# Training examples now target ONE polished component/page each (~800-2500
# tokens), not whole multi-file projects - see generate_training_data.py.
# 3072 leaves headroom for the chat template + a genuinely complete
# component while staying inside what a 4GB card can hold; if you hit an
# out-of-memory error, drop this to 2048 before touching anything else.
MAX_SEQ_LENGTH = 3072
USE_GRADIENT_CHECKPOINTING = True  # Saves VRAM at cost of ~15% slower training
EVAL_HOLDOUT = 10     # last N examples are held out for eval, not trained on


def main():
    # ─── 4-bit Quantization ───
    bnb_config = BitsAndBytesConfig(
        load_in_4bit=USE_4BIT,
        bnb_4bit_use_double_quant=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16,
    )

    # ─── Load Model ───
    print(f"Loading {BASE_MODEL} with 4-bit quantization...")
    model = AutoModelForCausalLM.from_pretrained(
        BASE_MODEL,
        quantization_config=bnb_config,
        device_map="auto",
        trust_remote_code=True,
    )
    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL, trust_remote_code=True)
    tokenizer.pad_token = tokenizer.eos_token

    # ─── Prepare for k-bit training ───
    model = prepare_model_for_kbit_training(model)
    if USE_GRADIENT_CHECKPOINTING:
        model.gradient_checkpointing_enable()

    # ─── LoRA Config ───
    peft_config = LoraConfig(
        r=LORA_R,
        lora_alpha=LORA_ALPHA,
        lora_dropout=LORA_DROPOUT,
        bias="none",
        task_type="CAUSAL_LM",
        target_modules=TARGET_MODULES,
    )
    model = get_peft_model(model, peft_config)
    model.print_trainable_parameters()  # ~0.5% of params

    # ─── Load Dataset ───
    print(f"Loading dataset from {DATASET_PATH}...")
    if not os.path.exists(DATASET_PATH):
        raise SystemExit(
            f"{DATASET_PATH} not found.\n"
            f"Run `python generate_training_data.py --count 150` first to create "
            f"real (instruction, code) training examples - this script no longer "
            f"falls back to placeholder data."
        )

    data = []
    with open(DATASET_PATH, "r") as f:
        for line in f:
            line = line.strip()
            if line:
                data.append(json.loads(line))

    if len(data) < 20:
        print(
            f"Warning: only {len(data)} examples found. This is thin for fine-tuning - "
            f"aim for 100+ for the model to generalize rather than memorize a handful "
            f"of examples. Continuing anyway."
        )

    # Format as chat
    def format_example(example):
        return {
            "text": f"<|im_start|>system\nYou are TerabitStudio, an elite full-stack developer.\n<|im_end|>\n<|im_start|>user\n{example['instruction']}\n<|im_end|>\n<|im_start|>assistant\n{example['output']}\n<|im_end|>"
        }

    random.shuffle(data)
    holdout = data[:EVAL_HOLDOUT] if len(data) > EVAL_HOLDOUT * 2 else []
    train_data = data[EVAL_HOLDOUT:] if holdout else data

    dataset = Dataset.from_list([format_example(d) for d in train_data])
    eval_dataset = Dataset.from_list([format_example(d) for d in holdout]) if holdout else None

    # MAX_STEPS is derived from the actual dataset size so it scales
    # automatically instead of being a hand-picked number that assumed 25
    # examples. With effective batch size (BATCH_SIZE * GRADIENT_ACCUMULATION)
    # and TARGET_EPOCHS passes over the data:
    effective_batch = BATCH_SIZE * GRADIENT_ACCUMULATION
    steps_per_epoch = max(1, len(train_data) // effective_batch)
    max_steps = steps_per_epoch * TARGET_EPOCHS
    print(f"{len(train_data)} training examples, {len(holdout)} held out for eval")
    print(f"{steps_per_epoch} steps/epoch x {TARGET_EPOCHS} epochs = {max_steps} max_steps")

    # ─── Training Arguments ───
    eval_kwargs = {}
    if eval_dataset is not None:
        eval_kwargs = {
            "eval_strategy": "steps",
            "eval_steps": max(10, steps_per_epoch),
            "per_device_eval_batch_size": BATCH_SIZE,
        }

    training_args = TrainingArguments(
        output_dir=OUTPUT_DIR,
        per_device_train_batch_size=BATCH_SIZE,
        gradient_accumulation_steps=GRADIENT_ACCUMULATION,
        max_steps=max_steps,
        learning_rate=LEARNING_RATE,
        fp16=True,
        logging_steps=10,
        save_steps=50,
        warmup_steps=WARMUP_STEPS,
        save_total_limit=2,
        remove_unused_columns=False,
        report_to="none",
        optim="paged_adamw_8bit",
        **eval_kwargs,
    )

    # ─── Trainer ───
    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        args=training_args,
        train_dataset=dataset,
        eval_dataset=eval_dataset,
        max_seq_length=MAX_SEQ_LENGTH,
        dataset_text_field="text",
    )

    # ─── Train ───
    print("Starting training...")
    trainer.train()

    # ─── Save ───
    model.save_pretrained(OUTPUT_DIR)
    tokenizer.save_pretrained(OUTPUT_DIR)
    print(f"Training complete! Model saved to {OUTPUT_DIR}")
    print(f"\n{'='*60}")
    print(f"HOW TO USE THE FINE-TUNED MODEL")
    print(f"{'='*60}")
    print(f"")
    print(f"Option A — Merge LoRA into GGUF (recommended for llama.cpp/llama-server):")
    print(f"  1. Install: pip install llama-cpp-python")
    print(f"  2. Convert LoRA to GGUF:")
    print(f"     python -m llama_cpp.convert_lora_to_gguf \\")
    print(f"       --base Qwen/Qwen2.5-7B-Instruct-GGUF/qwen2.5-7b-instruct-q4_k_m.gguf \\")
    print(f"       --lora {OUTPUT_DIR} \\")
    print(f"       --output ./qwen2.5-7b-finetuned.gguf")
    print(f"  3. Update model_service.py: set MODEL_PATH to ./qwen2.5-7b-finetuned.gguf")
    print(f"  4. Restart the backend")
    print(f"")
    print(f"Option B — Load directly in Python (if using transformers):")
    print(f"  from peft import PeftModel")
    print(f"  from transformers import AutoModelForCausalLM")
    print(f"  model = AutoModelForCausalLM.from_pretrained('Qwen/Qwen2.5-7B-Instruct')")
    print(f"  model = PeftModel.from_pretrained(model, '{OUTPUT_DIR}')")
    print(f"")
    print(f"Option C — Generate more/different training data:")
    print(f"  python generate_training_data.py --count 200")
    print(f"  then delete training_data.jsonl's old contents (or use --out to write a")
    print(f"  new file and merge) and re-run this script.")
    print(f"")
    print(f"{'='*60}")
    print(f"Expected training time: roughly proportional to max_steps ({max_steps} here) —")
    print(f"budget several hours on an RTX 3050 4GB; watch nvidia-smi during the first")
    print(f"few steps and drop MAX_SEQ_LENGTH if you see an out-of-memory error.")
    print(f"Expected VRAM usage: ~3.8-4.2 GB during training")
    print(f"Training examples: {len(train_data)} (+{len(holdout)} held out for eval)")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
