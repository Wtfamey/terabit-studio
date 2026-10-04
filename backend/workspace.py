"""Local folder workspace: point the app at a real project and edit inside it.

This is the module that makes Terabit a tool rather than a page that returns a
blob -- the Cursor half of the product. A user opens a folder; the app reads
it, generates against it and writes back into it. That means this file is the
only place in the codebase that writes to paths the user did not create, so it
is written defensively and tested like an attacker (see probe_workspace_api.py
and test_workspace.py).

The threat model is not "a malicious user attacks their own machine"; it is:
every path arriving here came from a URL, a JSON body or a model's generated
file list, and a single missed check turns "edit my project" into "read
C:\\Windows\\win.ini" or "write outside the folder it was given".

Rules, each one earning its place:

  * Containment is checked AFTER os.path.realpath, so a symlink inside the
    project that points outside is caught. Checking the string prefix first is
    the classic version of this bug.
  * Symlinks are refused on the UNRESOLVED path -- os.path.is_symlink() after
    realpath() is always False, and that bug shipped here once.
  * Absolute paths, drive-relative paths ("C:x"), UNC paths, "..", null bytes,
    reserved Windows device names and trailing dots/spaces are all refused up
    front, because they are wrong on every platform even when one of them
    happens to resolve locally.
  * Writes are atomic: temp sibling + os.replace. A crash mid-write must never
    truncate a file the user already had.
  * Overwrites carry a backup, and `/apply` does not overwrite by default --
    the agent emits a React project and the folder the user opened is usually
    something else, so collisions are reported, not clobbered.
  * A hostile path in a generated file list fails ONE file, never the batch.

The API surface is deliberately small: open_root / get / list_open / close /
copy_out at module level, and tree / read / write / apply_files on a Workspace.
"""
from __future__ import annotations

import os
import re
import tempfile
import threading
import time
import uuid
import zipfile
from pathlib import Path

MAX_FILES = 4000
MAX_READ_BYTES = 2_000_000
BINARY_SNIFF = 8000

# Directories that are never listed, read from or written to. "node_modules"
# is a dependency store, not the user's source; ".git" is history, and a
# generated file landing inside it corrupts a repository.
EXCLUDED_DIRS = {
    ".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv",
    ".next", ".nuxt", ".cache", ".terraform", ".terabit", ".idea", ".vscode",
    ".pytest_cache", ".mypy_cache", ".tox", "env",
}

# Windows device names. Reserved in every directory, on every drive, with or
# without an extension -- "CON.txt" opens the console.
_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)),
             *(f"lpt{i}" for i in range(1, 10))}

_LANG = {
    ".py": "python", ".js": "javascript", ".jsx": "javascript",
    ".ts": "typescript", ".tsx": "typescript", ".json": "json",
    ".html": "html", ".htm": "html", ".css": "css", ".scss": "scss",
    ".md": "markdown", ".txt": "text", ".yml": "yaml", ".yaml": "yaml",
    ".toml": "toml", ".sql": "sql", ".sh": "shell", ".ps1": "powershell",
    ".java": "java", ".go": "go", ".rs": "rust", ".rb": "ruby", ".php": "php",
    ".c": "c", ".h": "c", ".cpp": "cpp", ".cs": "csharp", ".svg": "xml",
    ".xml": "xml", ".env": "text", ".ini": "ini", ".csv": "csv",
}


class WorkspaceError(Exception):
    """A refusal with a human-readable reason (surfaced as HTTP 400)."""


# --------------------------------------------------------------- path policy

def _reject_reason(raw: str) -> str | None:
    """Why this path can never be used, or None if it survives inspection.

    Called before any filesystem access, on every path from every source.
    """
    if raw is None:
        return "No path was given."
    if "\x00" in raw:
        return "That path contains a null byte."
    p = raw.replace("\\", "/")
    if not p.strip():
        return "No path was given."
    # Leading whitespace is trimmed for the *shape* checks only; it is what
    # makes " /etc/passwd" an absolute path rather than a filename.
    pl = p.lstrip()
    if pl.startswith("/"):
        return "Absolute paths are not allowed; use a path inside the folder."
    if re.match(r"^[A-Za-z]:", pl):
        return "Drive-letter paths are not allowed; use a path inside the folder."
    if pl.startswith("//"):  # UNC ("\\\\server\\share") after the replace above
        return "UNC paths are not allowed."
    segments = [s for s in p.strip("/").split("/") if s not in ("", ".")]
    if not segments:
        return "No path was given."
    for seg in segments:
        if seg == "..":
            return "'..' is not allowed; paths must stay inside the folder."
        # A name may start with a dot ('.gitignore' is a real file) but may not
        # END with a dot or a space: Windows silently strips those, so
        # "index.html " and "index.html" are the same file and two different
        # requests would not be. Leading spaces are ambiguous too.
        if seg.lstrip(" ") != seg or seg.rstrip(" .") != seg:
            return f"'{seg}' has leading/trailing whitespace or a trailing dot."
        stem = seg.split(".")[0].lower()
        if stem in _RESERVED:
            return f"'{seg}' is a reserved Windows device name."
        if seg.lower() in EXCLUDED_DIRS:
            return f"'{seg}' is excluded (dependency, VCS or cache directory)."
    return None


