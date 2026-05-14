from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo
import json
from pathlib import Path
from typing import List, Dict

from .config import CONFIG
from .data import fetch_intraday, fetch_daily, fetch_wide_intraday_batch, wide_scan_rank, data_age_minutes, data_source_name, estimated_spread_pct
from .indicators import add_indicators
from .scoring import score_symbol
from .state import apply_signal_memory, update_open_signal_outcomes, attach_outcome_stats, load_outcomes, load_state, TRACKED_DECISIONS
from .market_context import build_market_context, symbol_sector_context


def market_phase() -> str:
    now = datetime.now(ZoneInfo("America/New_York"))
    hhmm = now.hour * 100 + now.minute
    if hhmm < 930:
        return "PREMARKET / NOT OPEN"
    if 930 <= hhmm < 1000:
        return "OPENING VOLATILITY"
    if 1000 <= hhmm < 1130:
        return "BEST MOMENTUM WINDOW"
    if 1130 <= hhmm < 1330:
        return "LUNCH CHOP"
    if 1330 <= hhmm < 1530:
        return "AFTERNOON TREND CHECK"
    if 1530 <= hhmm < 1600:
        return "LATE DAY RISK"
    return "MARKET CLOSED"


def phase_warning(phase: str) -> str:
    if "OPENING" in phase:
        return "Opening candles can fake out. Prefer cleaner confirmation after 10:00 AM ET."
    if "LUNCH" in phase:
        return "Lunch chop. Smaller size or wait for stronger confirmation."
    if "LATE" in phase:
        return "Late-day risk. Avoid chasing extended moves."
    if "CLOSED" in phase or "PREMARKET" in phase:
        return "Market is not in regular session. Treat signals as watchlist only."
    return "Normal research mode. Confirm chart before acting."


