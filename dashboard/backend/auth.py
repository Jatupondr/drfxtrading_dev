"""
auth.py — DRFX Dashboard Server-side Auth (FastAPI)
=====================================================
วางไฟล์นี้ในโฟลเดอร์เดียวกับ main.py

ENV ที่ต้องตั้ง (.env):
    ADMIN_USER=admin
    ADMIN_PASS_HASH=$2b$12$....   (สร้างด้วย bcrypt)

สร้าง hash ด้วย:
    python -c "import bcrypt; print(bcrypt.hashpw(b'YourPassword', bcrypt.gensalt()).decode())"
"""
import os
import secrets
import logging
from datetime import datetime, timezone, timedelta

import bcrypt
from fastapi import APIRouter, Request, Response, HTTPException
from pydantic import BaseModel

logger = logging.getLogger("auth")

# ── CONFIG (อ่านจาก .env) ────────────────────────────────────────────────────
ADMIN_USER             = os.environ.get("ADMIN_USER", "")
ADMIN_PASS_HASH        = os.environ.get("ADMIN_PASS_HASH", "")
SESSION_LIFETIME_HOURS = int(os.environ.get("SESSION_LIFETIME_HOURS", "8"))
COOKIE_NAME            = "drfx_session"
# ตั้ง COOKIE_SECURE=true ใน .env เมื่อใช้ HTTPS (เช่นผ่าน Cloudflare)
COOKIE_SECURE          = os.environ.get("COOKIE_SECURE", "false").lower() == "true"

# ── Simple in-memory session store ───────────────────────────────────────────
_sessions: dict[str, datetime] = {}


def _new_token() -> str:
    return secrets.token_hex(32)


def _is_valid(token: str) -> bool:
    if not token:
        return False
    exp = _sessions.get(token)
    if not exp:
        return False
    if datetime.now(timezone.utc) > exp:
        _sessions.pop(token, None)
        return False
    return True


def _create_session() -> str:
    token = _new_token()
    _sessions[token] = datetime.now(timezone.utc) + timedelta(hours=SESSION_LIFETIME_HOURS)
    # Cleanup expired sessions occasionally
    if len(_sessions) > 100:
        now = datetime.now(timezone.utc)
        expired = [t for t, e in _sessions.items() if e < now]
        for t in expired:
            _sessions.pop(t, None)
    return token


def _delete_session(token: str):
    _sessions.pop(token, None)


# ── Router ────────────────────────────────────────────────────────────────────
auth_router = APIRouter()


class LoginBody(BaseModel):
    username: str
    password: str


@auth_router.post("/api/login")
async def login(body: LoginBody, request: Request, response: Response):
    # Check ENV is configured
    if not ADMIN_USER or not ADMIN_PASS_HASH:
        logger.error("Admin auth not configured (ADMIN_USER / ADMIN_PASS_HASH missing in .env)")
        raise HTTPException(status_code=500, detail="Admin auth not configured")

    user_ok = secrets.compare_digest(
        body.username.strip().encode("utf-8"),
        ADMIN_USER.encode("utf-8"),
    )

    try:
        pass_ok = bcrypt.checkpw(body.password.encode("utf-8"), ADMIN_PASS_HASH.encode("utf-8"))
    except Exception as e:
        logger.warning(f"bcrypt check error: {e}")
        pass_ok = False

    client_ip = request.client.host if request.client else "?"

    if user_ok and pass_ok:
        token = _create_session()
        response.set_cookie(
            key=COOKIE_NAME,
            value=token,
            httponly=True,
            samesite="lax",
            max_age=SESSION_LIFETIME_HOURS * 3600,
            secure=COOKIE_SECURE,
        )
        logger.info(f"Admin login success from {client_ip}")
        return {"ok": True}

    logger.warning(f"Failed admin login attempt from {client_ip} (user={body.username!r})")
    raise HTTPException(status_code=401, detail="Invalid credentials")


@auth_router.post("/api/logout")
async def logout(request: Request, response: Response):
    token = request.cookies.get(COOKIE_NAME, "")
    if token:
        _delete_session(token)
    response.delete_cookie(COOKIE_NAME)
    return {"ok": True}


@auth_router.get("/api/me")
async def me(request: Request):
    token = request.cookies.get(COOKIE_NAME, "")
    return {"is_admin": _is_valid(token)}


# ── Helper: ใช้ใน endpoint อื่นที่ต้องการสิทธิ์ admin ───────────────────────
def require_admin(request: Request):
    """Raise 401 ถ้าไม่ใช่ admin"""
    token = request.cookies.get(COOKIE_NAME, "")
    if not _is_valid(token):
        raise HTTPException(status_code=401, detail="Unauthorized")
