from __future__ import annotations

import json
import os
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any, List

from .broker.alpaca_paper import submit_bracket_order
from .config import CONFIG
from .alerts.telegram import format_buy_setup_alert, format_wait_setup_alert, send_telegram_message

EXECUTION_STATE_PATH = Path("state/execution_state.json")
ALERT_STATE_PATH = Path("state/alert_state.json")


def _load(path: Path, default: Dict[str, Any]) -> Dict[str, Any]:
    if not path.exists():
        return default
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else default
    except Exception:
        return default


def _save(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True))


def _today_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _signal_key(signal: Dict[str, Any]) -> str:
    levels = signal.get("levels", {}) or {}
    return f"{_today_key()}|{signal.get('symbol')}|{levels.get('entry')}|{levels.get('stop')}|{levels.get('target1')}"


def buy_setups(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [s for s in payload.get("signals", []) if s.get("decision") == "BUY SETUP"]


def wait_setups(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [s for s in payload.get("signals", []) if s.get("decision") == "WAIT"]


def process_buy_setups(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Send Telegram alerts and optionally submit one Alpaca paper order.

    Alerting and execution are intentionally separate:
    - Telegram alert sends for every new BUY SETUP when Telegram secrets exist.
    - Auto paper trade only submits one order per run and only when AUTO_PAPER_TRADE=true.
    """
    setups = buy_setups(payload)[: int(os.getenv("MAX_BUY_ALERTS_PER_RUN") or CONFIG.max_buy_alerts_per_run)]
    waits = wait_setups(payload)[: int(os.getenv("MAX_WAIT_ALERTS_PER_RUN") or CONFIG.max_wait_alerts_per_run)]
    max_notional = float(os.getenv("MAX_NOTIONAL_PER_TRADE") or "2000")
    max_orders_per_run = int(os.getenv("MAX_NEW_ORDERS_PER_RUN") or CONFIG.max_new_orders_per_run)
    ts = datetime.now(timezone.utc).isoformat()

    alert_state = _load(ALERT_STATE_PATH, {"sent_keys": []})
    sent_keys = set(alert_state.get("sent_keys", [])[-500:])
    execution_state = _load(EXECUTION_STATE_PATH, {"orders": []})
    existing_order_keys = {o.get("signal_key") for o in execution_state.get("orders", [])}

    results: List[Dict[str, Any]] = []
    orders_submitted_this_run = 0

    for sig in setups:
        key = _signal_key(sig)
        order_result = None

        if orders_submitted_this_run < max_orders_per_run and key not in existing_order_keys:
            result = submit_bracket_order(sig, max_notional=max_notional)
            order_result = result.to_dict()
            if result.submitted:
                orders_submitted_this_run += 1
            execution_state.setdefault("orders", []).append({
                "ts": ts,
                "signal_key": key,
                "symbol": sig.get("symbol"),
                "result": order_result,
                "levels": sig.get("levels"),
            })
        elif key in existing_order_keys:
            order_result = {"submitted": False, "reason": "skipped: signal already processed for paper order"}
        else:
            order_result = {"submitted": False, "reason": "skipped: max new orders per run reached"}

        alert_result = {"sent": False, "reason": "duplicate alert suppressed"}
        if key not in sent_keys:
            text = format_buy_setup_alert(sig, order_result)
            alert_result = send_telegram_message(text)
            if alert_result.get("sent") or alert_result.get("reason") == "telegram not configured":
                # Record even when Telegram is not configured to avoid local spam loops.
                sent_keys.add(key)

        results.append({
            "symbol": sig.get("symbol"),
            "signal_key": key,
            "order": order_result,
            "telegram": alert_result,
        })


    wait_alerts_attempted = 0
    wait_alerts_sent = 0
    wait_alerts_suppressed = 0
    for sig in waits:
        wait_alerts_attempted += 1
        key = "WAIT|" + _signal_key(sig)
        if key in sent_keys:
            wait_alerts_suppressed += 1
            continue
        alert_result = send_telegram_message(format_wait_setup_alert(sig))
        if alert_result.get("sent"):
            wait_alerts_sent += 1
        elif alert_result.get("reason") == "telegram not configured":
            wait_alerts_suppressed += 1
        if alert_result.get("sent") or alert_result.get("reason") == "telegram not configured":
            sent_keys.add(key)
        results.append({
            "symbol": sig.get("symbol"),
            "signal_key": key,
            "order": {"submitted": False, "reason": "WAIT signals are alert-only"},
            "telegram": alert_result,
        })

    alert_state["sent_keys"] = list(sent_keys)[-500:]
    alert_state["updated_at"] = ts
    execution_state["orders"] = execution_state.get("orders", [])[-500:]
    execution_state["updated_at"] = ts
    execution_state["paper_only"] = True
    _save(ALERT_STATE_PATH, alert_state)
    _save(EXECUTION_STATE_PATH, execution_state)

    return {
        "processed_at": ts,
        "buy_setup_count": len(setups),
        "wait_setup_alert_count": len(waits),
        "wait_alerts_attempted_this_run": wait_alerts_attempted,
        "wait_alerts_sent_this_run": wait_alerts_sent,
        "wait_alerts_suppressed_this_run": wait_alerts_suppressed,
        "orders_submitted_this_run": orders_submitted_this_run,
        "results": results,
        "paper_only": True,
    }
