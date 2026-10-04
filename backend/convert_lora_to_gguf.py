import os
import sys
import subprocess

# Configuration
LORA_PATH = "./qwen-finetuned-lora/checkpoint-30"
BASE_MODEL = "Qwen/Qwen2.5-7B-Instruct"  # Hugging Face model ID
GGUF_OUTPUT = "./qwen2.5-7b-finetuned-lora.gguf"

def main():
    print("Converting LoRA adapter to GGUF format using llama.cpp...")
    
    # Use llama.cpp's convert_lora_to_gguf.py
    llama_cpp_dir = "../llama.cpp"
    convert_script = os.path.join(llama_cpp_dir, "convert_lora_to_gguf.py")
    
    if not os.path.exists(convert_script):
        print(f"Error: {convert_script} not found")
        return
    
    # Use training environment Python which has PyTorch
    train_env_python = "../train_env/Scripts/python.exe"
    if os.path.exists(train_env_python):
        python_exe = train_env_python
    else:
        python_exe = sys.executable
    
    cmd = [
        python_exe,
        convert_script,
        str(LORA_PATH),
        "--outfile", str(GGUF_OUTPUT),
        "--base-model-id", BASE_MODEL,
        "--outtype", "f16"
    ]
    
    print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    print(result.stdout)
    if result.stderr:
        print(result.stderr)
    
    if result.returncode == 0:
        print(f"\n{'='*60}")
        print(f"Done! LoRA adapter converted to {GGUF_OUTPUT}")
        print(f"Use this with the base GGUF model via --lora flag in llama-server")
        print(f"{'='*60}")
    else:
        print(f"Error: Conversion failed with return code {result.returncode}")

if __name__ == "__main__":
    main()
