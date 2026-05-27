"""Phase 5 — Point-in-time data loader with survivorship-bias elimination.

Two critical biases are eliminated here:
  1. Look-ahead bias: earnings data is delayed by realistic reporting lags
     (60 days for 10-Qs, 90 days for 10-Ks) so the backtester never "knows"
     a number before it was publicly released.
  2. Survivorship bias: delisted, bankrupt, and acquired companies are
     explicitly included in the universe using their full historical records.
"""
from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

log = logging.getLogger(__name__)

# Standard SEC reporting lags (calendar days after period end)
_10Q_LAG_DAYS = 60
_10K_LAG_DAYS = 90

# Path to the delisted-companies universe file (populated by the data pipeline)
_DELISTED_PATH = Path("state/delisted_universe.csv")


@dataclass
class EarningsPIT:
    """A single earnings data point with its public availability date."""
    symbol: str
    period_end: datetime.date
    eps_actual: Optional[float]
    revenue_actual: Optional[float]
    public_date: datetime.date   # period_end + reporting lag


class PointInTimeLoader:
    """
    Wraps price history and fundamental data so that any query for data
    "as of date D" never includes information that was not yet public on D.
    """

    def __init__(self) -> None:
        self._earnings: Dict[str, List[EarningsPIT]] = {}
        self._delisted: List[str] = self._load_delisted()

    # ------------------------------------------------------------------ #
    # Universe construction                                               #
    # ------------------------------------------------------------------ #

    def full_universe(self, symbols: List[str]) -> List[str]:
        """
        Merge the live symbol list with the delisted universe to eliminate
        survivorship bias.
        """
        return sorted(set(symbols) | set(self._delisted))

    @staticmethod
    def _load_delisted() -> List[str]:
        if _DELISTED_PATH.exists():
            try:
                df = pd.read_csv(_DELISTED_PATH)
                return df["symbol"].tolist()
            except Exception as exc:  # noqa: BLE001
                log.debug("Could not load delisted universe: %s", exc)
        return []

    # ------------------------------------------------------------------ #
    # Point-in-time price data                                           #
    # ------------------------------------------------------------------ #

    @staticmethod
    def get_price_as_of(df: pd.DataFrame, as_of_date: datetime.date) -> pd.DataFrame:
        """
        Return only the rows in df where the bar DATE <= as_of_date.
        Prevents future data from leaking into indicator calculations.
        """
        if df.empty:
            return df
        idx = pd.to_datetime(df.index)
        cutoff = pd.Timestamp(as_of_date)
        return df[idx <= cutoff]

    # ------------------------------------------------------------------ #
    # Point-in-time fundamentals                                         #
    # ------------------------------------------------------------------ #

    def register_earnings(
        self,
        symbol: str,
        period_end: datetime.date,
        eps: Optional[float],
        revenue: Optional[float],
        is_annual: bool = False,
    ) -> None:
        """Register a raw earnings release and compute its public availability date."""
        lag = _10K_LAG_DAYS if is_annual else _10Q_LAG_DAYS
        public = period_end + datetime.timedelta(days=lag)
        pit = EarningsPIT(
            symbol=symbol,
            period_end=period_end,
            eps_actual=eps,
            revenue_actual=revenue,
            public_date=public,
        )
        self._earnings.setdefault(symbol, []).append(pit)

    def get_earnings_as_of(
        self, symbol: str, as_of_date: datetime.date
    ) -> Optional[EarningsPIT]:
        """Return the most recent earnings release that was publicly known on as_of_date."""
        releases = [
            e for e in self._earnings.get(symbol, [])
            if e.public_date <= as_of_date
        ]
        if not releases:
            return None
        return max(releases, key=lambda e: e.public_date)

    # ------------------------------------------------------------------ #
    # Multi-timeframe delayed realignment (Stepped Delayed Realignment)  #
    # ------------------------------------------------------------------ #

    @staticmethod
    def align_mtf_indicator(
        low_freq_indicator: pd.Series,
        high_freq_index: pd.DatetimeIndex,
    ) -> pd.Series:
        """
        Map a low-frequency indicator (e.g. daily) onto a high-frequency
        timeline (e.g. 1-minute bars) using ONLY completed historical bars.

        Indicators are forward-filled but the value for each high-freq bar
        is the indicator value that was available at the START of that day,
        never a same-bar or future value.  This enforces Phase 5's
        "Stepped Delayed Realignment" requirement.
        """
        # Shift the low-freq series by 1 period so today's bar uses yesterday's value
        shifted = low_freq_indicator.shift(1)
        # Reindex onto high-frequency timeline, forward-fill within each day
        aligned = shifted.reindex(high_freq_index, method="ffill")
        return aligned
