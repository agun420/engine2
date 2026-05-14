from pathlib import Path
from datetime import datetime, timezone, timedelta

import pandas as pd

from src.backtest import replay_levels, summarize_replays
from src.config import CONFIG
from src.scoring import classify_chase_risk, classify_tradeability, compute_levels, action_text
from src import state as state_mod


def test_chase_risk_extreme():
    assert classify_chase_risk(vwap_distance_pct=8, atr_pct=8, rsi=80, day_change_pct=14) == "EXTREME"


def test_tradeability_weak_when_spread_wide():
    tradeability, warnings = classify_tradeability(100_000_000, 2.0, 10)
    assert tradeability == "WEAK"
    assert warnings


def test_levels_use_real_resistance_not_fixed_rr():
    levels, warnings = compute_levels(
        price=100,
        vwap=99,
        ema9=99.5,
        atr=2,
        recent_high=101.2,
        day_high=101.5,
        prior_day_high=107,
        prior_close=103,
    )
    assert levels["entry"] == 100
    assert levels["target1"] == 101.2
    assert levels["target1_source"] == "recent high"
    assert levels["risk_reward"] != 1.7
    assert levels["stop"] < levels["entry"]


def test_wait_action_text_is_beginner_clear():
    levels, _ = compute_levels(price=100, vwap=98, ema9=99, atr=2)
    text = action_text("WAIT", "TOO EXTENDED", levels, ["Too extended above VWAP"])
    assert "Do not chase" in text
    assert "Better entry" in text


def test_replay_target_before_stop():
    bars = pd.DataFrame([
        {"High": 101, "Low": 99},
        {"High": 104, "Low": 100},
    ])
    result = replay_levels("TEST", bars, entry=100, stop=97, target1=103)
    assert result["result"] == "TARGET_FIRST"


def test_summarize_replays():
    summary = summarize_replays([
        {"result": "TARGET_FIRST", "max_upside_pct": 3, "max_drawdown_pct": -1},
        {"result": "STOP_FIRST", "max_upside_pct": 1, "max_drawdown_pct": -2},
    ])
    assert summary["sample_size"] == 2
    assert summary["target_first_rate_pct"] == 50.0


def test_outcome_tracks_hidden_signal_target_hit(tmp_path, monkeypatch):
    monkeypatch.setattr(state_mod, "STATE_PATH", tmp_path / "signal_state.json")
    monkeypatch.setattr(state_mod, "OUTCOMES_PATH", tmp_path / "outcomes.json")
    opened = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    state_mod.save_state({
        "signals": {
            "TEST": {
                "first_seen": opened,
                "opened_at": opened,
                "decision": "BUY SETUP",
                "status": "TRIGGER READY",
                "lifecycle": "TRIGGER_READY",
                "entry": 100,
                "stop": 97,
                "target1": 103,
                "target2": 106,
                "last_price": 101,
                "closed": False,
            }
        }
    })
    state_mod.save_outcomes({"closed": [], "stats": {}})
    state_mod.update_open_signal_outcomes({"TEST": 103.5})
    outcomes = state_mod.load_outcomes()
    assert outcomes["closed"][0]["result"] == "TARGET_1_HIT"


def test_outcome_expires_when_symbol_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(state_mod, "STATE_PATH", tmp_path / "signal_state.json")
    monkeypatch.setattr(state_mod, "OUTCOMES_PATH", tmp_path / "outcomes.json")
    opened = (datetime.now(timezone.utc) - timedelta(minutes=CONFIG.signal_ttl_minutes + 5)).isoformat()
    state_mod.save_state({
        "signals": {
            "MISS": {
                "first_seen": opened,
                "opened_at": opened,
                "decision": "WAIT",
                "status": "WATCHLIST",
                "lifecycle": "SETUP_FORMING",
                "entry": 50,
                "stop": 48,
                "target1": 54,
                "target2": 58,
                "last_price": 51,
                "closed": False,
            }
        }
    })
    state_mod.save_outcomes({"closed": [], "stats": {}})
    state_mod.update_open_signal_outcomes({})
    outcomes = state_mod.load_outcomes()
    assert outcomes["closed"][0]["result"] == "EXPIRED"

from src.market_context import ContextSnapshot, symbol_sector_context, sector_boost


def test_sector_boost_rewards_leadership():
    ctx = ContextSnapshot(0.2, 0.6, 0.1, "RISK-ON", "ok", {"SPY": 0.2, "SMH": 1.1})
    sector = symbol_sector_context("NVDA", ctx)
    boost, reasons = sector_boost(sector)
    assert sector["sector_etf"] == "SMH"
    assert boost > 0
    assert reasons


def test_sector_boost_penalizes_risk_off():
    ctx = ContextSnapshot(-1.0, -1.2, -0.8, "RISK-OFF", "weak", {"SPY": -1.0, "XLF": -0.9})
    sector = symbol_sector_context("SOFI", ctx)
    boost, reasons = sector_boost(sector)
    assert boost < 0
    assert any("risk-off" in r.lower() for r in reasons)

from src.broker.alpaca_paper import submit_bracket_order, paper_trading_enabled
from src.alerts.telegram import format_buy_setup_alert
from src.execution import buy_setups, process_buy_setups
from src import execution as execution_mod


