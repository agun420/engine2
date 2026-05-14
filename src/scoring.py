from __future__ import annotations

from typing import Dict, Tuple, List, Optional
import pandas as pd
import numpy as np

from .config import CONFIG

CHASE_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "EXTREME": 3}


def pct(a: float, b: float) -> float:
    if b == 0 or np.isnan(b):
        return 0.0
    return (a / b - 1) * 100


def confidence_label(entry_score: int, opportunity_score: int) -> str:
    avg = (entry_score + opportunity_score) / 2
    if avg >= 88:
        return "HIGH"
    if avg >= 76:
        return "MEDIUM-HIGH"
    if avg >= 62:
        return "MEDIUM"
    return "LOW"


def classify_chase_risk(vwap_distance_pct: float, atr_pct: float, rsi: float, day_change_pct: float) -> str:
    risk_points = 0
    if vwap_distance_pct > 3.0:
        risk_points += 1
    if vwap_distance_pct > 6.0:
        risk_points += 1
    if atr_pct > 6.5:
        risk_points += 1
    if rsi > 74:
        risk_points += 1
    if day_change_pct > 11:
        risk_points += 1
    if risk_points <= 1:
        return "LOW"
    if risk_points == 2:
        return "MEDIUM"
    if risk_points == 3:
        return "HIGH"
    return "EXTREME"


def classify_tradeability(dollar_volume: float, spread_pct_est: float, price: float) -> Tuple[str, List[str]]:
    warnings: List[str] = []
    if dollar_volume < CONFIG.min_dollar_volume:
        warnings.append("Low dollar volume")
    if spread_pct_est > CONFIG.max_estimated_spread_pct:
        warnings.append("Estimated spread/range is wide")
    if price < 5:
        warnings.append("Lower-priced stock; size carefully")
    if warnings:
        return "WEAK", warnings
    if dollar_volume > 100_000_000 and spread_pct_est <= 0.35:
        return "STRONG", []
    return "OK", []


def catalyst_quality(symbol: str) -> str:
    """Conservative placeholder until a real news API is wired.

    Keep unknown catalysts from inflating scores. A future upgrade can classify
    earnings, FDA, contract wins, analyst changes, and social/news velocity.
    """
    return "UNKNOWN"




def grade_score(score: int) -> str:
    if score >= 85:
        return "A"
    if score >= 75:
        return "B"
    if score >= 60:
        return "C"
    if score >= 45:
        return "D"
    return "F"


def _clamp_score(value: float) -> int:
    return int(max(0, min(100, round(value))))


