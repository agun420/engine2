"""Phase 1 — Social engagement velocity (free: Reddit JSON + StockTwits).

Replaces the paid X/Twitter SimClusters API with two completely free,
no-auth-required sources:

  • Reddit JSON API  — r/wallstreetbets, r/stocks, r/investing, r/options
                       (public read endpoint, no OAuth)
  • StockTwits       — public symbol stream
                       (https://api.stocktwits.com/api/2/streams/symbol/{sym}.json)

The "bridging" concept is preserved: we track engagement velocity across
multiple distinct communities (subreddits / StockTwits) and fire when the
narrative bridges from a single niche into multiple communities simultaneously.
"""
from __future__ import annotations

import datetime
import logging
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import requests

log = logging.getLogger(__name__)

_HEADERS = {"User-Agent": "engine2-scanner/1.0 (research-only; contact: github.com/agun420/engine2)"}
_REDDIT_SEARCH = "https://www.reddit.com/r/{sub}/search.json"
_STOCKTWITS_URL = "https://api.stocktwits.com/api/2/streams/symbol/{sym}.json"

# The "community clusters" we monitor (analogous to SimClusters)
_REDDIT_SUBS = ["wallstreetbets", "stocks", "investing", "options", "shortsqueeze"]


@dataclass
class ClusterSignal:
    symbol: str
    cluster_tag: str
    tweet_count: int
    velocity: float
    prev_velocity: float
    velocity_delta: float
    bridging_score: float   # fraction of communities mentioning the ticker


@dataclass
class SimClustersMonitor:
    """
    Polls Reddit and StockTwits for a list of tickers, computing engagement
    velocity and acceleration across multiple community "clusters."
    """
    symbols: List[str]
    window_minutes: int = 5
    min_velocity_delta: float = 2.0

    _history: Dict[str, deque] = field(default_factory=lambda: defaultdict(lambda: deque(maxlen=2)))

    def poll(self) -> List[ClusterSignal]:
        signals = []
        for sym in self.symbols:
            sig = self._poll_symbol(sym)
            if sig:
                signals.append(sig)
        return signals

    def _poll_symbol(self, symbol: str) -> Optional[ClusterSignal]:
        community_counts: Dict[str, int] = {}
        total_posts = 0

        # ── Reddit clusters ────────────────────────────────────────────
        for sub in _REDDIT_SUBS:
            count = self._reddit_count(symbol, sub)
            if count > 0:
                community_counts[f"r/{sub}"] = count
                total_posts += count
            time.sleep(0.15)   # gentle rate limiting

        # ── StockTwits cluster ─────────────────────────────────────────
        st_count = self._stocktwits_count(symbol)
        if st_count > 0:
            community_counts["stocktwits"] = st_count
            total_posts += st_count

        if total_posts == 0:
            return None

        all_communities = len(_REDDIT_SUBS) + 1  # subs + stocktwits
        velocity = total_posts / max(self.window_minutes, 1)
        hist = self._history[symbol]
        prev_velocity = hist[-1] if hist else 0.0
        hist.append(velocity)
        velocity_delta = velocity - prev_velocity
        bridging_score = round(len(community_counts) / all_communities, 3)
        top_community = max(community_counts, key=community_counts.get) if community_counts else ""

        return ClusterSignal(
            symbol=symbol,
            cluster_tag=top_community,
            tweet_count=total_posts,
            velocity=round(velocity, 2),
            prev_velocity=round(prev_velocity, 2),
            velocity_delta=round(velocity_delta, 2),
            bridging_score=bridging_score,
        )

    def _reddit_count(self, symbol: str, subreddit: str) -> int:
        """Count Reddit posts mentioning $SYMBOL or SYMBOL in the last hour."""
        try:
            resp = requests.get(
                _REDDIT_SEARCH.format(sub=subreddit),
                headers=_HEADERS,
                params={
                    "q": f"${symbol} OR \"{symbol}\"",
                    "sort": "new",
                    "limit": 25,
                    "t": "hour",
                    "restrict_sr": "on",
                },
                timeout=10,
            )
            if resp.status_code == 429:
                log.debug("Reddit rate limit on r/%s — skipping", subreddit)
                return 0
            resp.raise_for_status()
            data = resp.json()
            posts = data.get("data", {}).get("children", [])
            # Filter to posts within window_minutes
            cutoff = time.time() - self.window_minutes * 60
            recent = [p for p in posts if p.get("data", {}).get("created_utc", 0) >= cutoff]
            return len(recent)
        except Exception as exc:  # noqa: BLE001
            log.debug("Reddit r/%s error for %s: %s", subreddit, symbol, exc)
            return 0

    def _stocktwits_count(self, symbol: str) -> int:
        """Count recent StockTwits messages for a symbol (public, no auth)."""
        try:
            resp = requests.get(
                _STOCKTWITS_URL.format(sym=symbol),
                headers=_HEADERS,
                timeout=10,
            )
            if resp.status_code == 429:
                log.debug("StockTwits rate limit for %s", symbol)
                return 0
            resp.raise_for_status()
            messages = resp.json().get("messages", [])
            # StockTwits returns last 30 messages; count those within window
            cutoff = datetime.datetime.utcnow() - datetime.timedelta(minutes=self.window_minutes)
            recent = []
            for m in messages:
                created = m.get("created_at", "")
                try:
                    ts = datetime.datetime.strptime(created, "%Y-%m-%dT%H:%M:%SZ")
                    if ts >= cutoff:
                        recent.append(m)
                except ValueError:
                    pass
            return len(recent)
        except Exception as exc:  # noqa: BLE001
            log.debug("StockTwits error for %s: %s", symbol, exc)
            return 0

    def is_bridging(self, symbol: str) -> bool:
        hist = self._history.get(symbol)
        if not hist or len(hist) < 2:
            return False
        return (hist[-1] - hist[-2]) >= self.min_velocity_delta

    def get_stocktwits_sentiment(self, symbol: str) -> Optional[float]:
        """
        Return bullish ratio (0-1) from StockTwits sentiment labels.
        None if insufficient data.
        """
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
            if total == 0:
                return None
            return round(bullish / total, 3)
        except Exception as exc:  # noqa: BLE001
            log.debug("StockTwits sentiment error for %s: %s", symbol, exc)
            return None
