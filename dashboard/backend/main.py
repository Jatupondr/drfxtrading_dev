"""
main.py — DRFX Trading Dashboard Backend v2.1
FastAPI server with REST endpoints, WebSocket real-time feed,
and SQLite database for historical data.

NEW: ข้อมูลถูกเก็บลง database ทุก 5 นาที
     ดูย้อนหลังได้แม้ MT5 ปิดแล้ว

NEW (Phase 1 + 2): EA Catalog Backend
     - GET  /api/catalog/config   (public — สำหรับ catalog site)
     - POST /api/catalog/eas      (admin — บันทึก EAs)
     - POST /api/catalog/pricing  (admin — บันทึก pricing tiers)
     - /catalog-admin             (admin panel UI)
"""

import os
import json
import asyncio
import logging
import httpx
from pathlib import Path
from datetime import datetime, timezone
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware      # NEW: for catalog CORS
from dotenv import load_dotenv

from mt5_service import MT5Service
from analytics import (
    compute_currency_strength,
    build_heatmap_matrix,
    fetch_economic_news,
    calculate_drawdown,
    HEATMAP_PAIRS,
)
from telegram_notify import (
    telegram_scheduler, send_telegram,
    build_daily_report, build_weekly_report, build_monthly_report,
)
from database import (
    init_database,
    save_account_snapshot,
    save_portfolio_snapshot,
    save_market_snapshot,
    update_daily_summary,
    get_account_history,
    get_portfolio_history,
    get_daily_summaries,
    get_market_history,
    get_latest_snapshot,
    get_database_stats,
    cleanup_old_data,
    set_account_label,
    get_account_label,
    get_all_account_labels,
    delete_account_label,
    save_account_order,
    get_account_order,
)

# ── Auth ──────────────────────────────────────────────────────────────
from auth import auth_router, require_admin

# ── EA Catalog (NEW) ─────────────────────────────────────────────────
from ea_catalog import catalog_router, init_catalog

# ── Users Admin (NEW — Phase 3) ──────────────────────────────────────
from users_admin import users_router

# ── Config ────────────────────────────────────────────────────────────
load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent / ".env")
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(name)-12s | %(levelname)s | %(message)s")
logger = logging.getLogger("dashboard")

HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))
WS_INTERVAL = int(os.getenv("WS_UPDATE_INTERVAL", "5"))
NEWS_INTERVAL = int(os.getenv("NEWS_UPDATE_INTERVAL", "300"))
SNAPSHOT_INTERVAL = int(os.getenv("SNAPSHOT_INTERVAL", "300"))  # บันทึกทุก 5 นาที
DATA_RETENTION_DAYS = int(os.getenv("DATA_RETENTION_DAYS", "90"))  # เก็บข้อมูล 90 วัน
FMP_KEY = os.getenv("FMP_API_KEY", "")

# ── Globals ───────────────────────────────────────────────────────────
mt5 = MT5Service()
connected_ws: set[WebSocket] = set()
demo_mode = False

_cache = {
    "portfolio": {},
    "market": [],
    "heatmap": {},
    "news": [],
    "equity_curves": {},
    "timestamp": "",
}

# ── USDTHB Real-time Rate ────────────────────────────────────────────
_usdthb = {
    "rate": 34.50,
    "source": "default",
    "updated": "",
}

async def _fetch_usdthb():
    """ดึงอัตราแลกเปลี่ยน USDTHB จาก API ฟรี"""
    apis = [
        # API 1: open.er-api.com (ฟรี ไม่ต้อง key)
        {
            "url": "https://open.er-api.com/v6/latest/USD",
            "parse": lambda d: d.get("rates", {}).get("THB"),
            "name": "open.er-api.com",
        },
        # API 2: cdn.jsdelivr.net (ฟรี จาก Fawaz Ahmed)
        {
            "url": "https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@latest/v1/currencies/usd.json",
            "parse": lambda d: d.get("usd", {}).get("thb"),
            "name": "fawazahmed0",
        },
    ]

    async with httpx.AsyncClient(timeout=10) as client:
        for api in apis:
            try:
                resp = await client.get(api["url"])
                if resp.status_code == 200:
                    data = resp.json()
                    rate = api["parse"](data)
                    if rate and rate > 0:
                        _usdthb["rate"] = round(float(rate), 4)
                        _usdthb["source"] = api["name"]
                        _usdthb["updated"] = datetime.now(timezone.utc).isoformat()
                        logger.info(f"USDTHB rate: {_usdthb['rate']} (from {api['name']})")
                        return
            except Exception as e:
                logger.debug(f"USDTHB fetch failed from {api['name']}: {e}")
                continue

    logger.warning("USDTHB: all APIs failed, using last known rate")


