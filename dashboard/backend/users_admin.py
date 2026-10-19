"""
users_admin.py — User/License Management via Apps Script Proxy
================================================================
Proxy layer ที่ FastAPI ใช้เรียก Apps Script admin endpoints:
  Browser → FastAPI (require_admin cookie) → Apps Script (adminKey) → Google Sheet

Auth: reuse require_admin from auth.py (cookie session)
     — never exposes LICENSE_ADMIN_KEY to browser

ENV required (.env):
  APPS_SCRIPT_URL     = https://script.google.com/macros/s/AKfycb.../exec
  LICENSE_ADMIN_KEY   = <same as ADMIN_KEY in DRFX_License_Server.gs>

Endpoints (all require_admin):
  GET    /api/users              → paginated list + search + filter
  POST   /api/users/update       → update whitelisted fields
  POST   /api/users/action       → quick actions (grant/lifetime/trial/block/reset)
  DELETE /api/users/{acct}/{ea}  → delete a (account, ea) row
"""

import os
import json
import logging
import httpx
from fastapi import APIRouter, Request, HTTPException, Query
from pydantic import BaseModel

from auth import require_admin

logger = logging.getLogger("users_admin")

# ── Config ─────────────────────────────────────────────────
APPS_SCRIPT_URL   = os.getenv("APPS_SCRIPT_URL", "").strip()
LICENSE_ADMIN_KEY = os.getenv("LICENSE_ADMIN_KEY", "").strip()
REQUEST_TIMEOUT   = int(os.getenv("APPS_SCRIPT_TIMEOUT", "30"))


# ── HTTP client helper ─────────────────────────────────────
async def _call_apps_script(action: str, **params) -> dict:
    """
    Call Apps Script Web App with admin key. Return parsed JSON.
    Raises HTTPException on network/HTTP/API errors.
    """
    if not APPS_SCRIPT_URL:
        raise HTTPException(500, "APPS_SCRIPT_URL not configured in .env")
    if not LICENSE_ADMIN_KEY:
        raise HTTPException(500, "LICENSE_ADMIN_KEY not configured in .env")

    query = {"action": action, "adminKey": LICENSE_ADMIN_KEY, **params}
    # Remove None / empty-string values (Apps Script treats missing = default)
    query = {k: str(v) for k, v in query.items() if v is not None and v != ""}

    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT, follow_redirects=True) as client:
            resp = await client.get(APPS_SCRIPT_URL, params=query)
    except httpx.TimeoutException:
        raise HTTPException(504, "Apps Script timed out")
    except httpx.RequestError as e:
        logger.error(f"Apps Script request failed: {e}")
        raise HTTPException(502, f"Apps Script request failed: {e}")

    if resp.status_code != 200:
        raise HTTPException(502, f"Apps Script HTTP {resp.status_code}: {resp.text[:200]}")

    try:
        data = resp.json()
    except json.JSONDecodeError:
        raise HTTPException(502, f"Apps Script returned non-JSON: {resp.text[:200]}")

    # Apps Script returns { ok: false, error: "..." } on failure
    if isinstance(data, dict) and data.get("ok") is False:
        err = data.get("error", "unknown error")
        # 401 for unauthorized (bad admin key), else 400
        status_code = 401 if err == "unauthorized" else 400
        raise HTTPException(status_code, f"Apps Script: {err}")

    return data


# ── Router ─────────────────────────────────────────────────
users_router = APIRouter(prefix="/api/users", tags=["users"])


@users_router.get("")
async def list_users(
    request: Request,
    page: int = Query(1, ge=1),
    pageSize: int = Query(50, ge=1, le=200),
    search: str = "",
    status: str = "",
    ea: str = "",
    broker: str = "",
    includeMeta: bool = False,
):
    """List licenses (paginated). Optional filters + search."""
    require_admin(request)

    params = dict(page=page, pageSize=pageSize)
    if search: params["search"] = search
    if status: params["status"] = status
    if ea:     params["ea"]     = ea
    if broker: params["broker"] = broker
    if includeMeta: params["includeMeta"] = "1"

    return await _call_apps_script("list", **params)


class UpdateBody(BaseModel):
    account: str
    ea: str
    updates: dict   # e.g. {"Status": "BLOCKED", "Notes": "test"}


@users_router.post("/update")
async def update_user(body: UpdateBody, request: Request):
    """Update whitelisted fields of a (account, EA) row."""
    require_admin(request)

    if not body.account.strip() or not body.ea.strip():
        raise HTTPException(400, "account and ea are required")
    if not body.updates:
        raise HTTPException(400, "updates cannot be empty")

    return await _call_apps_script(
        "update",
        account=body.account.strip(),
        ea=body.ea.strip(),
        updates=json.dumps(body.updates, ensure_ascii=False),
    )


class ActionBody(BaseModel):
    type: str      # grant | lifetime | trial | block | reset | grantAll | revokeAll
    account: str
    ea: str = ""    # optional for grantAll/revokeAll (account-level)
    days: int = 30
    reason: str = ""


@users_router.post("/action")
async def do_action(body: ActionBody, request: Request):
    """Execute a quick action (grant / lifetime / trial / block / reset / grantAll / revokeAll)."""
    require_admin(request)

    allowed = {"grant", "lifetime", "trial", "block", "reset", "grantall", "revokeall"}
    type_lower = body.type.lower()
    if type_lower not in allowed:
        raise HTTPException(400, f"type must be one of: {sorted(allowed)}")
    if not body.account.strip():
        raise HTTPException(400, "account is required")
    # ea required only for per-EA actions
    if type_lower not in ("grantall", "revokeall") and not body.ea.strip():
        raise HTTPException(400, "ea is required for this action")

    params = dict(
        type=type_lower,
        account=body.account.strip(),
    )
    if body.ea.strip():
        params["ea"] = body.ea.strip()
    if type_lower == "grant":
        params["days"] = max(1, body.days)
    if type_lower == "block" and body.reason:
        params["reason"] = body.reason

    return await _call_apps_script("action", **params)


@users_router.delete("/{account}/{ea:path}")
async def delete_user(account: str, ea: str, request: Request):
    """Delete a (account, EA) row from the Sheet."""
    require_admin(request)

    if not account.strip() or not ea.strip():
        raise HTTPException(400, "account and ea are required")

    return await _call_apps_script("delete", account=account.strip(), ea=ea.strip())
