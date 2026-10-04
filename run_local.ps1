# Zenith - Local Development Script
# Run this from the zenith/ directory

Write-Host "=== Zenith - Local Development ===" -ForegroundColor Cyan
Write-Host ""

# IMPORTANT: this script intentionally does NOT set $env:MODEL_PATH / N_CTX /
# N_GPU_LAYERS / MODEL_NAME / LORA_PATH anymore.
#
# It used to hardcode $env:MODEL_PATH to the base model and force N_CTX down
# to 8192 - since backend/model_service.py loads .env via python-dotenv with
# override=False, any environment variable already set when the Python
# process starts (like the ones this script used to set) permanently wins
# over the same key in .env. That meant .env's MODEL_PATH/MODEL_NAME/
# LORA_PATH could never take effect no matter what you put in it - which is
# exactly why the fine-tuned model never got picked up. Your zenith/.env file
# is now the single source of truth for all of that; edit it, don't edit this
# script.

Write-Host "Starting Backend (FastAPI) - configuration is read from zenith/.env" -ForegroundColor Green

$backendJob = Start-Job -ScriptBlock {
    Set-Location "$using:pwd\backend"
    python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
}

Write-Host "Backend job started (id $($backendJob.Id)). Tail its output with:" -ForegroundColor DarkGray
Write-Host "  Receive-Job -Id $($backendJob.Id) -Keep" -ForegroundColor DarkGray
Write-Host ""

# Start frontend
Write-Host "Starting Frontend (Vite)..." -ForegroundColor Green
Set-Location frontend
npm run dev
