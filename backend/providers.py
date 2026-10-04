"""Provider abstraction for Terabit Studio -- local-first, cloud-optional.

The product goal (Bolt/Lovable parity, but self-hostable) demands that the
SAME agentic pipeline runs against:

  - a local Ollama / llama.cpp server      (default: private, free, slower)
  - any OpenAI-compatible endpoint         (vLLM, LM Studio, OpenRouter,
                                            Together, Groq, OpenAI...)
  - Google Gemini / Anthropic native APIs  (fastest iteration)

Resolution order (see resolve_provider):
  1. explicit override (request-level `provider` / `model`)
  2. TERABIT_PROVIDER env ( "local" | "openai" | "gemini" | "anthropic" )
  3. auto: local server healthy -> local; else first configured cloud key.

All providers return (text, finish_reason) exactly like
model_service.generate_response_with_status, so main.py's continuation
logic and the agentic loop work unchanged across backends.
"""

import os
import re
import base64
import json
from pathlib import Path

import httpx

import model_service

# ---------------------------------------------------------------- keys


def _env_key(*names: str) -> str:
    for n in names:
        v = os.environ.get(n, "").strip()
        if v and not v.startswith("your-"):
            return v
    return ""


def gemini_key() -> str:
    return _env_key("GEMINI_API_KEY", "GOOGLE_API_KEY")


def anthropic_key() -> str:
    return _env_key("ANTHROPIC_API_KEY")


def openai_key() -> str:
    # OpenAI-compatible endpoints always need *some* key; local servers
    # accept any non-empty string, so only treat configured values as real.
    return _env_key(
        "OPENAI_API_KEY", "OPENROUTER_API_KEY", "GROQ_API_KEY",
        "TOGETHER_API_KEY", "FIREWORKS_API_KEY", "DEEPSEEK_API_KEY",
    )


def openai_base_url() -> str:
    return os.environ.get(
        "OPENAI_BASE_URL", "https://api.openai.com/v1"
    )


# The OpenAI-compatible provider doubles as the gateway to models this
# laptop cannot run locally. Qwen3-Coder, e.g., starts at 30B-A3B = 19 GB in
# Q4 -- more than this machine's VRAM (6 GB) and RAM (16 GB) combined -- so
# the way to ship its quality is a hosted endpoint. OPENROUTER_API_KEY alone
# is enough: base URL defaults to OpenRouter and the model id passes straight
# through (e.g. model="qwen/qwen3-coder" in the request, or
# OPENAI_MODEL=qwen/qwen3-coder in .env).
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


def _effective_base_url() -> str:
    """Base URL for the OpenAI-compatible provider, with OpenRouter defaults.

    If only OPENROUTER_API_KEY is configured (no explicit base URL), point at
    OpenRouter automatically so `provider: openai` + `model: qwen/qwen3-coder`
    works with zero extra configuration.
    """
    explicit = os.environ.get("OPENAI_BASE_URL", "")
    if explicit:
        return explicit
    if os.environ.get("OPENROUTER_API_KEY", "") and not os.environ.get("OPENAI_API_KEY", ""):
        return OPENROUTER_BASE_URL
    return "https://api.openai.com/v1"


# ---------------------------------------------------------------- health


def local_server_healthy() -> bool:
    host = os.environ.get("LLAMA_SERVER_HOST", "127.0.0.1")
    port = os.environ.get("LLAMA_SERVER_PORT", "11434")
    try:
        r = httpx.get(f"http://{host}:{port}/v1/models", timeout=1.5)
        return r.is_success
    except httpx.HTTPError:
        return False


# ---------------------------------------------------------------- resolution


def available_providers() -> dict:
    return {
        "local": local_server_healthy(),
        "openai": bool(openai_key()) or os.environ.get("OPENAI_BASE_URL", "") != "",
        "gemini": bool(gemini_key()),
        "anthropic": bool(anthropic_key()),
    }


def resolve_provider(requested: str = "") -> str:
    requested = (requested or os.environ.get("TERABIT_PROVIDER", "")).lower()
    avail = available_providers()
    if requested and requested in avail and avail[requested]:
        return requested
    if requested == "auto" or not requested:
        if avail["local"]:
            return "local"
        for name in ("openai", "gemini", "anthropic"):
            if avail[name]:
                return name
        return "local"  # last resort; calls will surface a clear error
    raise ValueError(
        f"Provider '{requested}' unavailable. Available: "
        f"{[k for k, v in avail.items() if v] or 'none'}"
    )


# ---------------------------------------------------------------- calls


def _strip_thinking(text: str) -> str:
    """Remove reasoning-model think blocks that would poison file parsing."""
    return re.sub(r"<think>[\s\S]*?</think>", "", text).strip()


