"""
database.py — Historical Data Storage (SQLite)
เก็บข้อมูล snapshot ของทุกบัญชีลง SQLite ทุก 5 นาที
ดูย้อนหลังได้แม้ MT5 ปิดแล้ว

Tables:
  - account_snapshots  : balance, equity, profit ทุก 5 นาที
  - daily_summary      : สรุปรายวัน (open/close balance, high/low equity, profit)
  - market_snapshots   : ราคาตลาดย้อนหลัง
"""

import sqlite3
import json
import os
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from pathlib import Path

logger = logging.getLogger("database")

# Database file อยู่ข้างๆ backend folder
DB_PATH = Path(__file__).resolve().parent.parent / "dashboard_data.db"


def get_connection() -> sqlite3.Connection:
    """Get SQLite connection with WAL mode for better concurrent reads."""
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_database():
    """สร้างตารางทั้งหมด (เรียกครั้งเดียวตอน server start)"""
    conn = get_connection()
    try:
        conn.executescript("""
            -- Snapshot ทุก 5 นาที ต่อบัญชี
            CREATE TABLE IF NOT EXISTS account_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                login INTEGER NOT NULL,
                label TEXT,
                server TEXT,
                balance REAL DEFAULT 0,
                equity REAL DEFAULT 0,
                profit REAL DEFAULT 0,
                margin REAL DEFAULT 0,
                free_margin REAL DEFAULT 0,
                margin_level REAL DEFAULT 0,
                floating REAL DEFAULT 0,
                connected INTEGER DEFAULT 0
            );

            -- สรุปรายวัน
            CREATE TABLE IF NOT EXISTS daily_summary (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                login INTEGER NOT NULL,
                label TEXT,
                open_balance REAL DEFAULT 0,
                close_balance REAL DEFAULT 0,
                high_equity REAL DEFAULT 0,
                low_equity REAL DEFAULT 0,
                day_profit REAL DEFAULT 0,
                total_trades INTEGER DEFAULT 0,
                UNIQUE(date, login)
            );

            -- ราคาตลาดย้อนหลัง
            CREATE TABLE IF NOT EXISTS market_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                symbol TEXT NOT NULL,
                bid REAL,
                ask REAL,
                spread REAL,
                change_pct REAL DEFAULT 0
            );

            -- Portfolio รวม (ทุกบัญชีรวมกัน)
            CREATE TABLE IF NOT EXISTS portfolio_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                total_balance REAL DEFAULT 0,
                total_equity REAL DEFAULT 0,
                total_profit REAL DEFAULT 0,
                today_profit REAL DEFAULT 0,
                weekly_profit REAL DEFAULT 0,
                monthly_profit REAL DEFAULT 0,
                account_count INTEGER DEFAULT 0
            );

            -- Index สำหรับ query เร็วๆ
            CREATE INDEX IF NOT EXISTS idx_snap_time ON account_snapshots(timestamp);
            CREATE INDEX IF NOT EXISTS idx_snap_login ON account_snapshots(login);
            CREATE INDEX IF NOT EXISTS idx_snap_login_time ON account_snapshots(login, timestamp);
            CREATE INDEX IF NOT EXISTS idx_daily_date ON daily_summary(date);
            CREATE INDEX IF NOT EXISTS idx_daily_login ON daily_summary(login, date);
            CREATE INDEX IF NOT EXISTS idx_market_time ON market_snapshots(timestamp);
            CREATE INDEX IF NOT EXISTS idx_market_symbol ON market_snapshots(symbol, timestamp);
            CREATE INDEX IF NOT EXISTS idx_portfolio_time ON portfolio_snapshots(timestamp);

            -- ชื่อบัญชีที่ตั้งเองจากหน้าเว็บ
            CREATE TABLE IF NOT EXISTS account_labels (
                login INTEGER PRIMARY KEY,
                custom_label TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            -- ลำดับบัญชีที่จัดเองจากหน้าเว็บ (drag & drop)
            CREATE TABLE IF NOT EXISTS account_order (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                order_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
        """)
        conn.commit()
        logger.info(f"Database initialized: {DB_PATH}")
    finally:
        conn.close()


