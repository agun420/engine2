from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional

from .config import CONFIG

STATE_PATH = Path("state/signal_state.json")
OUTCOMES_PATH = Path("state/outcomes.json")

TRACKED_DECISIONS = {"BUY SETUP", "WAIT"}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None


def load_json(path: Path, default: Dict) -> Dict:
    if not path.exists():
        return default
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else default
    except Exception:
        return default


def save_json(path: Path, data: Dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True))


def load_state() -> Dict:
    return load_json(STATE_PATH, {"signals": {}})


def load_outcomes() -> Dict:
    return load_json(OUTCOMES_PATH, {"closed": [], "stats": {}})


def save_state(state: Dict) -> None:
    save_json(STATE_PATH, state)


def save_outcomes(outcomes: Dict) -> None:
    save_json(OUTCOMES_PATH, outcomes)


def _close_signal(symbol: str, prev: Dict[str, Any], exit_price: float, result: str, reason: str, ts: str) -> Dict[str, Any]:
    entry = float(prev.get("entry", exit_price) or exit_price)
    stop = float(prev.get("stop", entry) or entry)
    target1 = float(prev.get("target1", entry) or entry)
    target2 = float(prev.get("target2", target1) or target1)
    pnl_pct = ((exit_price / entry) - 1) * 100 if entry else 0.0
    opened_at = prev.get("opened_at") or prev.get("first_seen")
    opened_dt = parse_iso(opened_at)
    closed_dt = parse_iso(ts)
    minutes_open = None
    if opened_dt and closed_dt:
        minutes_open = round((closed_dt - opened_dt).total_seconds() / 60, 1)
    return {
        "symbol": symbol,
        "opened_at": opened_at,
        "closed_at": ts,
        "minutes_open": minutes_open,
        "entry": round(entry, 2),
        "stop": round(stop, 2),
        "target1": round(target1, 2),
        "target2": round(target2, 2),
        "exit_price": round(float(exit_price), 2),
        "result": result,
        "reason": reason,
        "pnl_pct_est": round(pnl_pct, 2),
        "opening_decision": prev.get("decision"),
        "opening_status": prev.get("status"),
        "opening_lifecycle": prev.get("lifecycle"),
    }


def _already_recorded(closed: List[Dict[str, Any]], symbol: str, opened_at: Optional[str]) -> bool:
    return any(row.get("symbol") == symbol and row.get("opened_at") == opened_at for row in closed[-50:])


def update_open_signal_outcomes(price_snapshot: Dict[str, float], force_eod_close: bool = False) -> None:
    """Close tracked setups using every available current price, not just dashboard names.

    This fixes the release-candidate weakness where a signal that dropped out of
    the top cards could stay open forever. Any tracked symbol in the scanner
    universe is checked until target, stop, expiration, or end-of-day close.
    """
    ts = now_iso()
    now_dt = parse_iso(ts) or datetime.now(timezone.utc)
    state = load_state()
    outcomes = load_outcomes()
    closed = outcomes.setdefault("closed", [])
    memory = state.setdefault("signals", {})

    for symbol, prev in list(memory.items()):
        if prev.get("closed"):
            continue
        if prev.get("decision") not in TRACKED_DECISIONS:
            continue

        entry = float(prev.get("entry", 0) or 0)
        stop = float(prev.get("stop", 0) or 0)
        target1 = float(prev.get("target1", 0) or 0)
        opened_at = prev.get("opened_at") or prev.get("first_seen")
        opened_dt = parse_iso(opened_at) or now_dt
        age_minutes = (now_dt - opened_dt).total_seconds() / 60
        last_price = float(prev.get("last_price", entry) or entry)
        price = float(price_snapshot.get(symbol, last_price) or last_price)
        close_result = None
        close_reason = None

        if target1 and price >= target1:
            close_result = "TARGET_1_HIT"
            close_reason = "price reached target 1"
        elif stop and price <= stop:
            close_result = "STOP_OR_INVALIDATION"
            close_reason = "price reached stop/invalidation"
        elif force_eod_close:
            close_result = "EOD_CLOSED"
            close_reason = "end-of-day research close"
        elif age_minutes >= CONFIG.signal_ttl_minutes:
            close_result = "EXPIRED"
            close_reason = f"setup expired after {CONFIG.signal_ttl_minutes} minutes"

        if close_result:
            if not _already_recorded(closed, symbol, opened_at):
                closed.append(_close_signal(symbol, prev, price, close_result, close_reason, ts))
            prev["closed"] = True
            prev["closed_at"] = ts
            prev["close_reason"] = close_reason
            prev["lifecycle"] = close_result
        else:
            prev["last_checked_at"] = ts
            prev["last_price"] = round(price, 2)

    outcomes["closed"] = closed[-500:]
    outcomes["stats"] = compute_outcome_stats(outcomes["closed"])
    outcomes["updated_at"] = ts
    save_outcomes(outcomes)
    save_state(state)


