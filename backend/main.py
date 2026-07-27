import os
import re
import io
import uuid
import zipfile
import json
from pathlib import Path
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException, Depends, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi import Request
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional

from model_service import generate_response, generate_response_stream, start_server
from rag_engine import rag_search, generate_business_system_prompt
from database import get_db, User, ChatSession, ChatMessage, Asset
from auth import verify_password, hash_password, create_token, get_current_user
from preview_builder import build_preview_html

UPLOAD_DIR = Path(__file__).resolve().parent / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

app = FastAPI(title="TerabitStudio - AI Business OS Generator")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ───────── Request schemas ─────────

class RegisterRequest(BaseModel):
    email: str
    password: str

class LoginRequest(BaseModel):
    email: str
    password: str

class ChatRequest(BaseModel):
    messages: list
    temperature: float = 0.7
    max_tokens: int = 2048
    session_id: Optional[int] = None

class AssetInfo(BaseModel):
    url: str
    filename: str
    mime_type: str

class GenerateRequest(BaseModel):
    prompt: str
    business_type: str = "general"
    features: list = []
    assets: list[AssetInfo] = []
    temperature: float = 0.85
    session_id: Optional[int] = None

class SearchRequest(BaseModel):
    query: str
    mode: str = "chat"

class DownloadRequest(BaseModel):
    files: list
    project_name: str = "project"

class SessionCreateRequest(BaseModel):
    name: str = "New Chat"

# ───────── Startup ─────────

@app.on_event("startup")
async def startup():
    start_server()

# ───────── Auth endpoints ─────────

