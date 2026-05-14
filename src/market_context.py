from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Dict, Optional, Tuple

import pandas as pd

from .data import fetch_daily, fetch_intraday

SECTOR_ETF = {
    # Mega-cap tech / semis / software
    "AAPL": "XLK", "MSFT": "XLK", "NVDA": "SMH", "AMD": "SMH", "AVGO": "SMH",
    "MRVL": "SMH", "TSM": "SMH", "ASML": "SMH", "ARM": "SMH", "MU": "SMH", "INTC": "SMH",
    "META": "XLC", "GOOGL": "XLC", "NFLX": "XLC", "WBD": "XLC",
    "AMZN": "XLY", "TSLA": "XLY", "RIVN": "XLY", "LCID": "XLY", "NIO": "KWEB", "LI": "KWEB",
    "BABA": "KWEB", "JD": "KWEB",
    "COIN": "BITQ", "MARA": "BITQ", "RIOT": "BITQ",
    "PANW": "CIBR", "CRWD": "CIBR", "NET": "CIBR", "SNOW": "IGV", "SHOP": "IGV",
    "SOFI": "XLF", "HOOD": "XLF", "UPST": "XLF",
    "UBER": "IYT", "CCL": "PEJ", "DKNG": "PEJ", "RBLX": "XLC", "ROKU": "XLC",
    "SMCI": "SMH", "HPE": "XLK", "DELL": "XLK", "ANET": "XLK", "PLTR": "IGV",
    "CELH": "XLP", "CVNA": "XLY", "PATH": "IGV", "IONQ": "QTUM", "QBTS": "QTUM",
}

BENCHMARKS = ["SPY", "QQQ", "IWM"]


@dataclass
class ContextSnapshot:
    spy_change_pct: Optional[float]
    qqq_change_pct: Optional[float]
    iwm_change_pct: Optional[float]
    market_regime: str
    risk_note: str
    etf_changes: Dict[str, float]

    def to_dict(self) -> Dict:
        return asdict(self)


def _day_change(df: Optional[pd.DataFrame]) -> Optional[float]:
    if df is None or df.empty:
        return None
    try:
        first = float(df.iloc[0]["Open"])
        last = float(df.iloc[-1]["Close"])
        if first <= 0:
            return None
        return round((last / first - 1) * 100, 2)
    except Exception:
        return None


def _market_regime(spy: Optional[float], qqq: Optional[float], iwm: Optional[float]) -> Tuple[str, str]:
    values = [x for x in [spy, qqq, iwm] if x is not None]
    if not values:
        return "UNKNOWN", "Market context unavailable. Keep signals conservative."
    avg = sum(values) / len(values)
    if avg >= 0.65 and min(values) > -0.2:
        return "RISK-ON", "Broad market is supportive. Momentum setups get a small tailwind."
    if avg <= -0.65 or min(values) <= -1.0:
        return "RISK-OFF", "Broad market is weak. Require stronger confirmation and smaller risk."
    if max(values) - min(values) >= 1.0:
        return "MIXED / ROTATION", "Market is split by theme. Favor leaders only; avoid weak sectors."
    return "NEUTRAL", "Market is balanced. Use normal confirmation rules."


def build_market_context() -> ContextSnapshot:
    changes: Dict[str, float] = {}
    for ticker in set(BENCHMARKS + list(set(SECTOR_ETF.values()))):
        df = fetch_intraday(ticker)
        change = _day_change(df)
        if change is not None:
            changes[ticker] = change
    spy = changes.get("SPY")
    qqq = changes.get("QQQ")
    iwm = changes.get("IWM")
    regime, note = _market_regime(spy, qqq, iwm)
    return ContextSnapshot(spy, qqq, iwm, regime, note, changes)


def symbol_sector_context(symbol: str, context: ContextSnapshot) -> Dict:
    etf = SECTOR_ETF.get(symbol, "SPY")
    etf_change = context.etf_changes.get(etf)
    spy_change = context.etf_changes.get("SPY")
    rel = None
    if etf_change is not None and spy_change is not None:
        rel = round(etf_change - spy_change, 2)
    return {
        "sector_etf": etf,
        "sector_change_pct": etf_change,
        "sector_vs_spy_pct": rel,
        "market_regime": context.market_regime,
    }


def sector_boost(sector_ctx: Dict) -> Tuple[int, list[str]]:
    reasons: list[str] = []
    boost = 0
    rel = sector_ctx.get("sector_vs_spy_pct")
    sector_change = sector_ctx.get("sector_change_pct")
    regime = sector_ctx.get("market_regime")
    if sector_change is not None and sector_change > 0.5:
        boost += 5
        reasons.append("Sector/theme is positive")
    if rel is not None and rel > 0.35:
        boost += 5
        reasons.append("Sector is leading SPY")
    if regime == "RISK-ON":
        boost += 4
        reasons.append("Market regime is risk-on")
    if regime == "RISK-OFF":
        boost -= 8
        reasons.append("Market regime is risk-off")
    return boost, reasons
