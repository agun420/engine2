from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, List

import pandas as pd
import requests

try:
    import yfinance as yf
except Exception:  # Keeps tests/release validation usable before pip install.
    yf = None

ALPACA_DATA_URL = "https://data.alpaca.markets/v2/stocks"


def _normalize(df: pd.DataFrame) -> Optional[pd.DataFrame]:
    if df is None or df.empty:
        return None
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]
    rename = {"o": "Open", "h": "High", "l": "Low", "c": "Close", "v": "Volume", "t": "Datetime"}
    df = df.rename(columns=rename)
    needed = ["Open", "High", "Low", "Close", "Volume"]
    if not all(c in df.columns for c in needed):
        return None
    df = df[needed].dropna()
    return df if not df.empty else None


def _alpaca_headers() -> Optional[dict]:
    key = os.getenv("ALPACA_API_KEY")
    secret = os.getenv("ALPACA_SECRET_KEY")
    if not key or not secret:
        return None
    return {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}


def _alpaca_bars(symbol: str, timeframe: str, start: datetime, end: datetime, limit: int = 1000) -> Optional[pd.DataFrame]:
    headers = _alpaca_headers()
    if not headers:
        return None
    params = {
        "timeframe": timeframe,
        "start": start.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "end": end.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "adjustment": "raw",
        "feed": "iex",
        "limit": limit,
    }
    try:
        response = requests.get(f"{ALPACA_DATA_URL}/{symbol}/bars", headers=headers, params=params, timeout=20)
        response.raise_for_status()
        bars = response.json().get("bars", [])
        if not bars:
            return None
        df = pd.DataFrame(bars)
        if "t" in df.columns:
            df.index = pd.to_datetime(df["t"], utc=True)
        return _normalize(df)
    except Exception:
        return None



def fetch_wide_intraday_batch(symbols: List[str], period: str = "1d", interval: str = "5m") -> Dict[str, pd.DataFrame]:
    """Lightweight wide scan fetch.

    Uses one yfinance batch request for many symbols, then returns normalized
    per-symbol intraday frames. This is intentionally used only for ranking the
    universe. The full deep scan still validates each finalist with intraday and
    daily data before any alert or paper order can happen.
    """
    output: Dict[str, pd.DataFrame] = {}
    clean_symbols = [s for s in symbols if s]
    if yf is None or not clean_symbols:
        return output
    try:
        raw = yf.download(
            " ".join(clean_symbols),
            period=period,
            interval=interval,
            progress=False,
            auto_adjust=False,
            threads=True,
            group_by="ticker",
        )
        if raw is None or raw.empty:
            return output
        if isinstance(raw.columns, pd.MultiIndex):
            top_level = list(dict.fromkeys(raw.columns.get_level_values(0)))
            for symbol in clean_symbols:
                if symbol in top_level:
                    df = _normalize(raw[symbol].copy())
                    if df is not None and len(df) >= 5:
                        output[symbol] = df
        else:
            # Single-symbol fallback
            df = _normalize(raw.copy())
            if df is not None and len(df) >= 5 and len(clean_symbols) == 1:
                output[clean_symbols[0]] = df
    except Exception:
        return output
    return output


def wide_scan_rank(df: pd.DataFrame) -> float:
    """Cheap opportunity score used only to choose deep-scan finalists."""
    try:
        if df is None or df.empty or len(df) < 5:
            return -999.0
        close = df["Close"].astype(float)
        vol = df["Volume"].astype(float)
        last = float(close.iloc[-1])
        first = float(close.iloc[0])
        prev = float(close.iloc[-4]) if len(close) >= 4 else first
        if first <= 0 or prev <= 0 or last <= 0:
            return -999.0
        day_move = ((last / first) - 1.0) * 100.0
        short_momentum = ((last / prev) - 1.0) * 100.0
        avg_vol = max(float(vol.tail(20).mean()), 1.0)
        rel_vol = float(vol.tail(3).mean()) / avg_vol
        dollar_vol = float((close.tail(12) * vol.tail(12)).sum())
        liquidity_bonus = min(12.0, dollar_vol / 2_000_000.0)
        rank = day_move * 2.2 + short_momentum * 3.0 + min(rel_vol, 5.0) * 4.0 + liquidity_bonus
        # Penalize extreme extension so the deep scan has cleaner candidates.
        if day_move > 18:
            rank -= (day_move - 18) * 0.8
        return round(rank, 4)
    except Exception:
        return -999.0

def data_age_minutes(df: pd.DataFrame) -> Optional[float]:
    """Best-effort age check. Yahoo timestamps can be timezone-naive."""
    try:
        idx = df.index[-1]
        ts = idx.to_pydatetime() if hasattr(idx, "to_pydatetime") else idx
        if ts.tzinfo is None:
            # Treat naive timestamp as UTC only for a conservative freshness warning.
            ts = ts.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - ts.astimezone(timezone.utc)).total_seconds() / 60)
    except Exception:
        return None


def data_source_name() -> str:
    if _alpaca_headers():
        return "Alpaca IEX optional adapter with Yahoo fallback"
    if yf is None:
        return "No data adapter available until requirements are installed"
    return "Yahoo Finance / yfinance"


def fetch_intraday(symbol: str, period: str = "1d", interval: str = "5m") -> Optional[pd.DataFrame]:
    """Fetch intraday bars.

    Uses Alpaca IEX when paper keys exist, otherwise yfinance for zero-friction setup.
    Alpaca requests are delayed 16+ minutes to stay compatible with free IEX data.
    """
    end = datetime.now(timezone.utc) - timedelta(minutes=16)
    start = end - timedelta(days=2)
    alpaca = _alpaca_bars(symbol, "5Min", start, end, limit=1000)
    if alpaca is not None and len(alpaca) >= 25:
        return alpaca

    if yf is None:
        return None
    try:
        df = yf.download(symbol, period=period, interval=interval, progress=False, auto_adjust=False, threads=False)
        df = _normalize(df)
        return df if df is not None and len(df) >= 25 else None
    except Exception:
        return None


def fetch_daily(symbol: str, period: str = "3mo") -> Optional[pd.DataFrame]:
    end = datetime.now(timezone.utc) - timedelta(minutes=16)
    start = end - timedelta(days=120)
    alpaca = _alpaca_bars(symbol, "1Day", start, end, limit=250)
    if alpaca is not None and len(alpaca) >= 30:
        return alpaca

    if yf is None:
        return None
    try:
        df = yf.download(symbol, period=period, interval="1d", progress=False, auto_adjust=False, threads=False)
        df = _normalize(df)
        return df if df is not None and len(df) >= 30 else None
    except Exception:
        return None


def estimated_spread_pct(intraday: pd.DataFrame) -> float:
    """Estimate tradability when bid/ask is unavailable.

    Uses latest 5m high-low range as a rough proxy. This is conservative and shown
    as an estimate, not true NBBO spread.
    """
    try:
        latest = intraday.iloc[-1]
        close = float(latest["Close"])
        if close <= 0:
            return 99.0
        return round(((float(latest["High"]) - float(latest["Low"])) / close) * 100, 3)
    except Exception:
        return 99.0
