"""Phase 2 — Sentiment Volume Change (SVC) with non-negative scaling.

SVC = shift_in_sentiment × total_comment_volume

Non-negative scaling: f(x) = max(0, x + C)
Maps heavy negative sentiment to zero allocation, protecting against
long positions during market crashes or narrative collapses.
"""
from __future__ import annotations

from typing import Optional


def sentiment_volume_change(
    prev_sentiment: float,
    curr_sentiment: float,
    comment_volume: int,
) -> float:
    """
    Compute the Sentiment Volume Change signal.

    Args:
        prev_sentiment: Aggregated sentiment in the prior period (-1 to +1).
        curr_sentiment: Aggregated sentiment in the current period (-1 to +1).
        comment_volume: Total post/comment count in current period.

    Returns:
        SVC score (unbounded; sign indicates direction).
    """
    sentiment_shift = curr_sentiment - prev_sentiment
    return round(sentiment_shift * comment_volume, 4)


def non_negative_scale(x: float, C: float = 0.0) -> float:
    """
    Non-negative scaling function: f(x) = max(0, x + C).

    ``C`` is an additive bias term.  At C=0 any negative SVC maps to 0,
    completely blocking long allocation during bearish sentiment regimes.
    """
    return max(0.0, x + C)


def svc_allocation_score(
    prev_sentiment: float,
    curr_sentiment: float,
    comment_volume: int,
    bias_C: float = 0.0,
    normalise_by: Optional[float] = None,
) -> float:
    """
    Full SVC pipeline: compute → non-negative scale → optional normalise.

    ``normalise_by`` can be a baseline volume to express the score as a
    multiple of typical activity.
    """
    raw = sentiment_volume_change(prev_sentiment, curr_sentiment, comment_volume)
    scaled = non_negative_scale(raw, bias_C)
    if normalise_by and normalise_by > 0:
        scaled = round(scaled / normalise_by, 6)
    return round(scaled, 6)
