"""Phase 1 — Social sentiment composite (free: Reddit + StockTwits + Fear & Greed).

Replaces the paid LunarCrush API with a zero-auth composite score built from:

  • Reddit JSON API      — mention counts + upvote-weighted sentiment
                           across r/wallstreetbets, r/stocks, r/investing
  • StockTwits           — Bullish/Bearish ratio from labelled messages
  • CNN Fear & Greed     — macro sentiment overlay
                           (https://api.alternative.me/fng/ — completely free)

Output mirrors the LunarCrushMetrics dataclass so the rest of the pipeline
is unchanged: galaxy_score, sentiment, social_volume, etc.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Dict, List, Optional

import requests

log = logging.getLogger(__name__)

_HEADERS = {"User-Agent": "engine2-scanner/1.0 (research-only; github.com/agun420/engine2)"}
_REDDIT_SEARCH = "https://www.reddit.com/r/{sub}/search.json"
_STOCKTWITS_URL = "https://api.stocktwits.com/api/2/streams/symbol/{sym}.json"
_FEAR_GREED_URL = "https://api.alternative.me/fng/?limit=1"

_SUBS = ["wallstreetbets", "stocks", "investing"]


@dataclass
class LunarCrushMetrics:
    symbol: str
    galaxy_score: float          # 0-100 composite social health proxy
    alt_rank: int                # 1-999: lower = stronger momentum
    social_volume: int           # total mentions last 24 h
    social_score: float          # weighted engagement score
    sentiment: float             # -1 (bearish) to +1 (bullish)
    social_contributors: int     # unique sources/accounts
    news_sentiment: float        # macro Fear & Greed mapped to -1..+1
    price_correlation: float     # placeholder (requires price data)


def _fetch_fear_greed() -> Optional[float]:
    """Return Fear & Greed index 0-100 (higher = greedier)."""
    try:
        resp = requests.get(_FEAR_GREED_URL, headers=_HEADERS, timeout=8)
        resp.raise_for_status()
        value = int(resp.json()["data"][0]["value"])
        return float(value)
    except Exception as exc:  # noqa: BLE001
        log.debug("Fear & Greed fetch failed: %s", exc)
        return None


def _reddit_metrics(symbol: str) -> Dict:
    """Return {total_posts, upvote_sentiment} from Reddit across tracked subs."""
    total_posts = 0
    weighted_sentiment = 0.0
    weight_total = 0.0

    for sub in _SUBS:
        try:
            resp = requests.get(
                _REDDIT_SEARCH.format(sub=sub),
                headers=_HEADERS,
                params={
                    "q": f"${symbol} OR \"{symbol}\"",
                    "sort": "top",
                    "limit": 25,
                    "t": "day",
                    "restrict_sr": "on",
                },
                timeout=10,
            )
            if resp.status_code == 429:
                time.sleep(2)
                continue
            resp.raise_for_status()
            posts = resp.json().get("data", {}).get("children", [])
            for p in posts:
                d = p.get("data", {})
                score = max(int(d.get("score", 0)), 1)
                # Use upvote_ratio as a sentiment proxy (> 0.5 = net positive)
                upvote_ratio = float(d.get("upvote_ratio", 0.5))
                sentiment_contribution = (upvote_ratio - 0.5) * 2  # -1..+1
                weighted_sentiment += sentiment_contribution * score
                weight_total += score
                total_posts += 1
            time.sleep(0.2)
        except Exception as exc:  # noqa: BLE001
            log.debug("Reddit r/%s error for %s: %s", sub, symbol, exc)

    avg_sentiment = (weighted_sentiment / weight_total) if weight_total > 0 else 0.0
    return {"total_posts": total_posts, "reddit_sentiment": round(avg_sentiment, 4)}


def _stocktwits_metrics(symbol: str) -> Dict:
    """Return {bullish_ratio, message_count} from StockTwits."""
    try:
        resp = requests.get(
            _STOCKTWITS_URL.format(sym=symbol),
            headers=_HEADERS,
            timeout=10,
        )
        resp.raise_for_status()
        messages = resp.json().get("messages", [])
        bullish = sum(
            1 for m in messages
            if (m.get("entities", {}).get("sentiment") or {}).get("basic") == "Bullish"
        )
        bearish = sum(
            1 for m in messages
            if (m.get("entities", {}).get("sentiment") or {}).get("basic") == "Bearish"
        )
        total = bullish + bearish
        ratio = (bullish - bearish) / total if total > 0 else 0.0  # -1..+1
        return {"st_sentiment": round(ratio, 4), "st_count": len(messages)}
    except Exception as exc:  # noqa: BLE001
        log.debug("StockTwits error for %s: %s", symbol, exc)
        return {"st_sentiment": 0.0, "st_count": 0}


def _compute_galaxy_score(
    social_volume: int,
    sentiment: float,
    fear_greed: Optional[float],
) -> float:
    """
    Synthesise a 0-100 galaxy score (social health proxy).

    Components:
      • volume_score (0-40): logarithmic scale of mention count
      • sentiment_score (0-40): how bullish the community is
      • macro_score (0-20): Fear & Greed alignment
    """
    import math
    vol_score = min(math.log10(max(social_volume, 1)) * 10.0, 40.0)
    sent_score = (sentiment + 1) / 2 * 40.0   # -1..+1 → 0..40
    macro_score = ((fear_greed or 50.0) / 100.0) * 20.0
    return round(vol_score + sent_score + macro_score, 2)


def _compute_alt_rank(social_volume: int, sentiment: float) -> int:
    """
    Lower alt_rank = stronger momentum.
    Map composite score to 1-999.
    """
    composite = social_volume * max(0.0, sentiment + 1)
    # Rank 1-999: higher composite → lower rank
    rank = max(1, min(999, int(1000 - composite * 0.5)))
    return rank


class LunarCrushFeed:
    """
    Free LunarCrush replacement: builds social metrics from Reddit,
    StockTwits, and the CNN Fear & Greed Index.

    No API key required.
    """

    def __init__(self, symbols: List[str]) -> None:
        self.symbols = [s.upper() for s in symbols]
        self._cache: Dict[str, LunarCrushMetrics] = {}
        self._fear_greed: Optional[float] = None

    def fetch_all(self) -> Dict[str, LunarCrushMetrics]:
        # Fetch macro sentiment once per batch
        self._fear_greed = _fetch_fear_greed()
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
        reddit = _reddit_metrics(symbol)
        st = _stocktwits_metrics(symbol)

        total_volume = reddit["total_posts"] + st["st_count"]
        if total_volume == 0:
            return None

        # Blend Reddit (weight 0.6) and StockTwits (weight 0.4)
        r_sent = reddit["reddit_sentiment"]
        s_sent = st["st_sentiment"]
        blended = round(r_sent * 0.6 + s_sent * 0.4, 4)

        # Map Fear & Greed 0-100 → -1..+1 as "news sentiment"
        fg = self._fear_greed
        news_sent = round(((fg or 50.0) - 50.0) / 50.0, 4) if fg is not None else 0.0

        galaxy = _compute_galaxy_score(total_volume, blended, fg)
        alt_rank = _compute_alt_rank(total_volume, blended)

        return LunarCrushMetrics(
            symbol=symbol,
            galaxy_score=galaxy,
            alt_rank=alt_rank,
            social_volume=total_volume,
            social_score=round(galaxy * total_volume / 100.0, 2),
            sentiment=blended,
            social_contributors=reddit["total_posts"] + (1 if st["st_count"] > 0 else 0),
            news_sentiment=news_sent,
            price_correlation=0.0,  # requires price data — computed in scanner
        )

    def enrich_signal(self, signal: dict) -> dict:
        m = self.get(signal.get("symbol", ""))
        if m is None:
            return signal
        signal["lc_galaxy_score"] = m.galaxy_score
        signal["lc_alt_rank"] = m.alt_rank
        signal["lc_social_volume"] = m.social_volume
        signal["lc_sentiment"] = m.sentiment
        signal["lc_news_sentiment"] = m.news_sentiment
        signal["lc_price_correlation"] = m.price_correlation
        signal["fear_greed_index"] = self._fear_greed
        return signal