def compute_outcome_stats(closed: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not closed:
        return {"sample_size": 0, "target1_rate_pct": None, "avg_pnl_pct_est": None, "expired_rate_pct": None}
    sample = closed[-CONFIG.outcome_lookback_limit:]
    wins = [x for x in sample if x.get("result") == "TARGET_1_HIT"]
    expired = [x for x in sample if x.get("result") == "EXPIRED"]
    avg = sum(float(x.get("pnl_pct_est", 0) or 0) for x in sample) / len(sample)
    last_20 = sample[-20:]
    return {
        "sample_size": len(sample),
        "target1_rate_pct": round((len(wins) / len(sample)) * 100, 1),
        "avg_pnl_pct_est": round(avg, 2),
        "expired_rate_pct": round((len(expired) / len(sample)) * 100, 1),
        "last_20_target1_rate_pct": round((len([x for x in last_20 if x.get("result") == "TARGET_1_HIT"]) / max(1, len(last_20))) * 100, 1),
    }


def attach_outcome_stats(signals: List[Dict]) -> List[Dict]:
    outcomes = load_outcomes()
    stats = outcomes.get("stats", {})
    by_symbol: Dict[str, List[Dict[str, Any]]] = {}
    for row in outcomes.get("closed", []):
        by_symbol.setdefault(row.get("symbol"), []).append(row)
    for sig in signals:
        sym_rows = by_symbol.get(sig["symbol"], [])[-20:]
        wins = [x for x in sym_rows if x.get("result") == "TARGET_1_HIT"]
        sig["outcome_stats"] = {
            "global_sample_size": stats.get("sample_size", 0),
            "global_target1_rate_pct": stats.get("target1_rate_pct"),
            "global_avg_pnl_pct_est": stats.get("avg_pnl_pct_est"),
            "global_expired_rate_pct": stats.get("expired_rate_pct"),
            "symbol_sample_size": len(sym_rows),
            "symbol_target1_rate_pct": None if not sym_rows else round(len(wins) / len(sym_rows) * 100, 1),
        }
    return signals


def apply_signal_memory(signals: List[Dict]) -> List[Dict]:
    state = load_state()
    memory = state.setdefault("signals", {})
    ts = now_iso()
    for sig in signals:
        symbol = sig["symbol"]
        existing = memory.get(symbol, {})
        # If the prior setup already closed, start a fresh lifecycle.
        first_seen = ts if existing.get("closed") else existing.get("first_seen", ts)
        opened_at = ts if existing.get("closed") else existing.get("opened_at", first_seen)
        sig["first_seen"] = first_seen
        sig["last_seen"] = ts
        sig["previous_status"] = None if existing.get("closed") else existing.get("status")
        memory[symbol] = {
            "first_seen": first_seen,
            "opened_at": opened_at,
            "last_seen": ts,
            "last_checked_at": ts,
            "last_price": sig.get("price"),
            "status": sig["status"],
            "decision": sig["decision"],
            "lifecycle": sig.get("lifecycle"),
            "entry": sig["levels"]["entry"],
            "stop": sig["levels"]["stop"],
            "target1": sig["levels"]["target1"],
            "target2": sig["levels"].get("target2"),
            "closed": False,
        }
    state["updated_at"] = ts
    save_state(state)
    return signals
