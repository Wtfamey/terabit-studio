import os
import subprocess
import shutil
from typing import Optional
from dotenv import load_dotenv

load_dotenv()  # .env wasn't being loaded anywhere in this project before - values
# only took effect if manually mirrored into $env: (see run_local.ps1). This makes
# .env itself authoritative, so anything you add there actually takes effect.

from openai import OpenAI

server_process: Optional[subprocess.Popen] = None


def get_client() -> OpenAI:
    host = os.environ.get("LLAMA_SERVER_HOST", "127.0.0.1")
    port = os.environ.get("LLAMA_SERVER_PORT", "8080")
    base_url = f"http://{host}:{port}/v1"
    return OpenAI(base_url=base_url, api_key="not-needed")


def start_server():
    global server_process
    if server_process is not None:
        return

    model_path = os.environ.get("MODEL_PATH", "")
    if not os.path.exists(model_path):
        print(f"Model not found at {model_path}")
        print("Set MODEL_PATH env var. Or run llama-server separately.")
        return

    server_path = os.environ.get("LLAMA_SERVER_PATH", "llama-server")
    if not shutil.which(server_path):
        print(f"llama-server not found in PATH ({server_path})")
        print("Download from: https://github.com/ggerganov/llama.cpp/releases")
        print("Or run llama-server manually, then set LLAMA_SERVER_HOST/PORT.")
        return

    host = os.environ.get("LLAMA_SERVER_HOST", "127.0.0.1")
    port = os.environ.get("LLAMA_SERVER_PORT", "8080")
    ngl = os.environ.get("N_GPU_LAYERS", "-1")
    ctx = os.environ.get("N_CTX", "16384")
    cmd = [
        server_path,
        "-m", model_path,
        "--host", host,
        "--port", str(port),
        "-ngl", str(ngl),
        "-c", str(ctx),
        "-fa",
    ]
    print(f"Starting llama-server: {' '.join(cmd)}")
    server_process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    print(f"llama-server started on {host}:{port}")


def stop_server():
    global server_process
    if server_process:
        server_process.terminate()
        server_process = None


def _format_messages(messages: list) -> list:
    return [{"role": m["role"], "content": m["content"]} for m in messages]


def generate_response(
    messages: list,
    max_tokens: int = 2048,
    temperature: float = 0.7,
    top_p: float = 0.9,
    model: str = "qwen2.5:7b",
) -> str:
    openai_client = get_client()
    try:
        response = openai_client.chat.completions.create(
            model=model,
            messages=_format_messages(messages),
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            stream=False,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        host = os.environ.get("LLAMA_SERVER_HOST", "127.0.0.1")
        port = os.environ.get("LLAMA_SERVER_PORT", "8080")
        return f"Error: {e}. Is llama-server running on {host}:{port}?"


def generate_response_stream(
    messages: list,
    max_tokens: int = 2048,
    temperature: float = 0.7,
    top_p: float = 0.9,
    model: str = "qwen2.5:7b",
):
    openai_client = get_client()
    try:
        response = openai_client.chat.completions.create(
            model=model,
            messages=_format_messages(messages),
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            stream=True,
        )
        for chunk in response:
            delta = chunk.choices[0].delta
            if delta and delta.content:
                yield delta.content
    except Exception as e:
        yield f"\n[Error: {e}]"