@app.post("/api/auth/register")
def register(req: RegisterRequest, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.email == req.email).first()
    if existing:
        raise HTTPException(400, "Email already registered")
    user = User(email=req.email, password_hash=hash_password(req.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    token = create_token({"sub": str(user.id)})
    return {"token": token, "user": {"id": user.id, "email": user.email}}

@app.post("/api/auth/login")
def login(req: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == req.email).first()
    if not user or not verify_password(req.password, user.password_hash):
        raise HTTPException(401, "Invalid email or password")
    token = create_token({"sub": str(user.id)})
    return {"token": token, "user": {"id": user.id, "email": user.email}}

@app.get("/api/auth/me")
def me(user: Optional[User] = Depends(get_current_user)):
    if not user:
        raise HTTPException(401, "Not authenticated")
    return {"id": user.id, "email": user.email}

# ───────── Session endpoints ─────────

@app.get("/api/sessions")
def list_sessions(user: Optional[User] = Depends(get_current_user), db: Session = Depends(get_db)):
    if not user:
        return []
    sessions = db.query(ChatSession).filter(
        ChatSession.user_id == user.id
    ).order_by(ChatSession.updated_at.desc()).all()
    return [
        {"id": s.id, "name": s.name, "created_at": s.created_at.isoformat(), "updated_at": s.updated_at.isoformat()}
        for s in sessions
    ]

@app.post("/api/sessions")
def create_session(req: SessionCreateRequest, user: Optional[User] = Depends(get_current_user), db: Session = Depends(get_db)):
    if not user:
        # Allow anonymous sessions (no auth required for basic use)
        return {"id": 0, "name": req.name, "anonymous": True}
    session = ChatSession(user_id=user.id, name=req.name)
    db.add(session)
    db.commit()
    db.refresh(session)
    return {"id": session.id, "name": session.name, "created_at": session.created_at.isoformat()}

@app.delete("/api/sessions/{session_id}")
def delete_session(session_id: int, user: Optional[User] = Depends(get_current_user), db: Session = Depends(get_db)):
    session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    if not session:
        raise HTTPException(404, "Session not found")
    if user and session.user_id != user.id:
        raise HTTPException(403, "Forbidden")
    db.query(ChatMessage).filter(ChatMessage.session_id == session_id).delete()
    db.delete(session)
    db.commit()
    return {"ok": True}

# ───────── Message endpoints ─────────

@app.get("/api/sessions/{session_id}/messages")
def get_messages(session_id: int, db: Session = Depends(get_db)):
    messages = db.query(ChatMessage).filter(
        ChatMessage.session_id == session_id
    ).order_by(ChatMessage.created_at.asc()).all()
    return [
        {"id": m.id, "role": m.role, "content": m.content, "created_at": m.created_at.isoformat()}
        for m in messages
    ]

# ───────── Asset endpoints ─────────

ALLOWED_MIME_TYPES = {
    "image/jpeg", "image/png", "image/gif", "image/webp", "image/svg+xml",
    "application/pdf", "text/plain", "text/csv",
}

@app.post("/api/upload")
async def upload_asset(
    file: UploadFile = File(...),
    user: Optional[User] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if file.content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(400, f"Unsupported file type: {file.content_type}")
    ext = file.filename.rsplit(".", 1)[-1] if "." in file.filename else "bin"
    stored_name = f"{uuid.uuid4().hex}.{ext}"
    file_path = UPLOAD_DIR / stored_name
    content = await file.read()
    file_path.write_bytes(content)
    asset = Asset(
        user_id=user.id if user else None,
        filename=stored_name,
        original_name=file.filename,
        mime_type=file.content_type or "application/octet-stream",
        size=len(content),
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return {
        "id": asset.id,
        "url": f"/uploads/{stored_name}",
        "filename": stored_name,
        "original_name": file.filename,
        "mime_type": asset.mime_type,
        "size": asset.size,
        "created_at": asset.created_at.isoformat(),
    }


@app.get("/api/assets")
def list_assets(user: Optional[User] = Depends(get_current_user), db: Session = Depends(get_db)):
    query = db.query(Asset).order_by(Asset.created_at.desc())
    if user:
        query = query.filter((Asset.user_id == user.id) | (Asset.user_id == None))
    assets = query.all()
    return [
        {
            "id": a.id,
            "url": f"/uploads/{a.filename}",
            "filename": a.filename,
            "original_name": a.original_name,
            "mime_type": a.mime_type,
            "size": a.size,
            "created_at": a.created_at.isoformat(),
        }
        for a in assets
    ]


@app.delete("/api/assets/{asset_id}")
def delete_asset(
    asset_id: int,
    user: Optional[User] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    asset = db.query(Asset).filter(Asset.id == asset_id).first()
    if not asset:
        raise HTTPException(404, "Asset not found")
    if user and asset.user_id and asset.user_id != user.id:
        raise HTTPException(403, "Forbidden")
    file_path = UPLOAD_DIR / asset.filename
    if file_path.exists():
        file_path.unlink()
    db.delete(asset)
    db.commit()
    return {"ok": True}


# ───────── Core AI endpoints ─────────

SYSTEM_PROMPT = """You are TerabitStudio, an AI business systems architect.
You help users design, build, and refine business management systems.
Be concise, practical, and focus on delivering working solutions."""

@app.post("/api/chat")
async def chat(req: ChatRequest, user: Optional[User] = Depends(get_current_user), db: Session = Depends(get_db)):
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + req.messages
    response = generate_response(messages, temperature=req.temperature, max_tokens=req.max_tokens)

    if req.session_id and user:
        db.add(ChatMessage(session_id=req.session_id, role="user", content=req.messages[-1]["content"]))
        db.add(ChatMessage(session_id=req.session_id, role="assistant", content=response))
        db.commit()

    return {"response": response}


@app.post("/api/chat/stream")
async def chat_stream(req: ChatRequest, request: Request):
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + req.messages

    async def event_stream():
        for token in generate_response_stream(messages, temperature=req.temperature, max_tokens=req.max_tokens):
            if await request.is_disconnected():
                break
            yield f"data: {json.dumps({'token': token})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/api/generate")
async def generate(req: GenerateRequest, user: Optional[User] = Depends(get_current_user), db: Session = Depends(get_db)):
    system_prompt = generate_business_system_prompt(
        req.business_type, req.features, req.prompt,
        assets=[a.model_dump() for a in req.assets],
    )
    asset_context = ""
    if req.assets:
        asset_lines = "\n".join(
            f"- {a.filename} ({a.mime_type}): available at {a.url}"
            for a in req.assets
        )
        asset_context = f"\n\nUser has uploaded these assets you can reference in the code:\n{asset_lines}\nUse them via absolute URL paths like '{req.assets[0].url.split('/uploads/')[0] + '/uploads/'}...' when needed."
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Build a complete {req.business_type} system: {req.prompt}{asset_context}"},
    ]
    response = generate_response(messages, temperature=req.temperature, max_tokens=8192)

    files = parse_generated_files(response)
    if not files:
        files = parse_markdown_structure(response)

    files = validate_and_repair_files(files)
    files = inject_images(files)

    # Save to session if logged in
    if req.session_id and user:
        db.add(ChatMessage(session_id=req.session_id, role="user", content=req.prompt))
        db.add(ChatMessage(session_id=req.session_id, role="assistant", content=response))
        # Update session name from first prompt
        session = db.query(ChatSession).filter(ChatSession.id == req.session_id).first()
        if session and session.name == "New Chat":
            session.name = req.prompt[:40]
        db.commit()

    return {"response": response, "files": files}


@app.post("/api/generate/stream")
async def generate_stream(req: GenerateRequest, request: Request):
    system_prompt = generate_business_system_prompt(
        req.business_type, req.features, req.prompt,
        assets=[a.model_dump() for a in req.assets],
    )
    asset_context = ""
    if req.assets:
        asset_lines = "\n".join(
            f"- {a.filename} ({a.mime_type}): available at {a.url}"
            for a in req.assets
        )
        asset_context = f"\n\nUser has uploaded these assets you can reference in the code:\n{asset_lines}\nUse them via absolute URL paths when needed."
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Build a complete {req.business_type} system: {req.prompt}{asset_context}"},
    ]

    async def event_stream():
        buffer = ""
        for token in generate_response_stream(messages, temperature=req.temperature, max_tokens=8192):
            if await request.is_disconnected():
                break
            buffer += token
            yield f"data: {json.dumps({'token': token})}\n\n"
        # Final parse and send files
        files = parse_generated_files(buffer)
        if not files:
            files = parse_markdown_structure(buffer)
        yield f"data: {json.dumps({'done': True, 'files': files})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/api/search")
async def search(req: SearchRequest):
    if req.mode == "rag":
        context, sources = rag_search(req.query)
        if context:
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"Answer based on:\n\n{context}\n\nQuestion: {req.query}"},
            ]
            answer = generate_response(messages, max_tokens=1024)
            return {"answer": answer, "sources": sources}
        return {"answer": "No search results found.", "sources": []}

    response = generate_response(
        [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": req.query}],
        max_tokens=1024,
    )
    return {"answer": response, "sources": []}


@app.post("/api/correct")
async def correct_code(payload: dict):
    code = payload.get("code", "")
    language = payload.get("language", "auto")
    messages = [
        {"role": "system", "content": "You are a code review expert. Fix bugs, improve style, and optimize. Return only the corrected code."},
        {"role": "user", "content": f"Language: {language}\n\nCode:\n{code}"},
    ]
    corrected = generate_response(messages, temperature=0.1, max_tokens=4096)
    return {"corrected_code": corrected, "language": language}

# ───────── Preview & Download ─────────

@app.post("/api/preview")
async def generate_preview(payload: dict):
    """Build a self-contained HTML preview from generated project files."""
    files = payload.get("files", [])
    html = build_preview_html(files)
    return {"html": html}


@app.post("/api/download")
async def download_project(req: DownloadRequest):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in req.files:
            path = f.get("path", "")
            content = f.get("content", "")
            zf.writestr(path, content)
    buf.seek(0)
    safe_name = req.project_name.replace(" ", "_").replace("/", "_")
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename={safe_name}.zip"},
    )

