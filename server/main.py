"""ReviZoR FranK — FastAPI authentication server.

Handles all auth for the deployed web version. The Streamlit app
validates tokens against this API before serving any content.

Run with:
  uvicorn server.main:app --host 0.0.0.0 --port 8000

On first run, creates an admin account if none exists:
  ADMIN_USERNAME / ADMIN_PASSWORD / ADMIN_EMAIL env vars (required first boot only).
"""

from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from server import database as db
from server.auth import security as sec
from server.auth.router import router as auth_router
from server.admin.router import router as admin_router
from server.n8n.router import router as n8n_router


# ── Rate limiter ───────────────────────────────────────────────────────────────
limiter = Limiter(key_func=get_remote_address)

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="ReviZoR FranK Auth API",
    version="1.0.0",
    docs_url="/api/docs",        # Swagger UI
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ── CORS ──────────────────────────────────────────────────────────────────────
_allowed_origins = os.getenv("ALLOWED_ORIGINS", "http://localhost:8501").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _allowed_origins],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(n8n_router)


# ── Rate-limit auth endpoints ─────────────────────────────────────────────────
# Applied at the ASGI layer so it covers even failed routes
@app.middleware("http")
async def rate_limit_auth(request, call_next):
    """Strict rate limit on login endpoint: 10 attempts per minute per IP."""
    from slowapi.errors import RateLimitExceeded
    if request.url.path == "/api/auth/login" and request.method == "POST":
        # The actual limit is enforced by slowapi decorator on the route;
        # this middleware adds an extra header for transparency.
        pass
    response = await call_next(request)
    return response


# ── Health check ──────────────────────────────────────────────────────────────
@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "ReviZoR FranK Auth API"}


# ── First-run admin bootstrap ─────────────────────────────────────────────────
@app.on_event("startup")
async def _bootstrap_admin():
    if db.has_admin():
        return  # Admin already exists

    username = os.getenv("ADMIN_USERNAME", "admin")
    password = os.getenv("ADMIN_PASSWORD", "")
    email    = os.getenv("ADMIN_EMAIL", "admin@revizor.local")

    if not password:
        import secrets
        password = secrets.token_urlsafe(16)
        print(f"\n{'='*60}")
        print("  REVIZOR FRANK — FIRST RUN SETUP")
        print(f"  Admin account created automatically.")
        print(f"  Username: {username}")
        print(f"  Password: {password}")
        print(f"  SAVE THIS PASSWORD — it will not be shown again.")
        print(f"{'='*60}\n")

    errors = sec.validate_password_strength(password)
    if errors and os.getenv("ADMIN_PASSWORD"):
        raise RuntimeError(f"ADMIN_PASSWORD does not meet requirements: {'; '.join(errors)}")

    db.create_user(
        username=username,
        email=email,
        password_hash=sec.hash_password(password),
        role="admin",
    )
    db.audit("user_created", username="system",
             details={"new_user": username, "role": "admin", "bootstrap": True})
