# Question Paper Reviewer
# Starts the server on http://127.0.0.1:8000
# Keep this window open while you use the browser. Press Ctrl+C to stop.

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".\.venv\Scripts\python.exe")) {
    Write-Host "Creating virtual environment..."
    python -m venv .venv
}

Write-Host "Installing / verifying dependencies..."
.\.venv\Scripts\pip install -r requirements.txt --quiet

Write-Host ""
Write-Host "Starting server — open: http://127.0.0.1:8000"
Write-Host ""

.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
