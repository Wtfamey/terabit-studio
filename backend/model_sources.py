"""Model provisioning: find, download, verify and remember GGUF model files.

A packaged Terabit has no model weights and no inference runtime inside the
119 MB installer (see docs/SHIPPING_AND_MODEL_BUNDLING.md -- NSIS cannot even
produce a >2 GB installer). So the app has to be able to answer four questions
about the machine it just landed on, without a human reading a wiki:

  1. Is there already a usable model? Three places count, in priority order:
     a file this app downloaded before (data_dir/models + the manifest), a
     `.gguf` sitting beside the installer or in the user's model folders
     (the air-gapped / LM-Studio-refugee path), or a tag inside a local Ollama
     install. Nothing is copied or moved -- the file stays where its owner put
     it, and the manifest records the path.
  2. If not, can it be downloaded? A catalogue entry only becomes downloadable
     when it has a URL; the fine-tuned v3 GGUF has no public host yet, so its
     entry lists what it is and how big it is, and the app says so instead of
     offering a button that 404s.
  3. Is that file what it claims to be? Every download and every import is
     checked against the catalogue's size and SHA-256 -- a 4.7 GB transfer
     that silently corrupts is the difference between "slow" and "broken".
     Resumable downloads keep the `.part` file, so a cancelled or interrupted
     transfer continues instead of starting over.
  4. Enough room? C: on the machine this was built on has 11 GB free of 473;
     a 4.7 GB model must go where the space is, so every file lives under
     `data_dir()/models` (relocatable with TERABIT_DATA_DIR) and the space
     check happens before the first byte, with the real numbers in the error.

Everything here is filesystem and localhost only. The two network calls are
the model download itself and the Ollama `/api/tags` probe; both are bounded
and both are failure-tolerant, because this module powers exactly the screen a
user sees when the install is broken.

Catalogue provenance (measured 2026-10-03, not estimated):
  * `terabit-v3-7b` -- `D:/terabit-retrain/terabit-v3-q4km.gguf`, the merged
    fine-tune (4,683,073,344 bytes, sha256 c5ccb629...). The Ollama tag
    `terabit-finetuned-v3` is the same weights as base + 40 MB LoRA adapter.
  * `qwen2.5-coder-3b` -- size and sha256 read from the Hugging Face API for
    Qwen/Qwen2.5-Coder-3B-Instruct-GGUF (2,104,932,800 bytes, sha
    724fb256...). Upstream, NOT fine-tuned: offered for machines below the
    fine-tune's VRAM floor, and labelled as such in the UI.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
import time
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Callable, Optional
from urllib import error as _urlerror
from urllib import request as _urlrequest

import model_service
import paths

# A model file smaller than this is a mis-click (a stray text file named
# .gguf), never a model: the smallest useful q4 GGUF is ~1.5 GB.
MIN_MODEL_BYTES = 1 << 20

CHUNK = 1 << 20  # 1 MiB per read: big enough for line-rate, small enough that
                 # cancel and progress stay responsive on a slow disk.
_RATE_WINDOW_S = 8.0


class ModelError(RuntimeError):
    """A provisioning failure a user can act on (space, hash, source, path)."""

    def __init__(self, message: str, code: str = "error", **details):
        super().__init__(message)
        self.code = code
        self.details = details


@dataclass(frozen=True)
class ModelSource:
    """One catalogue entry. Frozen so a merged override can never mutate the
    built-in list in place -- `effective_catalog()` hands out copies."""

    id: str
    label: str
    note: str
    file_name: str
    bytes: int
    sha256: str
    params_b: float
    quant: str
    license: str
    min_vram_gb: float
    context: int
    finetuned: bool = False
    recommended: bool = False
    ollama_tag: str = ""
    url: str = ""

    @property
    def gib(self) -> float:
        return round(self.bytes / (1024 ** 3), 2)

    def public(self) -> dict:
        data = asdict(self)
        data["gib"] = self.gib
        data["downloadable"] = bool(self.url)
        return data


_HF = "https://huggingface.co/{repo}/resolve/main/{file}"

_BUILTIN: tuple[ModelSource, ...] = (
    ModelSource(
        id="terabit-v3-7b",
        label="Terabit v3 (7B, fine-tuned, recommended)",
        note="The model this app was tuned with: writes copy in the user's "
             "own language and follows the product brief. Runs on 6 GB of "
             "VRAM with a small CPU spill; 8 GB keeps it fully resident.",
        file_name="terabit-v3-q4km.gguf",
        bytes=4683073344,
        sha256="c5ccb62937f31500394cdd8429b05bf8c268e3c1d6d17c5b4ddc1c8bf79b6aa9",
        params_b=7.6,
        quant="Q4_K_M",
        license="Apache-2.0 (Qwen2.5-Coder base) + Terabit adapter",
        # 6 GB, measured on the reference laptop: the 7B Q4_K_M with an 8192
        # token context keeps ~4.1 GB of ~5.4 GB resident on a 3050 6 GB and
        # finishes a full build in ~20 minutes. 8 GB removes the spill, which
        # is why the UI says so, but 6 GB is the honest floor.
        min_vram_gb=6.0,
        context=8192,
        finetuned=True,
        recommended=True,
        ollama_tag="terabit-finetuned-v3",
        # No public host yet. Fill this in (or ship a catalog override /
        # TERABIT_MODEL_CATALOG) once the GGUF is published; until then the
        # app uses a sidecar file, an import, or the Ollama tag.
        url="",
    ),
    ModelSource(
        id="qwen2.5-coder-3b",
        label="Qwen2.5-Coder 3B (upstream base, small GPUs)",
        note="Not fine-tuned -- the fallback for machines under the v3 VRAM "
             "floor. Fits 4-6 GB VRAM comfortably and generates faster.",
        file_name="qwen2.5-coder-3b-instruct-q4_k_m.gguf",
        bytes=2104932800,
        sha256="724fb256bec1ff062b2f65e4569e871ad2e95ab2a3989723d1769c54294730b7",
        params_b=3.1,
        quant="Q4_K_M",
        license="Apache-2.0",
        min_vram_gb=4.0,
        context=8192,
        finetuned=False,
        recommended=False,
        url=_HF.format(repo="Qwen/Qwen2.5-Coder-3B-Instruct-GGUF",
                       file="qwen2.5-coder-3b-instruct-q4_k_m.gguf"),
    ),
    ModelSource(
        id="deepseek-coder-6.7b",
        label="DeepSeek Coder 6.7B (upstream, code-optimized)",
        note="Not fine-tuned, but purpose-built for code. Better React/Tailwind "
             "generation than the 7B fine-tune for complex pages. Fits 6 GB "
             "VRAM with a small CPU spill.",
        file_name="deepseek-coder-6.7b-instruct-q4_k_m.gguf",
        bytes=4164804608,
        sha256="",
        params_b=6.7,
        quant="Q4_K_M",
        license="MIT",
        min_vram_gb=6.0,
        context=16384,
        finetuned=False,
        recommended=False,
        ollama_tag="deepseek-coder:6.7b",
        url="",
    ),
)


# ─────────────────────────────── catalogue ───────────────────────────────

def _id_to_env(model_id: str) -> str:
    return "TERABIT_MODEL_URL_" + re.sub(r"[^A-Za-z0-9]+", "_", model_id).upper()


def _catalog_override_file() -> Optional[Path]:
    raw = os.environ.get("TERABIT_MODEL_CATALOG")
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None


def effective_catalog() -> list[ModelSource]:
    """Built-ins, plus per-model URL env overrides, plus an optional JSON
    override file that can add entries or replace fields by id.

    The override file is how a test, a fork, or an ops person points the app at
    their own mirror without touching code -- and it is the only supported way
    to change a size or hash, because those are load-bearing for verification.
    """
    entries: dict[str, ModelSource] = {m.id: m for m in _BUILTIN}
    override = _catalog_override_file()
    if override:
        try:
            data = json.loads(override.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ModelError(f"TERABIT_MODEL_CATALOG is not readable JSON: {exc}",
                             code="bad_catalog") from exc
        rows = data.get("models") if isinstance(data, dict) else data
        if not isinstance(rows, list):
            raise ModelError("TERABIT_MODEL_CATALOG must be a list or {models: []}",
                             code="bad_catalog")
        for row in rows:
            if not isinstance(row, dict) or not row.get("id"):
                raise ModelError("each catalogue override needs an id",
                                 code="bad_catalog")
            base = entries.get(str(row["id"]))
            fields = {f: row[f] for f in asdict(base).keys() if f in row} if base \
                else {f: row[f] for f in ModelSource.__dataclass_fields__ if f in row}
            if base:
                entries[base.id] = replace(base, **fields)
            else:
                missing = [f for f in ("id", "label", "file_name", "bytes", "sha256")
                           if f not in fields]
                if missing:
                    raise ModelError(f"catalogue entry {row['id']} is missing "
                                     f"{', '.join(missing)}", code="bad_catalog")
                entries[str(row["id"])] = ModelSource(**fields)

    catalog: list[ModelSource] = []
    for source in entries.values():
        env_url = os.environ.get(_id_to_env(source.id))
        catalog.append(replace(source, url=env_url) if env_url else source)
    return catalog


def get_source(model_id: str) -> ModelSource:
    for source in effective_catalog():
        if source.id == model_id:
            return source
    raise ModelError(f"Unknown model id: {model_id}", code="unknown_model")


# ─────────────────────────────── locations ───────────────────────────────

def models_dir() -> Path:
    """Where this app stores models it downloaded. Never the install folder:
    an Electron install under Program Files is read-only-ish, and the disk
    with the space is frequently not C:. Relocatable via TERABIT_DATA_DIR."""
    target = paths.data_dir() / "models"
    target.mkdir(parents=True, exist_ok=True)
    return target


def search_dirs() -> list[Path]:
    """Folders that may already hold a `.gguf`, most authoritative first.

    The user's own folders are deliberately included: a build shipped as
    "installer + terabit-model.gguf beside it" is a supported shape, and the
    file must be usable where it sits -- copying 4.7 GB to prove ownership
    would be a bug, not a feature.
    """
    dirs: list[Path] = [models_dir(), paths.data_dir(), paths.app_dir()]
    dirs += [paths.app_dir() / "models", Path.home() / ".terabit" / "models"]
    if not paths.is_frozen():
        repo = Path(__file__).resolve().parents[1]
        dirs.append(repo / "models")
    out: list[Path] = []
    seen: set[str] = set()
    for d in dirs:
        key = str(d).lower()
        if key not in seen:
            seen.add(key)
            out.append(d)
    return out


def scan_ggufs() -> list[dict]:
    """Every plausible model file in the search folders (top level only -- a
    recursive scan of a home directory is how a UI freezes)."""
    found: list[dict] = []
    seen: set[str] = set()
    for folder in search_dirs():
        try:
            children = list(folder.iterdir())
        except OSError:
            continue
        for path in children:
            if not path.is_file() or path.suffix.lower() != ".gguf":
                continue
            if path.name.endswith(".part"):
                continue
            key = str(path.resolve()).lower()
            if key in seen:
                continue
            seen.add(key)
            try:
                stat = path.stat()
            except OSError:
                continue
            found.append({
                "path": str(path),
                "name": path.name,
                "bytes": stat.st_size,
                "gib": round(stat.st_size / (1024 ** 3), 2),
                "modified": int(stat.st_mtime),
            })
    found.sort(key=lambda f: f["bytes"], reverse=True)
    return found


def match_gguf(entry: dict, catalog: Optional[list[ModelSource]] = None) -> Optional[ModelSource]:
    """Does this file look like a catalogued model? Name wins, then exact
    size -- 608 bytes of metadata are the only difference between the base
    Qwen2.5-7B and the merged v3, so an exact-size match is meaningful."""
    for source in catalog or effective_catalog():
        if entry["name"].lower() == source.file_name.lower():
            return source
    for source in catalog or effective_catalog():
        if entry["bytes"] == source.bytes:
            return source
    return None


def human_bytes(n: int) -> str:
    step = 1024.0
    value = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < step or unit == "TB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= step
    return f"{value:.1f} TB"


def disk_free(target: Path) -> dict:
    try:
        usage = shutil.disk_usage(str(target))
        return {"path": str(target), "free_bytes": usage.free,
                "total_bytes": usage.total, "free_human": human_bytes(usage.free)}
    except OSError as exc:
        return {"path": str(target), "free_bytes": -1, "total_bytes": -1,
                "free_human": "unknown", "error": str(exc)}


# ────────────────────────── runtime + hardware ──────────────────────────

def find_llama_server() -> dict:
    """Is there a llama.cpp server to run a downloaded GGUF with? Ollama ships
    its own copy inside its install, so "Ollama is reachable" also counts as a
    runtime even when no llama-server binary is on PATH."""
    exe = "llama-server.exe" if os.name == "nt" else "llama-server"
    candidates: list[tuple[str, Path]] = []
    env = os.environ.get("LLAMA_SERVER_PATH")
    if env:
        candidates.append(("env", Path(env).expanduser()))
    for folder in (paths.app_dir() / "llama", paths.app_dir(), models_dir() / "llama",
                   paths.data_dir() / "llama"):
        candidates.append(("app", folder / exe))
    which = shutil.which("llama-server")
    if which:
        candidates.append(("path", Path(which)))
    for source, path in candidates:
        try:
            if path.is_file():
                return {"found": True, "path": str(path), "source": source}
        except OSError:
            continue
    return {"found": False, "path": "", "source": "none"}


def detect_vram_gb(runner: Optional[Callable] = None) -> Optional[float]:
    """Best-effort total GPU memory via nvidia-smi. None is a valid answer
    (no NVIDIA GPU, or the tool is absent) and the caller must handle it --
    every machine without a discrete GPU lands here."""
    def _run(cmd, **kw):
        return (runner or subprocess.run)(cmd, capture_output=True, text=True,
                                          timeout=4, **kw)
    try:
        proc = _run(["nvidia-smi", "--query-gpu=memory.total",
                     "--format=csv,noheader,nounits"])
        if getattr(proc, "returncode", 1) != 0:
            return None
        first = (proc.stdout or "").strip().splitlines()[0].strip()
        mib = float(first)
        return round(mib / 1024.0, 1) if mib > 0 else None
    except Exception:  # noqa: BLE001 - a probe, not a feature
        return None


def recommend(vram_gb: Optional[float], catalog: Optional[list[ModelSource]] = None) -> str:
    """Pick a default: the fine-tune when the GPU can hold it, the small
    upstream model otherwise, and the fine-tune when VRAM is unknown (it is
    the product; CPU fallback still works, just slowly)."""
    catalog = catalog or effective_catalog()
    fitted = [m for m in catalog if m.recommended]
    if not fitted:
        fitted = sorted(catalog, key=lambda m: m.params_b, reverse=True)[:1]
    if vram_gb is None:
        return fitted[0].id
    affordable = [m for m in catalog if m.min_vram_gb <= vram_gb]
    if not affordable:
        return min(catalog, key=lambda m: m.min_vram_gb).id
    best = max(affordable, key=lambda m: (m.finetuned, m.params_b))
    return best.id


# ─────────────────────────────── ollama ───────────────────────────────

_OLLAMA_CACHE: dict = {"key": "", "at": 0.0, "data": None}
_OLLAMA_TTL_S = 4.0


def probe_ollama(base_url: Optional[str] = None, timeout: float = 2.0,
                 use_cache: bool = True) -> dict:
    """Which tags does a local Ollama have? Cached for a few seconds because
    the first-run screen polls state while a download runs, and hammering a
    dead port with 2s timeouts would make that screen stutter."""
    host = os.environ.get("LLAMA_SERVER_HOST", "127.0.0.1")
    port = os.environ.get("LLAMA_SERVER_PORT", "11434")
    base = (base_url or f"http://{host}:{port}").rstrip("/")
    now = time.monotonic()
    if use_cache and _OLLAMA_CACHE["data"] and _OLLAMA_CACHE["key"] == base \
            and now - _OLLAMA_CACHE["at"] < _OLLAMA_TTL_S:
        return _OLLAMA_CACHE["data"]
    result = {"reachable": False, "base_url": base, "tags": [], "error": None}
    try:
        import httpx
        with httpx.Client(timeout=timeout) as client:
            response = client.get(f"{base}/api/tags")
        response.raise_for_status()
        models = (response.json().get("models") or [])
        result["tags"] = [str(m.get("name", "")) for m in models if m.get("name")]
        result["reachable"] = True
    except Exception as exc:  # noqa: BLE001 - reports the failure by design
        result["error"] = f"{type(exc).__name__}"
    if use_cache:
        _OLLAMA_CACHE.update({"key": base, "at": now, "data": result})
    return result


def _ollama_has(tag: str, tags: list[str]) -> bool:
    want = tag.split(":")[0]
    return any(t == tag or t.split(":")[0] == want for t in tags)


# Ollama IGNORES the `num_ctx` option sent through its OpenAI-compatible /v1
# endpoint, so the only way to get a bigger context window is a tag with
# `PARAMETER num_ctx` baked into its Modelfile (see backend/Modelfile.v3-ctx8k).
# This pipeline sends 3-5k-token prompts; on a default-context tag Ollama
# silently drops the middle of the prompt -- which is where the user's request
# and the product brief live. So when an 8k variant of a tag is installed, use
# it. The choice is sticky: flipping between two tags of the same weights
# mid-run would load a second copy of the model into a 6 GB card.
_CTX_VARIANTS = {
    "terabit-finetuned-v3": "terabit-v3-ctx8k",
    "deepseek-coder:6.7b": "deepseek-coder-ctx8k",
}
_ctx_choice: dict = {}   # base tag -> (chosen tag, decided_at, is_variant)
_CTX_NEGATIVE_TTL_S = 60.0

# Context-variant ids ("terabit-v3-ctx8k") name a base model at a specific
# context window; resolving them to the base tag lets the _CTX_VARIANTS table
# above pick the right context variant uniformly. Without this, an id that
# bypassed the catalogue lookup (a hand-written .env value) never reached the
# variant logic and was called verbatim.
_TAG_ALIASES = {
    "terabit-v3-ctx8k": "terabit-finetuned-v3",
    "terabit-v3-ctx16k": "terabit-finetuned-v3",
    "deepseek-coder-ctx8k": "deepseek-coder:6.7b",
    "deepseek-coder-ctx16k": "deepseek-coder:6.7b",
}


def resolve_ollama_tag(model_id: str) -> str:
    """Catalogue id / tag -> the Ollama tag to call, preferring an installed
    8k-context variant of it (see _CTX_VARIANTS)."""
    tag = _resolve_base_tag(model_id)
    variant = _CTX_VARIANTS.get(tag)
    if not variant:
        return tag
    now = time.monotonic()
    cached = _ctx_choice.get(tag)
    if cached and (cached[2] or now - cached[1] < _CTX_NEGATIVE_TTL_S):
        return cached[0]
    info = probe_ollama()
    if not info.get("reachable"):
        return cached[0] if cached else tag   # unreachable: decide nothing
    has_variant = _ollama_has(variant, info.get("tags") or [])
    chosen = variant if has_variant else tag
    _ctx_choice[tag] = (chosen, now, has_variant)
    if has_variant:
        print(f"[model] using {variant} (8k-context variant of {tag})")
    else:
        print(f"[model] {variant} is not installed in Ollama; using {tag} at "
              f"Ollama's default context (long prompts will be truncated). "
              f"Create it from backend/Modelfile.* with `ollama create`.")
    return chosen


def _resolve_base_tag(model_id: str) -> str:
    """Map a catalogue model ID to its Ollama tag.
    
    Catalogue IDs use hyphens (deepseek-coder-6.7b) but Ollama tags use colons (deepseek-coder:6.7b).
    """
    if model_id in _TAG_ALIASES:
        return _TAG_ALIASES[model_id]
    for source in effective_catalog():
        if source.id == model_id and source.ollama_tag:
            return source.ollama_tag
    # Fallback: replace last hyphen with colon (deepseek-coder-6.7b -> deepseek-coder:6.7b)
    if "-" in model_id and not ":" in model_id:
        parts = model_id.rsplit("-", 1)
        if parts[-1].replace(".", "").isdigit():
            return parts[0] + ":" + parts[1]
    return model_id


# ────────────────────────────── manifest ──────────────────────────────

def _manifest_path() -> Path:
    return models_dir() / "installed.json"


def manifest_read() -> dict:
    try:
        data = json.loads(_manifest_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _manifest_write(data: dict) -> None:
    target = _manifest_path()
    tmp = target.with_suffix(".json.tmp")
    try:
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False),
                       encoding="utf-8")
        os.replace(tmp, target)
    except OSError:
        # A manifest that cannot be written must not fail the download that
        # just succeeded -- the file is on disk and re-verified on every read.
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def manifest_record(record_id: str, **fields) -> dict:
    data = manifest_read()
    row = dict(data.get(record_id) or {})
    row.update(fields)
    row.setdefault("recorded_at", time.time())
    data[record_id] = row
    _manifest_write(data)
    return row


def manifest_forget(record_id: str) -> None:
    data = manifest_read()
    if record_id in data:
        data.pop(record_id)
        _manifest_write(data)


# ─────────────────────────── hashing / verifying ───────────────────────────

def sha256_file(path: Path, progress: Optional[Callable] = None,
                cancel: Optional[threading.Event] = None) -> str:
    digest = hashlib.sha256()
    done = 0
    total = path.stat().st_size
    with open(path, "rb") as fh:
        while True:
            if cancel is not None and cancel.is_set():
                raise ModelError("Cancelled while verifying.", code="cancelled")
            block = fh.read(CHUNK)
            if not block:
                break
            digest.update(block)
            done += len(block)
            if progress:
                progress(done, total, 0.0)
    return digest.hexdigest()


def _check_size(path: Path, source: ModelSource) -> None:
    actual = path.stat().st_size
    if actual != source.bytes:
        raise ModelError(
            f"{path.name} is {human_bytes(actual)}, but {source.label} is "
            f"{human_bytes(source.bytes)}. Wrong file or incomplete download.",
            code="size_mismatch", expected=source.bytes, actual=actual)


def _check_hash(path: Path, source: ModelSource,
                progress: Optional[Callable] = None,
                cancel: Optional[threading.Event] = None) -> None:
    actual = sha256_file(path, progress=progress, cancel=cancel)
    if actual != source.sha256:
        raise ModelError(
            f"{path.name} failed its SHA-256 check (got {actual[:16]}..., "
            f"expected {source.sha256[:16]}...). The file is corrupt; "
            "delete it and download again.", code="hash_mismatch",
            expected=source.sha256, actual=actual)


# ───────────────────────────── installing ─────────────────────────────

def _record_install(source: ModelSource, path: Path, delivery: str,
                    verified: bool = True) -> dict:
    return manifest_record(source.id, model_id=source.id, file=str(path),
                           file_name=path.name, bytes=path.stat().st_size,
                           sha256=source.sha256 if verified else "",
                           delivery=delivery, verified=verified,
                           verified_at=time.time() if verified else None)


def installed(catalog: Optional[list[ModelSource]] = None,
              ollama: Optional[dict] = None) -> dict[str, dict]:
    """For each catalogue entry, what is available on this machine and from
    where. Priority: a downloaded file we recorded > a sidecar file > an
    Ollama tag. A manifest row whose file vanished is reported as absent
    (with a `stale` marker), never as ready -- that is the difference between
    a good error message and a 404 in the middle of a generation."""
    catalog = catalog or effective_catalog()
    ollama = ollama if ollama is not None else probe_ollama()
    manifest = manifest_read()
    ggufs = scan_ggufs()
    out: dict[str, dict] = {}
    for source in catalog:
        row = manifest.get(source.id)
        entry: Optional[dict] = None
        if row and row.get("file"):
            path = Path(row["file"])
            if path.is_file() and path.stat().st_size == source.bytes:
                entry = {"delivery": row.get("delivery", "download"),
                         "path": str(path), "bytes": path.stat().st_size,
                         "verified": bool(row.get("verified")),
                         "verified_at": row.get("verified_at"),
                         "recorded": True}
            elif path.is_file():
                entry = {"delivery": "corrupt", "path": str(path),
                         "bytes": path.stat().st_size, "verified": False,
                         "stale": True,
                         "expected_bytes": source.bytes}
        if entry is None:
            for candidate in ggufs:
                if match_gguf(candidate, [source]) is source:
                    entry = {"delivery": "sidecar", "path": candidate["path"],
                             "bytes": candidate["bytes"], "verified": False,
                             "verified_at": None, "recorded": False}
                    break
        if entry is None and source.ollama_tag and ollama.get("reachable") \
                and _ollama_has(source.ollama_tag, ollama.get("tags") or []):
            entry = {"delivery": "ollama", "path": "", "bytes": 0,
                     "verified": True, "verified_at": None, "recorded": False,
                     "tag": source.ollama_tag}
        if entry is None:
            # An imported file recorded under its own id (unmatched gguf).
            for key, row in manifest.items():
                if key.startswith("imported-") and row.get("model_id") == source.id:
                    path = Path(row.get("file", ""))
                    if path.is_file() and path.stat().st_size == source.bytes:
                        entry = {"delivery": "import", "path": str(path),
                                 "bytes": path.stat().st_size,
                                 "verified": bool(row.get("verified")),
                                 "verified_at": row.get("verified_at"),
                                 "recorded": True}
                    break
        if entry:
            out[source.id] = entry
    return out


def imports() -> list[dict]:
    """Files the user pointed us at that matched no catalogue entry. They are
    usable (activate writes their path), just not the model we recommend."""
    rows = []
    for key, row in manifest_read().items():
        if not key.startswith("imported-") or not row.get("file"):
            continue
        path = Path(row["file"])
        rows.append({"record_id": key, "path": str(path),
                     "name": row.get("file_name") or path.name,
                     "bytes": row.get("bytes", 0),
                     "sha256": row.get("sha256", ""),
                     "exists": path.is_file(),
                     "verified": bool(row.get("verified"))})
    return rows


def active_model() -> dict:
    """What generation will use right now, per the environment."""
    model_path = os.environ.get("MODEL_PATH", "")
    active_id = os.environ.get("TERABIT_ACTIVE_MODEL", "")
    return {"id": active_id, "model_path": model_path,
            "model_name": os.environ.get("MODEL_NAME", "qwen2.5:7b")}


# ────────────────────────────── downloading ──────────────────────────────

def _default_opener(url: str, headers: dict, timeout: float):
    request = _urlrequest.Request(url, headers=headers)
    return _urlrequest.urlopen(request, timeout=timeout)  # noqa: S310 - the
    # URL comes from the catalogue (or its documented override), not from
    # user input over the network; the whole feature is "fetch this model".


class _Rate:
    """Bytes/second over a sliding window, so the UI shows a moving speed
    instead of lifetime average (which lies for the first minute and after
    every stall)."""

    def __init__(self, window: float = _RATE_WINDOW_S):
        self.window = window
        self.samples: list[tuple[float, int]] = []
        self.last = 0.0

    def update(self, downloaded: int) -> float:
        now = time.monotonic()
        self.samples.append((now, downloaded))
        cutoff = now - self.window
        while len(self.samples) > 2 and self.samples[0][0] < cutoff:
            self.samples.pop(0)
        span = now - self.samples[0][0]
        if span < 0.25:
            return self.last
        self.last = max(0.0, (downloaded - self.samples[0][1]) / span)
        return self.last


def download(model_id: str, *, dest_dir: Optional[Path] = None,
             progress: Optional[Callable] = None,
             cancel: Optional[threading.Event] = None,
             opener: Optional[Callable] = None,
             replace: bool = False, timeout: float = 60.0,
             attempts: int = 3, backoff_s: float = 1.5) -> dict:
    """Fetch one catalogue model into the data dir, resumably and verified.

    Returns a status dict (`present` | `downloaded` | `cancelled`) -- a user
    cancel is a state, not an exception. Raises ModelError for everything a
    user must fix: no URL, no space, size/hash mismatch, network failure after
    all attempts.
    """
    source = get_source(model_id)
    if not source.url:
        raise ModelError(
            f"{source.label} has no download source configured. Import the "
            f".gguf file ({source.file_name}, {human_bytes(source.bytes)}), "
            f"or use an Ollama tag ({source.ollama_tag or 'none'}).",
            code="no_source", model_id=model_id)
    dest_dir = dest_dir or models_dir()
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / source.file_name
    part = dest.with_name(dest.name + ".part")
    opener = opener or _default_opener

    if dest.is_file():
        if dest.stat().st_size == source.bytes and not replace:
            _check_hash(dest, source, progress=progress, cancel=cancel)
            _record_install(source, dest, "download", verified=True)
            return {"status": "present", "model_id": model_id, "path": str(dest),
                    "bytes": dest.stat().st_size, "sha256": source.sha256}
        if not replace:
            raise ModelError(
                f"{dest.name} exists but is {human_bytes(dest.stat().st_size)}, "
                f"expected {human_bytes(source.bytes)}. Pass replace to "
                "download it again.", code="exists_wrong_size")

    offset = part.stat().st_size if part.is_file() else 0
    if offset > source.bytes:      # a stale/garbage .part: restart, don't resume
        offset = 0
    needed = max(0, source.bytes - offset)
    free = disk_free(dest_dir)
    if free["free_bytes"] >= 0 and free["free_bytes"] < needed * 1.02 + (64 << 20):
        raise ModelError(
            f"Not enough space in {dest_dir} for {source.label}: needs "
            f"{human_bytes(needed)} more, only {free['free_human']} free. "
            "Point TERABIT_DATA_DIR at a bigger drive and retry.",
            code="no_space", free_bytes=free["free_bytes"], needed=needed)
    if progress:
        progress(offset, source.bytes, 0.0)

    rate = _Rate()
    last_error: Optional[Exception] = None
    for attempt in range(1, max(1, attempts) + 1):
        if cancel is not None and cancel.is_set():
            return {"status": "cancelled", "model_id": model_id,
                    "part": str(part), "downloaded": part.stat().st_size
                    if part.is_file() else 0}
        try:
            downloaded = _transfer(source, part, offset, progress, cancel,
                                   opener, timeout, rate)
        except ModelError:
            raise
        except Exception as exc:  # noqa: BLE001 - retried below
            last_error = exc
            if attempt < attempts:
                time.sleep(backoff_s * attempt)
                offset = part.stat().st_size if part.is_file() else 0
                continue
            raise ModelError(
                f"Download of {source.label} failed after {attempt} attempts: "
                f"{type(exc).__name__}: {exc}. The partial file is kept, so a "
                "retry resumes where it stopped.", code="network") from exc
        if downloaded is None:  # cancelled mid-transfer
            return {"status": "cancelled", "model_id": model_id,
                    "part": str(part),
                    "downloaded": part.stat().st_size if part.is_file() else 0}
        if downloaded != source.bytes:
            raise ModelError(
                f"Download stopped at {human_bytes(downloaded)} of "
                f"{human_bytes(source.bytes)} and the server sent no more data. "
                "Retry to resume.", code="incomplete")
        break

    if last_error is not None and not part.is_file():
        raise ModelError(f"Download failed: {last_error}", code="network")

    _check_hash(part, source, progress=progress, cancel=cancel)
    os.replace(part, dest)
    _record_install(source, dest, "download", verified=True)
    return {"status": "downloaded", "model_id": model_id, "path": str(dest),
            "bytes": dest.stat().st_size, "sha256": source.sha256}


def _transfer(source: ModelSource, part: Path, offset: int,
              progress: Optional[Callable], cancel: Optional[threading.Event],
              opener: Callable, timeout: float, rate: _Rate) -> Optional[int]:
    """One HTTP attempt. Returns bytes-on-disk, or None if cancelled.

    Range handling is explicit because the two failure modes matter: a server
    that honours `Range` (206) appends to the .part file; a server that
    ignores it (200) is treated as "start over", never as "append the whole
    body to a half file" -- that would produce a plausible-looking corrupt
    model, the exact bug the SHA check exists to catch.
    """
    headers = {"User-Agent": "TerabitStudio/1.1 (+local model provisioning)"}
    if offset > 0:
        headers["Range"] = f"bytes={offset}-"
    with opener(source.url, headers, timeout) as response:
        status = getattr(response, "status", 200)
        if status == 416:
            # The .part is at least as large as the file; if it is exactly the
            # right size the hash check decides; otherwise start clean.
            if offset == source.bytes:
                return offset
            part.unlink(missing_ok=True)
            raise ModelError("Server rejected the resume range.", code="resume")
        if offset > 0 and status != 206:
            offset = 0
        mode = "ab" if (offset > 0 and status == 206) else "wb"
        if mode == "wb":
            offset = 0
        done = offset
        with open(part, mode) as fh:
            while True:
                if cancel is not None and cancel.is_set():
                    fh.flush()
                    return None
                block = response.read(CHUNK)
                if not block:
                    break
                fh.write(block)
                done += len(block)
                if progress:
                    progress(done, source.bytes, rate.update(done))
        return done


# ───────────────────────────── verifying / import ─────────────────────────────

def verify_installed(model_id: str, progress: Optional[Callable] = None,
                     cancel: Optional[threading.Event] = None) -> dict:
    """Re-hash what is on disk against the catalogue. This is what turns
    "there is a file" into "there is a model"."""
    source = get_source(model_id)
    entry = installed().get(model_id) or {}
    path = Path(entry.get("path") or "")
    if not path.is_file():
        raise ModelError(f"{source.label} is not installed.", code="not_installed")
    started = time.monotonic()
    _check_size(path, source)
    _check_hash(path, source, progress=progress, cancel=cancel)
    _record_install(source, path, entry.get("delivery", "download"), verified=True)
    return {"model_id": model_id, "path": str(path), "verified": True,
            "bytes": path.stat().st_size, "sha256": source.sha256,
            "seconds": round(time.monotonic() - started, 1)}


def import_file(path: str, model_id: Optional[str] = None,
                progress: Optional[Callable] = None,
                cancel: Optional[threading.Event] = None) -> dict:
    """Point the app at a `.gguf` that already exists -- next to the installer,
    in a Downloads folder, on a USB stick. Nothing is copied: the manifest
    records the path and what we learned about it.

    A catalogue match is trusted only after the size AND hash agree. An
    unmatched file is still accepted (it is the user's machine and their
    file), recorded under its own hash-derived id, and marked unverified so
    the UI can say which of the two it is.
    """
    target = Path(path).expanduser()
    if not target.is_file():
        raise ModelError(f"No file at {target}", code="not_found")
    if target.suffix.lower() != ".gguf":
        raise ModelError(f"{target.name} is not a .gguf model file.",
                         code="not_gguf")
    size = target.stat().st_size
    if size < MIN_MODEL_BYTES:
        raise ModelError(
            f"{target.name} is only {human_bytes(size)} -- that is not a model "
            "file.", code="too_small")

    source = None
    if model_id:
        source = get_source(model_id)
    else:
        entry = {"path": str(target), "name": target.name, "bytes": size}
        source = match_gguf(entry)
    warning = None
    if source is not None:
        try:
            _check_size(target, source)
            _check_hash(target, source, progress=progress, cancel=cancel)
            _record_install(source, target, "import", verified=True)
            return {"accepted": True, "model_id": source.id, "path": str(target),
                    "bytes": size, "sha256": source.sha256, "verified": True,
                    "warning": None}
        except ModelError as exc:
            if exc.code not in ("size_mismatch", "hash_mismatch"):
                raise
            warning = (f"This file looks like {source.label} but failed its "
                       f"check: {exc}")

    digest = sha256_file(target, progress=progress, cancel=cancel)
    record_id = f"imported-{digest[:12]}"
    manifest_record(record_id, model_id=source.id if source else "",
                    file=str(target), file_name=target.name, bytes=size,
                    sha256=digest, delivery="import", verified=False,
                    verified_at=None)
    return {"accepted": True, "model_id": source.id if source else None,
            "record_id": record_id, "path": str(target), "bytes": size,
            "sha256": digest, "verified": False,
            "warning": warning or (
                "This is not one of the catalogue models; generation quality "
                "is whatever this file gives. It can still be used.")}


def installed_path(model_id: str) -> dict:
    """Resolve any usable form of a model to a path/tag, or explain why not."""
    entry = installed().get(model_id)
    if entry and entry.get("delivery") != "corrupt":
        return entry
    if entry and entry.get("delivery") == "corrupt":
        raise ModelError(
            f"The file for {model_id} is {human_bytes(entry['bytes'])} but the "
            f"model is {human_bytes(entry['expected_bytes'])} -- it is truncated "
            "or a different file. Delete it and download again.",
            code="corrupt")
    for row in imports():
        if row.get("record_id") == model_id or row.get("model_id") == model_id:
            if row["exists"]:
                return row
    raise ModelError(f"{model_id} is not installed on this machine.",
                     code="not_installed")


def activate(model_id: str, env_path: Optional[Path] = None) -> dict:
    """Make a model the one generation uses, without a restart.

    Writes MODEL_PATH / MODEL_NAME / TERABIT_ACTIVE_MODEL to the process
    environment AND to the .env the next launch reads, using the same
    preserve-every-other-line approach the fine-tune promotion uses. For an
    Ollama-delivered model MODEL_PATH is cleared, because the file is inside
    Ollama's store and must be addressed by tag, not by path.
    """
    source = next((m for m in effective_catalog() if m.id == model_id), None)
    if source is not None:
        entry = installed_path(model_id)
        if entry.get("delivery") == "ollama":
            values = {"MODEL_NAME": source.ollama_tag, "MODEL_PATH": ""}
        else:
            values = {"MODEL_NAME": Path(entry["path"]).stem,
                      "MODEL_PATH": entry["path"]}
    else:
        rows = [r for r in imports() if r["record_id"] == model_id]
        if not rows or not rows[0]["exists"]:
            raise ModelError(f"Unknown or missing model: {model_id}",
                             code="unknown_model")
        values = {"MODEL_NAME": Path(rows[0]["path"]).stem,
                  "MODEL_PATH": rows[0]["path"]}
    values["TERABIT_ACTIVE_MODEL"] = model_id
    for key, value in values.items():
        os.environ[key] = value
    # Switch the in-memory active model immediately so the running backend
    # uses it for the very next generation -- no restart required.
    model_service.set_active_model(model_id)
    env_file = env_path or paths.env_file()
    _write_env(env_file, values)
    warning = None
    ollama = probe_ollama()
    if values.get("MODEL_PATH") and ollama.get("reachable"):
        warning = (f"A server is already answering on {ollama['base_url']}. If "
                   "that is Ollama, it can only serve its own tags -- restart "
                   "the app with the bundled runtime (or stop Ollama) for "
                   "this file to be served.")
    return {"active": active_model(), "env_file": str(env_file),
            "warning": warning}


def _write_env(env_file: Path, values: dict) -> None:
    try:
        text = env_file.read_text(encoding="utf-8")
    except OSError:
        text = ""
    lines = text.splitlines()
    out: list[str] = []
    written: set[str] = set()
    for line in lines:
        stripped = line.strip()
        key = stripped.split("=", 1)[0].strip() if "=" in stripped else ""
        if key in values and not stripped.startswith("#"):
            out.append(f"{key}={values[key]}")
            written.add(key)
        else:
            out.append(line)
    for key, value in values.items():
        if key not in written:
            out.append(f"{key}={value}")
    try:
        env_file.parent.mkdir(parents=True, exist_ok=True)
        env_file.write_text("\n".join(out).rstrip("\n") + "\n", encoding="utf-8")
    except OSError as exc:
        raise ModelError(f"Could not write {env_file}: {exc}", code="env_write")


# ──────────────────────────────── state ────────────────────────────────

def state() -> dict:
    """The one report the first-run screen needs. Never raises: a probe that
    fails becomes an issue string, because this is the screen a user lands on
    precisely when things are broken."""
    issues: list[str] = []
    try:
        catalog = effective_catalog()
    except ModelError as exc:
        return {"ok": False, "issues": [str(exc)], "catalog": [],
                "models_dir": str(models_dir()), "installed": {},
                "ollama": probe_ollama(), "runtime": {"llama_server": find_llama_server()},
                "vram_gb": detect_vram_gb(), "recommended": "",
                "active": active_model(), "disk": disk_free(models_dir()),
                "imports": imports(), "unmatched_ggufs": []}

    ollama = probe_ollama()
    runtime = find_llama_server()
    vram = detect_vram_gb()
    installed_map = installed(catalog, ollama)
    manifest = manifest_read()
    models = models_dir()
    disk = disk_free(models)
    imported = imports()
    unmatched = [g for g in scan_ggufs() if match_gguf(g, catalog) is None]

    rows = []
    for source in catalog:
        entry = installed_map.get(source.id) or {}
        rows.append({
            **source.public(),
            "status": ("installed" if entry.get("delivery") not in (None, "ollama")
                       else "ollama" if entry.get("delivery") == "ollama"
                       else "absent"),
            "delivery": entry.get("delivery"),
            "path": entry.get("path", ""),
            "verified": bool(entry.get("verified")),
            "available": bool(entry),
        })

    recommended = recommend(vram, catalog)
    active = active_model()
    ollama_ready = any(r["status"] == "ollama" for r in rows)
    installed_ready = any(r["available"] for r in rows)

    if not runtime["found"] and not ollama.get("reachable"):
        issues.append(
            "No model runtime found: neither a llama-server binary nor a local "
            "Ollama on " + ollama["base_url"] + ". Install Ollama "
            "(https://ollama.com), or wait for the bundled runtime.")
    if not installed_ready and not ollama_ready:
        downloadable = [r for r in rows if r["downloadable"]]
        if downloadable:
            issues.append(
                "No model installed yet. Download the recommended model in "
                "Model setup below ("
                + ", ".join(f"{r['label']} {human_bytes(r['bytes'])}"
                            for r in downloadable[:2]) + ").")
        else:
            issues.append(
                "No model installed and no download source is configured. "
                "Import a .gguf file (Model setup below) or install Ollama and "
                "pull a tag.")
    if not active.get("model_path") and not active.get("id"):
        issues.append("No model is selected yet -- pick one in Model setup.")
    if 0 <= disk["free_bytes"] < (2 << 30):
        issues.append(
            f"Only {disk['free_human']} free in {disk['path']}; a model needs "
            "up to 4.7 GB. Set TERABIT_DATA_DIR to a roomier drive.")
    for model_id, row in manifest.items():
        if not row.get("file"):
            continue
        path = Path(row["file"])
        if not path.is_file():
            issues.append(
                f"Recorded model file is missing: {row['file']} "
                f"(id {model_id}). Re-import it or download again.")
    if active.get("model_path") and not Path(active["model_path"]).is_file():
        issues.append(
            f"The active model file is gone: {active['model_path']}. Pick "
            "another model in Model setup.")

    return {
        "ok": not issues,
        "issues": issues,
        "catalog": rows,
        "models_dir": str(models),
        "disk": disk,
        "ollama": ollama,
        "runtime": {"llama_server": runtime, "ollama": bool(ollama.get("reachable"))},
        "vram_gb": vram,
        "recommended": recommended,
        "active": active,
        "installed": {k: v for k, v in installed_map.items()},
        "imports": imported,
        "unmatched_ggufs": unmatched,
        "search_dirs": [str(d) for d in search_dirs()],
    }
