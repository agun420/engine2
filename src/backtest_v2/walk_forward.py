"""Phase 5 — Purged Walk-Forward Analysis with embargo periods.

Standard k-fold cross-validation is forbidden here because it destroys
temporal order and leaks future data into training.

Instead we use purged walk-forward:
  1. Expand or roll the training window forward in time.
  2. Insert an EMBARGO GAP between the end of training and the start of
     testing to prevent any label overlap (e.g. multi-day holding periods).
  3. Record out-of-sample equity curves for each fold.
  4. Aggregate fold Sharpes to get a bias-free performance estimate.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Tuple

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)


@dataclass
class WalkForwardFold:
    fold_id: int
    train_start: pd.Timestamp
    train_end: pd.Timestamp
    test_start: pd.Timestamp
    test_end: pd.Timestamp
    out_of_sample_returns: List[float] = field(default_factory=list)
    sharpe: float = 0.0
    n_trades: int = 0


@dataclass
class WalkForwardResult:
    folds: List[WalkForwardFold]
    combined_sharpe: float
    combined_returns: np.ndarray
    n_total_trades: int


def purged_walk_forward(
    df: pd.DataFrame,
    strategy_fn: Callable[[pd.DataFrame, pd.DataFrame], pd.Series],
    n_folds: int = 5,
    embargo_bars: int = 5,
    expanding: bool = True,
) -> WalkForwardResult:
    """
    Run purged walk-forward analysis.

    Args:
        df: Full historical DataFrame with DatetimeIndex.
        strategy_fn: fn(train_df, test_df) → pd.Series of daily returns.
        n_folds: Number of out-of-sample folds.
        embargo_bars: Bars to purge between train and test (prevents leakage
                      from multi-bar labels).
        expanding: If True, training window grows with each fold.
                   If False, a rolling window of fixed length is used.

    Returns:
        WalkForwardResult with per-fold and aggregate metrics.
    """
    assert isinstance(df.index, pd.DatetimeIndex), "df must have a DatetimeIndex"
    df = df.sort_index()
    n = len(df)

    # Build fold boundaries
    fold_size = n // (n_folds + 1)
    folds: List[WalkForwardFold] = []
    all_returns: List[float] = []

    for i in range(n_folds):
        test_start_idx = fold_size * (i + 1) + embargo_bars
        test_end_idx = min(test_start_idx + fold_size, n)

        if expanding:
            train_end_idx = fold_size * (i + 1)
            train_start_idx = 0
        else:
            train_end_idx = fold_size * (i + 1)
            train_start_idx = max(0, train_end_idx - fold_size * 2)

        train_df = df.iloc[train_start_idx:train_end_idx]
        test_df = df.iloc[test_start_idx:test_end_idx]

        if len(train_df) < 20 or len(test_df) < 5:
            log.debug("Fold %d skipped — insufficient data", i + 1)
            continue

        try:
            oos_returns = strategy_fn(train_df, test_df)
            oos_arr = oos_returns.dropna().values.tolist()
        except Exception as exc:  # noqa: BLE001
            log.warning("Fold %d strategy_fn error: %s", i + 1, exc)
            oos_arr = []

        fold = WalkForwardFold(
            fold_id=i + 1,
            train_start=df.index[train_start_idx],
            train_end=df.index[train_end_idx - 1],
            test_start=df.index[test_start_idx],
            test_end=df.index[test_end_idx - 1],
            out_of_sample_returns=oos_arr,
            n_trades=len(oos_arr),
        )
        if oos_arr:
            r = np.array(oos_arr)
            fold.sharpe = round(r.mean() / (r.std() + 1e-10) * np.sqrt(252), 4)
        folds.append(fold)
        all_returns.extend(oos_arr)

    combined = np.array(all_returns)
    if len(combined) > 1 and combined.std() > 0:
        comb_sharpe = round(combined.mean() / combined.std() * np.sqrt(252), 4)
    else:
        comb_sharpe = 0.0

    return WalkForwardResult(
        folds=folds,
        combined_sharpe=comb_sharpe,
        combined_returns=combined,
        n_total_trades=len(combined),
    )


def _split_train_test(
    df: pd.DataFrame, test_pct: float = 0.2, embargo_bars: int = 5
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Simple helper for a single train/test split with embargo."""
    n = len(df)
    split = int(n * (1 - test_pct))
    train = df.iloc[:split]
    test = df.iloc[split + embargo_bars:]
    return train, test
