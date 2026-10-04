"""Module-level tests for the local folder workspace.

`probe_workspace_api.py` proves containment survives the wire (URL decoding,
JSON bodies, query strings). This suite proves the same rules inside Python,
and covers the two things a request-level probe cannot express well:

  * a SYMLINK inside the project that points outside it -- the classic
    containment bug, and the one the first draft of workspace.py shipped;
  * what happens on disk: atomic writes, backups for replacements, excluded
    directories, binary/large reads, and the export zip.

Run:  cd backend && python test_workspace.py
"""
import os
import shutil
import tempfile
import zipfile
from pathlib import Path

import workspace as ws_mod

PASS = 0


def check(cond, msg):
    global PASS
    assert cond, f"FAIL {msg}"
    PASS += 1


def refuses(path, why):
    try:
        ws_mod._contained(root, path)
    except ws_mod.WorkspaceError:
        check(True, why)
        return
    check(False, f"{why}: {path!r} was allowed")


# ── fixture: a real project, a sentinel OUTSIDE it, and a symlink out ─────
base = Path(tempfile.mkdtemp(prefix="terabit-ws-test-"))
outside = base / "outside"
root = base / "project"
(outside).mkdir()
(root / "src").mkdir(parents=True)
(root / "node_modules" / "x").mkdir(parents=True)
(root / ".git").mkdir()
(outside / "secret.txt").write_text("LEAKED-SENTINEL-9f3a", encoding="utf-8")
(root / "index.html").write_text("<h1>hello</h1>", encoding="utf-8")
(root / "src" / "app.py").write_text("print(1)\n", encoding="utf-8")
(root / "node_modules" / "x" / "evil.js").write_text("evil", encoding="utf-8")
(root / ".git" / "config").write_text("[core]", encoding="utf-8")
(root / "binary.bin").write_bytes(b"\x00\x01\x02binary")
(root / "big.txt").write_text("x" * 50, encoding="utf-8")

symlink_ok = True
try:
    os.symlink(outside / "secret.txt", root / "alias.txt")
except (OSError, NotImplementedError):
    symlink_ok = False

w = ws_mod.open_root(str(root))
check(w.id, "open_root returns an id")
check(Path(w.root) == root.resolve(), "root is the resolved folder")

# ── path policy ───────────────────────────────────────────────────────────
for hostile, why in [
    ("../secret.txt", "parent escape"),
    ("src/../../secret.txt", "deep parent escape"),
    ("/etc/passwd", "absolute posix"),
    ("C:/Windows/win.ini", "absolute windows"),
    ("C:secret.txt", "drive relative"),
    ("\\\\localhost\\c$\\windows", "UNC"),
    ("node_modules/x/evil.js", "dependency dir"),
    (".git/config", "vcs dir"),
    ("   ", "whitespace only"),
    ("index.html.", "trailing dot"),
    ("index.html ", "trailing space"),
    ("index.html\x00.txt", "null byte"),
    ("con.txt", "reserved device name"),
    ("src/nul", "reserved name in subdir"),
]:
    refuses(hostile, why)
if symlink_ok:
    refuses("alias.txt", "symlink escaping the folder")
    check("alias.txt" not in {f["path"] for f in w.tree()["files"]},
          "symlinked files are not listed")

# ── tree ──────────────────────────────────────────────────────────────────
tree = w.tree()
paths = {f["path"] for f in tree["files"]}
check("src/app.py" in paths and "index.html" in paths, f"tree: {sorted(paths)}")
check(not any(p.startswith("node_modules") for p in paths), "node_modules hidden")
check(not any(p.startswith(".git") for p in paths), ".git hidden")
entry = next(f for f in tree["files"] if f["path"] == "src/app.py")
check(entry["language"] == "python" and entry["size"] > 0, entry)
check(tree["name"] == root.name and not tree["truncated"], "tree metadata")

# ── read ──────────────────────────────────────────────────────────────────
got = w.read("src/app.py")
# the fixture was written in text mode, so it may carry Windows newlines
check(got["content"].replace("\r\n", "\n") == "print(1)\n"
      and not got.get("binary"), got)