# ───────── Status ─────────

@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "name": "TerabitStudio",
        "version": "1.1.0",
        "model": os.environ.get("MODEL_PATH", "").split("/")[-1] or "qwen2.5-coder-7b",
        "auth": bool(os.environ.get("JWT_SECRET", False)),
    }

# ───────── File Parsers ─────────

def parse_generated_files(response: str) -> list:
    files = []
    patterns = [
        r"`(.+?\.(?:jsx?|tsx?|css|html|json|py|env|yml|yaml|md|config\.js|config\.cjs))`\s*\n```[\w]*\n([\s\S]*?)```",
        r"`(.+?)`\s*\n```[\w]*\n([\s\S]*?)```",
        r"#### `(.+?)`\s*\n```[\w]*\n([\s\S]*?)```",
        r"\*\*(.+?)\*\*\s*\n```[\w]*\n([\s\S]*?)```",
    ]
    for pattern in patterns:
        matches = re.findall(pattern, response, re.MULTILINE)
        for filepath, content in matches:
            fp = filepath.strip().strip("`").strip("*").strip()
            if fp and content.strip():
                files.append({"path": fp, "content": content.strip()})
        if files:
            break
    # Deduplicate by path (keep last occurrence)
    seen = set()
    unique = []
    for f in reversed(files):
        if f["path"] not in seen:
            seen.add(f["path"])
            unique.append(f)
    return list(reversed(unique))