async def _usdthb_loop():
    """อัพเดท USDTHB ทุก 5 นาที"""
    await _fetch_usdthb()  # ดึงครั้งแรกทันที
    while True:
        await asyncio.sleep(300)  # ทุก 5 นาที
        await _fetch_usdthb()


# ── Demo data generator ──────────────────────────────────────────────
def _generate_demo_data() -> dict:
    """Generate realistic demo data when MT5 is not available."""
    import random
    import math

    now = datetime.now(timezone.utc)
    t = now.timestamp()

    accounts = []
    labels = ["DRFX-Live-01", "DRFX-Live-02", "DRFX-Prop-01"]
    bases = [50000, 25000, 100000]
    for i, (label, base) in enumerate(zip(labels, bases)):
        noise = math.sin(t / 300 + i) * base * 0.02
        balance = round(base + noise * 0.5 + random.uniform(-50, 50), 2)
        equity = round(balance + noise + random.uniform(-200, 200), 2)
        profit = round(equity - balance, 2)
        today = round(profit * 0.3 + random.uniform(-100, 100), 2)
        weekly = round(profit * 0.7 + random.uniform(-200, 200), 2)
        monthly = round(profit * 1.5 + random.uniform(-500, 500), 2)
        accounts.append({
            "login": 10000001 + i,
            "label": label,
            "server": f"DemoServer-{i+1}",
            "balance": balance,
            "equity": equity,
            "profit": profit,
            "margin": round(balance * 0.05, 2),
            "free_margin": round(equity - balance * 0.05, 2),
            "margin_level": round(equity / (balance * 0.05) * 100, 1) if balance > 0 else 0,
            "leverage": 100,
            "currency": "USD",
            "connected": True,
            "today": today,
            "weekly": weekly,
            "monthly": monthly,
        })

    totals = {
        "total_balance": round(sum(a["balance"] for a in accounts), 2),
        "total_equity": round(sum(a["equity"] for a in accounts), 2),
        "total_profit": round(sum(a["profit"] for a in accounts), 2),
        "today_profit": round(sum(a["today"] for a in accounts), 2),
        "weekly_profit": round(sum(a["weekly"] for a in accounts), 2),
        "monthly_profit": round(sum(a["monthly"] for a in accounts), 2),
        "accounts": accounts,
        "timestamp": now.isoformat(),
    }

    pairs = {
        "EURUSD": (1.0850, 0.00015), "GBPUSD": (1.2680, 0.00020),
        "USDJPY": (154.50, 0.020), "BTCUSD": (68500, 50),
        "XAUUSD": (2350.0, 0.50),
    }
    market = []
    for sym, (mid, vol) in pairs.items():
        bid = round(mid + math.sin(t / 60 + hash(sym) % 10) * vol * 10 + random.uniform(-vol, vol), 5)
        ask = round(bid + vol * 2, 5)
        change = round(math.sin(t / 600 + hash(sym) % 7) * 0.5 + random.uniform(-0.1, 0.1), 3)
        market.append({"symbol": sym, "bid": bid, "ask": ask, "spread": round(ask - bid, 5), "change": change})

    strength = compute_currency_strength(market)
    for pair in HEATMAP_PAIRS:
        if not any(m["symbol"] == pair for m in market):
            base_c, quote_c = pair[:3], pair[3:6]
            synth_change = round(
                (strength.get(base_c, 0) - strength.get(quote_c, 0)) / 50 + random.uniform(-0.1, 0.1), 3
            )
            market.append({"symbol": pair, "change": synth_change})
    strength = compute_currency_strength(market)
    heatmap = {"strength": strength, "matrix": build_heatmap_matrix(strength)}

    curves = {}
    for acct in accounts:
        points = []
        bal = acct["balance"] - 2000
        for d in range(30):
            bal += random.uniform(-100, 150)
            eq = bal + random.uniform(-200, 200)
            dt = now.replace(hour=0, minute=0, second=0) - __import__("datetime").timedelta(days=30 - d)
            points.append({"time": dt.isoformat(), "balance": round(bal, 2), "equity": round(eq, 2)})
        points.append({"time": now.isoformat(), "balance": acct["balance"], "equity": acct["equity"]})
        curves[str(acct["login"])] = points

    return {
        "portfolio": totals,
        "market": [m for m in market if len(m.get("symbol", "")) == 6 and m.get("bid")],
        "heatmap": heatmap,
        "equity_curves": curves,
    }