# =====================================================================
# WRITE — บันทึกข้อมูล
# =====================================================================

def save_account_snapshot(accounts_data: list[dict]):
    """บันทึก snapshot ของทุกบัญชี (เรียกทุก 5 นาที)"""
    if not accounts_data:
        return
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    conn = get_connection()
    try:
        rows = []
        for a in accounts_data:
            rows.append((
                now,
                a.get("login", 0),
                a.get("label", ""),
                a.get("server", ""),
                a.get("balance", 0),
                a.get("equity", 0),
                a.get("profit", 0),
                a.get("margin", 0),
                a.get("free_margin", 0),
                a.get("margin_level", 0),
                a.get("floating", a.get("profit", 0)),
                1 if a.get("connected", False) else 0,
            ))
        conn.executemany("""
            INSERT INTO account_snapshots
            (timestamp, login, label, server, balance, equity, profit,
             margin, free_margin, margin_level, floating, connected)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, rows)
        conn.commit()
        logger.debug(f"Saved {len(rows)} account snapshots")
    finally:
        conn.close()


def save_portfolio_snapshot(portfolio: dict):
    """บันทึก portfolio รวมทุกบัญชี"""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    conn = get_connection()
    try:
        conn.execute("""
            INSERT INTO portfolio_snapshots
            (timestamp, total_balance, total_equity, total_profit,
             today_profit, weekly_profit, monthly_profit, account_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            now,
            portfolio.get("total_balance", 0),
            portfolio.get("total_equity", 0),
            portfolio.get("total_profit", 0),
            portfolio.get("today_profit", 0),
            portfolio.get("weekly_profit", 0),
            portfolio.get("monthly_profit", 0),
            len(portfolio.get("accounts", [])),
        ))
        conn.commit()
    finally:
        conn.close()


def save_market_snapshot(market_data: list[dict]):
    """บันทึกราคาตลาด"""
    if not market_data:
        return
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    conn = get_connection()
    try:
        rows = [(
            now,
            m.get("symbol", ""),
            m.get("bid", 0),
            m.get("ask", 0),
            m.get("spread", 0),
            m.get("change", 0),
        ) for m in market_data if m.get("symbol")]
        conn.executemany("""
            INSERT INTO market_snapshots
            (timestamp, symbol, bid, ask, spread, change_pct)
            VALUES (?, ?, ?, ?, ?, ?)
        """, rows)
        conn.commit()
    finally:
        conn.close()