def _contained(root: Path, raw: str) -> Path:
    """Resolve `raw` inside `root`, or raise WorkspaceError.

    Two checks, in this order, and both are load-bearing:
      1. every existing segment is refused if it is a symlink (on the
         UNRESOLVED path -- after realpath a symlink is indistinguishable);
      2. the realpath of the target is inside the realpath of the root.
    """
    reason = _reject_reason(raw)
    if reason:
        raise WorkspaceError(reason)
    rel = raw.replace("\\", "/").strip().lstrip("/")
    probe = root
    for seg in [s for s in rel.split("/") if s not in ("", ".")]:
        probe = probe / seg
        if probe.is_symlink():
            raise WorkspaceError(
                f"'{seg}' is a symlink; refusing to follow it out of the folder.")
    target = (root / rel)
    real_root = Path(os.path.realpath(root))
    real = Path(os.path.realpath(target))
    try:
        real.relative_to(real_root)
    except ValueError:
        raise WorkspaceError("That path resolves outside the opened folder.") from None
    return target


def _language_of(name: str) -> str:
    suffix = Path(name).suffix.lower()
    if suffix:
        return _LANG.get(suffix, suffix.lstrip("."))
    return _LANG.get(name.lower(), "text")


# ----------------------------------------------------------------- workspace

class Workspace:
    """One opened folder. Created through `open_root`, never directly."""

    def __init__(self, root: Path):
        self.id = uuid.uuid4().hex[:16]
        self.root = Path(os.path.realpath(root))
        self.name = self.root.name or str(self.root)
        self.opened_at = time.time()

    # -- listing ----------------------------------------------------------
    def tree(self) -> dict:
        files: list[dict] = []
        truncated = False
        for dirpath, dirnames, filenames in os.walk(self.root):
            # In-place so os.walk does not descend into them at all.
            dirnames[:] = sorted(d for d in dirnames
                                 if d.lower() not in EXCLUDED_DIRS)
            for name in sorted(filenames):
                full = Path(dirpath) / name
                if full.is_symlink():
                    continue
                rel = full.relative_to(self.root).as_posix()
                try:
                    size = full.stat().st_size
                except OSError:
                    continue
                files.append({"path": rel, "size": size,
                              "language": _language_of(name)})
                if len(files) >= MAX_FILES:
                    truncated = True
                    break
            if truncated:
                break
        return {"id": self.id, "root": str(self.root), "name": self.name,
                "files": files, "truncated": truncated}

    # -- read -------------------------------------------------------------
    def read(self, raw_path: str) -> dict:
        target = _contained(self.root, raw_path)
        if not target.exists() or not target.is_file():
            raise WorkspaceError("That file does not exist in the opened folder.")
        try:
            size = target.stat().st_size
        except OSError as exc:  # noqa: BLE001
            raise WorkspaceError(f"Could not read that file: {exc}") from None
        if size > MAX_READ_BYTES:
            return {"path": raw_path, "content": "", "too_large": True,
                    "message": (f"{target.name} is {size // 1024} KB; open it in "
                                f"your editor instead of the built-in viewer.")}
        try:
            blob = target.read_bytes()
        except OSError as exc:  # noqa: BLE001
            raise WorkspaceError(f"Could not read that file: {exc}") from None
        if b"\x00" in blob[:BINARY_SNIFF]:
            return {"path": raw_path, "content": "", "binary": True,
                    "message": f"{target.name} looks like a binary file."}
        text = blob.decode("utf-8", "replace")
        return {"path": raw_path, "content": text, "bytes": size,
                "language": _language_of(target.name)}

    # -- write ------------------------------------------------------------
    def write(self, raw_path: str, content: str) -> dict:
        target = _contained(self.root, raw_path)
        previous = None
        created = True
        if target.exists():
            if target.is_dir():
                raise WorkspaceError("That path is a directory.")
            created = False
            try:
                previous = target.read_text(encoding="utf-8", errors="replace")
            except OSError:  # noqa: BLE001
                previous = None
        _atomic_write(target, content)
        return {"path": raw_path, "bytes": len(content.encode("utf-8")),
                "created": created, "previous": previous}

    # -- apply a generated file list --------------------------------------
    def apply_files(self, files: list[dict], overwrite: bool = False) -> dict:
        """Write a generated list. One bad path fails one file, not the batch."""
        written: list[str] = []
        skipped: list[str] = []
        failed: list[dict] = []
        backups: dict[str, str] = {}
        for item in files or []:
            if not isinstance(item, dict):
                failed.append({"path": "", "error": "entry is not an object"})
                continue
            rel = str(item.get("path") or "")
            content = str(item.get("content") or "")
            try:
                target = _contained(self.root, rel)
            except WorkspaceError as exc:
                failed.append({"path": rel, "error": str(exc)})
                continue
            if target.exists() and not overwrite:
                skipped.append(rel)
                continue
            try:
                if target.exists():
                    try:
                        backups[rel] = target.read_text(encoding="utf-8",
                                                        errors="replace")
                        _backup(self.root, rel, backups[rel])
                    except OSError:  # noqa: BLE001
                        pass
                _atomic_write(target, content)
            except OSError as exc:  # noqa: BLE001
                failed.append({"path": rel, "error": f"write failed: {exc}"})
                continue
            written.append(rel)
        return {"written": written, "skipped": skipped, "failed": failed,
                "backups": backups}


