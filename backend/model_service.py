import os
import subprocess
import shutil
import threading
import time
from typing import Optional
import httpx
from dotenv import load_dotenv
from pathlib import Path

# The repository-level .env is the documented configuration source.  Loading
# it explicitly also keeps behaviour identical whether uvicorn is started from
# the project root, the backend directory, Docker, or the PowerShell launcher.
#
# override=True on the root .env is deliberate and load-bearing.  With the
# default override=False, any MODEL_NAME already present in the environment of
# the process that launched uvicorn wins forever -- and uvicorn --reload
# respawns workers that INHERIT that stale environment, so editing .env has no
# effect until the server is fully restarted.  Measured 2026-10-02: .env said
# terabit-finetuned-v3, /api/health still reported terabit-finetuned-v2, and a
# fresh `python -c` in the same directory resolved v3 correctly.  That is the
# same class of bug run_local.ps1 already documents, and this makes .env the
# single source of truth so it cannot recur.  The backend-local .env still
# loads with override=False, so it only fills keys the root file omits.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
try:
    # Frozen builds have no repository above them; the .env lives next to the
    # executable (that is the file the README and the installer tell the user
    # to edit), and it must win over any stale shell environment exactly as
    # the root .env does from source.
    import paths as _paths
    if _paths.is_frozen():
        load_dotenv(_paths.env_file(), override=True)
except Exception:  # noqa: BLE001
    pass
# A benchmark or a CI run sometimes has to control MODEL_NAME / N_CTX from the
# process environment instead of the developer's .env. override=True is still
# the default (it is what makes .env the single source of truth); the escape
# hatch exists so a measurement can be uniform without editing a shared file.
if os.environ.get("TERABIT_SKIP_DOTENV") != "1":
    load_dotenv(PROJECT_ROOT / ".env", override=True)
    load_dotenv(Path(__file__).resolve().parent / ".env", override=False)

from openai import OpenAI

from context_budget import get_num_ctx
import model_sources

server_process: Optional[subprocess.Popen] = None


# Hard ceiling for a single completion round-trip. A 7B on a local GPU
# legitimately needs minutes for a full section, but nothing should ever
# exceed this: without it a wedged ollama call hangs the generation/repair
# loop indefinitely (observed: 22+ min stuck on one repair).
#
# 900s, not 600: a full multi-file section on the spilled-CPU config (the
# measured 6 GB RTX 3050 running the 7B on CPU) regularly takes >10 min for a
# single large file; the old ceiling turned those legitimate runs into hard
# failures that read as "the model did not answer".
REQUEST_TIMEOUT_S = int(os.environ.get("MODEL_REQUEST_TIMEOUT_S", "900"))

# In-memory active model -- can be switched at runtime via set_active_model().
# Falls back to MODEL_NAME env var if never set programmatically.
_active_model: Optional[str] = None


def set_active_model(model_id: str) -> None:
    """Switch the active model at runtime without restarting the backend."""
    global _active_model
    _active_model = model_id


def get_active_model() -> str:
    """Return the active model id, falling back to MODEL_NAME env var."""
    if _active_model:
        return _active_model
    return os.environ.get("MODEL_NAME", "qwen2.5:7b")

# Model-specific generation parameters (measured per model)
MODEL_GENERATION_CONFIG: dict[str, dict] = {
    "deepseek-coder:6.7b": {
        "temperature": 0.3,
        "top_p": 0.9,
        "max_tokens": 8000,
    },
    "terabit-v3-ctx8k": {
        "temperature": 0.7,
        "top_p": 0.9,
        "max_tokens": 7000,
    },
    "terabit-finetuned-v3": {
        "temperature": 0.7,
        "top_p": 0.9,
        "max_tokens": 7000,
    },
    "default": {
        "temperature": 0.7,
        "top_p": 0.9,
        "max_tokens": 7000,
    },
}


def _model_config(model: str) -> dict:
    """Return generation config for a specific model, falling back to default."""
    return MODEL_GENERATION_CONFIG.get(model, MODEL_GENERATION_CONFIG["default"])


def get_client() -> OpenAI:
    host = os.environ.get("LLAMA_SERVER_HOST", "127.0.0.1")
    port = os.environ.get("LLAMA_SERVER_PORT", "11434")
    base_url = f"http://{host}:{port}/v1"
    # max_retries=0: callers (repair loop, scaffold fallback) already have
    # their own retry/budget logic; silent library retries would double the
    # wall time of an already-failing call.
    return OpenAI(base_url=base_url, api_key="not-needed",
                  timeout=REQUEST_TIMEOUT_S, max_retries=0)


