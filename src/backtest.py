from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List
import pandas as pd


@dataclass
class ReplayResult:
    symbol: str
    entry: float
    stop: float
    target1: float
    result: str
    max_upside_pct: float
    max_drawdown_pct: float
    bars_to_result: int


def replay_levels(symbol: str, bars: pd.DataFrame, entry: float, stop: float, target1: float) -> Dict:
    """Replay simple target-before-stop logic over future bars.

    This is used for validation and tests. It assumes entry is already triggered.
    It does not model slippage or partial fills.
    """
    if bars is None or bars.empty:
        return ReplayResult(symbol, entry, stop, target1, "NO_DATA", 0.0, 0.0, 0).__dict__

    max_high = entry
    min_low = entry
    result = "EXPIRED"
    bars_to_result = len(bars)

    for i, (_, row) in enumerate(bars.iterrows(), start=1):
        high = float(row["High"])
        low = float(row["Low"])
        max_high = max(max_high, high)
        min_low = min(min_low, low)
        hit_stop = low <= stop
        hit_target = high >= target1
        if hit_stop and hit_target:
            result = "AMBIGUOUS_SAME_BAR"
            bars_to_result = i
            break
        if hit_stop:
            result = "STOP_FIRST"
            bars_to_result = i
            break
        if hit_target:
            result = "TARGET_FIRST"
            bars_to_result = i
            break

    return ReplayResult(
        symbol=symbol,
        entry=round(entry, 2),
        stop=round(stop, 2),
        target1=round(target1, 2),
        result=result,
        max_upside_pct=round(((max_high / entry) - 1) * 100, 2),
        max_drawdown_pct=round(((min_low / entry) - 1) * 100, 2),
        bars_to_result=bars_to_result,
    ).__dict__


def summarize_replays(results: List[Dict]) -> Dict:
    if not results:
        return {"sample_size": 0, "target_first_rate_pct": None}
    target = [r for r in results if r.get("result") == "TARGET_FIRST"]
    avg_up = sum(float(r.get("max_upside_pct", 0)) for r in results) / len(results)
    avg_dd = sum(float(r.get("max_drawdown_pct", 0)) for r in results) / len(results)
    return {
        "sample_size": len(results),
        "target_first_rate_pct": round(len(target) / len(results) * 100, 1),
        "avg_max_upside_pct": round(avg_up, 2),
        "avg_max_drawdown_pct": round(avg_dd, 2),
    }