check(w.read("binary.bin").get("binary") is True, "binary detection")
big = w.read("big.txt")
check(big.get("too_large") is True or big["content"], "large read has a verdict")
for hostile, why in [("../secret.txt", "read parent escape"),
                     (".git/config", "read vcs dir"),
                     ("nope.txt", "missing file")]:
    try:
        w.read(hostile)
        check(False, f"{why} was allowed")
    except ws_mod.WorkspaceError:
        check(True, why)

# ── write: atomic, created flag, previous content ─────────────────────────
res = w.write("src/new.py", "y = 2\n")
check(res["created"] is True and res["bytes"] == len("y = 2\n".encode()), res)
check((root / "src" / "new.py").read_text() == "y = 2\n", "file on disk")
res = w.write("src/new.py", "y = 3\n")
check(res["created"] is False and res["previous"] == "y = 2\n", res)
check(not list((root / "src").glob(".terabit-*")), "no temp files left behind")

# ── apply: collision policy, backups, one bad file never fails the batch ──
applied = w.apply_files([
    {"path": "src/new.py", "content": "y = 4\n"},        # collision -> skipped
    {"path": "docs/readme.md", "content": "# hi\n"},     # new -> written
    {"path": "../escape.py", "content": "x"},            # hostile -> failed
])
check(applied["skipped"] == ["src/new.py"], applied)
check(applied["written"] == ["docs/readme.md"], applied)
check(len(applied["failed"]) == 1 and applied["failed"][0]["path"] == "../escape.py", applied)
check((root / "docs" / "readme.md").read_text() == "# hi\n", "new file written")

applied = w.apply_files([{"path": "src/new.py", "content": "y = 5\n"}], overwrite=True)
check(applied["written"] == ["src/new.py"], applied)
check(applied["backups"].get("src/new.py") == "y = 3\n", applied["backups"])
check((root / "src" / "new.py").read_text() == "y = 5\n", "overwrite landed")
stamp_dirs = list((root / ".terabit" / "backups").glob("*"))
check(bool(stamp_dirs), "a backup is kept on disk")
check((stamp_dirs[0] / "src" / "new.py").read_text() == "y = 3\n", "backup content")
check(not any(p.startswith(".terabit") for p in
              {f["path"] for f in w.tree()["files"]}),
      "backups are not part of the tree")

# ── unicode round trip ────────────────────────────────────────────────────
w.write("docs/नोट्स.md", "पाठ\n")
check(w.read("docs/नोट्स.md")["content"] == "पाठ\n", "unicode path round trip")

# ── registry: get / list / close ──────────────────────────────────────────
check(ws_mod.get(w.id).id == w.id, "get by id")
check(any(x["id"] == w.id for x in ws_mod.list_open()), "list_open")
check(ws_mod.close(w.id) is True, "close returns True")
try:
    ws_mod.get(w.id)
    check(False, "closed workspace must be refused")
except ws_mod.WorkspaceError:
    check(True, "closed workspace refused")
check(ws_mod.close("not-a-real-id") is False, "closing an unknown id is False")

w2 = ws_mod.open_root(str(root))
dest = ws_mod.copy_out(w2, "my project!")
check(dest.endswith(".zip") and os.path.exists(dest), dest)
with zipfile.ZipFile(dest) as zf:
    names = zf.namelist()
check(any(n.endswith("src/app.py") for n in names), names[:6])
check(not any("node_modules" in n for n in names), "export excludes deps")

# ── folder shape errors are refusals, not tracebacks ─────────────────────
for bad, why in [(str(base / "missing"), "missing folder"),
                 (str(outside / "secret.txt"), "a file, not a folder"),
                 ("", "empty path")]:
    try:
        ws_mod.open_root(bad)
        check(False, f"{why} was opened")
    except ws_mod.WorkspaceError:
        check(True, why)

shutil.rmtree(base, ignore_errors=True)
if dest:
    try:
        os.remove(dest)
    except OSError:
        pass
print(f"ALL WORKSPACE TESTS PASS ({PASS} checks)")