def _atomic_write(target: Path, content: str) -> None:
    """Temp sibling + os.replace. Never leave a half-written file behind."""
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".terabit-", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(content)
        os.replace(tmp, target)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _backup(root: Path, rel: str, content: str) -> None:
    """Keep the replaced version under .terabit/backups/<ts>/<rel>."""
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dest = root / ".terabit" / "backups" / stamp / rel
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        # newline="" so the backup is byte-faithful: a backup that silently
        # rewrites every \n to \r\n is not an undo, it is a second edit.
        with open(dest, "w", encoding="utf-8", newline="") as fh:
            fh.write(content)
    except OSError:
        pass  # a backup is a courtesy; it must never fail a write


# --------------------------------------------------------------- registry

_LOCK = threading.Lock()
_OPEN: dict[str, Workspace] = {}


def open_root(path: str) -> Workspace:
    if path is None or not str(path).strip():
        raise WorkspaceError("Choose a folder first.")
    root = Path(str(path).strip().strip('"')).expanduser()
    if not root.exists():
        raise WorkspaceError(f"That folder does not exist: {root}")
    if not root.is_dir():
        raise WorkspaceError(f"That path is not a folder: {root}")
    if root.is_symlink():
        raise WorkspaceError("That folder is a symlink; refusing to follow it.")
    ws = Workspace(root)
    with _LOCK:
        _OPEN[ws.id] = ws
    return ws


def get(workspace_id: str) -> Workspace:
    with _LOCK:
        ws = _OPEN.get(str(workspace_id))
    if ws is None:
        raise WorkspaceError(
            "That folder is not open any more. Open it again to continue.")
    if not ws.root.exists():
        raise WorkspaceError("The opened folder no longer exists on disk.")
    return ws


def list_open() -> list[dict]:
    with _LOCK:
        return [{"id": w.id, "root": str(w.root), "name": w.name}
                for w in _OPEN.values()]


def close(workspace_id: str) -> bool:
    with _LOCK:
        return _OPEN.pop(str(workspace_id), None) is not None


def copy_out(ws: Workspace, name: str = "terabit-export") -> str:
    """Zip the folder out to a place the user can find, for export/download."""
    safe = re.sub(r"[^\w.-]+", "-", str(name or "terabit-export")).strip("-")
    out_dir = Path(tempfile.gettempdir()) / "terabit-exports"
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / f"{safe or 'terabit-export'}-{time.strftime('%Y%m%d-%H%M%S')}.zip"
    listing = ws.tree()
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        for entry in listing["files"]:
            full = ws.root / entry["path"]
            try:
                zf.write(full, arcname=f"{ws.name}/{entry['path']}")
            except OSError:
                continue
    return str(dest)