def parse_markdown_structure(response: str) -> list:
    files = []
    lines = response.split("\n")
    current_path = None
    current_content = []
    in_code = False

    for line in lines:
        if line.startswith("```"):
            if in_code:
                if current_path:
                    files.append({"path": current_path, "content": "\n".join(current_content).strip()})
                current_path = None
                current_content = []
                in_code = False
            else:
                in_code = True
                current_content = []
            continue
        if in_code:
            current_content.append(line)
        elif "`" in line:
            parts = line.split("`")
            for p in parts:
                stripped = p.strip()
                if any(stripped.endswith(ext) for ext in [".js", ".jsx", ".ts", ".tsx", ".css", ".html", ".json", ".py", ".yml", ".yaml", ".md", ".env"]):
                    current_path = stripped
                    break
                if "package.json" in stripped:
                    current_path = "package.json"
                    break
    return files

# ───────── Validation & Repair ─────────

IMPORT_PATTERN = re.compile(r'import\s+(?:\{[^}]*\}|\*\s+as\s+\w+|\w+(?:,\s*(?:\{[^}]*\}|\*\s+as\s+\w+|\w+))?)\s+from\s+[\'"]([^\'"]+)[\'"]')
EXTENSIONS = [".js", ".jsx", ".ts", ".tsx", ".mjs"]

PLACEHOLDER_COMPONENT = """// Auto-generated placeholder
export default function Placeholder() { return <div />; }
"""

PLACEHOLDER_MODULE = """// Auto-generated placeholder
const placeholder = {};
export default placeholder;
"""


def _resolve_import_path(importer_path: str, import_spec: str) -> str | None:
    """Resolve a relative import spec to an actual file path."""
    if not import_spec.startswith("."):
        return None  # node_modules import, skip

    base_dir = "/".join(importer_path.split("/")[:-1]) if "/" in importer_path else ""
    if base_dir:
        resolved = base_dir + "/" + import_spec
    else:
        resolved = import_spec

    resolved = resolved.replace("./", "")

    # Normalize ../
    parts = resolved.split("/")
    normalized = []
    for p in parts:
        if p == ".." and normalized:
            normalized.pop()
        elif p != "." and p != "..":
            normalized.append(p)
    resolved = "/".join(normalized)

    return resolved