# ── Startup / Shutdown ───────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    global demo_mode

    # Initialize database
    init_database()
    logger.info("Database initialized")

    # NEW: Initialize EA catalog data dir
    init_catalog()

    # Load accounts from env
    raw = os.getenv("MT5_ACCOUNTS", "[]")
    try:
        accts = json.loads(raw)
    except json.JSONDecodeError:
        accts = []

    if not accts:
        logger.warning("No MT5_ACCOUNTS configured — running in DEMO MODE")
        demo_mode = True
    else:
        ok = mt5.initialize()
        if not ok:
            logger.warning("MT5 terminal not available — running in DEMO MODE")
            demo_mode = True
        else:
            for a in accts:
                mt5.add_account(a["login"], a["password"], a["server"], a.get("label", ""), a.get("path", ""))
            logger.info(f"Loaded {len(mt5.accounts)} MT5 accounts")

    # Pre-fill news cache
    _cache["news"] = await fetch_economic_news(FMP_KEY)

    # Background tasks
    bg_news = asyncio.create_task(_news_loop())
    bg_snapshot = asyncio.create_task(_snapshot_loop())
    bg_cleanup = asyncio.create_task(_cleanup_loop())
    bg_rate = asyncio.create_task(_usdthb_loop())
    bg_telegram = asyncio.create_task(telegram_scheduler(
        get_accounts_fn=lambda: list(_ea_accounts.values()),
        get_rate_fn=lambda: _usdthb.get("rate", 34.50),
    ))

    yield

    bg_news.cancel()
    bg_snapshot.cancel()
    bg_cleanup.cancel()
    bg_rate.cancel()
    bg_telegram.cancel()
    if not demo_mode:
        mt5.shutdown()


app = FastAPI(title="DRFX Trading Dashboard", version="2.1", lifespan=lifespan)

# ── NEW: CORS สำหรับ catalog site ที่อยู่คนละ origin ────────────────
# แก้ origins ผ่าน .env: CATALOG_CORS_ORIGINS=http://ip1:port,https://domain2
CATALOG_CORS_ORIGINS = os.getenv(
    "CATALOG_CORS_ORIGINS",
    "https://drfxtrading.net,http://drfxtrading.net,https://dashboard.drfxtrading.net,http://78.46.68.197:3001,http://localhost:3001"
).split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in CATALOG_CORS_ORIGINS if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include auth router (POST /api/login, POST /api/logout, GET /api/me)
app.include_router(auth_router)

# NEW: Include catalog router (public read + admin write)
app.include_router(catalog_router)

# NEW: Include users admin router (proxy to Apps Script License Sheet)
app.include_router(users_router)

# Serve frontend
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


# ── Background tasks ─────────────────────────────────────────────────
async def _news_loop():
    """Refresh news periodically."""
    while True:
        await asyncio.sleep(NEWS_INTERVAL)
        _cache["news"] = await fetch_economic_news(FMP_KEY)


async def _snapshot_loop():
    """บันทึก snapshot ลง database ทุก SNAPSHOT_INTERVAL วินาที (default: 5 นาที)"""
    # บันทึกครั้งแรกทันที 30 วินาทีหลัง start
    await asyncio.sleep(30)
    while True:
        try:
            data = _refresh_data()
            portfolio = data.get("portfolio", {})
            accounts = portfolio.get("accounts", [])
            market = data.get("market", [])

            if accounts:
                save_account_snapshot(accounts)
                save_portfolio_snapshot(portfolio)
                update_daily_summary(accounts)
                logger.info(f"Snapshot saved: {len(accounts)} accounts, {len(market)} market prices")

            if market:
                save_market_snapshot(market)

        except Exception as e:
            logger.error(f"Snapshot save error: {e}")

        await asyncio.sleep(SNAPSHOT_INTERVAL)