def update_daily_summary(accounts_data: list[dict]):
    """อัพเดทสรุปรายวัน (เรียกทุก snapshot, upsert)"""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    conn = get_connection()
    try:
        for a in accounts_data:
            login = a.get("login", 0)
            balance = a.get("balance", 0)
            equity = a.get("equity", 0)
            profit = a.get("profit", 0)

            existing = conn.execute(
                "SELECT * FROM daily_summary WHERE date=? AND login=?",
                (today, login)
            ).fetchone()

            if existing:
                high_eq = max(existing["high_equity"], equity)
                low_eq = min(existing["low_equity"], equity) if existing["low_equity"] > 0 else equity
                conn.execute("""
                    UPDATE daily_summary
                    SET close_balance=?, high_equity=?, low_equity=?, day_profit=?
                    WHERE date=? AND login=?
                """, (balance, high_eq, low_eq, balance - existing["open_balance"], today, login))
            else:
                conn.execute("""
                    INSERT INTO daily_summary
                    (date, login, label, open_balance, close_balance,
                     high_equity, low_equity, day_profit, total_trades)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (today, login, a.get("label", ""), balance, balance,
                      equity, equity, 0, 0))
        conn.commit()
    finally:
        conn.close()


# =====================================================================
# ACCOUNT LABELS — ตั้งชื่อบัญชีจากหน้าเว็บ
# =====================================================================

def set_account_label(login: int, label: str):
    """ตั้งชื่อบัญชี (เรียกจากหน้าเว็บ)"""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    conn = get_connection()
    try:
        conn.execute("""
            INSERT INTO account_labels (login, custom_label, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(login) DO UPDATE SET custom_label=?, updated_at=?
        """, (login, label, now, label, now))
        conn.commit()
        logger.info(f"Label set: {login} -> '{label}'")
    finally:
        conn.close()


def get_account_label(login: int) -> Optional[str]:
    """ดึงชื่อที่ตั้งเอง (return None ถ้าไม่เคยตั้ง)"""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT custom_label FROM account_labels WHERE login=?", (login,)
        ).fetchone()
        return row["custom_label"] if row else None
    finally:
        conn.close()


def get_all_account_labels() -> dict:
    """ดึงชื่อที่ตั้งเองทุกบัญชี {login: label}"""
    conn = get_connection()
    try:
        rows = conn.execute("SELECT login, custom_label FROM account_labels").fetchall()
        return {row["login"]: row["custom_label"] for row in rows}
    finally:
        conn.close()


def delete_account_label(login: int):
    """ลบชื่อที่ตั้งเอง (กลับไปใช้ชื่อจาก EA)"""
    conn = get_connection()
    try:
        conn.execute("DELETE FROM account_labels WHERE login=?", (login,))
        conn.commit()
    finally:
        conn.close()


# =====================================================================
# ACCOUNT ORDER — ลำดับบัญชีที่จัดเองจากหน้าเว็บ
# =====================================================================

def save_account_order(order_list: list):
    """บันทึกลำดับบัญชี [login1, login2, ...] """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    conn = get_connection()
    try:
        conn.execute("""
            INSERT INTO account_order (id, order_json, updated_at)
            VALUES (1, ?, ?)
            ON CONFLICT(id) DO UPDATE SET order_json=?, updated_at=?
        """, (json.dumps(order_list), now, json.dumps(order_list), now))
        conn.commit()
    finally:
        conn.close()


def get_account_order() -> list:
    """ดึงลำดับบัญชีที่จัดไว้ return [] ถ้าไม่เคยตั้ง"""
    conn = get_connection()
    try:
        row = conn.execute("SELECT order_json FROM account_order WHERE id=1").fetchone()
        if row:
            return json.loads(row["order_json"])
        return []
    finally:
        conn.close()


# =====================================================================
# READ — ดึงข้อมูลย้อนหลัง
# =====================================================================

def get_account_history(login: int, days: int = 30) -> list[dict]:
    """ดึงประวัติ balance/equity ของบัญชี ย้อนหลัง N วัน"""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT timestamp, balance, equity, profit, floating
            FROM account_snapshots
            WHERE login=? AND timestamp>=?
            ORDER BY timestamp ASC
        """, (login, since)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_portfolio_history(days: int = 30) -> list[dict]:
    """ดึงประวัติ portfolio รวม ย้อนหลัง N วัน"""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT timestamp, total_balance, total_equity, total_profit,
                   today_profit, weekly_profit, monthly_profit
            FROM portfolio_snapshots
            WHERE timestamp>=?
            ORDER BY timestamp ASC
        """, (since,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_daily_summaries(login: int = 0, days: int = 30) -> list[dict]:
    """ดึงสรุปรายวัน ถ้า login=0 ดึงทุกบัญชี"""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    conn = get_connection()
    try:
        if login > 0:
            rows = conn.execute("""
                SELECT * FROM daily_summary
                WHERE login=? AND date>=?
                ORDER BY date ASC
            """, (login, since)).fetchall()
        else:
            rows = conn.execute("""
                SELECT date,
                       SUM(open_balance) as open_balance,
                       SUM(close_balance) as close_balance,
                       MAX(high_equity) as high_equity,
                       MIN(low_equity) as low_equity,
                       SUM(day_profit) as day_profit
                FROM daily_summary
                WHERE date>=?
                GROUP BY date
                ORDER BY date ASC
            """, (since,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_market_history(symbol: str, days: int = 7) -> list[dict]:
    """ดึงราคาตลาดย้อนหลัง"""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT timestamp, bid, ask, spread, change_pct
            FROM market_snapshots
            WHERE symbol=? AND timestamp>=?
            ORDER BY timestamp ASC
        """, (symbol, since)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_latest_snapshot() -> dict:
    """ดึง snapshot ล่าสุดจาก database (ใช้ตอน MT5 ปิด)"""
    conn = get_connection()
    try:
        # Portfolio ล่าสุด
        port = conn.execute("""
            SELECT * FROM portfolio_snapshots ORDER BY timestamp DESC LIMIT 1
        """).fetchone()

        # Account ล่าสุดแต่ละบัญชี
        accounts = conn.execute("""
            SELECT a.* FROM account_snapshots a
            INNER JOIN (
                SELECT login, MAX(timestamp) as max_ts
                FROM account_snapshots
                GROUP BY login
            ) b ON a.login = b.login AND a.timestamp = b.max_ts
        """).fetchall()

        # Market ล่าสุดแต่ละ symbol
        market = conn.execute("""
            SELECT m.* FROM market_snapshots m
            INNER JOIN (
                SELECT symbol, MAX(timestamp) as max_ts
                FROM market_snapshots
                GROUP BY symbol
            ) b ON m.symbol = b.symbol AND m.timestamp = b.max_ts
        """).fetchall()

        result = {
            "portfolio": dict(port) if port else {},
            "accounts": [dict(a) for a in accounts],
            "market": [dict(m) for m in market],
            "from_database": True,
            "timestamp": port["timestamp"] if port else "",
        }
        return result
    finally:
        conn.close()


def get_database_stats() -> dict:
    """สถิติ database"""
    conn = get_connection()
    try:
        snap_count = conn.execute("SELECT COUNT(*) FROM account_snapshots").fetchone()[0]
        port_count = conn.execute("SELECT COUNT(*) FROM portfolio_snapshots").fetchone()[0]
        daily_count = conn.execute("SELECT COUNT(*) FROM daily_summary").fetchone()[0]
        market_count = conn.execute("SELECT COUNT(*) FROM market_snapshots").fetchone()[0]

        first_snap = conn.execute("SELECT MIN(timestamp) FROM account_snapshots").fetchone()[0]
        last_snap = conn.execute("SELECT MAX(timestamp) FROM account_snapshots").fetchone()[0]

        # ขนาดไฟล์
        db_size = os.path.getsize(str(DB_PATH)) if DB_PATH.exists() else 0

        return {
            "snapshots": snap_count,
            "portfolio_records": port_count,
            "daily_summaries": daily_count,
            "market_records": market_count,
            "first_record": first_snap or "N/A",
            "last_record": last_snap or "N/A",
            "db_size_mb": round(db_size / 1024 / 1024, 2),
        }
    finally:
        conn.close()


# =====================================================================
# MAINTENANCE — ลบข้อมูลเก่า
# =====================================================================

def cleanup_old_data(keep_days: int = 90):
    """ลบ snapshots เก่ากว่า N วัน (เก็บ daily_summary ไว้ตลอด)"""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=keep_days)).strftime("%Y-%m-%d %H:%M:%S")
    conn = get_connection()
    try:
        r1 = conn.execute("DELETE FROM account_snapshots WHERE timestamp < ?", (cutoff,))
        r2 = conn.execute("DELETE FROM market_snapshots WHERE timestamp < ?", (cutoff,))
        r3 = conn.execute("DELETE FROM portfolio_snapshots WHERE timestamp < ?", (cutoff,))
        conn.commit()
        total = r1.rowcount + r2.rowcount + r3.rowcount
        if total > 0:
            logger.info(f"Cleaned up {total} old records (older than {keep_days} days)")
            conn.execute("VACUUM")
    finally:
        conn.close()
