# Zenith - Local Development Script
# Run this from the zenith/ directory

Write-Host "=== Zenith - Local Development ===" -ForegroundColor Cyan
Write-Host ""

# Check if the model file exists
$modelPath = "C:\Users\win\Desktop\super project\zenith\models\qwen2.5-7b-q4_k_m.gguf"
if (-not (Test-Path $modelPath)) {
    Write-Host "Warning: Model not found at $modelPath" -ForegroundColor Yellow
    Write-Host "Set the MODEL_PATH env var to your GGUF file location." -ForegroundColor Yellow
}

# Start backend
Write-Host "Starting Backend (FastAPI)..." -ForegroundColor Green
$env:MODEL_PATH = $modelPath
$env:N_CTX = "16384"
$env:N_GPU_LAYERS = "-1"

$backendJob = Start-Job -ScriptBlock {
    param($mp)
    $env:MODEL_PATH = $mp
    Set-Location "$using:pwd\backend"
    python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
} -ArgumentList $modelPath

# Start frontend
Write-Host "Starting Frontend (Vite)..." -ForegroundColor Green
Set-Location frontend
npm run dev
