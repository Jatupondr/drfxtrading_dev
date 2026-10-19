"""
analytics.py — Portfolio Analytics & Market Intelligence
Provides portfolio statistics, currency heatmap data,
and economic news event retrieval.
"""

import httpx
import pandas as pd
import numpy as np
from datetime import datetime, timezone
from typing import Optional
import logging
import asyncio

logger = logging.getLogger("analytics")

# =====================================================================
# Currency Heatmap
# =====================================================================
MAJOR_CURRENCIES = ["USD", "EUR", "GBP", "JPY", "AUD", "CAD", "CHF", "NZD"]

HEATMAP_PAIRS = [
    "EURUSD", "GBPUSD", "AUDUSD", "NZDUSD",
    "USDJPY", "USDCAD", "USDCHF",
    "EURGBP", "EURJPY", "EURAUD", "EURCHF", "EURCAD", "EURNZD",
    "GBPJPY", "GBPAUD", "GBPCHF", "GBPCAD", "GBPNZD",
    "AUDJPY", "AUDCAD", "AUDCHF", "AUDNZD",
    "NZDJPY", "NZDCAD", "NZDCHF",
    "CADJPY", "CADCHF",
    "CHFJPY",
]


def compute_currency_strength(market_data: list[dict]) -> dict:
    """
    Compute relative currency strength from % changes of pairs.
    Returns a dict like {"USD": 2.5, "EUR": -1.3, ...} normalised -100..+100.
    """
    scores = {c: 0.0 for c in MAJOR_CURRENCIES}
    counts = {c: 0 for c in MAJOR_CURRENCIES}

    for item in market_data:
        sym = item.get("symbol", "")
        change = item.get("change", 0.0)
        if len(sym) < 6:
            continue
        base = sym[:3]
        quote = sym[3:6]
        if base in scores:
            scores[base] += change
            counts[base] += 1
        if quote in scores:
            scores[quote] -= change
            counts[quote] += 1

    for c in MAJOR_CURRENCIES:
        if counts[c] > 0:
            scores[c] = round(scores[c] / counts[c], 3)

    # Normalise to -100..+100 range
    vals = list(scores.values())
    max_abs = max(abs(v) for v in vals) if vals else 1
    if max_abs == 0:
        max_abs = 1
    normalised = {c: round((v / max_abs) * 100, 1) for c, v in scores.items()}
    return normalised


def build_heatmap_matrix(strength: dict) -> list[dict]:
    """
    Build an NxN heatmap matrix for the 8 major currencies.
    Each cell = base_strength - quote_strength (synthetic pair score).
    """
    matrix = []
    for base in MAJOR_CURRENCIES:
        row = {"currency": base}
        for quote in MAJOR_CURRENCIES:
            if base == quote:
                row[quote] = 0
            else:
                row[quote] = round(strength.get(base, 0) - strength.get(quote, 0), 1)
        matrix.append(row)
    return matrix


# =====================================================================
# Economic News
# =====================================================================
async def fetch_economic_news(api_key: str = "") -> list[dict]:
    """
    Fetch upcoming economic events from FinancialModelingPrep
    or return mock data if no API key.
    """
    if api_key and api_key != "your_api_key_here":
        try:
            url = f"https://financialmodelingprep.com/api/v3/economic_calendar?apikey={api_key}"
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    data = resp.json()
                    events = []
                    for item in data[:20]:
                        events.append({
                            "time": item.get("date", ""),
                            "country": item.get("country", ""),
                            "event": item.get("event", ""),
                            "impact": item.get("impact", "Low"),
                            "forecast": str(item.get("estimate", "—")),
                            "previous": str(item.get("previous", "—")),
                            "actual": str(item.get("actual", "—")),
                        })
                    return events
        except Exception as e:
            logger.warning(f"News fetch failed: {e}")

    # Fallback: mock upcoming events
    return _generate_mock_news()


def _generate_mock_news() -> list[dict]:
    """Generate realistic mock economic news for demo."""
    now = datetime.now(timezone.utc)
    events = [
        {"offset": 1, "country": "US", "event": "Non-Farm Payrolls", "impact": "High",
         "forecast": "185K", "previous": "177K", "actual": "—"},
        {"offset": 2, "country": "US", "event": "Fed Interest Rate Decision", "impact": "High",
         "forecast": "5.50%", "previous": "5.50%", "actual": "—"},
        {"offset": 3, "country": "EU", "event": "ECB Press Conference", "impact": "High",
         "forecast": "—", "previous": "—", "actual": "—"},
        {"offset": 4, "country": "GB", "event": "GDP q/q", "impact": "High",
         "forecast": "0.2%", "previous": "0.1%", "actual": "—"},
        {"offset": 5, "country": "US", "event": "CPI m/m", "impact": "High",
         "forecast": "0.3%", "previous": "0.4%", "actual": "—"},
        {"offset": 6, "country": "JP", "event": "BOJ Policy Rate", "impact": "High",
         "forecast": "-0.10%", "previous": "-0.10%", "actual": "—"},
        {"offset": 8, "country": "AU", "event": "Employment Change", "impact": "Medium",
         "forecast": "25.0K", "previous": "14.6K", "actual": "—"},
        {"offset": 10, "country": "CA", "event": "CPI m/m", "impact": "High",
         "forecast": "0.2%", "previous": "0.1%", "actual": "—"},
        {"offset": 12, "country": "US", "event": "Retail Sales m/m", "impact": "Medium",
         "forecast": "0.4%", "previous": "0.6%", "actual": "—"},
        {"offset": 14, "country": "CH", "event": "SNB Policy Rate", "impact": "High",
         "forecast": "1.75%", "previous": "1.75%", "actual": "—"},
        {"offset": 16, "country": "EU", "event": "Flash Manufacturing PMI", "impact": "Medium",
         "forecast": "47.5", "previous": "46.6", "actual": "—"},
        {"offset": 18, "country": "US", "event": "Core PCE Price Index m/m", "impact": "High",
         "forecast": "0.2%", "previous": "0.3%", "actual": "—"},
    ]
    result = []
    for ev in events:
        t = now + pd.Timedelta(hours=ev["offset"])
        result.append({
            "time": t.strftime("%Y-%m-%d %H:%M"),
            "country": ev["country"],
            "event": ev["event"],
            "impact": ev["impact"],
            "forecast": ev["forecast"],
            "previous": ev["previous"],
            "actual": ev["actual"],
        })
    return result


# =====================================================================
# Portfolio statistics helpers
# =====================================================================
def calculate_drawdown(equity_curve: list[dict]) -> dict:
    """Calculate max drawdown from equity curve."""
    if not equity_curve:
        return {"max_dd": 0, "max_dd_pct": 0}

    equities = [p["equity"] for p in equity_curve]
    peak = equities[0]
    max_dd = 0.0
    for eq in equities:
        if eq > peak:
            peak = eq
        dd = peak - eq
        if dd > max_dd:
            max_dd = dd
    max_dd_pct = (max_dd / peak * 100) if peak > 0 else 0
    return {"max_dd": round(max_dd, 2), "max_dd_pct": round(max_dd_pct, 2)}


def calculate_sharpe(returns: list[float], risk_free_rate: float = 0.0) -> float:
    """Annualised Sharpe ratio from daily returns."""
    if len(returns) < 2:
        return 0.0
    arr = np.array(returns)
    excess = arr - risk_free_rate / 252
    if np.std(excess) == 0:
        return 0.0
    return round(float(np.mean(excess) / np.std(excess) * np.sqrt(252)), 2)
