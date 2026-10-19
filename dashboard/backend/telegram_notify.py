"""
telegram_notify.py — DRFX Dashboard Telegram Notifications
ส่งสรุปผลกำไร รายวัน / รายสัปดาห์ / รายเดือน ไปยัง Telegram

ใช้ร่วมกับ main.py โดยเรียก start_telegram_scheduler()
"""

import os
import logging
import asyncio
import httpx
from datetime import datetime, timezone, timedelta

logger = logging.getLogger("telegram")

# ── Config ────────────────────────────────────────────────────────────
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
# เวลาส่งสรุปรายวัน (server time ของ MT5 broker, เช่น 23:55)
DAILY_HOUR = int(os.getenv("TELEGRAM_DAILY_HOUR", "21"))
DAILY_MIN = int(os.getenv("TELEGRAM_DAILY_MIN", "30"))

# ── Format helpers ────────────────────────────────────────────────────
DIVIDER = "━━━━━━━━━━━━━━━"  # สั้นลง อ่านง่ายบนมือถือ


# ── Telegram sender ───────────────────────────────────────────────────
async def send_telegram(text: str) -> bool:
    """ส่งข้อความไปยัง Telegram"""
    if not BOT_TOKEN or not CHAT_ID:
        logger.warning("Telegram: BOT_TOKEN or CHAT_ID not set — skip")
        return False

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code == 200:
                logger.info("Telegram: Message sent OK")
                return True
            logger.error(f"Telegram: HTTP {resp.status_code} — {resp.text}")
            return False
    except Exception as e:
        logger.error(f"Telegram: Send failed — {e}")
        return False


# ── Report builder (unified) ──────────────────────────────────────────
def _pct(value: float, base: float) -> float:
    """คำนวณ % เทียบกับ base (Cost) — return 0 ถ้า base ไม่ valid"""
    return (value / base * 100) if base > 0 else 0.0


def _build_report(
    accounts: list,
    rate: float,
    *,
    period_key: str,        # "today" | "weekly" | "monthly"
    dd_key: str,            # "max_dd_today" | "max_dd_week" | "max_dd_month"
    title: str,             # "Daily Report" / "Weekly Report" / "Monthly Report"
    date_label: str,        # ข้อความวันที่ใต้หัวเรื่อง
) -> str:
    """สร้างข้อความสรุปแบบรวม — ใช้ได้ทั้ง daily/weekly/monthly"""

    total_cost = sum(a.get("balance", 0) for a in accounts)
    total_profit = sum(a.get(period_key, 0) for a in accounts)
    thb_profit = total_profit * rate / 100

    # ─ Header ─
    lines = [
        f"⚡ <b>DRFX {title}</b>",
        f"📅 {date_label}",
        "",
    ]

    # ─ Per-account blocks (เรียงจากมากไปน้อย) ─
    sorted_accts = sorted(accounts, key=lambda a: a.get(period_key, 0), reverse=True)
    for a in sorted_accts:
        label = a.get("label", str(a.get("login", "?")))
        cost = a.get("balance", 0)
        profit = a.get(period_key, 0)
        dd = abs(a.get(dd_key, 0))  # แสดงเป็นค่าบวก

        profit_pct = _pct(profit, cost)
        dd_pct = _pct(dd, cost)

        psign = "+" if profit >= 0 else "−"

        lines += [
            f"<b>{label}</b>",
            f"Cost     : {cost:,.0f} USC",
            f"Profit   : {psign}{abs(profit):,.0f} ≈ {psign}{abs(profit_pct):.2f}%",
            f"MaxDD    : {dd:,.0f} ≈ {dd_pct:.2f}%",
            "",
        ]

    # ─ Portfolio summary (ปิดท้าย) ─
    psign = "+" if total_profit >= 0 else "−"
    total_pct = _pct(total_profit, total_cost)

    lines += [
        DIVIDER,
        "💼 <b>Portfolio Total</b>",
        f"Cost     : {total_cost:,.0f} USC",
        f"Profit   : <b>{psign}{abs(total_profit):,.0f} ≈ {psign}{abs(total_pct):.2f}%</b>",
        f"           ({psign}฿{abs(thb_profit):,.0f})",
    ]

    # ─ Footer ─
    lines += [
        "",
        f"💱 1 USC = ฿{rate:.4f}  •  📡 {len(accounts)} accounts",
    ]

    return "\n".join(lines)


def build_daily_report(accounts: list, rate: float) -> str:
    """สร้างข้อความสรุปรายวัน"""
    now = datetime.now(timezone.utc)
    return _build_report(
        accounts, rate,
        period_key="today",
        dd_key="max_dd_today",
        title="Daily Report",
        date_label=now.strftime("%A, %d %B %Y"),
    )


def build_weekly_report(accounts: list, rate: float) -> str:
    """สร้างข้อความสรุปรายสัปดาห์"""
    now = datetime.now(timezone.utc)
    return _build_report(
        accounts, rate,
        period_key="weekly",
        dd_key="max_dd_week",
        title="Weekly Report",
        date_label=f"Week ending {now.strftime('%d %b %Y')}",
    )


def build_monthly_report(accounts: list, rate: float) -> str:
    """สร้างข้อความสรุปรายเดือน"""
    now = datetime.now(timezone.utc)
    return _build_report(
        accounts, rate,
        period_key="monthly",
        dd_key="max_dd_month",
        title="Monthly Report",
        date_label=now.strftime("%B %Y"),
    )


# ── Scheduler ─────────────────────────────────────────────────────────
async def telegram_scheduler(get_accounts_fn, get_rate_fn):
    """
    Background loop — ส่งสรุปอัตโนมัติ:
    - Daily:   ทุกวัน ตาม DAILY_HOUR:DAILY_MIN
    - Weekly:  ทุกวันศุกร์ (หลังส่ง daily)
    - Monthly: วันสุดท้ายของเดือน (หลังส่ง daily)
    """
    if not BOT_TOKEN or not CHAT_ID:
        logger.warning("Telegram: Not configured — scheduler disabled")
        logger.warning("Telegram: Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env")
        return

    logger.info(f"Telegram: Scheduler started — daily at {DAILY_HOUR:02d}:{DAILY_MIN:02d}")

    # ส่ง startup message
    await send_telegram(
        "🟢 <b>DRFX Dashboard Online</b>\n"
        "<i>Telegram notifications active</i>"
    )

    last_daily_date = ""

    while True:
        await asyncio.sleep(30)

        now = datetime.now(timezone.utc)
        today_str = now.strftime("%Y-%m-%d")

        # ── Daily report ──
        if (now.hour == DAILY_HOUR
                and now.minute == DAILY_MIN
                and today_str != last_daily_date):

            last_daily_date = today_str

            accounts = get_accounts_fn()
            rate = get_rate_fn()

            if not accounts:
                continue

            # Daily
            try:
                await send_telegram(build_daily_report(accounts, rate))
                logger.info("Telegram: Daily report sent")
            except Exception as e:
                logger.error(f"Telegram: Daily report failed — {e}")

            # Weekly — ทุกวันศุกร์
            if now.weekday() == 4:
                try:
                    await send_telegram(build_weekly_report(accounts, rate))
                    logger.info("Telegram: Weekly report sent")
                except Exception as e:
                    logger.error(f"Telegram: Weekly report failed — {e}")

            # Monthly — วันสุดท้ายของเดือน
            if (now + timedelta(days=1)).month != now.month:
                try:
                    await send_telegram(build_monthly_report(accounts, rate))
                    logger.info("Telegram: Monthly report sent")
                except Exception as e:
                    logger.error(f"Telegram: Monthly report failed — {e}")
