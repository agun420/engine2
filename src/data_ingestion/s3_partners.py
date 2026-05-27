"""Phase 1 — S3 Partners short-squeeze divergence loophole.

The scanner triggers only when a stock's Squeeze Risk Score mathematically
exceeds its Crowded Score.  This divergence indicates momentum has reversed
and shorts are taking ~5 %+ mark-to-market losses, making forced liquidations
probable.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Optional

import requests

log = logging.getLogger(__name__)

_S3_API_KEY = os.getenv("S3_PARTNERS_API_KEY", "")
_S3_BASE = "https://api.s3partners.com/v1"  # placeholder endpoint


@dataclass
class S3ShortData:
    symbol: str
    short_interest_pct: float  # % of float short
    squeeze_risk_score: float  # 0-100: momentum-reversal risk
    crowded_score: float       # 0-100: how crowded the short trade is
    days_to_cover: float
    borrow_rate_pct: float

    @property
    def divergence(self) -> float:
        """Squeeze Risk − Crowded Score.  Positive → squeeze loophole active."""
        return round(self.squeeze_risk_score - self.crowded_score, 2)

    @property
    def loophole_active(self) -> bool:
        return self.squeeze_risk_score > self.crowded_score


def squeeze_divergence_triggered(data: S3ShortData, min_divergence: float = 0.0) -> bool:
    """Return True when the squeeze loophole condition is met."""
    return data.loophole_active and data.divergence >= min_divergence


def fetch_s3_short_data(symbol: str) -> Optional[S3ShortData]:
    """
    Fetch live short-interest metrics from S3 Partners API.

    Requires ``S3_PARTNERS_API_KEY`` env var.  Returns None on any error so
    the scanner degrades gracefully when S3 data is unavailable.
    """
    if not _S3_API_KEY:
        log.debug("S3_PARTNERS_API_KEY not set — skipping S3 fetch for %s", symbol)
        return None
    try:
        resp = requests.get(
            f"{_S3_BASE}/short-interest/{symbol}",
            headers={"Authorization": f"Bearer {_S3_API_KEY}"},
            timeout=8,
        )
        resp.raise_for_status()
        d = resp.json()
        return S3ShortData(
            symbol=symbol,
            short_interest_pct=float(d.get("short_interest_pct", 0)),
            squeeze_risk_score=float(d.get("squeeze_risk_score", 0)),
            crowded_score=float(d.get("crowded_score", 0)),
            days_to_cover=float(d.get("days_to_cover", 0)),
            borrow_rate_pct=float(d.get("borrow_rate_pct", 0)),
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("S3 Partners fetch failed for %s: %s", symbol, exc)
        return None


def enrich_signal_with_s3(signal: dict, min_divergence: float = 0.0) -> dict:
    """
    Attach S3 short-squeeze data to an existing signal dict.
    Adds keys: s3_squeeze_risk, s3_crowded_score, s3_divergence,
    s3_loophole_active, s3_days_to_cover, s3_borrow_rate_pct.
    """
    sym = signal.get("symbol", "")
    data = fetch_s3_short_data(sym)
    if data is None:
        return signal
    signal["s3_squeeze_risk"] = data.squeeze_risk_score
    signal["s3_crowded_score"] = data.crowded_score
    signal["s3_divergence"] = data.divergence
    signal["s3_loophole_active"] = squeeze_divergence_triggered(data, min_divergence)
    signal["s3_days_to_cover"] = data.days_to_cover
    signal["s3_borrow_rate_pct"] = data.borrow_rate_pct
    return signal
