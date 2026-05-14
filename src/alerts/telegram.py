from __future__ import annotations

import os
from typing import Dict, Any, Iterable, List
import requests


def telegram_configured() -> bool:
    return bool(os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_CHAT_ID"))


def format_buy_setup_alert(signal: Dict[str, Any], order_result: Dict[str, Any] | None = None) -> str:
    levels = signal.get("levels", {}) or {}
    reasons = signal.get("reasons") or []
    warnings = signal.get("warnings") or []
    reason_text = "; ".join(reasons[:4]) if reasons else "Scanner rules passed."
    warning_text = " | Warnings: " + "; ".join(warnings[:3]) if warnings else ""
    order_text = ""
    if order_result:
        if order_result.get("submitted"):
            order_text = f"\nPaper order: submitted bracket order, qty {order_result.get('qty')}"
        else:
            order_text = f"\nPaper order: {order_result.get('reason')}"
    return (
        f"🚨 BUY SETUP: {signal.get('symbol')}\n"
        f"Price: ${float(signal.get('price', 0)):.2f}\n"
        f"Entry goal: ${float(levels.get('entry', 0)):.2f}\n"
        f"Better entry: ${float(levels.get('better_entry', 0)):.2f}\n"
        f"Stop loss: ${float(levels.get('stop', 0)):.2f}\n"
        f"Sell target 1: ${float(levels.get('target1', 0)):.2f}\n"
        f"Sell target 2: ${float(levels.get('target2', 0)):.2f}\n"
        f"Risk/reward: {float(levels.get('risk_reward', 0)):.2f}\n"
        f"Scores: opportunity {signal.get('opportunity_score')}/100, entry {signal.get('entry_score')}/100\n"
        f"Reason: {reason_text}{warning_text}"
        f"{order_text}\n"
        f"Mode: Alpaca paper/research only."
    )



def format_wait_setup_alert(signal: Dict[str, Any]) -> str:
    levels = signal.get("levels", {}) or {}
    reasons = signal.get("reasons") or []
    warnings = signal.get("warnings") or []
    reason_text = "; ".join(reasons[:4]) if reasons else "Setup is forming, but entry rules are not complete yet."
    warning_text = " | Warnings: " + "; ".join(warnings[:3]) if warnings else ""
    return (
        f"⏳ WAIT SETUP: {signal.get('symbol')}\n"
        f"Do not chase yet.\n"
        f"Price: ${float(signal.get('price', 0)):.2f}\n"
        f"Entry goal: ${float(levels.get('entry', 0)):.2f}\n"
        f"Better entry: ${float(levels.get('better_entry', 0)):.2f}\n"
        f"Stop loss if entered later: ${float(levels.get('stop', 0)):.2f}\n"
        f"Sell target 1: ${float(levels.get('target1', 0)):.2f}\n"
        f"Sell target 2: ${float(levels.get('target2', 0)):.2f}\n"
        f"Scores: opportunity {signal.get('opportunity_score')}/100, entry {signal.get('entry_score')}/100\n"
        f"Reason: {reason_text}{warning_text}\n"
        f"Mode: alert only. No paper order for WAIT signals."
    )

def send_telegram_message(text: str) -> Dict[str, Any]:
    if not telegram_configured():
        return {"sent": False, "reason": "telegram not configured"}
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        response = requests.post(url, json={"chat_id": chat_id, "text": text}, timeout=15)
        if response.ok:
            return {"sent": True, "reason": "sent"}
        return {"sent": False, "reason": f"telegram HTTP {response.status_code}: {response.text[:120]}"}
    except Exception as exc:
        return {"sent": False, "reason": str(exc)}