def start_server():
    global server_process
    if server_process is not None:
        return

    # Ollama exposes the same OpenAI-compatible endpoint.  Prefer an already
    # running local service instead of trying (and failing) to launch a second
    # llama-server process on the same port.
    host = os.environ.get("LLAMA_SERVER_HOST", "127.0.0.1")
    port = os.environ.get("LLAMA_SERVER_PORT", "11434")
    try:
        response = httpx.get(f"http://{host}:{port}/v1/models", timeout=1.5)
        if response.is_success:
            print(f"Using existing local model server at {host}:{port}")
            return
    except httpx.HTTPError:
        pass

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
    port = os.environ.get("LLAMA_SERVER_PORT", "11434")
    ngl = os.environ.get("N_GPU_LAYERS", "-1")
    ctx = os.environ.get("N_CTX", "16384")
    lora_path = os.environ.get("LORA_PATH", "")

    cmd = [
        server_path,
        "-m", model_path,
        "--host", host,
        "--port", str(port),
        "-ngl", str(ngl),
        "-c", str(ctx),
        "-fa",
    ]

    # Threads for the CPU side of a partial offload (and for CPU-only machines).
    # Without -t llama.cpp picks physical cores, which is right for throughput
    # but can make the laptop unresponsive while a 7B spills; the shipped .env
    # sets this explicitly.
    threads = os.environ.get("N_THREADS", "")
    if threads:
        cmd.extend(["-t", str(threads)])

    # Quantised KV cache. On the measured 6 GB RTX 3050, f16 KV for 8192 ctx
    # costs ~470 MB of the model's budget; q8_0 halves that for a quality
    # difference nobody has measured on this workload. Only meaningful with
    # flash attention, which every build we ship has (-fa above).
    kv_type = os.environ.get("KV_CACHE_TYPE", "")
    if kv_type:
        cmd.extend(["-ctk", kv_type, "-ctv", kv_type])

    # Add LoRA adapter if specified
    if lora_path and os.path.exists(lora_path):
        cmd.extend(["--lora", lora_path])
        print(f"Loading LoRA adapter from: {lora_path}")
    
    print(f"Starting llama-server: {' '.join(cmd)}")
    server_process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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
    model: str = "",
) -> str:
    text, _finish_reason = generate_response_with_status(
        messages, max_tokens=max_tokens, temperature=temperature, top_p=top_p, model=model,
    )
    return text


def generate_response_with_status(
    messages: list,
    max_tokens: int = 2048,
    temperature: float = 0.7,
    top_p: float = 0.9,
    model: str = "",
):
    """Same as generate_response, but also returns the completion's
    finish_reason ('stop', 'length', etc). Callers that need the FULL output
    of a large multi-file generation (see main.py's generate_complete_response)
    use this to detect when the model was cut off by max_tokens rather than
    finishing on its own, so they can request a continuation instead of
    silently shipping truncated code."""
    openai_client = get_client()
    model = model or get_active_model()
    # Map catalogue ID to Ollama tag (e.g., deepseek-coder-6.7b -> deepseek-coder:6.7b)
    model = model_sources.resolve_ollama_tag(model)
    cfg = _model_config(model)
    if max_tokens is None:
        max_tokens = cfg["max_tokens"]
    if temperature is None:
        temperature = cfg["temperature"]
    if top_p is None:
        top_p = cfg["top_p"]
    try:
        response = openai_client.chat.completions.create(
            model=model,
            messages=_format_messages(messages),
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            stream=False,
            extra_body={"options": {
                "num_ctx": get_num_ctx(),
                "num_thread": int(os.environ.get("N_THREADS", str(os.cpu_count() or 8))),
            }},
        )
        choice = response.choices[0]
        return (choice.message.content or "").strip(), (choice.finish_reason or "stop")
    except Exception as e:
        host = os.environ.get("LLAMA_SERVER_HOST", "127.0.0.1")
        port = os.environ.get("LLAMA_SERVER_PORT", "11434")
        return f"Error: {e}. Is llama-server running on {host}:{port}?", "error"


def generate_response_stream(
    messages: list,
    max_tokens: int | None = None,
    temperature: float | None = None,
    top_p: float | None = None,
    model: str = "",
):
    openai_client = get_client()
    model = model or get_active_model()
    # Map catalogue ID to Ollama tag (e.g., deepseek-coder-6.7b -> deepseek-coder:6.7b)
    model = model_sources.resolve_ollama_tag(model)
    cfg = _model_config(model)
    if max_tokens is None:
        max_tokens = cfg["max_tokens"]
    if temperature is None:
        temperature = cfg["temperature"]
    if top_p is None:
        top_p = cfg["top_p"]
    try:
        response = openai_client.chat.completions.create(
            model=model,
            messages=_format_messages(messages),
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            stream=True,
            extra_body={"options": {
                "num_ctx": get_num_ctx(),
                "num_thread": int(os.environ.get("N_THREADS", str(os.cpu_count() or 8))),
            }},
        )
        for chunk in response:
            delta = chunk.choices[0].delta
            if delta and delta.content:
                yield delta.content
    except Exception as e:
        yield f"\n[Error: {e}]"


_warmup_done = threading.Event()


def warm_up_model_async(attempts: int = 24, interval_s: float = 5.0) -> None:
    """Fire-and-forget model warm-up on backend startup.

    First inference after a cold start pays model load into VRAM (measured
    ~4s from Ollama; a self-contained bundle loading 4.7 GB from disk into 6 GB
    of VRAM takes longer). Doing this in a background thread when the API boots
    means the first real user request skips it.

    It RETRIES on purpose. When the bundled llama-server is still paging the
    model in it answers 503 ("loading model"), and the first version of this
    function gave up on the first refusal -- so the warm-up never happened and
    every user's first request paid the load anyway. Polling for up to two
    minutes costs nothing (it is a daemon thread) and makes the "open the app,
    it is already warm" promise true. Never raises.
    """
    def _warm():
        for attempt in range(1, max(1, attempts) + 1):
            try:
                get_client().chat.completions.create(
                    model=os.environ.get("MODEL_NAME", "qwen2.5:7b"),
                    messages=[{"role": "user", "content": "ping"}],
                    max_tokens=4,
                    extra_body={"options": {"num_ctx": get_num_ctx()}},
                )
                _warmup_done.set()
                print("[model] warm-up complete")
                return
            except Exception as exc:  # noqa: BLE001 - reported, then retried
                if attempt == attempts:
                    print(f"[model] warm-up gave up after {attempts} attempts: {exc}")
                    return
                if attempt in (1, 3, 6, 12):
                    print(f"[model] warm-up waiting for the model server "
                          f"(attempt {attempt}): {exc}")
                time.sleep(interval_s)

    threading.Thread(target=_warm, name="model-warmup", daemon=True).start()