def _sample_buy_signal():
    return {
        "symbol": "TEST",
        "price": 100.0,
        "decision": "BUY SETUP",
        "chase_risk": "LOW",
        "entry_score": 88,
        "opportunity_score": 91,
        "levels": {
            "entry": 100.0,
            "better_entry": 99.0,
            "stop": 97.0,
            "target1": 105.0,
            "target2": 110.0,
            "risk_reward": 1.67,
        },
        "reasons": ["Above VWAP", "Volume expansion"],
        "warnings": [],
    }


def test_paper_order_dry_run_is_safe(monkeypatch):
    monkeypatch.delenv("AUTO_PAPER_TRADE", raising=False)
    result = submit_bracket_order(_sample_buy_signal(), max_notional=2000, dry_run=True)
    assert result.submitted is False
    assert result.qty == 20
    assert "dry run" in result.reason
    assert paper_trading_enabled() is False


def test_telegram_alert_contains_required_trade_fields():
    text = format_buy_setup_alert(_sample_buy_signal(), {"submitted": False, "reason": "test"})
    assert "BUY SETUP: TEST" in text
    assert "Entry goal" in text
    assert "Stop loss" in text
    assert "Sell target 1" in text
    assert "Reason" in text


def test_execution_process_dedupes_and_does_not_require_alpaca(tmp_path, monkeypatch):
    monkeypatch.setattr(execution_mod, "EXECUTION_STATE_PATH", tmp_path / "execution_state.json")
    monkeypatch.setattr(execution_mod, "ALERT_STATE_PATH", tmp_path / "alert_state.json")
    monkeypatch.delenv("AUTO_PAPER_TRADE", raising=False)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    payload = {"signals": [_sample_buy_signal()]}
    first = process_buy_setups(payload)
    second = process_buy_setups(payload)
    assert first["buy_setup_count"] == 1
    assert first["orders_submitted_this_run"] == 0
    assert "AUTO_PAPER_TRADE" in first["results"][0]["order"]["reason"]
    assert second["results"][0]["order"]["reason"] == "skipped: signal already processed for paper order"

from src.alerts.telegram import format_wait_setup_alert


def test_middle_ground_config_defaults():
    assert CONFIG.wide_scan_limit == 150
    assert CONFIG.deep_scan_limit == 40
    assert CONFIG.max_buy_alerts_per_run == 5
    assert CONFIG.max_wait_alerts_per_run == 3
    assert CONFIG.max_new_orders_per_run == 1


def test_wait_telegram_alert_is_alert_only():
    sig = _sample_buy_signal()
    sig["decision"] = "WAIT"
    text = format_wait_setup_alert(sig)
    assert "WAIT SETUP: TEST" in text
    assert "Do not chase" in text
    assert "No paper order" in text

from datetime import datetime as _dt
from zoneinfo import ZoneInfo as _ZoneInfo
from src.broker import alpaca_paper as alpaca_paper_mod
from src.broker.alpaca_paper import is_safe_paper_execution_window


def test_paper_execution_window_blocks_after_hours():
    ok, reason = is_safe_paper_execution_window(_dt(2026, 5, 13, 16, 30, tzinfo=_ZoneInfo("America/New_York")))
    assert ok is False
    assert "3:45" in reason or "after" in reason


def test_paper_execution_window_allows_regular_session():
    ok, reason = is_safe_paper_execution_window(_dt(2026, 5, 13, 10, 15, tzinfo=_ZoneInfo("America/New_York")))
    assert ok is True
    assert "safe" in reason


def test_stale_data_blocks_paper_order_when_enabled(monkeypatch):
    monkeypatch.setenv("AUTO_PAPER_TRADE", "true")
    monkeypatch.setattr(alpaca_paper_mod, "is_safe_paper_execution_window", lambda: (True, "safe"))
    sig = _sample_buy_signal()
    sig["warnings"] = ["Data may be stale"]
    result = submit_bracket_order(sig, max_notional=2000)
    assert result.submitted is False
    assert "stale" in result.reason


def test_score_symbol_includes_advanced_breakdown():
    rows = []
    for i in range(30):
        base = 100 + i * 0.15
        rows.append({
            "Open": base - 0.25,
            "High": base + 0.55,
            "Low": base - 0.45,
            "Close": base + 0.25,
            "Volume": 1_500_000 + i * 20_000,
            "VWAP": base - 0.2,
            "EMA9": base - 0.1,
            "EMA20": base - 0.3,
            "ATR14": 1.8,
            "RSI14": 61,
            "VOL_MA20": 1_200_000,
        })
    intraday = pd.DataFrame(rows)
    daily = pd.DataFrame([{
        "Open": 90+i*0.2,
        "High": 92+i*0.2,
        "Low": 89+i*0.2,
        "Close": 91+i*0.2,
        "Volume": 2_000_000,
    } for i in range(25)])
    sig = __import__("src.scoring", fromlist=["score_symbol"]).score_symbol(
        "NVDA", intraday, daily, spread_pct_est=0.1, sector_context={
            "sector_etf": "SMH",
            "sector_change_pct": 1.2,
            "sector_vs_spy_pct": 0.8,
            "market_regime": "RISK-ON",
        }
    )
    adv = sig["advanced_breakdown"]
    assert adv["composite"] > 0
    assert adv["grade"] in {"A", "B", "C", "D", "F"}
    for factor in ["catalyst", "technical", "volume_liquidity", "relative_strength", "sector_market", "risk_quality", "execution_timing"]:
        assert factor in adv["factors"]
        assert "score" in adv["factors"][factor]
