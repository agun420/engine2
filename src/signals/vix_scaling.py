"""Phase 2 / Top Tips — Sentiment-VIX dynamic scaling.

Dynamically scale sentiment scores by the inverse of the VIX.
When volatility spikes (crash / bear regime), this automatically reduces
market exposure without any manual regime-switching logic.

Scale factor = base_sentiment × (reference_vix / current_vix)

At VIX = 15 (calm), scale ≈ 1×.
At VIX = 30 (fear), scale ≈ 0.5×.
At VIX = 60 (crisis), scale ≈ 0.25×.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

import requests

log = logging.getLogger(__name__)

_ALPACA_KEY = os.getenv("ALPACA_API_KEY", "")
_ALPACA_SECRET = os.getenv("ALPACA_SECRET_KEY", "")
_REFERENCE_VIX = 15.0   # calm-market baseline


def fetch_current_vix() -> Optional[float]:
    """
    Pull the latest VIX close from Alpaca (falls back to yfinance).

    Returns None if data is unavailable so callers can degrade gracefully.
    """
    vix = _vix_from_alpaca()
    if vix is not None:
        return vix
    return _vix_from_yfinance()


def _vix_from_alpaca() -> Optional[float]:
    if not (_ALPACA_KEY and _ALPACA_SECRET):
        return None
    try:
        import datetime
        end = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        start = (datetime.datetime.utcnow() - datetime.timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
        resp = requests.get(
            "https://data.alpaca.markets/v2/stocks/VIX/bars",
            headers={"APCA-API-KEY-ID": _ALPACA_KEY, "APCA-API-SECRET-KEY": _ALPACA_SECRET},
            params={"timeframe": "1Day", "start": start, "end": end, "limit": 3},
            timeout=8,
        )
        resp.raise_for_status()
        bars = resp.json().get("bars", [])
        if bars:
            return float(bars[-1]["c"])
    except Exception as exc:  # noqa: BLE001
        log.debug("Alpaca VIX fetch failed: %s", exc)
    return None


def _vix_from_yfinance() -> Optional[float]:
    try:
        import yfinance as yf  # type: ignore
        t = yf.Ticker("^VIX")
        hist = t.history(period="2d")
        if not hist.empty:
            return float(hist["Close"].iloc[-1])
    except Exception as exc:  # noqa: BLE001
        log.debug("yfinance VIX fetch failed: %s", exc)
    return None


def vix_sentiment_scale(
    sentiment: float,
    current_vix: Optional[float] = None,
    reference_vix: float = _REFERENCE_VIX,
) -> float:
    """
    Return VIX-scaled sentiment.

    If ``current_vix`` is not provided, fetches it automatically.
    Returns 0.0 if VIX data is unavailable (safe default: no position).
    """
    vix = current_vix if current_vix is not None else fetch_current_vix()
    if vix is None or vix <= 0:
        log.warning("VIX unavailable — returning zero sentiment to suppress positions")
        return 0.0
    scale = reference_vix / vix
    return round(sentiment * scale, 6)


def vix_regime(current_vix: Optional[float] = None) -> str:
    """Human-readable regime label based on VIX level."""
    vix = current_vix if current_vix is not None else fetch_current_vix()
    if vix is None:
        return "UNKNOWN"
    if vix < 15:
        return "LOW_VOL_BULL"
    if vix < 20:
        return "NORMAL"
    if vix < 30:
        return "ELEVATED"
    if vix < 40:
        return "HIGH_FEAR"
    return "CRISIS"
