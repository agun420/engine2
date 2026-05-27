"""Phase 4 — LLM Multi-Agent Management Panel.

When LightGBM flags a breakout, the signal is routed to three specialised
sub-agents that debate in parallel before reaching consensus:

  • WebResearchAgent      — checks current news & catalyst freshness
  • InstitutionalAgent   — validates macro / sector / institutional trends
  • CrossCheckAgent      — detects data conflicts and model inconsistencies

To bypass context-window exhaustion the orchestrating agent compresses
repetitive context, attaches rich metadata, and only escalates the
summarised brief to the Management Panel for debate.
"""
from __future__ import annotations

import json
import logging
import os
import textwrap
from dataclasses import dataclass
from typing import Dict, List, Optional

import requests

log = logging.getLogger(__name__)

_ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY", "")
_MODEL = os.getenv("PANEL_LLM_MODEL", "claude-sonnet-4-6")
_CLAUDE_API = "https://api.anthropic.com/v1/messages"


# ------------------------------------------------------------------ #
# Data structures                                                     #
# ------------------------------------------------------------------ #

@dataclass
class AgentVerdict:
    agent: str
    verdict: str            # BUY / PASS / INVESTIGATE
    confidence: float       # 0-1
    reasoning: str
    flags: List[str]


@dataclass
class PanelDecision:
    symbol: str
    final_verdict: str      # BUY / PASS / INVESTIGATE
    consensus_confidence: float
    verdicts: List[AgentVerdict]
    summary: str
    approved_for_execution: bool


# ------------------------------------------------------------------ #
# Helper: Claude call                                                 #
# ------------------------------------------------------------------ #

def _call_claude(system: str, user: str, max_tokens: int = 512) -> str:
    if not _ANTHROPIC_KEY:
        return json.dumps({"verdict": "PASS", "confidence": 0.5,
                           "reasoning": "LLM not available", "flags": []})
    try:
        resp = requests.post(
            _CLAUDE_API,
            headers={
                "x-api-key": _ANTHROPIC_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": _MODEL,
                "max_tokens": max_tokens,
                "system": system,
                "messages": [{"role": "user", "content": user}],
            },
            timeout=45,
        )
        resp.raise_for_status()
        return resp.json()["content"][0]["text"]
    except Exception as exc:  # noqa: BLE001
        log.error("Claude API error: %s", exc)
        return json.dumps({"verdict": "PASS", "confidence": 0.3,
                           "reasoning": f"API error: {exc}", "flags": ["api_error"]})


# ------------------------------------------------------------------ #
# Individual agents                                                   #
# ------------------------------------------------------------------ #

_WEB_SYSTEM = textwrap.dedent("""
You are the Web Research Agent in a quant trading panel.
Your job: assess whether the current news cycle supports a long entry.
Output ONLY valid JSON: {"verdict":"BUY|PASS|INVESTIGATE",
"confidence":0.0-1.0,"reasoning":"...","flags":["..."]}
Flag: "stale_catalyst" if the last news event is >48 h old.
Flag: "negative_headline" if there is a significant negative headline.
""").strip()

_INST_SYSTEM = textwrap.dedent("""
You are the Institutional Knowledge Agent in a quant trading panel.
Your job: assess macro regime, sector rotation, and whether institutions
are likely accumulating or distributing this ticker.
Output ONLY valid JSON: {"verdict":"BUY|PASS|INVESTIGATE",
"confidence":0.0-1.0,"reasoning":"...","flags":["..."]}
Flag: "macro_headwind" if rate/inflation environment is hostile to the sector.
Flag: "distribution_pattern" if the price action shows potential distribution.
""").strip()

_CROSS_SYSTEM = textwrap.dedent("""
You are the Cross-Checking Agent in a quant trading panel.
Your job: identify data conflicts, model inconsistencies, or red-flags that
the other agents may have missed.
Output ONLY valid JSON: {"verdict":"BUY|PASS|INVESTIGATE",
"confidence":0.0-1.0,"reasoning":"...","flags":["..."]}
Flag: "data_conflict" if signals contradict each other.
Flag: "overfitting_risk" if the signal pattern is suspiciously clean.
""").strip()


def _run_agent(agent_name: str, system: str, brief: str) -> AgentVerdict:
    raw = _call_claude(system, brief)
    try:
        import re
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        d: Dict = json.loads(match.group()) if match else {}
    except Exception:  # noqa: BLE001
        d = {}
    return AgentVerdict(
        agent=agent_name,
        verdict=d.get("verdict", "PASS"),
        confidence=float(d.get("confidence", 0.5)),
        reasoning=d.get("reasoning", "parse error"),
        flags=d.get("flags", []),
    )


# ------------------------------------------------------------------ #
# Orchestrator                                                        #
# ------------------------------------------------------------------ #

_ORCHESTRATOR_SYSTEM = textwrap.dedent("""
You are the Management Panel orchestrator for a quantitative trading system.
You receive a compressed brief and verdicts from three specialised agents.
Your task: synthesise the verdicts into a final consensus decision.
Output ONLY valid JSON:
{"final_verdict":"BUY|PASS|INVESTIGATE",
 "consensus_confidence":0.0-1.0,
 "summary":"...",
 "approved_for_execution":true|false}
Approve for execution ONLY if final_verdict is BUY AND consensus_confidence >= 0.65.
""").strip()


class MultiAgentPanel:
    """
    Routes a LightGBM-flagged breakout signal through a three-agent debate
    and returns a final consensus decision.
    """

    def evaluate(self, symbol: str, signal_data: dict) -> PanelDecision:
        # --- Compress context to avoid token exhaustion ---
        brief = self._build_brief(symbol, signal_data)

        # --- Parallel agent opinions (sequential calls here; use threading for prod) ---
        web = _run_agent("WebResearchAgent", _WEB_SYSTEM, brief)
        inst = _run_agent("InstitutionalAgent", _INST_SYSTEM, brief)
        cross = _run_agent("CrossCheckAgent", _CROSS_SYSTEM, brief)

        # --- Management Panel synthesis ---
        panel_input = json.dumps({
            "symbol": symbol,
            "brief_summary": brief[:600],
            "agent_verdicts": [
                {"agent": v.agent, "verdict": v.verdict,
                 "confidence": v.confidence, "flags": v.flags}
                for v in [web, inst, cross]
            ],
        })
        raw = _call_claude(_ORCHESTRATOR_SYSTEM, panel_input, max_tokens=256)
        try:
            import re
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            d: Dict = json.loads(match.group()) if match else {}
        except Exception:  # noqa: BLE001
            d = {}

        return PanelDecision(
            symbol=symbol,
            final_verdict=d.get("final_verdict", "PASS"),
            consensus_confidence=float(d.get("consensus_confidence", 0.5)),
            verdicts=[web, inst, cross],
            summary=d.get("summary", ""),
            approved_for_execution=bool(d.get("approved_for_execution", False)),
        )

    @staticmethod
    def _build_brief(symbol: str, data: dict) -> str:
        """Compress signal metadata into a concise brief for the agents."""
        keys = [
            "decision", "score", "entry", "stop", "target1",
            "rr_ratio", "vwap_dist_pct", "rel_vol",
            "s3_loophole_active", "s3_divergence",
            "lc_galaxy_score", "lc_sentiment",
            "lstm_signal", "svc_score",
            "lightgbm_proba", "market_regime",
        ]
        subset = {k: data.get(k) for k in keys if k in data}
        return (
            f"Symbol: {symbol}\n"
            f"LightGBM breakout flagged. Key metrics:\n"
            f"{json.dumps(subset, indent=2)}"
        )
