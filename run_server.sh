#!/bin/bash
# Question Paper Reviewer — Mac / Linux startup
set -e
cd "$(dirname "$0")"

if [ ! -f ".venv/bin/python" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
fi

echo "Installing / verifying dependencies..."
.venv/bin/pip install -r requirements.txt --quiet

echo ""
echo "Starting server — open: http://127.0.0.1:8000"
echo ""
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
