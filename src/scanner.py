from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo
import json
from pathlib import Path
from typing import List, Dict, Optional

from .config import CONFIG
from .data import fetch_intraday, fetch_daily, fetch_wide_intraday_batch, wide_scan_rank, data_age_minutes, data_source_name, estimated_spread_pct
from .indicators import add_indicators
from .scoring import score_symbol
from .state import apply_signal_memory, update_open_signal_outcomes, attach_outcome_stats, load_outcomes, load_state, TRACKED_DECISIONS
from .market_context import build_market_context, symbol_sector_context

# ── Phase 1: data ingestion ──────────────────────────────────────────────────
from .data_ingestion.s3_partners import enrich_signal_with_s3
from .data_ingestion.simclusters import SimClustersMonitor
from .data_ingestion.lunarcrush import LunarCrushFeed

# ── Phase 2: NLP & signal scaling ────────────────────────────────────────────
from .signals.svc_scaling import svc_allocation_score
from .signals.vix_scaling import vix_sentiment_scale, fetch_current_vix, vix_regime

# ── Phase 4: aggregation & panel ─────────────────────────────────────────────
from .aggregation.lightgbm_aggregator import LightGBMAggregator, FEATURE_COLUMNS
from .agents.multi_agent_panel import MultiAgentPanel

log = logging.getLogger(__name__)

# Module-level singletons initialised once per process
_simclusters: Optional[SimClustersMonitor] = None
_lunarcrush: Optional[LunarCrushFeed] = None
_lgbm: Optional[LightGBMAggregator] = None
_panel: Optional[MultiAgentPanel] = None
_cached_vix: Optional[float] = None


def _get_singletons(symbols: List[str]):
    global _simclusters, _lunarcrush, _lgbm, _panel, _cached_vix
    if _simclusters is None:
        _simclusters = SimClustersMonitor(
            symbols=symbols,
            window_minutes=CONFIG.simcluster_window_minutes,
            min_velocity_delta=CONFIG.simcluster_min_velocity_delta,
        )
    if _lunarcrush is None:
        _lunarcrush = LunarCrushFeed(symbols=symbols)
    if _lgbm is None:
        _lgbm = LightGBMAggregator()
    if _panel is None:
        _panel = MultiAgentPanel()
    # Refresh VIX once per scan run
    _cached_vix = fetch_current_vix()
    return _simclusters, _lunarcrush, _lgbm, _panel


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

    # Initialise Phase 1-4 singletons and pre-fetch bulk social data
    sim, lc, lgbm, panel = _get_singletons(CONFIG.universe)
    lc.fetch_all()
    sim_signals = {s.symbol: s for s in sim.poll()}

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
                # ── Phase 1: enrich with S3 short-squeeze divergence ──────
                signal = enrich_signal_with_s3(signal, CONFIG.s3_min_divergence)

                # ── Phase 1: attach LunarCrush social metrics ─────────────
                signal = lc.enrich_signal(signal)

                # ── Phase 1: SimClusters engagement velocity ──────────────
                sc = sim_signals.get(symbol)
                if sc:
                    signal["simcluster_velocity"] = sc.velocity
                    signal["simcluster_velocity_delta"] = sc.velocity_delta
                    signal["simcluster_bridging_score"] = sc.bridging_score
                    signal["simcluster_bridging"] = sim.is_bridging(symbol)

                # ── Phase 2: VIX-scaled sentiment ─────────────────────────
                raw_sent = float(signal.get("lc_sentiment", 0.0))
                signal["vix_scaled_sentiment"] = vix_sentiment_scale(raw_sent, _cached_vix, CONFIG.vix_reference_level)
                signal["vix_regime"] = vix_regime(_cached_vix)

                # ── Phase 2: Sentiment Volume Change (SVC) ────────────────
                prev_sent = float(signal.get("prev_lc_sentiment", raw_sent))
                vol_count = int(signal.get("lc_social_volume", 0))
                signal["svc_score"] = svc_allocation_score(
                    prev_sent, raw_sent, vol_count, CONFIG.svc_bias_c
                )

                # ── Phase 4: LightGBM non-linear aggregation ──────────────
                features = _build_feature_dict(signal, context)
                lgbm_result = lgbm.predict(symbol, features)
                signal["lightgbm_proba"] = lgbm_result.breakout_proba
                signal["lightgbm_flagged"] = lgbm_result.flagged
                signal["lgbm_feature_importances"] = lgbm_result.feature_importances

                # ── Phase 4: Multi-agent panel (optional) ─────────────────
                if lgbm_result.flagged and CONFIG.enable_panel_review:
                    try:
                        decision = panel.evaluate(symbol, signal)
                        signal["panel_verdict"] = decision.final_verdict
                        signal["panel_confidence"] = decision.consensus_confidence
                        signal["panel_approved"] = decision.approved_for_execution
                        signal["panel_summary"] = decision.summary
                    except Exception as exc:  # noqa: BLE001
                        log.warning("Panel review failed for %s: %s", symbol, exc)
                        signal["panel_verdict"] = "ERROR"

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
        "scanner_mode": "elite: wide scan 150 → deep 40 → S3/SimClusters/LunarCrush enrichment → MemeBERT-LSTM → LightGBM GOSS/EFB → Multi-Agent Panel",
        "pipeline_status": {
            "vix": _cached_vix,
            "vix_regime": vix_regime(_cached_vix),
            "lgbm_model_loaded": _lgbm._model is not None if _lgbm else False,
            "panel_review_enabled": CONFIG.enable_panel_review,
            "simcluster_symbols_polled": len(sim_signals),
        },
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


def _build_feature_dict(signal: dict, context) -> dict:
    """Map signal fields onto the LightGBM feature vector."""
    regime_map = {"LOW_VOL_BULL": 0, "NORMAL": 1, "ELEVATED": 2, "HIGH_FEAR": 3, "CRISIS": 4}
    return {
        "rsi14": float(signal.get("rsi14", 50)),
        "vwap_dist_pct": float(signal.get("vwap_dist_pct", 0)),
        "atr_pct": float(signal.get("atr_pct", 0)),
        "rel_vol": float(signal.get("rel_vol", 1)),
        "ema9_slope": float(signal.get("ema9_slope", 0)),
        "day_change_pct": float(signal.get("day_change_pct", 0)),
        "short_momentum": float(signal.get("short_momentum", 0)),
        "candle_strength": float(signal.get("candle_strength", 0)),
        "s3_squeeze_risk": float(signal.get("s3_squeeze_risk", 0)),
        "s3_crowded_score": float(signal.get("s3_crowded_score", 0)),
        "s3_divergence": float(signal.get("s3_divergence", 0)),
        "lc_galaxy_score": float(signal.get("lc_galaxy_score", 0)),
        "lc_sentiment": float(signal.get("lc_sentiment", 0)),
        "lc_social_volume": float(signal.get("lc_social_volume", 0)),
        "svc_score": float(signal.get("svc_score", 0)),
        "simcluster_velocity": float(signal.get("simcluster_velocity", 0)),
        "simcluster_bridging": float(signal.get("simcluster_bridging_score", 0)),
        "lstm_signal": float(signal.get("lstm_signal", 0)),
        "memebert_sentiment": float(signal.get("memebert_sentiment", 0)),
        "vix_scaled_sentiment": float(signal.get("vix_scaled_sentiment", 0)),
        "market_regime_code": float(regime_map.get(signal.get("vix_regime", "NORMAL"), 1)),
    }


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
