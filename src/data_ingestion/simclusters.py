"""Phase 1 — X (Twitter) SimClusters engagement-velocity front-running.

X's open-sourced recommendation algorithm groups users into ~145,000 hidden
"SimClusters."  By tracking engagement velocity within overlapping financial
clusters rather than the global feed, we can mathematically front-run retail
narratives as they bridge from a niche cluster into the mainstream algorithm.
"""
from __future__ import annotations

import logging
import os
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import requests

log = logging.getLogger(__name__)

_BEARER = os.getenv("TWITTER_BEARER_TOKEN", "")
_SEARCH_URL = "https://api.twitter.com/2/tweets/search/recent"
# Approximate SimCluster IDs for known finance communities (illustrative).
# In production these would be derived from the open-source SimClusters model.
_FINANCE_CLUSTER_QUERY_TAGS = [
    "wallstreetbets OR WSB",
    "stocktwits OR $",
    "options trading OR unusual options",
    "short squeeze OR shortinterest",
    "meme stock OR memestocks",
]


@dataclass
class ClusterSignal:
    symbol: str
    cluster_tag: str
    tweet_count: int        # total tweets in rolling window
    velocity: float         # tweets per minute in window
    prev_velocity: float    # velocity in the prior window
    velocity_delta: float   # acceleration (positive = narrative is accelerating)
    bridging_score: float   # 0-1: how many distinct clusters mention the ticker


@dataclass
class SimClustersMonitor:
    """
    Polls the Twitter v2 Search API for a list of tickers across financial
    SimCluster query tags, computing engagement velocity and acceleration.

    ``window_minutes`` sets the rolling window for velocity calculation.
    ``min_velocity_delta`` is the acceleration threshold to flag a bridging event.
    """

    symbols: List[str]
    window_minutes: int = 5
    min_velocity_delta: float = 2.0

    _history: Dict[str, deque] = field(default_factory=lambda: defaultdict(lambda: deque(maxlen=2)))

    def poll(self) -> List[ClusterSignal]:
        """Fetch engagement metrics for all tracked symbols."""
        if not _BEARER:
            log.debug("TWITTER_BEARER_TOKEN not set — SimClusters skipped")
            return []
        signals: List[ClusterSignal] = []
        for symbol in self.symbols:
            sig = self._poll_symbol(symbol)
            if sig:
                signals.append(sig)
        return signals

    def _poll_symbol(self, symbol: str) -> Optional[ClusterSignal]:
        cluster_counts: Dict[str, int] = {}
        total_tweets = 0
        for tag in _FINANCE_CLUSTER_QUERY_TAGS:
            query = f"${symbol} ({tag}) -is:retweet lang:en"
            count = self._count_tweets(query)
            if count:
                cluster_counts[tag] = count
                total_tweets += count

        if total_tweets == 0:
            return None

        velocity = total_tweets / self.window_minutes
        hist = self._history[symbol]
        prev_velocity = hist[-1] if hist else 0.0
        hist.append(velocity)
        velocity_delta = velocity - prev_velocity
        bridging_score = round(len(cluster_counts) / len(_FINANCE_CLUSTER_QUERY_TAGS), 3)
        top_cluster = max(cluster_counts, key=cluster_counts.get) if cluster_counts else ""

        return ClusterSignal(
            symbol=symbol,
            cluster_tag=top_cluster,
            tweet_count=total_tweets,
            velocity=round(velocity, 2),
            prev_velocity=round(prev_velocity, 2),
            velocity_delta=round(velocity_delta, 2),
            bridging_score=bridging_score,
        )

    def _count_tweets(self, query: str) -> int:
        try:
            resp = requests.get(
                _SEARCH_URL,
                headers={"Authorization": f"Bearer {_BEARER}"},
                params={
                    "query": query,
                    "max_results": 100,
                    "tweet.fields": "created_at",
                    "start_time": self._window_start_iso(),
                },
                timeout=10,
            )
            if resp.status_code == 429:
                log.warning("Twitter rate limit hit — sleeping 15 s")
                time.sleep(15)
                return 0
            resp.raise_for_status()
            meta = resp.json().get("meta", {})
            return int(meta.get("result_count", 0))
        except Exception as exc:  # noqa: BLE001
            log.debug("SimClusters query failed: %s", exc)
            return 0

    def _window_start_iso(self) -> str:
        import datetime
        dt = datetime.datetime.utcnow() - datetime.timedelta(minutes=self.window_minutes)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    def is_bridging(self, symbol: str) -> bool:
        """True when latest velocity acceleration exceeds threshold."""
        hist = self._history.get(symbol)
        if not hist or len(hist) < 2:
            return False
        delta = hist[-1] - hist[-2]
        return delta >= self.min_velocity_delta
