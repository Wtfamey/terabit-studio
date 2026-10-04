"""Model provisioning API -- what Settings and the first-run screen read.

Deliberately read-only in this build. The catalogue, sidecar detection, Ollama
discovery and manifest already exist in model_sources.py; the desktop build
ships the model inside the app, so the one thing the UI needs here is the
truth about what is on this machine:

  * which catalogue models are installed, as sidecar files, or as Ollama tags;
  * where the model folder is and how much room is left on that drive;
  * whether a llama.cpp runtime was found and whether Ollama answers;
  * the VRAM-derived recommendation and any issue worth showing a human.

Download/import/activate exist as functions in model_sources (with resume,
SHA-256 verification and a manifest) and become endpoints when the update and
repair flow needs them; exposing a download button before there is a published
URL host would just be a button that 404s.
"""
from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter, Query

import model_sources

router = APIRouter(prefix="/api/models", tags=["models"])

# state() shells out to nvidia-smi (up to 4s) and probes Ollama (up to 2s), so
# the answer is cached briefly: the Settings page polls it while a long model
# operation is happening and must not queue subprocess probes.
_CACHE: dict = {"at": 0.0, "data": None}
_TTL_S = 3.0


@router.get("/state")
async def models_state(refresh: bool = Query(False, description="bypass the 3s cache")):
    now = time.monotonic()
    if not refresh and _CACHE["data"] is not None and now - _CACHE["at"] < _TTL_S:
        return _CACHE["data"]
    data = await asyncio.to_thread(model_sources.state)
    _CACHE.update({"at": time.monotonic(), "data": data})
    return data
