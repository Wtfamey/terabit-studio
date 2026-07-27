# DEPRECATED - DO NOT USE
#
# This script targeted llama.cpp's `llama-train` CLI tool for direct GGUF
# LoRA training. That tool was removed from llama.cpp a long time ago - if
# you ran the command this script prints, it would fail with something like
# "'llama-train' is not recognized as an internal or external command",
# because the binary simply doesn't exist in current llama.cpp builds.
#
# It also used a broken dataset (TRAINING_DATA below is prose DESCRIBING a
# UI, not actual code - the same issue the original train.py had).
#
# Use train_unsloth.py (recommended) or train.py instead, fed by real data
# from generate_training_data.py. See those files' docstrings for the full
# procedure.