def scan() -> Dict:
    signals: List[Dict] = []
    errors: List[Dict] = []
    price_snapshot: Dict[str, float] = {}
    stale_count = 0
    source = data_source_name()
    context = build_market_context()

    # Middle-ground coverage: scan wide with a cheap batch call, then score deep only
    # on the best candidates. This keeps API pressure lower while reducing missed
    # opportunities.
    wide_universe = CONFIG.universe[: min(CONFIG.wide_scan_limit, CONFIG.max_symbols)]
    wide_frames = fetch_wide_intraday_batch(wide_universe)
    if wide_frames:
        ranked = sorted(
            ((symbol, wide_scan_rank(df)) for symbol, df in wide_frames.items()),
            key=lambda item: item[1],
            reverse=True,
        )
        candidate_symbols = [symbol for symbol, score in ranked[: CONFIG.deep_scan_limit] if score > -900]
    else:
        # Fallback keeps the scanner useful if yfinance batch is temporarily unavailable.
        ranked = []
        candidate_symbols = wide_universe[: CONFIG.deep_scan_limit]

    # Always refresh tracked open setups first. This lets hidden prior signals close
    # by target/stop instead of only expiring when they fall off the dashboard.
    state = load_state()
    active_tracked = [
        sym for sym, row in state.get("signals", {}).items()
        if not row.get("closed") and row.get("decision") in TRACKED_DECISIONS
    ]
    desired_symbols = list(dict.fromkeys(active_tracked + candidate_symbols))

    base_calls = 1 if wide_frames else 0
    max_deep_by_budget = max(0, (CONFIG.max_data_calls_per_run - base_calls) // 2)
    deep_cap = min(len(desired_symbols), CONFIG.deep_scan_limit + len(active_tracked))
    budget_trimmed = False
    if CONFIG.stop_on_rate_limit and deep_cap > max_deep_by_budget:
        deep_cap = max_deep_by_budget
        budget_trimmed = True
    deep_symbols = desired_symbols[:max(0, deep_cap)]

    estimated_data_calls = base_calls + (len(deep_symbols) * 2)
    budget_status = "OK"
    if budget_trimmed:
        budget_status = "TRIMMED_TO_BUDGET"
    elif estimated_data_calls > CONFIG.max_data_calls_per_run:
        budget_status = "WARNING"
    api_budget = {
        "mode": CONFIG.api_budget_mode,
        "wide_scan_limit": CONFIG.wide_scan_limit,
        "deep_scan_limit": CONFIG.deep_scan_limit,
        "wide_symbols_requested": len(wide_universe),
        "wide_symbols_returned": len(wide_frames),
        "active_tracked_symbols": len(active_tracked),
        "deep_symbols_selected": len(deep_symbols),
        "estimated_data_calls": estimated_data_calls,
        "max_data_calls_per_run": CONFIG.max_data_calls_per_run,
        "stop_on_rate_limit": CONFIG.stop_on_rate_limit,
        "status": budget_status,
    }

    if CONFIG.stop_on_rate_limit and estimated_data_calls > CONFIG.max_data_calls_per_run:
        errors.append({"symbol": "API_BUDGET", "error": "Run stopped because estimated data calls exceed budget"})
        deep_symbols = []

    for symbol in deep_symbols:
        intraday = fetch_intraday(symbol)
        daily = fetch_daily(symbol)
        if intraday is None or daily is None:
            errors.append({"symbol": symbol, "error": "No usable data"})
            continue
        try:
            raw_latest_price = float(intraday.iloc[-1]["Close"])
            price_snapshot[symbol] = raw_latest_price
            age = data_age_minutes(intraday)
            if age is not None and age > CONFIG.stale_data_minutes:
                stale_count += 1
            spread_est = estimated_spread_pct(intraday)
            intraday = add_indicators(intraday).dropna()
            daily = add_indicators(daily).dropna()
            if intraday.empty or daily.empty:
                errors.append({"symbol": symbol, "error": "Indicator data unavailable"})
                continue
            sector_ctx = symbol_sector_context(symbol, context)
            signal = score_symbol(symbol, intraday, daily, spread_est, age, source, sector_ctx)
            if age is not None and age > CONFIG.stale_data_minutes:
                signal["warnings"].append("Data may be stale")
            if signal["decision"] != "AVOID":
                signals.append(signal)
        except Exception as exc:
            errors.append({"symbol": symbol, "error": str(exc)})

    # Before trimming to dashboard cards, close any open signal using all prices we have.
    phase = market_phase()
    force_eod_close = phase == "MARKET CLOSED"
    update_open_signal_outcomes(price_snapshot, force_eod_close=force_eod_close)

    signals.sort(
        key=lambda x: (
            x["decision"] == "BUY SETUP",
            x["decision"] == "WAIT",
            x["opportunity_score"],
            x["entry_score"],
        ),
        reverse=True,
    )
    signals = signals[:CONFIG.top_n]

    signals = attach_outcome_stats(signals)
    signals = apply_signal_memory(signals)

    now_et = datetime.now(ZoneInfo("America/New_York"))
    outcomes = load_outcomes()
    data_health = "OK" if stale_count == 0 else "STALE WARNING"
    validation_warning = None
    sample_size = outcomes.get("stats", {}).get("sample_size", 0)
    if sample_size < 30:
        validation_warning = "Outcome sample is still small. Treat scores as unproven until more signals close."

    payload = {
        "scanner_name": "Elite Scanner 100/100",
        "updated_at_et": now_et.strftime("%Y-%m-%d %I:%M:%S %p ET"),
        "market_phase": phase,
        "phase_warning": phase_warning(phase),
        "paper_only": True,
        "schema_version": "1.0.0",
        "data_source": source,
        "market_context": context.to_dict(),
        "api_budget": api_budget,
        "data_health": data_health,
        "stale_symbol_count": stale_count,
        "validation_warning": validation_warning,
        "summary": {
            "buy_setups": sum(1 for s in signals if s["decision"] == "BUY SETUP"),
            "wait": sum(1 for s in signals if s["decision"] == "WAIT"),
            "watch_only": sum(1 for s in signals if s["decision"] == "WATCH ONLY"),
            "total": len(signals),
            "wide_symbols_checked": len(wide_frames) if wide_frames else len(wide_universe),
            "deep_symbols_checked": len(price_snapshot),
            "symbols_checked": len(price_snapshot),
            "outcome_sample_size": sample_size,
            "target1_rate_pct": outcomes.get("stats", {}).get("target1_rate_pct"),
            "avg_pnl_pct_est": outcomes.get("stats", {}).get("avg_pnl_pct_est"),
        },
        "scanner_mode": "middle-ground: wide scan 150 symbols, deep scan top 40, trade narrow",
        "beginner_rules": [
            "BUY SETUP means the scanner found a valid setup, not a guaranteed trade.",
            "WAIT means do not chase; use the better entry or wait for confirmation.",
            "Stop loss is the invalidation area. If price loses it, the setup is wrong.",
            "Target 1 is the first profit zone. Target 2 is stretch target.",
            "Paper-test first. Do not use this as live financial advice.",
        ],
        "signals": signals,
        "errors": errors[:10],
    }
    return payload


def write_outputs(payload: Dict) -> None:
    out = Path("docs/data/signals.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True))

    # Keep a dated signal archive for validation/backtesting.
    stamp = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")
    hist = Path(f"docs/data/history/signals_{stamp}.json")
    hist.parent.mkdir(parents=True, exist_ok=True)
    hist.write_text(json.dumps(payload, indent=2, sort_keys=True))


def main() -> None:
    payload = scan()
    write_outputs(payload)
    print(json.dumps(payload["summary"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