def build_advanced_breakdown(
    *,
    catalyst: str,
    price: float,
    vwap: float,
    ema9: float,
    ema20: float,
    rsi: float,
    day_change_pct: float,
    volume_ratio: float,
    dollar_volume: float,
    spread_pct_est: float,
    vwap_distance_pct: float,
    atr_pct: float,
    risk_reward: float,
    chase_risk: str,
    tradeability: str,
    sector_context: Dict,
    recent_breakout: bool,
) -> Dict:
    """Return a human-readable advanced factor report.

    This keeps the beginner dashboard simple while preserving the deeper
    scanner logic that advanced users expect to inspect. Scores are diagnostic
    only; hard safety filters still control BUY/WAIT/AVOID decisions.
    """
    cat_base = {"A+": 95, "A": 88, "B": 76, "C": 62, "UNKNOWN": 45}.get(catalyst, 45)

    technical = 0
    tech_notes = []
    if price >= vwap:
        technical += 24; tech_notes.append("above VWAP")
    else:
        tech_notes.append("below VWAP")
    if price >= ema9:
        technical += 18; tech_notes.append("above EMA9")
    if price >= ema20:
        technical += 18; tech_notes.append("above EMA20")
    if 45 <= rsi <= 70:
        technical += 20; tech_notes.append("RSI healthy")
    elif rsi > 74:
        technical += 6; tech_notes.append("RSI hot")
    else:
        technical += 10; tech_notes.append("RSI weak/neutral")
    if recent_breakout:
        technical += 20; tech_notes.append("short-term breakout")

    volume_liquidity = 0
    vol_notes = []
    if volume_ratio >= 2.0:
        volume_liquidity += 35; vol_notes.append("strong volume expansion")
    elif volume_ratio >= 1.2:
        volume_liquidity += 25; vol_notes.append("volume expansion")
    else:
        volume_liquidity += 12; vol_notes.append("volume not expanded")
    if dollar_volume >= 100_000_000:
        volume_liquidity += 35; vol_notes.append("high dollar volume")
    elif dollar_volume >= CONFIG.min_dollar_volume:
        volume_liquidity += 25; vol_notes.append("liquid enough")
    else:
        volume_liquidity += 5; vol_notes.append("thin liquidity")
    if spread_pct_est <= CONFIG.max_estimated_spread_pct:
        volume_liquidity += 30; vol_notes.append("spread/range acceptable")
    elif spread_pct_est <= CONFIG.max_estimated_spread_pct * 2:
        volume_liquidity += 15; vol_notes.append("spread/range elevated")
    else:
        volume_liquidity += 2; vol_notes.append("spread/range too wide")

    relative_strength = 0
    rs_notes = []
    if day_change_pct >= 6:
        relative_strength += 38; rs_notes.append("strong intraday relative move")
    elif day_change_pct >= 2:
        relative_strength += 26; rs_notes.append("positive intraday relative move")
    elif day_change_pct > 0:
        relative_strength += 14; rs_notes.append("slightly positive")
    else:
        relative_strength += 4; rs_notes.append("not outperforming intraday")
    sector_vs_spy = sector_context.get("sector_vs_spy_pct")
    try:
        sector_vs_spy = float(sector_vs_spy)
        if sector_vs_spy > 0.5:
            relative_strength += 24; rs_notes.append("sector beating SPY")
        elif sector_vs_spy >= 0:
            relative_strength += 16; rs_notes.append("sector inline/slightly ahead")
        else:
            relative_strength += 6; rs_notes.append("sector lagging SPY")
    except Exception:
        relative_strength += 10; rs_notes.append("sector comparison unavailable")
    if price >= ema20:
        relative_strength += 18; rs_notes.append("above short trend")
    if volume_ratio >= 1.2:
        relative_strength += 20; rs_notes.append("move has volume support")

    sector_market = 50
    sector_notes = []
    regime = sector_context.get("market_regime", "UNKNOWN")
    if regime == "RISK-ON":
        sector_market += 18; sector_notes.append("market risk-on")
    elif regime == "RISK-OFF":
        sector_market -= 18; sector_notes.append("market risk-off")
    else:
        sector_notes.append("market regime mixed/unknown")
    if sector_context.get("sector_etf"):
        sector_notes.append(f"sector ETF {sector_context.get('sector_etf')}")
    try:
        if float(sector_context.get("sector_change_pct", 0)) > 0:
            sector_market += 12; sector_notes.append("sector positive")
    except Exception:
        pass
    try:
        if float(sector_context.get("sector_vs_spy_pct", 0)) > 0:
            sector_market += 10; sector_notes.append("sector leading SPY")
    except Exception:
        pass

    risk_quality = 100
    risk_notes = []
    chase_penalty = {"LOW": 0, "MEDIUM": 14, "HIGH": 32, "EXTREME": 48}.get(chase_risk, 20)
    risk_quality -= chase_penalty
    risk_notes.append(f"chase risk {chase_risk}")
    if atr_pct > 6.5:
        risk_quality -= 18; risk_notes.append("volatility high")
    elif atr_pct <= 4.5:
        risk_quality += 4; risk_notes.append("volatility manageable")
    if risk_reward >= 2.0:
        risk_quality += 12; risk_notes.append("strong RR")
    elif risk_reward >= CONFIG.min_risk_reward_for_buy:
        risk_quality += 4; risk_notes.append("RR acceptable")
    else:
        risk_quality -= 20; risk_notes.append("RR weak")
    if tradeability == "WEAK":
        risk_quality -= 24; risk_notes.append("tradeability weak")
    elif tradeability == "STRONG":
        risk_quality += 8; risk_notes.append("tradeability strong")

    execution_timing = 50
    timing_notes = []
    if 0 <= vwap_distance_pct <= CONFIG.max_vwap_extension_pct_for_buy:
        execution_timing += 24; timing_notes.append("near valid VWAP extension")
    elif vwap_distance_pct > CONFIG.max_vwap_extension_pct_for_buy:
        execution_timing -= 22; timing_notes.append("too far above VWAP")
    else:
        execution_timing -= 8; timing_notes.append("below VWAP")
    if recent_breakout:
        execution_timing += 14; timing_notes.append("breakout timing")
    if price >= ema9:
        execution_timing += 12; timing_notes.append("holding EMA9")
    if chase_risk in {"HIGH", "EXTREME"}:
        execution_timing -= 18; timing_notes.append("timing may be late")

    raw = {
        "catalyst": (cat_base, [f"catalyst quality: {catalyst.lower()}"]),
        "technical": (technical, tech_notes),
        "volume_liquidity": (volume_liquidity, vol_notes),
        "relative_strength": (relative_strength, rs_notes),
        "sector_market": (sector_market, sector_notes),
        "risk_quality": (risk_quality, risk_notes),
        "execution_timing": (execution_timing, timing_notes),
    }
    factors = {}
    for name, (score, notes) in raw.items():
        clean = _clamp_score(score)
        factors[name] = {
            "score": clean,
            "grade": grade_score(clean),
            "notes": notes[:4],
        }
    composite = _clamp_score(sum(v["score"] for v in factors.values()) / max(len(factors), 1))
    return {
        "composite": composite,
        "grade": grade_score(composite),
        "summary": "Advanced view explains the score drivers; the simple BUY/WAIT decision still controls action.",
        "factors": factors,
    }

