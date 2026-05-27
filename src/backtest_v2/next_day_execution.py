"""Phase 5 — Next-day execution pricing.

To model the "friction illusion" correctly:
  - Portfolio rebalancing decisions are made on day D (based on close data).
  - Actual trade execution uses the average of day D+1's OHLC bars.

This prevents the common backtest bias where signals are both evaluated AND
filled at the same close price, which is impossible in live trading.
"""
from __future__ import annotations

from typing import Literal, Optional

import pandas as pd


ExecutionMode = Literal["next_ohlc_avg", "next_open", "twap_approx"]


def next_day_execution_price(
    df: pd.DataFrame,
    signal_date: pd.Timestamp,
    mode: ExecutionMode = "next_ohlc_avg",
) -> Optional[float]:
    """
    Return the fill price for a trade signalled at close on ``signal_date``.

    Modes:
      ``next_ohlc_avg`` (default) — average of next day's O+H+L+C / 4.
      ``next_open``               — next day's open only (optimistic).
      ``twap_approx``             — (O + 2*C) / 3 approximation.

    Returns None if the next trading day is not in the DataFrame.
    """
    if df.empty:
        return None

    dates = pd.to_datetime(df.index)
    future = dates[dates > signal_date]
    if future.empty:
        return None

    next_date = future.min()
    row = df.loc[next_date]

    o = float(row["Open"])
    h = float(row["High"])
    l = float(row["Low"])
    c = float(row["Close"])

    if mode == "next_ohlc_avg":
        return round((o + h + l + c) / 4, 4)
    if mode == "next_open":
        return round(o, 4)
    # twap_approx
    return round((o + 2 * c) / 3, 4)


def apply_next_day_execution(
    signals: pd.DataFrame,
    price_df: pd.DataFrame,
    mode: ExecutionMode = "next_ohlc_avg",
) -> pd.DataFrame:
    """
    Vectorised version: given a signals DataFrame with a DatetimeIndex,
    compute the fill price for every row.

    Adds a ``fill_price`` column to the returned DataFrame.
    """
    fills = []
    for sig_date in signals.index:
        price = next_day_execution_price(price_df, sig_date, mode)
        fills.append(price)
    out = signals.copy()
    out["fill_price"] = fills
    return out


def compute_slippage_adjusted_return(
    fill_price: float,
    exit_price: float,
    slippage_bps: float = 10.0,
    direction: int = 1,
) -> float:
    """
    Compute the round-trip slippage-adjusted return for a single trade.

    ``slippage_bps`` is the one-way slippage in basis points (default 10 bps).
    """
    gross_return = (exit_price / fill_price - 1) * direction
    slippage = slippage_bps / 10_000 * 2  # round-trip
    return round(gross_return - slippage, 6)