def chat(
    messages: list,
    max_tokens: int = 2048,
    temperature: float = 0.7,
    provider: str = "",
    model: str = "",
) -> tuple:
    """Single chat completion -> (text, finish_reason). Local-first dispatch."""
    p = resolve_provider(provider)
    if p == "local":
        return model_service.generate_response_with_status(
            messages, max_tokens=max_tokens, temperature=temperature, model=model
        )
    if p == "openai":
        return _chat_openai(messages, max_tokens, temperature, model)
    if p == "gemini":
        return _chat_gemini(messages, max_tokens, temperature, model)
    if p == "anthropic":
        return _chat_anthropic(messages, max_tokens, temperature, model)
    raise ValueError(f"Unknown provider: {p}")


def stream(messages: list, max_tokens: int = 2048, temperature: float = 0.7,
           provider: str = "", model: str = ""):
    """Yield text deltas; local server streams, cloud providers simulated
    by chunking the full response (good enough for progress UI)."""
    p = resolve_provider(provider)
    if p == "local":
        yield from model_service.generate_response_stream(
            messages, max_tokens=max_tokens, temperature=temperature, model=model
        )
        return
    text, _ = chat(messages, max_tokens=max_tokens, temperature=temperature,
                   provider=p, model=model)
    for i in range(0, len(text), 120):
        yield text[i:i + 120]


DEFAULT_OPENAI_MODEL = "gpt-4o-mini"
DEFAULT_GEMINI_MODEL = "gemini-2.0-flash"
DEFAULT_ANTHROPIC_MODEL = "claude-3-5-haiku-latest"


def _default_cloud_model(p: str) -> str:
    return {
        "openai": os.environ.get("OPENAI_MODEL", DEFAULT_OPENAI_MODEL),
        "gemini": os.environ.get("GEMINI_MODEL", DEFAULT_GEMINI_MODEL),
        "anthropic": os.environ.get("ANTHROPIC_MODEL", DEFAULT_ANTHROPIC_MODEL),
    }.get(p, "")


def _chat_openai(messages, max_tokens, temperature, model):
    from openai import OpenAI

    client = OpenAI(
        api_key=openai_key() or "local",
        base_url=_effective_base_url(),
    )
    try:
        resp = client.chat.completions.create(
            model=model or _default_cloud_model("openai"),
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        choice = resp.choices[0]
        return _strip_thinking(choice.message.content or ""), (choice.finish_reason or "stop")
    except Exception as e:
        return f"Error: {e}", "error"


def _chat_gemini(messages, max_tokens, temperature, model):
    key = gemini_key()
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model or _default_cloud_model('gemini')}:generateContent"
    )
    # Gemini needs explicit instruction Turn for system content
    system_text = "\n".join(m["content"] for m in messages if m["role"] == "system")
    turns = [m for m in messages if m["role"] != "system"]
    body = {
        "systemInstruction": {"parts": [{"text": system_text}]} if system_text else None,
        "contents": [
            {
                "role": "assistant" if m["role"] == "assistant" else "user",
                "parts": [{"text": m["content"]}],
            }
            for m in turns
        ],
        "generationConfig": {
            "maxOutputTokens": max_tokens,
            "temperature": temperature,
        },
    }
    body = {k: v for k, v in body.items() if v is not None}
    try:
        r = httpx.post(url, json=body, params={"key": key}, timeout=180)
        r.raise_for_status()
        data = r.json()
        cand = data["candidates"][0]
        text = "".join(
            p.get("text", "") for p in cand.get("content", {}).get("parts", [])
        )
        finish = cand.get("finishReason", "STOP")
        # MAP Gemini finish codes onto OpenAI-style reasons
        finish = {"STOP": "stop", "MAX_TOKENS": "length"}.get(finish, "stop")
        return _strip_thinking(text.strip()), finish
    except Exception as e:
        return f"Error: {e}", "error"


def _chat_anthropic(messages, max_tokens, temperature, model):
    key = anthropic_key()
    system_text = "\n".join(m["content"] for m in messages if m["role"] == "system")
    turns = [
        {"role": m["role"], "content": m["content"]}
        for m in messages if m["role"] != "system"
    ]
    try:
        r = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": key,
                "anthropic-version": "2023-06-01",
            },
            json={
                "model": model or _default_cloud_model("anthropic"),
                "max_tokens": max_tokens,
                "temperature": temperature,
                "system": system_text or None,
                "messages": turns,
            },
            timeout=180,
        )
        r.raise_for_status()
        data = r.json()
        text = "".join(b.get("text", "") for b in data.get("content", []))
        finish = data.get("stop_reason", "stop")
        finish = {"end_turn": "stop", "max_tokens": "length"}.get(finish, "stop")
        return _strip_thinking(text.strip()), finish
    except Exception as e:
        return f"Error: {e}", "error"
