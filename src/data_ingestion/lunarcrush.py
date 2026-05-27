"""Phase 1 — LunarCrush MCP social sentiment feed.

Uses the LunarCrush API (MCP-compatible) to pull live social sentiment,
galaxy scores, and alt-rank data directly into the signal pipeline — no
custom scrapers required.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Dict, List, Optional

import requests

log = logging.getLogger(__name__)

_LC_KEY = os.getenv("LUNARCRUSH_API_KEY", "")
_LC_BASE = "https://lunarcrush.com/api4/public"


@dataclass
class LunarCrushMetrics:
    symbol: str
    galaxy_score: float          # 0-100 overall social health
    alt_rank: int                # lower = stronger social momentum
    social_volume: int           # total social mentions in last 24 h
    social_score: float          # weighted engagement score
    sentiment: float             # -1 (bearish) to +1 (bullish)
    social_contributors: int     # unique accounts posting
    news_sentiment: float        # news-specific sentiment -1 to +1
    price_correlation: float     # rolling price/social correlation


class LunarCrushFeed:
    """
    Fetches live social metrics for a list of stock tickers via LunarCrush.

    Requires ``LUNARCRUSH_API_KEY`` environment variable.
    """

    def __init__(self, symbols: List[str]) -> None:
        self.symbols = [s.upper() for s in symbols]
        self._cache: Dict[str, LunarCrushMetrics] = {}

    def fetch_all(self) -> Dict[str, LunarCrushMetrics]:
        """Fetch metrics for all tracked symbols and update internal cache."""
        if not _LC_KEY:
            log.debug("LUNARCRUSH_API_KEY not set — skipping")
            return {}
        results: Dict[str, LunarCrushMetrics] = {}
        for sym in self.symbols:
            m = self._fetch_one(sym)
            if m:
                results[sym] = m
                self._cache[sym] = m
        return results

    def get(self, symbol: str) -> Optional[LunarCrushMetrics]:
        return self._cache.get(symbol.upper())

    def _fetch_one(self, symbol: str) -> Optional[LunarCrushMetrics]:
        try:
            resp = requests.get(
                f"{_LC_BASE}/coins/{symbol}/v1",
                headers={"Authorization": f"Bearer {_LC_KEY}"},
                timeout=10,
            )
            resp.raise_for_status()
            d = resp.json().get("data", {})
            return LunarCrushMetrics(
                symbol=symbol,
                galaxy_score=float(d.get("galaxy_score", 0)),
                alt_rank=int(d.get("alt_rank", 9999)),
                social_volume=int(d.get("social_volume", 0)),
                social_score=float(d.get("social_score", 0)),
                sentiment=float(d.get("sentiment", 0)),
                social_contributors=int(d.get("social_contributors", 0)),
                news_sentiment=float(d.get("news_sentiment", 0)),
                price_correlation=float(d.get("price_score", 0)),
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("LunarCrush fetch failed for %s: %s", symbol, exc)
            return None

    def enrich_signal(self, signal: dict) -> dict:
        """Attach LunarCrush fields to an existing signal dict."""
        m = self.get(signal.get("symbol", ""))
        if m is None:
            return signal
        signal["lc_galaxy_score"] = m.galaxy_score
        signal["lc_alt_rank"] = m.alt_rank
        signal["lc_social_volume"] = m.social_volume
        signal["lc_sentiment"] = m.sentiment
        signal["lc_news_sentiment"] = m.news_sentiment
        signal["lc_price_correlation"] = m.price_correlation
        return signal
