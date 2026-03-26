#!/usr/bin/env bash
# ReviZoR FranK — Deployment helper script
# Run this on your server to set up the full stack.
set -e

echo ""
echo " ============================================="
echo "  ReviZoR FranK — Deployment Setup"
echo " ============================================="
echo ""

# ── Check prerequisites ────────────────────────────────────────────────────────
command -v docker >/dev/null 2>&1 || { echo "[ERROR] Docker is not installed."; exit 1; }
command -v docker compose >/dev/null 2>&1 || { echo "[ERROR] Docker Compose v2 is not installed."; exit 1; }
command -v openssl >/dev/null 2>&1 || { echo "[ERROR] openssl is not installed."; exit 1; }

# ── .env setup ─────────────────────────────────────────────────────────────────
if [ ! -f ".env" ]; then
    echo "[INFO] Creating .env from template..."
    cp .env.example .env

    # Auto-generate SECRET_KEY
    SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")
    sed -i "s|generate_a_strong_random_secret_key_here|$SECRET|" .env
    echo "[INFO] Generated SECRET_KEY automatically."
    echo ""
    echo "[ACTION REQUIRED] Edit .env and set:"
    echo "   ANTHROPIC_API_KEY — your Claude API key"
    echo "   ADMIN_EMAIL       — your admin email"
    echo "   ADMIN_PASSWORD    — your admin password (or leave blank for auto-generate)"
    echo "   ALLOWED_ORIGINS   — your domain (e.g. https://revizor.yourdomain.com)"
    echo ""
    echo "Then run this script again."
    exit 0
fi

# ── SSL certificates ──────────────────────────────────────────────────────────
mkdir -p nginx/certs
if [ ! -f "nginx/certs/revizor.crt" ]; then
    echo "[INFO] No SSL certificate found. Generating self-signed cert for testing..."
    echo "[WARNING] For production, replace with a real certificate (e.g. Let's Encrypt)."
    openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
        -keyout nginx/certs/revizor.key \
        -out nginx/certs/revizor.crt \
        -subj "/CN=revizor-frank/O=ReviZoR/C=US" \
        -quiet
    echo "[INFO] Self-signed certificate created at nginx/certs/"
fi

# ── Build & start ──────────────────────────────────────────────────────────────
echo "[INFO] Building Docker images..."
docker compose build --quiet

echo "[INFO] Starting services..."
docker compose up -d

echo ""
echo " ============================================="
echo "  ReviZoR FranK is now running!"
echo " ============================================="
echo ""
echo "  App URL:    https://localhost"
echo "  API docs:   https://localhost/api/docs"
echo "  Admin:      https://localhost/api/docs#/admin"
echo ""
echo "  Check logs:   docker compose logs -f"
echo "  Stop:         docker compose down"
echo "  Update:       git pull && docker compose build && docker compose up -d"
echo ""
echo "  First-time admin password is printed in the API container logs:"
echo "    docker compose logs api | grep Password"
echo ""
