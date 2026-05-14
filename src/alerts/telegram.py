from __future__ import annotations

import hashlib
import json
import os
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
ALERT_STATE_PATH = ROOT / "state" / "alert_state.json"


def _now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _load_alert_state() -> dict[str, Any]:
    if not ALERT_STATE_PATH.exists():
        return {
            "sent_alerts": {},
            "last_updated": None,
            "telegram_policy": "BUY_SETUP_ONLY",
        }

    try:
        with ALERT_STATE_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, dict):
            return {
                "sent_alerts": {},
                "last_updated": None,
                "telegram_policy": "BUY_SETUP_ONLY",
            }

        data.setdefault("sent_alerts", {})
        data["telegram_policy"] = "BUY_SETUP_ONLY"
        return data

    except Exception:
        return {
            "sent_alerts": {},
            "last_updated": None,
            "telegram_policy": "BUY_SETUP_ONLY",
        }


def _save_alert_state(state: dict[str, Any]) -> None:
    ALERT_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    state["last_updated"] = _now_iso()
    state["telegram_policy"] = "BUY_SETUP_ONLY"

    with ALERT_STATE_PATH.open("w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, sort_keys=True)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def _money(value: Any) -> str:
    number = _safe_float(value)
    if number <= 0:
        return "N/A"
    return f"${number:,.2f}"


def _pct(value: Any) -> str:
    try:
        return f"{float(value):.2f}%"
    except Exception:
        return "N/A"


def _get_value(signal: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in signal and signal[key] not in (None, ""):
            return signal[key]

    levels = signal.get("levels")
    if isinstance(levels, dict):
        for key in keys:
            if key in levels and levels[key] not in (None, ""):
                return levels[key]

    return default


def _signal_symbol(signal: dict[str, Any]) -> str:
    return str(_get_value(signal, "symbol", "ticker", default="UNKNOWN")).upper()


def _signal_decision(signal: dict[str, Any]) -> str:
    return str(_get_value(signal, "decision", "status", "action", default="")).upper()


def _alert_fingerprint(signal: dict[str, Any]) -> str:
    symbol = _signal_symbol(signal)
    decision = _signal_decision(signal)

    entry = _get_value(signal, "entry", "entry_goal", "entry_area", "buy_zone", default="")
    stop = _get_value(signal, "stop_loss", "stop", "sl", default="")
    target = _get_value(signal, "target_1", "target1", "tp1", "sell_target_1", default="")

    raw = f"{symbol}|{decision}|{entry}|{stop}|{target}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _format_buy_setup_message(
    signal: dict[str, Any],
    paper_order_status: str | None = None,
) -> str:
    symbol = _signal_symbol(signal)

    price = _get_value(signal, "price", "last_price", "current_price")
    day_move = _get_value(signal, "day_move_pct", "change_pct", "pct_change")

    entry = _get_value(signal, "entry", "entry_goal", "entry_area", "buy_zone")
    better_entry = _get_value(signal, "better_entry", "pullback_entry", "ideal_entry")
    stop = _get_value(signal, "stop_loss", "stop", "sl")
    target_1 = _get_value(signal, "target_1", "target1", "tp1", "sell_target_1")
    target_2 = _get_value(signal, "target_2", "target2", "tp2", "sell_target_2")

    opportunity_score = _get_value(signal, "opportunity_score", "score", "total_score", default="N/A")
    entry_score = _get_value(signal, "entry_score", "trade_score", "setup_score", default="N/A")
    rr = _get_value(signal, "risk_reward", "rr", "risk_reward_ratio", default="N/A")
    confidence = _get_value(signal, "confidence", default="N/A")
    chase_risk = _get_value(signal, "chase_risk", default="N/A")
    tradeability = _get_value(signal, "tradeability", default="N/A")
    reason = _get_value(signal, "reason", "why", "summary", default="BUY SETUP found.")

    if isinstance(reason, list):
        reason = "; ".join(str(x) for x in reason[:5])

    paper_line = paper_order_status or _get_value(signal, "paper_order_status", default="Not submitted")

    lines = [
        f"🟢 BUY SETUP: {symbol}",
        "",
        f"Price: {_money(price)}",
        f"Day move: {_pct(day_move)}",
        "",
        f"Entry goal: {_money(entry)}",
        f"Better entry: {_money(better_entry)}",
        f"Stop loss: {_money(stop)}",
        f"Sell target 1: {_money(target_1)}",
        f"Sell target 2: {_money(target_2)}",
        "",
        f"Opportunity score: {opportunity_score}/100",
        f"Entry score: {entry_score}/100",
        f"Confidence: {confidence}",
        f"Risk/reward: {rr}",
        f"Chase risk: {chase_risk}",
        f"Tradeability: {tradeability}",
        "",
        f"Reason: {reason}",
        f"Paper order: {paper_line}",
        "",
        "Paper-only research alert. Confirm chart before acting.",
    ]

    return "\n".join(lines)


# Public compatibility function used by tests/test_scoring.py.
def format_buy_setup_alert(
    signal: dict[str, Any],
    paper_order_status: str | None = None,
) -> str:
    return _format_buy_setup_message(
        signal=signal,
        paper_order_status=paper_order_status,
    )


def _send_telegram_message(text: str) -> tuple[bool, str]:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()

    if not token or not chat_id:
        return False, "telegram not configured"

    url = f"https://api.telegram.org/bot{token}/sendMessage"

    payload = urllib.parse.urlencode(
        {
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": "true",
        }
    ).encode("utf-8")

    try:
        request = urllib.request.Request(url, data=payload, method="POST")
        with urllib.request.urlopen(request, timeout=15) as response:
            if 200 <= response.status < 300:
                return True, "sent"
            return False, f"telegram http {response.status}"

    except Exception as exc:
        return False, f"telegram error: {exc}"


def send_buy_setup_alerts(
    signals: list[dict[str, Any]],
    execution_results: dict[str, Any] | None = None,
    max_alerts: int | None = None,
) -> dict[str, Any]:
    """
    Telegram policy: BUY_SETUP_ONLY.

    This function only sends Telegram alerts for:
      decision == BUY SETUP

    WAIT, WATCH ONLY, and AVOID stay on the dashboard only.
    """

    if max_alerts is None:
        max_alerts = int(os.getenv("MAX_BUY_ALERTS_PER_RUN", "5"))

    execution_results = execution_results or {}
    state = _load_alert_state()
    sent_alerts = state.setdefault("sent_alerts", {})

    summary = {
        "telegram_policy": "BUY_SETUP_ONLY",
        "buy_alerts_attempted": 0,
        "buy_alerts_sent": 0,
        "buy_alerts_suppressed": 0,
        "wait_alerts_attempted": 0,
        "wait_alerts_sent": 0,
        "wait_alerts_suppressed": 0,
        "skipped_non_buy_setup": 0,
        "messages": [],
    }

    for signal in signals:
        decision = _signal_decision(signal)

        if decision != "BUY SETUP":
            summary["skipped_non_buy_setup"] += 1
            continue

        if summary["buy_alerts_attempted"] >= max_alerts:
            summary["buy_alerts_suppressed"] += 1
            continue

        symbol = _signal_symbol(signal)
        fingerprint = _alert_fingerprint(signal)

        if fingerprint in sent_alerts:
            summary["buy_alerts_suppressed"] += 1
            summary["messages"].append(f"{symbol}: duplicate BUY SETUP alert suppressed")
            continue

        paper_status = None
        if isinstance(execution_results, dict):
            by_symbol = execution_results.get("by_symbol")
            if isinstance(by_symbol, dict):
                symbol_result = by_symbol.get(symbol)
                if isinstance(symbol_result, dict):
                    paper_status = symbol_result.get("status") or symbol_result.get("message")

        message = _format_buy_setup_message(signal, paper_status)

        summary["buy_alerts_attempted"] += 1
        ok, status = _send_telegram_message(message)

        if ok:
            sent_alerts[fingerprint] = {
                "symbol": symbol,
                "decision": decision,
                "sent_at": _now_iso(),
            }
            summary["buy_alerts_sent"] += 1
            summary["messages"].append(f"{symbol}: BUY SETUP Telegram sent")
        else:
            summary["buy_alerts_suppressed"] += 1
            summary["messages"].append(f"{symbol}: BUY SETUP Telegram not sent - {status}")

    _save_alert_state(state)
    return summary


def process_telegram_alerts(
    signals: list[dict[str, Any]],
    execution_results: dict[str, Any] | None = None,
    max_buy_alerts: int | None = None,
    max_wait_alerts: int | None = None,
) -> dict[str, Any]:
    """
    Backward-compatible wrapper.

    max_wait_alerts is intentionally ignored because Telegram is BUY_SETUP_ONLY.
    """
    return send_buy_setup_alerts(
        signals=signals,
        execution_results=execution_results,
        max_alerts=max_buy_alerts,
    )


def send_alerts(
    signals: list[dict[str, Any]],
    execution_results: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return send_buy_setup_alerts(
        signals=signals,
        execution_results=execution_results,
    )