async def _cleanup_loop():
    """ลบข้อมูลเก่าทุกวัน"""
    while True:
        await asyncio.sleep(86400)  # ทุก 24 ชั่วโมง
        try:
            cleanup_old_data(DATA_RETENTION_DAYS)
        except Exception as e:
            logger.error(f"Cleanup error: {e}")


# ── Data refresh ─────────────────────────────────────────────────────
def _refresh_data() -> dict:
    """Get latest snapshot. Priority: EA Push > MT5 API > Demo"""

    # ── Priority 1: EA Push data (ถ้ามี EA ส่งข้อมูลมา ใช้ข้อมูลจริง) ──
    if _ea_accounts:
        accounts = list(_ea_accounts.values())
        _cache["portfolio"] = {
            "total_balance": round(sum(a["balance"] for a in accounts), 2),
            "total_equity": round(sum(a["equity"] for a in accounts), 2),
            "total_profit": round(sum(a["profit"] for a in accounts), 2),
            "today_profit": round(sum(a.get("today", 0) for a in accounts), 2),
            "yesterday_profit": round(sum(a.get("yesterday", 0) for a in accounts), 2),
            "weekly_profit": round(sum(a.get("weekly", 0) for a in accounts), 2),
            "monthly_profit": round(sum(a.get("monthly", 0) for a in accounts), 2),
            "accounts": accounts,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        # Equity curves from database history
        curves = {}
        for acct in accounts:
            login = acct.get("login", 0)
            history = get_account_history(login, days=30)
            if history:
                curves[str(login)] = [
                    {"time": h["timestamp"], "balance": h["balance"], "equity": h["equity"]}
                    for h in history
                ]
            else:
                # ถ้ายังไม่มีประวัติ ใช้ข้อมูลปัจจุบัน
                curves[str(login)] = [{
                    "time": datetime.now(timezone.utc).isoformat(),
                    "balance": acct["balance"],
                    "equity": acct["equity"],
                }]
        _cache["equity_curves"] = curves
        _cache["market"] = _cache.get("market", [])
        _cache["heatmap"] = _cache.get("heatmap", {"strength": {}, "matrix": []})

    # ── Priority 2: MT5 API (ถ้าไม่มี EA แต่มี MT5 accounts) ──
    elif not demo_mode:
        _cache["portfolio"] = mt5.get_portfolio_summary()
        market_syms = ["EURUSD", "GBPUSD", "USDJPY", "BTCUSD", "XAUUSD"]
        _cache["market"] = mt5.get_market_overview(market_syms)

        all_market = mt5.get_market_overview(HEATMAP_PAIRS)
        strength = compute_currency_strength(all_market)
        _cache["heatmap"] = {"strength": strength, "matrix": build_heatmap_matrix(strength)}

        curves = {}
        for acct in mt5.accounts:
            curves[str(acct.login)] = mt5.get_equity_curve(acct)
        _cache["equity_curves"] = curves

    # ── Priority 3: Demo data (ไม่มี EA และไม่มี MT5) ──
    else:
        data = _generate_demo_data()
        _cache["portfolio"] = data["portfolio"]
        _cache["market"] = data["market"]
        _cache["heatmap"] = data["heatmap"]
        _cache["equity_curves"] = data["equity_curves"]

    _cache["timestamp"] = datetime.now(timezone.utc).isoformat()
    return {
        "portfolio": _cache["portfolio"],
        "market": _cache["market"],
        "heatmap": _cache["heatmap"],
        "equity_curves": _cache["equity_curves"],
        "news": _cache["news"],
        "timestamp": _cache["timestamp"],
        "demo_mode": demo_mode and not _ea_accounts,
        "usdthb": _usdthb,
    }


# ══════════════════════════════════════════════════════════════════════
# REST Endpoints — Live Data
# ══════════════════════════════════════════════════════════════════════

@app.get("/")
async def index():
    return FileResponse(str(FRONTEND_DIR / "index.html"))

@app.get("/guide.html")
async def guide_page():
    return FileResponse(str(FRONTEND_DIR / "guide.html"))


@app.get("/guide/{filename}")
async def guide_asset(filename: str):
    return FileResponse(str(FRONTEND_DIR / "guide" / filename))


# NEW: EA Catalog admin panel UI
@app.get("/catalog-admin")
async def catalog_admin_page():
    """Serve EA Catalog admin panel (auth handled client-side via /api/me)"""
    return FileResponse(str(FRONTEND_DIR / "catalog-admin.html"))


@app.get("/api/snapshot")
async def api_snapshot():
    return JSONResponse(_refresh_data())


@app.get("/api/portfolio")
async def api_portfolio():
    _refresh_data()
    return JSONResponse(_cache["portfolio"])


@app.get("/api/market")
async def api_market():
    _refresh_data()
    return JSONResponse(_cache["market"])


@app.get("/api/heatmap")
async def api_heatmap():
    _refresh_data()
    return JSONResponse(_cache["heatmap"])


@app.get("/api/news")
async def api_news():
    return JSONResponse(_cache["news"])


@app.get("/api/equity/{login}")
async def api_equity(login: str):
    _refresh_data()
    curve = _cache["equity_curves"].get(login, [])
    dd = calculate_drawdown(curve)
    return JSONResponse({"curve": curve, "drawdown": dd})


@app.get("/api/rate/usdthb")
async def api_usdthb():
    """ดึงอัตราแลกเปลี่ยน USDTHB real-time"""
    return JSONResponse(_usdthb)


# ══════════════════════════════════════════════════════════════════════
# REST Endpoints — Telegram (ส่งรายงานแบบ manual)
# ══════════════════════════════════════════════════════════════════════

@app.post("/api/telegram/daily")
async def api_telegram_daily():
    """ส่งสรุปรายวันไป Telegram ทันที"""
    accounts = list(_ea_accounts.values())
    if not accounts:
        return JSONResponse({"error": "No accounts"}, status_code=400)
    rate = _usdthb.get("rate", 34.50)
    msg = build_daily_report(accounts, rate)
    ok = await send_telegram(msg)
    return JSONResponse({"status": "sent" if ok else "failed"})


@app.post("/api/telegram/weekly")
async def api_telegram_weekly():
    """ส่งสรุปรายสัปดาห์ไป Telegram ทันที"""
    accounts = list(_ea_accounts.values())
    if not accounts:
        return JSONResponse({"error": "No accounts"}, status_code=400)
    rate = _usdthb.get("rate", 34.50)
    msg = build_weekly_report(accounts, rate)
    ok = await send_telegram(msg)
    return JSONResponse({"status": "sent" if ok else "failed"})


@app.post("/api/telegram/monthly")
async def api_telegram_monthly():
    """ส่งสรุปรายเดือนไป Telegram ทันที"""
    accounts = list(_ea_accounts.values())
    if not accounts:
        return JSONResponse({"error": "No accounts"}, status_code=400)
    rate = _usdthb.get("rate", 34.50)
    msg = build_monthly_report(accounts, rate)
    ok = await send_telegram(msg)
    return JSONResponse({"status": "sent" if ok else "failed"})


# ══════════════════════════════════════════════════════════════════════
# REST Endpoints — EA Push (รับข้อมูลจาก EA โดยตรง ไม่ต้องรัน MT5 API)
# ══════════════════════════════════════════════════════════════════════

EA_API_KEY = os.getenv("EA_API_KEY", "")  # ต้องตั้งใน .env — ว่าง = ปฏิเสธ push ทั้งหมด

# เก็บ EA data ล่าสุดต่อบัญชี (in-memory)
_ea_accounts: dict[int, dict] = {}


@app.post("/api/push/account")
async def ea_push_account(request: Request):
    """
    รับข้อมูลจาก DRFX_DashboardReporter EA
    EA ส่ง POST มาทุก N นาที พร้อมข้อมูลบัญชี
    """
    try:
        request_data = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    if not request_data:
        return JSONResponse({"error": "No data received"}, status_code=400)

    # Verify API key
    api_key = request_data.get("api_key", "")
    if not EA_API_KEY or api_key != EA_API_KEY:
        logger.warning(f"EA push: invalid API key from login {request_data.get('login', '?')}")
        return JSONResponse({"error": "Invalid API key"}, status_code=401)

    login = request_data.get("login", 0)
    if not login:
        return JSONResponse({"error": "Missing login"}, status_code=400)

    # Build account data — Profit = closed deals only (ไม่รวม floating)
    ea_name = request_data.get("name", f"EA-{login}")
    custom_label = get_account_label(login)

    account_data = {
        "login": login,
        "label": custom_label or ea_name,
        "ea_name": ea_name,
        "server": request_data.get("server", ""),
        "balance": request_data.get("balance", 0),
        "equity": request_data.get("equity", 0),
        "profit": request_data.get("profit", 0),
        "margin": request_data.get("margin", 0),
        "free_margin": request_data.get("free_margin", 0),
        "margin_level": request_data.get("margin_level", 0),
        "leverage": request_data.get("leverage", 0),
        "currency": request_data.get("currency", "USD"),
        "connected": True,
        "today": request_data.get("today_closed_profit", 0),
        "yesterday": request_data.get("yesterday_closed_profit", 0),
        "yesterday_date": request_data.get("yesterday_date", ""),
        "weekly": request_data.get("weekly_closed_profit", 0),
        "monthly": request_data.get("monthly_closed_profit", 0),
        "floating": request_data.get("profit", 0),
        "max_dd_today": request_data.get("max_dd_today", 0),
        "max_dd_yesterday": request_data.get("max_dd_yesterday", 0),
        "max_dd_week": request_data.get("max_dd_week", 0),
        "max_dd_month": request_data.get("max_dd_month", 0),
        "positions": request_data.get("positions", []),
        "positions_count": request_data.get("positions_count", 0),
        "source": "ea_push",
        "last_update": datetime.now(timezone.utc).isoformat(),
    }

    # Store in memory
    _ea_accounts[login] = account_data

    # Save to database
    try:
        save_account_snapshot([account_data])
        update_daily_summary([account_data])

        # Save portfolio (sum of all EA accounts)
        all_accounts = list(_ea_accounts.values())
        portfolio = {
            "total_balance": round(sum(a["balance"] for a in all_accounts), 2),
            "total_equity": round(sum(a["equity"] for a in all_accounts), 2),
            "total_profit": round(sum(a["profit"] for a in all_accounts), 2),
            "today_profit": round(sum(a.get("today", 0) for a in all_accounts), 2),
            "weekly_profit": round(sum(a.get("weekly", 0) for a in all_accounts), 2),
            "monthly_profit": round(sum(a.get("monthly", 0) for a in all_accounts), 2),
            "accounts": all_accounts,
        }
        save_portfolio_snapshot(portfolio)

        logger.info(
            f"EA push: {account_data['label']} ({login}) | "
            f"Bal: {account_data['balance']} | Eq: {account_data['equity']} | "
            f"P/L: {account_data['profit']}"
        )
    except Exception as e:
        logger.error(f"EA push save error: {e}")

    return JSONResponse({
        "status": "ok",
        "login": login,
        "received": datetime.now(timezone.utc).isoformat(),
        "accounts_tracked": len(_ea_accounts),
    })


@app.get("/api/ea/accounts")
async def api_ea_accounts():
    """ดูบัญชีทั้งหมดที่ EA ส่งข้อมูลมา"""
    accounts = list(_ea_accounts.values())
    return JSONResponse({
        "count": len(accounts),
        "accounts": accounts,
        "portfolio": {
            "total_balance": round(sum(a["balance"] for a in accounts), 2),
            "total_equity": round(sum(a["equity"] for a in accounts), 2),
            "total_profit": round(sum(a["profit"] for a in accounts), 2),
        },
    })


@app.get("/api/ea/account/{login}")
async def api_ea_account_detail(login: int):
    """ดูรายละเอียดบัญชีที่ EA ส่งมา (รวม open positions)"""
    acct = _ea_accounts.get(login)
    if not acct:
        return JSONResponse({"error": "Account not found"}, status_code=404)
    return JSONResponse(acct)


@app.delete("/api/ea/account/{login}")
async def api_ea_delete_account(login: int, request: Request):
    """ลบบัญชีออกจาก Dashboard (admin only)"""
    require_admin(request)
    if login in _ea_accounts:
        label = _ea_accounts[login].get("label", str(login))
        del _ea_accounts[login]
        logger.info(f"Account deleted from dashboard: {label} ({login})")
        return JSONResponse({"status": "ok", "login": login, "deleted": True})
    return JSONResponse({"error": "Account not found"}, status_code=404)


# ══════════════════════════════════════════════════════════════════════
# REST Endpoints — Account Labels (ตั้งชื่อบัญชีจากหน้าเว็บ)
# ══════════════════════════════════════════════════════════════════════

@app.get("/api/labels")
async def api_get_labels():
    """ดึงชื่อบัญชีที่ตั้งเองทั้งหมด"""
    labels = get_all_account_labels()
    return JSONResponse({"labels": {str(k): v for k, v in labels.items()}})


@app.post("/api/labels/{login}")
async def api_set_label(login: int, request: Request):
    """ตั้งชื่อบัญชี (admin only)"""
    require_admin(request)
    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    label = data.get("label", "").strip()
    if not label:
        return JSONResponse({"error": "Label cannot be empty"}, status_code=400)
    if len(label) > 50:
        return JSONResponse({"error": "Label too long (max 50)"}, status_code=400)

    set_account_label(login, label)

    # อัพเดท in-memory ทันที
    if login in _ea_accounts:
        _ea_accounts[login]["label"] = label

    return JSONResponse({"status": "ok", "login": login, "label": label})


@app.delete("/api/labels/{login}")
async def api_delete_label(login: int, request: Request):
    """ลบชื่อที่ตั้งเอง (กลับไปใช้ชื่อจาก EA) (admin only)"""
    require_admin(request)
    delete_account_label(login)

    # กลับไปใช้ชื่อจาก EA
    if login in _ea_accounts:
        _ea_accounts[login]["label"] = _ea_accounts[login].get("ea_name", f"EA-{login}")

    return JSONResponse({"status": "ok", "login": login, "reverted": True})


# ══════════════════════════════════════════════════════════════════════
# REST Endpoints — Account Order (ลำดับบัญชี drag & drop)
# ══════════════════════════════════════════════════════════════════════

@app.get("/api/order")
async def api_get_order():
    """ดึงลำดับบัญชีที่จัดไว้"""
    order = get_account_order()
    return JSONResponse({"order": order})


@app.post("/api/order")
async def api_save_order(request: Request):
    """บันทึกลำดับบัญชี (admin only)"""
    require_admin(request)
    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    order = data.get("order", [])
    if not isinstance(order, list):
        return JSONResponse({"error": "order must be a list"}, status_code=400)

    save_account_order(order)
    return JSONResponse({"status": "ok", "order": order})


# ══════════════════════════════════════════════════════════════════════
# REST Endpoints — Historical Data (ดูย้อนหลังได้แม้ MT5 ปิด)
# ══════════════════════════════════════════════════════════════════════

@app.get("/api/history/account/{login}")
async def api_account_history(login: int, days: int = Query(default=30, ge=1, le=365)):
    """ดึงประวัติ balance/equity ของบัญชี ย้อนหลัง N วัน"""
    data = get_account_history(login, days)
    return JSONResponse({
        "login": login,
        "days": days,
        "records": len(data),
        "data": data,
    })


@app.get("/api/history/portfolio")
async def api_portfolio_history(days: int = Query(default=30, ge=1, le=365)):
    """ดึงประวัติ portfolio รวม ย้อนหลัง N วัน"""
    data = get_portfolio_history(days)
    return JSONResponse({
        "days": days,
        "records": len(data),
        "data": data,
    })


@app.get("/api/history/daily")
async def api_daily_summary(
    login: int = Query(default=0),
    days: int = Query(default=30, ge=1, le=365),
):
    """สรุปรายวัน (login=0 = รวมทุกบัญชี)"""
    data = get_daily_summaries(login, days)
    return JSONResponse({
        "login": login,
        "days": days,
        "records": len(data),
        "data": data,
    })


@app.get("/api/history/market/{symbol}")
async def api_market_history(symbol: str, days: int = Query(default=7, ge=1, le=90)):
    """ราคาตลาดย้อนหลัง"""
    data = get_market_history(symbol.upper(), days)
    return JSONResponse({
        "symbol": symbol.upper(),
        "days": days,
        "records": len(data),
        "data": data,
    })


@app.get("/api/history/latest")
async def api_latest_from_db():
    """ดึงข้อมูลล่าสุดจาก database (ใช้เมื่อ MT5 ปิด)"""
    data = get_latest_snapshot()
    return JSONResponse(data)


@app.get("/api/history/stats")
async def api_db_stats():
    """สถิติ database"""
    return JSONResponse(get_database_stats())


# ══════════════════════════════════════════════════════════════════════
# REST Endpoints — Hidden Ports (admin toggle ซ่อนพอร์ตในหน้า read-only)
# ══════════════════════════════════════════════════════════════════════

_hidden_ports: set[int] = set()  # เก็บ login ที่ซ่อน


@app.get("/api/hidden-ports")
async def api_get_hidden_ports():
    return JSONResponse({"hidden": list(_hidden_ports)})


@app.post("/api/hidden-ports")
async def api_set_hidden_ports(request: Request):
    require_admin(request)
    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)
    logins = data.get("hidden", [])
    if not isinstance(logins, list):
        return JSONResponse({"error": "hidden must be a list"}, status_code=400)
    _hidden_ports.clear()
    _hidden_ports.update(int(l) for l in logins if str(l).isdigit())
    logger.info(f"Hidden ports updated: {_hidden_ports}")
    return JSONResponse({"status": "ok", "hidden": list(_hidden_ports)})

