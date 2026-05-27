"""Phase 1 — Short-squeeze divergence (free: yfinance + FINRA REGSHO).

Replaces the paid S3 Partners API with a fully free implementation:

  • yfinance Ticker.info  → shortPercentOfFloat, shortRatio, sharesShort,
                            sharesShortPriorMonth
  • FINRA REGSHO daily    → short sale volume as a borrow-pressure proxy
                            (https://regsho.finra.org — public, no key)

Squeeze Risk Score  = f(short_pct, days_to_cover, price_momentum)
Crowded Score       = f(short_pct, short_pct_change_vs_prior_month)

The loophole fires when Squeeze Risk > Crowded Score, meaning momentum has
turned against short sellers while the position is still heavily crowded.
"""
from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass
from typing import Optional

import requests

log = logging.getLogger(__name__)

_FINRA_REGSHO = "https://regsho.finra.org/CNMSshvol{date}.txt"
_HEADERS = {"User-Agent": "engine2-scanner/1.0 research-only"}


@dataclass
class S3ShortData:
    symbol: str
    short_interest_pct: float   # % of float short
    squeeze_risk_score: float   # 0-100
    crowded_score: float        # 0-100
    days_to_cover: float
    borrow_rate_pct: float      # estimated proxy

    @property
    def divergence(self) -> float:
        return round(self.squeeze_risk_score - self.crowded_score, 2)

    @property
    def loophole_active(self) -> bool:
        return self.squeeze_risk_score > self.crowded_score


def squeeze_divergence_triggered(data: S3ShortData, min_divergence: float = 0.0) -> bool:
    return data.loophole_active and data.divergence >= min_divergence


# ── yfinance short data ──────────────────────────────────────────────────────

def _yf_short_data(symbol: str) -> dict:
    """Pull short-interest fields from yfinance (free, no API key)."""
    try:
        import yfinance as yf  # type: ignore
        info = yf.Ticker(symbol).info
        return {
            "short_pct_float": float(info.get("shortPercentOfFloat") or 0),
            "short_ratio":     float(info.get("shortRatio") or 0),
            "shares_short":    int(info.get("sharesShort") or 0),
            "shares_short_prior": int(info.get("sharesShortPriorMonth") or 0),
            "float_shares":    int(info.get("floatShares") or 1),
        }
    except Exception as exc:  # noqa: BLE001
        log.debug("yfinance short data failed for %s: %s", symbol, exc)
        return {}


# ── FINRA REGSHO short volume ────────────────────────────────────────────────

def _finra_short_volume(symbol: str) -> Optional[float]:
    """
    Fetch today's (or most recent) FINRA REGSHO short sale volume ratio.
    Returns short_vol / total_vol (0-1) or None on failure.
    """
    for days_back in range(0, 5):
        date = (datetime.date.today() - datetime.timedelta(days=days_back)).strftime("%Y%m%d")
        url = _FINRA_REGSHO.format(date=date)
        try:
            resp = requests.get(url, headers=_HEADERS, timeout=8)
            if resp.status_code != 200:
                continue
            for line in resp.text.splitlines():
                parts = line.split("|")
                if len(parts) >= 5 and parts[1].upper() == symbol.upper():
                    short_vol = int(parts[2])
                    total_vol = int(parts[4]) or 1
                    return round(short_vol / total_vol, 4)
        except Exception as exc:  # noqa: BLE001
            log.debug("FINRA REGSHO parse error: %s", exc)
    return None


# ── Score computation ────────────────────────────────────────────────────────

