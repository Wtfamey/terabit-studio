# Terabit Studio

> **AI-powered Business OS Generator** — Describe any business system in plain English, and get a complete, production-ready React + Vite + Tailwind CSS application.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](backend/requirements.txt)
[![React](https://img.shields.io/badge/react-18-61dafb.svg)](frontend/package.json)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688.svg)](backend/requirements.txt)
[![Qwen 2.5](https://img.shields.io/badge/Qwen-2.5%207B-0a7cff.svg)](https://huggingface.co/Qwen/Qwen2.5-7B-Instruct-GGUF)

---

## Features

- **Natural Language to App** — Describe a CRM, POS, e-commerce platform, or any business system in plain English; Zenith generates the complete frontend code.
- **Code Editor** — Edit generated files inline with Monaco Editor (the engine behind VS Code).
- **Live Preview** — See your generated app rendered instantly in an isolated iframe.
- **File Explorer** — Navigate and manage all generated project files.
- **Chat Interface** — Refine your app iteratively through conversation.
- **RAG-Enhanced Search** — Retrieve relevant code patterns and documentation.
- **Asset Manager** — Upload and manage images, PDFs, and other assets.
- **Authentication** — Built-in user registration and JWT-based auth.
- **Local & Private** — Runs entirely on your machine with a local LLM. No data leaves your computer.
- **Docker Support** — One-command deployment with Docker Compose.
- **Fine-tuning Ready** — Generate training data and fine-tune Qwen 2.5 7B with QLoRA.

## Architecture

```
User Prompt → Frontend (React + Vite) → Backend (FastAPI) → LLM Server (llama.cpp / Ollama)
                                                                  ↓
                                                            Generated Code
                                                                  ↓
                                                        File Explorer + Monaco Editor + Live Preview
```

## Quick Start

### Prerequisites

- Python 3.11+
- Node.js 18+
- An LLM inference server (choose one):
  - [Ollama](https://ollama.com) (recommended) with `qwen2.5:7b` pulled
  - [llama.cpp](https://github.com/ggerganov/llama.cpp) with a Qwen 2.5 7B GGUF model

### 1. Clone & Install

```bash
git clone https://github.com/Wtfamey/terabit-studio.git
cd terabit-studio

# Backend
cd backend
pip install -r requirements.txt
cd ..

# Frontend
cd frontend
npm install
cd ..
```

### 2. Configure

```bash
cp .env.example .env
# Edit .env with your model path and settings
```

### 3. Start the LLM Server

**Option A — Ollama (recommended):**
```bash
ollama pull qwen2.5:7b
ollama serve
```

**Option B — llama.cpp:**
```bash
# Download llama-server from https://github.com/ggerganov/llama.cpp/releases
llama-server -m /path/to/qwen2.5-7b-instruct-q4_k_m.gguf --host 127.0.0.1 --port 8080 -ngl -1 -c 16384
```

### 4. Start the Backend

```bash
cd backend
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### 5. Start the Frontend

```bash
cd frontend
npm run dev
```

Open **[http://localhost:5173](http://localhost:5173)** in your browser.

> **Windows users:** You can also run `.\run_local.ps1` from the project root to start both backend and frontend.

### Docker Deployment

```bash
cd frontend && npm install && npm run build && cd ..
docker-compose up --build
```

The app will be available at [http://localhost](http://localhost).

## API Reference

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/health` | GET | Health check |
| `/api/auth/register` | POST | Register a new user |
| `/api/auth/login` | POST | Login and receive JWT |
| `/api/auth/me` | GET | Get current user info |
| `/api/sessions` | GET | List chat sessions |
| `/api/sessions` | POST | Create a new session |
| `/api/sessions/{id}` | DELETE | Delete a session |
| `/api/sessions/{id}/messages` | GET | Get session messages |
| `/api/chat` | POST | Send a chat message |
| `/api/chat/stream` | POST | Streaming chat (SSE) |
| `/api/generate` | POST | Generate a complete business system |
| `/api/generate/stream` | POST | Streaming generation (SSE) |
| `/api/search` | POST | RAG-enhanced search |
| `/api/correct` | POST | Correct generated code |
| `/api/preview` | POST | Build preview HTML |
| `/api/download` | POST | Download project as ZIP |
| `/api/upload` | POST | Upload an asset file |
| `/api/assets` | GET | List uploaded assets |
| `/api/assets/{id}` | DELETE | Delete an asset |

## Project Structure

```
zenith/
├── backend/
│   ├── main.py                  # FastAPI server with all API routes
│   ├── model_service.py         # OpenAI-compatible LLM client
│   ├── rag_engine.py            # DuckDuckGo RAG + semantic filtering
│   ├── auth.py                  # JWT authentication (bcrypt)
│   ├── database.py              # SQLAlchemy models & database
│   ├── preview_builder.py       # HTML preview generator
│   ├── generate_training_data.py # Gemini-powered training data generator
│   ├── train.py                 # QLoRA fine-tuning (transformers + PEFT)
│   ├── train_unsloth.py         # QLoRA fine-tuning (Unsloth)
│   ├── requirements.txt         # Runtime dependencies
│   └── requirements-training.txt # Training dependencies
├── frontend/
│   ├── src/
│   │   ├── pages/               # Home, Builder, Login, Register
│   │   ├── components/          # FileExplorer, CodeEditor, PreviewFrame, AssetManager
│   │   ├── contexts/            # AuthContext (JWT management)
│   │   ├── types/               # TypeScript interfaces & business templates
│   │   └── hooks/               # WebContainer stub
│   ├── package.json
│   └── vite.config.ts
├── docker-compose.yml
├── nginx.conf
└── run_local.ps1
```

## Tech Stack

### Frontend
- **React 18** with TypeScript
- **Vite 6** for fast development & builds
- **Tailwind CSS 3** for styling
- **Monaco Editor** for code editing
- **lucide-react** for icons
- **react-router-dom** for routing

### Backend
- **Python 3.11+** with FastAPI
- **SQLAlchemy** + SQLite for persistence
- **JWT** authentication with bcrypt
- **OpenAI-compatible client** for LLM integration
- **Sentence Transformers** for semantic search
- **DuckDuckGo Search** for RAG augmentation

### AI / ML
- **Qwen 2.5 7B** (GGUF, Q4_K_M quantization)
- **llama.cpp** or **Ollama** for inference
- **Unsloth** or **Hugging Face PEFT** for QLoRA fine-tuning
- **Gemini API** for training data generation

## Fine-tuning

Terabit Studio supports fine-tuning Qwen 2.5 7B to improve code generation quality.

```bash
cd backend

# Activate training environment
source ../train_env/Scripts/activate  # Windows
# or: source ../train_env/bin/activate  # Linux/Mac

# Generate training data (requires GEMINI_API_KEY in .env)
python generate_training_data.py

# Train with Unsloth (recommended for 4-bit QLoRA)
python train_unsloth.py

# Or train with vanilla transformers + PEFT
python train.py
```

> **Note:** Fine-tuning a 7B model requires significant VRAM. An RTX 3050 (6GB) can train 20+ examples with QLoRA 4-bit, layer offloading, and gradient accumulation.

## Roadmap

- [ ] User-created business template library
- [ ] Collaborative editing sessions
- [ ] Export to GitHub repository
- [ ] WebContainer-based live preview
- [ ] Multi-model support (GPT-4, Claude, Gemini)
- [ ] Plugin system for custom generators

## License

[MIT](LICENSE)

## Acknowledgments

- [Qwen team](https://github.com/QwenLM/Qwen) for the Qwen 2.5 model
- [ggerganov](https://github.com/ggerganov/llama.cpp) for llama.cpp
- [Unsloth](https://github.com/unslothai/unsloth) for efficient fine-tuning