# ══════════════════════════════════════════════════════════════════════
# REST Endpoints — Myfxbook & Copy Trade Links (admin ตั้ง link ต่อบัญชี)
# ══════════════════════════════════════════════════════════════════════

_mfx_links: dict[int, str] = {}  # login -> myfxbook url
_ct_links: dict[int, str] = {}   # login -> copy trade guide url


# ── Myfxbook ──────────────────────────────────────────────────────────

@app.get("/api/mfxlinks")
async def api_get_mfxlinks():
    return JSONResponse({"links": _mfx_links})


@app.post("/api/mfxlinks")
async def api_set_mfxlinks(request: Request):
    require_admin(request)
    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    links = data.get("links", {})
    if not isinstance(links, dict):
        return JSONResponse({"error": "links must be a dict"}, status_code=400)

    _mfx_links.clear()
    _mfx_links.update({int(k): str(v) for k, v in links.items() if v})
    logger.info(f"Myfxbook links updated: {len(_mfx_links)} entries")
    return JSONResponse({"status": "ok", "links": _mfx_links})


# ── Copy Trade ────────────────────────────────────────────────────────

@app.get("/api/ctlinks")
async def api_get_ctlinks():
    return JSONResponse({"links": _ct_links})


@app.post("/api/ctlinks")
async def api_set_ctlinks(request: Request):
    require_admin(request)
    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    links = data.get("links", {})
    if not isinstance(links, dict):
        return JSONResponse({"error": "links must be a dict"}, status_code=400)

    _ct_links.clear()
    _ct_links.update({int(k): str(v) for k, v in links.items() if v})
    logger.info(f"Copy Trade links updated: {len(_ct_links)} entries")
    return JSONResponse({"status": "ok", "links": _ct_links})

# ══════════════════════════════════════════════════════════════════════
# WebSocket
# ══════════════════════════════════════════════════════════════════════

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    connected_ws.add(ws)
    logger.info(f"WS connected ({len(connected_ws)} active)")
    try:
        while True:
            data = _refresh_data()
            await ws.send_json(data)
            await asyncio.sleep(WS_INTERVAL)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"WS error: {e}")
    finally:
        connected_ws.discard(ws)
        logger.info(f"WS disconnected ({len(connected_ws)} active)")


# ── Run ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=HOST, port=int(PORT), reload=True)
