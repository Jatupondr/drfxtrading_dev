"""
mt5_service.py — MetaTrader 5 Multi-Account / Multi-Broker Service Layer
Handles connections, account data retrieval, position tracking,
and history queries for all configured MT5 accounts.

Supports:
  - Multiple accounts on the same broker (same terminal)
  - Multiple accounts on different brokers (different terminals)
  - Each account can specify its own terminal_path
  - Automatic shutdown/initialize cycle when switching terminals
"""

try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone
from typing import Optional
import logging

logger = logging.getLogger("mt5_service")


class MT5Account:
    """Represents a single MT5 account connection."""

    def __init__(
        self,
        login: int,
        password: str,
        server: str,
        label: str = "",
        terminal_path: str = "",
    ):
        self.login = login
        self.password = password
        self.server = server
        self.label = label or f"Account-{login}"
        self.terminal_path = terminal_path  # path ไปยัง terminal64.exe ของโบรกนั้นๆ
        self.connected = False
        self._last_info = None

    def to_dict(self) -> dict:
        return {
            "login": self.login,
            "server": self.server,
            "label": self.label,
            "connected": self.connected,
            "terminal_path": self.terminal_path,
        }


class MT5Service:
    """
    Multi-account / Multi-broker MT5 service.
    Manages connections and data for multiple trading accounts,
    each potentially on a different broker terminal.
    """

    def __init__(self):
        self.accounts: list[MT5Account] = []
        self._initialized = False
        self._current_terminal = ""  # path ของ terminal ที่เชื่อมอยู่ตอนนี้
        self._current_login = 0      # login ที่ active อยู่ตอนนี้

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def initialize(self, terminal_path: str = "") -> bool:
        """Initialize the MT5 terminal. ระบุ path เพื่อล็อค terminal ตัวที่ต้องการ"""
        if terminal_path:
            self._initialized = mt5.initialize(terminal_path)
        else:
            self._initialized = mt5.initialize()

        if self._initialized:
            self._current_terminal = terminal_path
            logger.info(f"MT5 initialized: {terminal_path or 'default'}")
        else:
            logger.error(f"MT5 init failed: {mt5.last_error()}")
        return self._initialized

    def shutdown(self):
        mt5.shutdown()
        self._initialized = False
        self._current_terminal = ""
        self._current_login = 0

    def add_account(
        self,
        login: int,
        password: str,
        server: str,
        label: str = "",
        terminal_path: str = "",
    ):
        acct = MT5Account(login, password, server, label, terminal_path)
        self.accounts.append(acct)
        return acct

    # ------------------------------------------------------------------
    # Connection helpers
    # ------------------------------------------------------------------
    def _switch_account(self, acct: MT5Account) -> bool:
        """
        Login ไปยังบัญชีที่ต้องการ
        - ถ้าคนละ terminal → shutdown ตัวเก่า แล้ว initialize ตัวใหม่
        - ถ้า terminal เดิม + login เดิม → ไม่ต้องทำอะไร (ประหยัดเวลา)
        - ถ้า terminal เดิม + คนละ login → สั่ง login อย่างเดียว
        """
        target_terminal = acct.terminal_path or ""

        # ---- กรณี 1: ต้องเปลี่ยน terminal (คนละโบรก) ----
        if self._initialized and target_terminal != self._current_terminal:
            logger.info(
                f"Switching terminal: {self._current_terminal or 'default'}"
                f" -> {target_terminal or 'default'}"
            )
            mt5.shutdown()
            self._initialized = False
            self._current_terminal = ""
            self._current_login = 0

        # ---- Initialize ถ้ายังไม่ได้ทำ ----
        if not self._initialized:
            if target_terminal:
                self._initialized = mt5.initialize(target_terminal)
            else:
                self._initialized = mt5.initialize()

            if not self._initialized:
                logger.warning(
                    f"MT5 init failed for {acct.label} "
                    f"({target_terminal or 'default'}): {mt5.last_error()}"
                )
                acct.connected = False
                return False
            self._current_terminal = target_terminal

        # ---- กรณี 2: login เดิมอยู่แล้ว ไม่ต้องสลับ ----
        if self._current_login == acct.login:
            acct.connected = True
            return True

        # ---- กรณี 3: สลับ login ----
        ok = mt5.login(acct.login, password=acct.password, server=acct.server)
        acct.connected = ok
        if ok:
            self._current_login = acct.login
            logger.debug(f"Logged in: {acct.label} ({acct.login})")
        else:
            logger.warning(f"Login failed for {acct.label}: {mt5.last_error()}")
            self._current_login = 0
        return ok

    # ------------------------------------------------------------------
    # Account data
    # ------------------------------------------------------------------
    def get_account_info(self, acct: MT5Account) -> Optional[dict]:
        if not self._switch_account(acct):
            return None
        info = mt5.account_info()
        if info is None:
            return None
        d = info._asdict()
        acct._last_info = d
        return {
            "login": d["login"],
            "label": acct.label,
            "server": acct.server,
            "balance": round(d["balance"], 2),
            "equity": round(d["equity"], 2),
            "margin": round(d["margin"], 2),
            "free_margin": round(d["margin_free"], 2),
            "margin_level": round(d.get("margin_level", 0), 2),
            "profit": round(d["profit"], 2),
            "leverage": d["leverage"],
            "currency": d["currency"],
            "connected": True,
        }

    def get_all_accounts_info(self) -> list[dict]:
        results = []
        for acct in self.accounts:
            info = self.get_account_info(acct)
            if info:
                results.append(info)
            else:
                results.append({
                    "login": acct.login,
                    "label": acct.label,
                    "server": acct.server,
                    "balance": 0, "equity": 0, "margin": 0,
                    "free_margin": 0, "margin_level": 0, "profit": 0,
                    "leverage": 0, "currency": "USD", "connected": False,
                })
        return results

    # ------------------------------------------------------------------
    # Positions & history
    # ------------------------------------------------------------------
    def get_open_positions(self, acct: MT5Account) -> list[dict]:
        if not self._switch_account(acct):
            return []
        positions = mt5.positions_get()
        if positions is None:
            return []
        return [p._asdict() for p in positions]

    def get_closed_deals(
        self, acct: MT5Account, days: int = 30
    ) -> pd.DataFrame:
        if not self._switch_account(acct):
            return pd.DataFrame()
        now = datetime.now(timezone.utc)
        from_date = now - timedelta(days=days)
        deals = mt5.history_deals_get(from_date, now)
        if deals is None or len(deals) == 0:
            return pd.DataFrame()
        df = pd.DataFrame([d._asdict() for d in deals])
        df["time"] = pd.to_datetime(df["time"], unit="s")
        return df

    def get_profit_by_period(self, acct: MT5Account) -> dict:
        """Calculate today / weekly / monthly profit from deal history."""
        df = self.get_closed_deals(acct, days=31)
        now = datetime.now(timezone.utc)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = today_start - timedelta(days=today_start.weekday())
        month_start = today_start.replace(day=1)

        floating = 0.0
        info = self.get_account_info(acct)
        if info:
            floating = info["profit"]

        if df.empty:
            return {
                "today": round(floating, 2),
                "weekly": round(floating, 2),
                "monthly": round(floating, 2),
                "floating": round(floating, 2),
            }

        today_p = float(df[df["time"] >= today_start]["profit"].sum()) if not df.empty else 0
        week_p = float(df[df["time"] >= week_start]["profit"].sum()) if not df.empty else 0
        month_p = float(df[df["time"] >= month_start]["profit"].sum()) if not df.empty else 0

        return {
            "today": round(today_p + floating, 2),
            "weekly": round(week_p + floating, 2),
            "monthly": round(month_p + floating, 2),
            "floating": round(floating, 2),
        }

    # ------------------------------------------------------------------
    # Equity curve (for charting)
    # ------------------------------------------------------------------
    def get_equity_curve(self, acct: MT5Account, days: int = 30) -> list[dict]:
        df = self.get_closed_deals(acct, days=days)
        info = self.get_account_info(acct)
        if info is None:
            return []

        current_balance = info["balance"]
        current_equity = info["equity"]

        if df.empty:
            ts = datetime.now(timezone.utc).isoformat()
            return [{"time": ts, "balance": current_balance, "equity": current_equity}]

        df_out = df[df["entry"] == 1].copy()
        if df_out.empty:
            ts = datetime.now(timezone.utc).isoformat()
            return [{"time": ts, "balance": current_balance, "equity": current_equity}]

        df_out = df_out.sort_values("time")
        df_out["cum_profit"] = df_out["profit"].cumsum()
        start_balance = current_balance - float(df_out["cum_profit"].iloc[-1])

        curve = []
        for _, row in df_out.iterrows():
            bal = start_balance + row["cum_profit"]
            curve.append({
                "time": row["time"].isoformat(),
                "balance": round(bal, 2),
                "equity": round(bal, 2),
            })
        curve.append({
            "time": datetime.now(timezone.utc).isoformat(),
            "balance": current_balance,
            "equity": current_equity,
        })
        return curve

    # ------------------------------------------------------------------
    # Market data
    # ------------------------------------------------------------------
    def get_symbol_price(self, symbol: str) -> Optional[dict]:
        if not self._initialized:
            self.initialize()
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            return None
        t = tick._asdict()
        return {
            "symbol": symbol,
            "bid": t["bid"],
            "ask": t["ask"],
            "spread": round(t["ask"] - t["bid"], 5),
            "time": datetime.fromtimestamp(t["time"], tz=timezone.utc).isoformat(),
        }

    def get_market_overview(self, symbols: list[str] = None) -> list[dict]:
        if symbols is None:
            symbols = ["EURUSD", "GBPUSD", "USDJPY", "BTCUSD", "XAUUSD"]
        results = []
        for sym in symbols:
            price = self.get_symbol_price(sym)
            if price:
                info = mt5.symbol_info(sym)
                if info:
                    si = info._asdict()
                    price["change"] = round(
                        ((price["bid"] - si.get("session_open", price["bid"]))
                         / si.get("session_open", price["bid"])) * 100, 3
                    ) if si.get("session_open", 0) > 0 else 0.0
                else:
                    price["change"] = 0.0
                results.append(price)
        return results

    # ------------------------------------------------------------------
    # Portfolio aggregation
    # ------------------------------------------------------------------
    def get_portfolio_summary(self) -> dict:
        total_balance = 0.0
        total_equity = 0.0
        total_profit = 0.0
        today_profit = 0.0
        weekly_profit = 0.0
        monthly_profit = 0.0

        accounts_data = []
        for acct in self.accounts:
            info = self.get_account_info(acct)
            periods = self.get_profit_by_period(acct)
            if info:
                total_balance += info["balance"]
                total_equity += info["equity"]
                total_profit += info["profit"]
                today_profit += periods["today"]
                weekly_profit += periods["weekly"]
                monthly_profit += periods["monthly"]
                accounts_data.append({**info, **periods})
            else:
                accounts_data.append({
                    "login": acct.login, "label": acct.label,
                    "server": acct.server, "connected": False,
                    "balance": 0, "equity": 0, "profit": 0,
                    "today": 0, "weekly": 0, "monthly": 0,
                })

        return {
            "total_balance": round(total_balance, 2),
            "total_equity": round(total_equity, 2),
            "total_profit": round(total_profit, 2),
            "today_profit": round(today_profit, 2),
            "weekly_profit": round(weekly_profit, 2),
            "monthly_profit": round(monthly_profit, 2),
            "accounts": accounts_data,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
