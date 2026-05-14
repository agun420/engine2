from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, Any, Optional, List
from datetime import datetime
from zoneinfo import ZoneInfo

from ..config import CONFIG


@dataclass
class PaperOrderResult:
    submitted: bool
    symbol: str
    qty: int
    notional_estimate: float
    reason: str
    order_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "submitted": self.submitted,
            "symbol": self.symbol,
            "qty": self.qty,
            "notional_estimate": round(float(self.notional_estimate), 2),
            "reason": self.reason,
            "order_id": self.order_id,
        }




def is_safe_paper_execution_window(now: Optional[datetime] = None) -> tuple[bool, str]:
    """Allow paper entries only in the safer regular-session window.

    GitHub Actions can be delayed or manually triggered. This guard prevents
    bracket orders from being submitted outside the intended New York session.
    """
    now_et = now.astimezone(ZoneInfo("America/New_York")) if now else datetime.now(ZoneInfo("America/New_York"))
    if now_et.weekday() >= 5:
        return False, "skipped: outside regular market days"
    hhmm = now_et.hour * 100 + now_et.minute
    if hhmm < 935:
        return False, "skipped: before safe entry window 9:35 AM ET"
    if hhmm > 1545:
        return False, "skipped: after safe entry window 3:45 PM ET"
    return True, "safe execution window"


def _signal_has_stale_data(signal: Dict[str, Any]) -> bool:
    warnings = [str(w).lower() for w in signal.get("warnings", [])]
    if any("stale" in w for w in warnings):
        return True
    age = signal.get("data_age_minutes")
    try:
        return age is not None and float(age) > CONFIG.stale_data_minutes
    except Exception:
        return False

def paper_trading_enabled() -> bool:
    """Hard opt-in switch for GitHub Actions or local runs.

    The scanner is safe by default. Even though this adapter uses Alpaca paper
    mode only, it will not submit any paper order unless AUTO_PAPER_TRADE=true.
    """
    return os.getenv("AUTO_PAPER_TRADE", "false").strip().lower() == "true"


def _alpaca_credentials_present() -> bool:
    return bool(os.getenv("ALPACA_API_KEY") and os.getenv("ALPACA_SECRET_KEY"))


def _client():
    if not _alpaca_credentials_present():
        raise RuntimeError("Missing ALPACA_API_KEY or ALPACA_SECRET_KEY")
    try:
        from alpaca.trading.client import TradingClient
    except Exception as exc:  # pragma: no cover - depends on optional package install
        raise RuntimeError("alpaca-py is not installed. Run pip install -r requirements.txt") from exc
    return TradingClient(os.environ["ALPACA_API_KEY"], os.environ["ALPACA_SECRET_KEY"], paper=True)


def _open_position_symbols(client) -> set:
    try:
        return {p.symbol for p in client.get_all_positions()}
    except Exception:
        return set()


def _open_order_symbols(client) -> set:
    try:
        return {o.symbol for o in client.get_orders()}
    except Exception:
        return set()


def account_snapshot() -> Dict[str, Any]:
    """Return a minimal Alpaca paper account snapshot for logs/dashboard extensions."""
    if not _alpaca_credentials_present():
        return {"connected": False, "paper": True, "reason": "missing Alpaca secrets"}
    client = _client()
    acct = client.get_account()
    return {
        "connected": True,
        "paper": True,
        "status": getattr(acct, "status", None),
        "buying_power": float(getattr(acct, "buying_power", 0) or 0),
        "equity": float(getattr(acct, "equity", 0) or 0),
        "cash": float(getattr(acct, "cash", 0) or 0),
    }


def submit_bracket_order(signal: Dict[str, Any], max_notional: float, dry_run: bool = False) -> PaperOrderResult:
    """Submit one conservative whole-share Alpaca paper bracket order.

    Safety rules enforced here:
    - paper=True TradingClient only
    - requires AUTO_PAPER_TRADE=true unless dry_run=True
    - long-only market entry
    - whole shares only
    - bracket order with target1 take-profit and stop loss
    - skips if position or open order already exists for the symbol
    - max notional cap
    """
    symbol = str(signal.get("symbol", "")).upper().strip()
    levels = signal.get("levels", {}) or {}
    price = float(signal.get("price") or levels.get("entry") or 0)
    entry = float(levels.get("entry") or price or 0)
    stop = float(levels.get("stop") or 0)
    target1 = float(levels.get("target1") or 0)
    decision = signal.get("decision")
    chase_risk = signal.get("chase_risk")
    entry_score = int(signal.get("entry_score") or 0)

    if decision != "BUY SETUP":
        return PaperOrderResult(False, symbol, 0, 0, "skipped: signal is not BUY SETUP")
    if chase_risk not in {"LOW", "MEDIUM"}:
        return PaperOrderResult(False, symbol, 0, 0, f"skipped: chase risk is {chase_risk}")
    if entry_score < 80:
        return PaperOrderResult(False, symbol, 0, 0, "skipped: entry score below 80")
    if price <= 0 or entry <= 0 or stop <= 0 or target1 <= 0:
        return PaperOrderResult(False, symbol, 0, 0, "skipped: invalid levels")
    if not (stop < entry < target1):
        return PaperOrderResult(False, symbol, 0, 0, "skipped: bracket levels are not valid")

    qty = int(max_notional // price)
    if qty < 1:
        return PaperOrderResult(False, symbol, 0, 0, "skipped: max notional too small for one whole share")
    notional = qty * price

    if dry_run:
        return PaperOrderResult(False, symbol, qty, notional, "dry run: order not submitted")
    if not paper_trading_enabled():
        return PaperOrderResult(False, symbol, qty, notional, "skipped: AUTO_PAPER_TRADE is not true")

    safe_window, safe_reason = is_safe_paper_execution_window()
    if not safe_window:
        return PaperOrderResult(False, symbol, 0, 0, safe_reason)
    if _signal_has_stale_data(signal):
        return PaperOrderResult(False, symbol, 0, 0, "skipped: stale data guard blocked paper order")

    client = _client()
    if symbol in _open_position_symbols(client):
        return PaperOrderResult(False, symbol, 0, 0, "skipped: already holding symbol")
    if symbol in _open_order_symbols(client):
        return PaperOrderResult(False, symbol, 0, 0, "skipped: open order already exists")

    try:
        from alpaca.trading.requests import MarketOrderRequest, TakeProfitRequest, StopLossRequest
        from alpaca.trading.enums import OrderSide, TimeInForce, OrderClass
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("alpaca-py trading classes unavailable") from exc

    order = MarketOrderRequest(
        symbol=symbol,
        qty=qty,
        side=OrderSide.BUY,
        time_in_force=TimeInForce.DAY,
        order_class=OrderClass.BRACKET,
        take_profit=TakeProfitRequest(limit_price=round(target1, 2)),
        stop_loss=StopLossRequest(stop_price=round(stop, 2)),
    )
    submitted = client.submit_order(order_data=order)
    return PaperOrderResult(True, symbol, qty, notional, "submitted Alpaca paper bracket order", str(getattr(submitted, "id", "")))