def _find_file(exact_path: str, existing_paths: set) -> str | None:
    """Find a file with various extension attempts."""
    if exact_path in existing_paths:
        return exact_path
    base, _ = os.path.splitext(exact_path)
    for ext in EXTENSIONS:
        candidate = base + ext
        if candidate in existing_paths:
            return candidate
    # Try index files
    for ext in EXTENSIONS:
        candidate = exact_path.rstrip("/") + f"/index{ext}"
        if candidate in existing_paths:
            return candidate
    return None


def validate_and_repair_files(files: list[dict]) -> list[dict]:
    """Scan all generated files for unresolved imports and create placeholders."""
    existing_paths = {f["path"] for f in files}
    missing = set()

    for f in files:
        path = f["path"]
        content = f["content"]
        if not any(path.endswith(ext) for ext in EXTENSIONS):
            continue

        for match in IMPORT_PATTERN.finditer(content):
            import_spec = match.group(1)
            resolved = _resolve_import_path(path, import_spec)
            if resolved is None:
                continue
            found = _find_file(resolved, existing_paths)
            if found is None:
                missing.add(resolved)

    new_files = []
    for m in sorted(missing):
        if m in existing_paths:
            continue
        is_component = m.endswith("x") or m.split("/")[-1][0].isupper()
        placeholder = PLACEHOLDER_COMPONENT if is_component else PLACEHOLDER_MODULE
        # Pick best extension
        if not any(m.endswith(e) for e in EXTENSIONS):
            m += ".jsx" if is_component else ".js"
        new_files.append({"path": m, "content": placeholder})
        print(f"[repair] Created missing file: {m}")

    return files + new_files


# ───────── Image Injection ─────────

UNSPLASH_IDS = [
    "1506744038136-46273834b3fb", "1517694712202-14dd9538aa97",
    "1551288049-bebda4e38f71", "1497366216548-37526070297c",
    "1556761175-b413da4baf72", "1504384308090-c894fdcc538d",
    "1522071820081-009f3b6b01b1", "1519389950473-47ba0277781c",
    "1454165804606-c3d57bc86b40", "1507003212552-3f11eab7bf6d",
    "1504639725590-34d0984388bd", "1498050108023-c5249f4df085",
    "1552664732117-c8a0b9b7c5e0", "1517245386807-bb43f82c33c4",
    "1553877522-43269d4ea984", "1507003212552-3f11eab7bf6d",
    "1517245386807-bb43f82c33c4", "1553877522-43269d4ea984",
    "1522202176988-66273c2e55e9", "1486312338219-ce68d2c6f44d",
]
import random


def inject_images(files: list[dict]) -> list[dict]:
    """Replace placeholder image sources with real Unsplash URLs."""
    placeholder_patterns = [
        r'src=["\'](?:placeholder|https?://placehold\.(?:it|co)|#|data:image/[^;]+;base64,)["\']',
        r'src=["\'](?:/images/[^"\']+\.(?:jpg|png|svg))["\']',
    ]
    for f in files:
        if not f["path"].endswith((".html", ".jsx", ".tsx")):
            continue
        content = f["content"]
        replaced = False
        for pattern in placeholder_patterns:
            def replacer(m):
                nonlocal replaced
                replaced = True
                img_id = random.choice(UNSPLASH_IDS)
                return f'src="https://images.unsplash.com/photo-{img_id}?w=800&q=80"'
            content = re.sub(pattern, replacer, content)
        if replaced:
            f["content"] = content
    return files


# ───────── Serve static files ─────────

uploads_dir = UPLOAD_DIR
app.mount("/uploads", StaticFiles(directory=str(uploads_dir)), name="uploads")

frontend_dir = Path(__file__).resolve().parents[1] / "frontend" / "dist"
if frontend_dir.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