def _clean_level(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    try:
        value = float(value)
    except Exception:
        return None
    if not np.isfinite(value) or value <= 0:
        return None
    return value


def compute_levels(
    price: float,
    vwap: float,
    ema9: float,
    atr: float,
    recent_high: Optional[float] = None,
    day_high: Optional[float] = None,
    prior_day_high: Optional[float] = None,
    prior_close: Optional[float] = None,
) -> Tuple[Dict[str, float], List[str]]:
    """Build beginner levels using chart structure first, formulas second.

    A previous beta used target = entry + risk * fixed_rr. That made the
    risk/reward filter nearly meaningless. This version uses actual resistance
    candidates first: recent high, day high, prior-day high, gap-fill/prior close.
    ATR-based targets are only fallback/stretch candidates.
    """
    warnings: List[str] = []
    price = max(float(price), 0.01)
    vwap = max(float(vwap), 0.01)
    ema9 = max(float(ema9), 0.01)
    atr = max(float(atr), price * 0.005)

    support = max(min(vwap, ema9), 0.01)
    better_entry = max(support, price - CONFIG.wait_pullback_atr_mult * atr)
    entry = price if price >= support else support

    structural_stop = min(vwap, ema9) - (CONFIG.atr_stop_mult * atr)
    hard_max_stop = entry * (1 - CONFIG.max_stop_pct)
    stop = max(structural_stop, hard_max_stop)
    stop = min(stop, entry - 0.01)
    risk = max(entry - stop, 0.01)

    candidates = []
    for label, value in [
        ("recent high", recent_high),
        ("day high", day_high),
        ("prior day high", prior_day_high),
        ("prior close/gap fill", prior_close),
        ("ATR extension", entry + atr),
        ("stretch ATR extension", entry + 1.75 * atr),
    ]:
        level = _clean_level(value)
        if level is not None and level > entry + max(0.03, 0.12 * atr):
            candidates.append((level, label))

    candidates = sorted(candidates, key=lambda item: item[0])
    if candidates:
        target1, target1_source = candidates[0]
        target2, target2_source = (candidates[1] if len(candidates) > 1 else (entry + max(2.0 * atr, 2.0 * risk), "stretch target"))
    else:
        target1 = entry + max(0.85 * atr, 1.05 * risk)
        target2 = entry + max(1.6 * atr, 1.8 * risk)
        target1_source = "fallback ATR target"
        target2_source = "fallback ATR stretch"
        warnings.append("No clear overhead resistance found; targets are ATR estimates")

    # Ensure target 2 is above target 1.
    if target2 <= target1:
        target2 = target1 + max(0.6 * atr, 0.8 * risk)
        target2_source = "adjusted stretch target"

    rr = (target1 - entry) / risk if risk > 0 else 0
    invalidation = stop

    if stop >= entry:
        warnings.append("Stop is too close or invalid")
    if (entry - stop) / max(entry, 0.01) > CONFIG.max_stop_pct:
        warnings.append("Wide stop; reduce size or wait")
    if rr < CONFIG.min_risk_reward_for_buy:
        warnings.append("Risk/reward not attractive enough")

    return {
        "entry": round(entry, 2),
        "stop": round(stop, 2),
        "target1": round(target1, 2),
        "target2": round(target2, 2),
        "risk_reward": round(rr, 2),
        "better_entry": round(better_entry, 2),
        "invalidation": round(invalidation, 2),
        "target1_source": target1_source,
        "target2_source": target2_source,
    }, warnings


def action_text(decision: str, status: str, levels: Dict[str, float], warnings: List[str]) -> str:
    if decision == "BUY SETUP":
        return f"Buy setup only near ${levels['entry']:.2f}. Stop below ${levels['stop']:.2f}. First target ${levels['target1']:.2f}."
    if decision == "WAIT":
        if any("extended" in w.lower() or "pullback" in w.lower() for w in warnings):
            return f"Wait. Do not chase. Better entry is near ${levels['better_entry']:.2f}; invalid below ${levels['invalidation']:.2f}."
        if levels.get("risk_reward", 0) < CONFIG.min_risk_reward_for_buy:
            return f"Wait. Risk/reward is weak. Needs cleaner entry near ${levels['better_entry']:.2f} or higher target confirmation."
        return f"Wait for confirmation near ${levels['entry']:.2f}. Avoid if it loses ${levels['invalidation']:.2f}."
    if decision == "AVOID":
        return "Avoid. The setup failed a hard safety filter."
    return "Watch only. Not enough confirmation for a buy setup."


def lifecycle_from_decision(decision: str, status: str) -> str:
    if decision == "BUY SETUP":
        return "TRIGGER_READY"
    if decision == "WAIT" and status == "TOO EXTENDED":
        return "WAIT_FOR_PULLBACK"
    if decision == "WAIT":
        return "SETUP_FORMING"
    if decision == "AVOID":
        return "INVALIDATED"
    return "WATCH_ONLY"


def score_symbol(symbol: str, intraday: pd.DataFrame, daily: pd.DataFrame, spread_pct_est: float = 0.0, data_age_minutes=None, data_source="Yahoo Finance", sector_context: Optional[Dict] = None) -> Dict:
    latest = intraday.iloc[-1]
    first = intraday.iloc[0]
    price = float(latest["Close"])
    vwap = float(latest.get("VWAP", price))
    ema9 = float(latest.get("EMA9", price))
    ema20 = float(latest.get("EMA20", price))
    atr = float(latest.get("ATR14", price * 0.02))
    rsi = float(latest.get("RSI14", 50))
    vol_ma = float(latest.get("VOL_MA20", latest["Volume"]))
    volume_ratio = float(latest["Volume"] / vol_ma) if vol_ma > 0 else 1.0
    day_change_pct = pct(price, float(first["Open"]))
    vwap_distance_pct = pct(price, vwap)
    ema9_distance_pct = pct(price, ema9)
    atr_pct = (atr / price) * 100 if price else 0.0
    avg_daily_volume = float(daily["Volume"].tail(20).mean())
    dollar_volume = float(avg_daily_volume * price)

    # Chart structure targets.
    recent_high = float(intraday["High"].tail(12).max()) if len(intraday) >= 12 else float(intraday["High"].max())
    day_high = float(intraday["High"].max())
    prior_day_high = float(daily["High"].iloc[-2]) if len(daily) >= 2 else None
    prior_close = float(daily["Close"].iloc[-2]) if len(daily) >= 2 else None

    opportunity = 0
    entry_score = 0
    reasons: List[str] = []
    warnings: List[str] = []
    sector_context = sector_context or {}

    # Opportunity score: should this be on the desk?
    if day_change_pct > 1.0:
        opportunity += 16; reasons.append("Positive intraday move")
    if day_change_pct > 4.0:
        opportunity += 12; reasons.append("Strong momentum")
    if volume_ratio > 1.2:
        opportunity += 15; reasons.append("Volume expansion")
    if price > vwap:
        opportunity += 13; reasons.append("Above VWAP")
    if price > ema20:
        opportunity += 10; reasons.append("Above EMA20")
    if dollar_volume >= CONFIG.min_dollar_volume:
        opportunity += 12; reasons.append("Liquid enough")
    if 45 <= rsi <= 72:
        opportunity += 8; reasons.append("RSI in healthy zone")
    if daily["Close"].iloc[-1] > daily["Close"].rolling(20).mean().iloc[-1]:
        opportunity += 10; reasons.append("Daily trend supportive")
    if spread_pct_est <= CONFIG.max_estimated_spread_pct:
        opportunity += 4; reasons.append("Tradable range/spread estimate")

    # Market / sector context: small boost only. Never lets a bad entry bypass risk rules.
    try:
        from .market_context import sector_boost
        boost, sector_reasons = sector_boost(sector_context)
        opportunity += boost
        reasons.extend(sector_reasons)
        if sector_context.get("market_regime") == "RISK-OFF":
            warnings.append("Market regime is risk-off; be more selective")
    except Exception:
        pass

    # Entry score: is it buyable now?
    if price >= vwap:
        entry_score += 18
    if price >= ema9:
        entry_score += 14
    if volume_ratio >= 1.0:
        entry_score += 12
    if 0 <= vwap_distance_pct <= CONFIG.max_vwap_extension_pct_for_buy:
        entry_score += 20
    elif vwap_distance_pct > CONFIG.max_vwap_extension_pct_for_buy:
        warnings.append("Too extended above VWAP")
    if atr_pct <= 6.0:
        entry_score += 10
    else:
        warnings.append("High volatility")
    if 45 <= rsi <= 70:
        entry_score += 10
    elif rsi > 74:
        warnings.append("RSI is overheated")
    recent_breakout = bool(len(intraday) > 12 and price > float(intraday["High"].rolling(10).max().iloc[-2]))
    if recent_breakout:
        entry_score += 10; reasons.append("Breaking short-term high")
    if dollar_volume >= CONFIG.min_dollar_volume:
        entry_score += 6
    if spread_pct_est <= CONFIG.max_estimated_spread_pct:
        entry_score += 4

    chase_risk = classify_chase_risk(vwap_distance_pct, atr_pct, rsi, day_change_pct)
    tradeability, trade_warnings = classify_tradeability(dollar_volume, spread_pct_est, price)
    warnings.extend(trade_warnings)
    levels, level_warnings = compute_levels(price, vwap, ema9, atr, recent_high, day_high, prior_day_high, prior_close)
    warnings.extend(level_warnings)

    catalyst = catalyst_quality(symbol)
    advanced_breakdown = build_advanced_breakdown(
        catalyst=catalyst,
        price=price,
        vwap=vwap,
        ema9=ema9,
        ema20=ema20,
        rsi=rsi,
        day_change_pct=day_change_pct,
        volume_ratio=volume_ratio,
        dollar_volume=dollar_volume,
        spread_pct_est=spread_pct_est,
        vwap_distance_pct=vwap_distance_pct,
        atr_pct=atr_pct,
        risk_reward=levels["risk_reward"],
        chase_risk=chase_risk,
        tradeability=tradeability,
        sector_context=sector_context,
        recent_breakout=recent_breakout,
    )

    decision = "WATCH ONLY"
    status = "LOW CONFIRMATION"

    if price < CONFIG.min_price or price > CONFIG.max_price:
        decision = "AVOID"; status = "FILTERED"; warnings.append("Outside price range")
    elif dollar_volume < CONFIG.min_dollar_volume:
        decision = "AVOID"; status = "LOW LIQUIDITY"; warnings.append("Dollar volume too low")
    elif spread_pct_est > CONFIG.max_estimated_spread_pct * 2.25:
        decision = "AVOID"; status = "TOO WIDE"; warnings.append("Range/spread estimate too wide")
    elif CHASE_ORDER[chase_risk] > CHASE_ORDER[CONFIG.max_chase_risk_for_buy]:
        decision = "WAIT"; status = "TOO EXTENDED"; warnings.append("Wait for pullback")
    elif levels["risk_reward"] < CONFIG.min_risk_reward_for_buy:
        decision = "WAIT"; status = "WEAK RISK/REWARD"; warnings.append("Risk/reward not attractive")
    elif opportunity >= CONFIG.buy_min_opportunity_score and entry_score >= CONFIG.buy_min_entry_score and tradeability != "WEAK":
        decision = "BUY SETUP"; status = "TRIGGER READY"
    elif opportunity >= CONFIG.watch_min_opportunity_score:
        decision = "WAIT"; status = "WATCHLIST"
    else:
        decision = "WATCH ONLY"; status = "LOW CONFIRMATION"

    opp = int(min(opportunity, 100))
    ent = int(min(entry_score, 100))
    lifecycle = lifecycle_from_decision(decision, status)

    return {
        "symbol": symbol,
        "price": round(price, 2),
        "decision": decision,
        "status": status,
        "lifecycle": lifecycle,
        "action_text": action_text(decision, status, levels, warnings),
        "opportunity_score": opp,
        "entry_score": ent,
        "confidence_label": confidence_label(ent, opp),
        "chase_risk": chase_risk,
        "tradeability": tradeability,
        "catalyst_quality": catalyst,
        "advanced_breakdown": advanced_breakdown,
        "levels": levels,
        "day_change_pct": round(day_change_pct, 2),
        "vwap_distance_pct": round(vwap_distance_pct, 2),
        "ema9_distance_pct": round(ema9_distance_pct, 2),
        "volume_ratio": round(volume_ratio, 2),
        "dollar_volume": round(dollar_volume, 2),
        "atr_pct": round(atr_pct, 2),
        "spread_pct_est": round(spread_pct_est, 3),
        "sector_context": sector_context,
        "data_source": data_source,
        "data_age_minutes": None if data_age_minutes is None else round(float(data_age_minutes), 1),
        "outcome_stats": {},
        "reasons": reasons[:8],
        "warnings": list(dict.fromkeys(warnings))[:8],
    }
