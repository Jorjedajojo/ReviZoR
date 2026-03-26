#!/usr/bin/env bash
set -e

echo ""
echo " ========================================="
echo "  ReviZoR FranK - CV Optimization Engine"
echo " ========================================="
echo ""

cd "$(dirname "$0")"

if ! command -v python3 &>/dev/null; then
    echo "[ERROR] Python 3 is not installed."
    exit 1
fi

if [ ! -f ".env" ]; then
    echo "[WARNING] .env file not found. Creating from template..."
    cp .env.example .env
    echo "[INFO] Please edit .env and add your ANTHROPIC_API_KEY, then restart."
    exit 1
fi

if [ ! -d "venv" ]; then
    echo "[INFO] Creating virtual environment..."
    python3 -m venv venv
fi

source venv/bin/activate
pip install -r requirements.txt -q

echo "[INFO] Starting ReviZoR FranK..."
python -m streamlit run revizor_frank/app.py --server.headless=false --browser.gatherUsageStats=false