def _compute_scores(
    short_pct: float,       # 0-1 (e.g. 0.25 = 25 % of float)
    days_to_cover: float,
    shares_short: int,
    shares_short_prior: int,
    finra_short_ratio: Optional[float],
    price_momentum: float,  # recent % change (positive = price rising vs shorts)
) -> tuple[float, float]:
    """
    Return (squeeze_risk_score, crowded_score) on 0-100 scale.

    Squeeze Risk Score captures momentum-reversal pressure on shorts:
      • High short % + high days_to_cover + rising price → shorts losing money
      • FINRA ratio: very high intraday short volume → short sellers active
        (paradoxically increases squeeze risk if price keeps rising)

    Crowded Score captures how crowded / consensus the short trade is:
      • High short % + recent increase in short interest → trade is crowded
    """
    s = short_pct * 100          # convert to percentage scale

    # ── Squeeze Risk ──────────────────────────────────────────────────────
    # Each component is normalised to ~0-30 contribution
    dtc_component = min(days_to_cover * 4.0, 30.0)       # 7.5 days → 30
    momentum_boost = max(0.0, price_momentum * 200.0)     # +5 % rise → +10 pts
    momentum_boost = min(momentum_boost, 30.0)
    short_pct_contrib = min(s * 0.8, 25.0)               # 31 % short → 25
    finra_bonus = 0.0
    if finra_short_ratio is not None:
        # > 60 % intraday short volume → aggressive short activity → squeeze risk
        finra_bonus = min((finra_short_ratio - 0.50) * 100, 15.0) if finra_short_ratio > 0.50 else 0.0
    squeeze_risk = short_pct_contrib + dtc_component + momentum_boost + finra_bonus

    # ── Crowded Score ─────────────────────────────────────────────────────
    short_change_pct = 0.0
    if shares_short_prior > 0:
        short_change_pct = (shares_short - shares_short_prior) / shares_short_prior * 100
    crowding_trend = min(max(short_change_pct * 0.5, 0.0), 20.0)  # +20 % MoM rise → 10 pts
    crowded = min(s * 1.2, 60.0) + crowding_trend                  # short % dominates

    return round(min(squeeze_risk, 100.0), 2), round(min(crowded, 100.0), 2)


# ── Public API ───────────────────────────────────────────────────────────────

def fetch_s3_short_data(symbol: str, price_momentum: float = 0.0) -> Optional[S3ShortData]:
    """
    Build squeeze/crowded scores from free data sources (yfinance + FINRA).

    ``price_momentum``: recent intraday % change (positive = price rising while
    shorts exist → increases squeeze risk).  Pass 0 if unavailable.
    """
    yf_data = _yf_short_data(symbol)
    if not yf_data:
        return None

    short_pct = yf_data.get("short_pct_float", 0.0)
    days_to_cover = yf_data.get("short_ratio", 0.0)
    shares_short = yf_data.get("shares_short", 0)
    shares_short_prior = yf_data.get("shares_short_prior", 0)

    finra_ratio = _finra_short_volume(symbol)

    squeeze_risk, crowded = _compute_scores(
        short_pct, days_to_cover, shares_short, shares_short_prior,
        finra_ratio, price_momentum
    )

    # Borrow rate proxy: very high short % + high FINRA ratio → estimated tight borrow
    borrow_est = round(short_pct * 100 * 0.25 + (finra_ratio or 0.5) * 5.0, 2)

    return S3ShortData(
        symbol=symbol,
        short_interest_pct=round(short_pct * 100, 2),
        squeeze_risk_score=squeeze_risk,
        crowded_score=crowded,
        days_to_cover=days_to_cover,
        borrow_rate_pct=borrow_est,
    )


def enrich_signal_with_s3(signal: dict, min_divergence: float = 0.0) -> dict:
    """Attach squeeze/crowded data to an existing signal dict."""
    sym = signal.get("symbol", "")
    momentum = float(signal.get("day_change_pct", 0.0)) / 100.0
    data = fetch_s3_short_data(sym, price_momentum=momentum)
    if data is None:
        return signal
    signal["s3_squeeze_risk"] = data.squeeze_risk_score
    signal["s3_crowded_score"] = data.crowded_score
    signal["s3_divergence"] = data.divergence
    signal["s3_loophole_active"] = squeeze_divergence_triggered(data, min_divergence)
    signal["s3_days_to_cover"] = data.days_to_cover
    signal["s3_borrow_rate_pct"] = data.borrow_rate_pct
    return signal
