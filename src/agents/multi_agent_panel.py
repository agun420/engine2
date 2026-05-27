"""Phase 4 — LLM Multi-Agent Management Panel (free LLM: Gemini / Groq).

Uses the free LLM abstraction (Gemini 1.5 Flash → Groq → rule-based fallback)
instead of the paid Anthropic API.  No paid key required.

Three specialised sub-agents debate in sequence:
  • WebResearchAgent      — catalyst freshness and news check
  • InstitutionalAgent   — macro/sector/institutional flow check
  • CrossCheckAgent      — data conflict and model consistency check

The orchestrator then synthesises their verdicts into a consensus decision.
Context compression prevents token exhaustion on free-tier LLMs.
"""
from __future__ import annotations

import json
import logging
import textwrap
from dataclasses import dataclass
from typing import Dict, List

from .free_llm import call_llm, extract_json, llm_available

log = logging.getLogger(__name__)


@dataclass
class AgentVerdict:
    agent: str
    verdict: str
    confidence: float
    reasoning: str
    flags: List[str]


@dataclass
class PanelDecision:
    symbol: str
    final_verdict: str
    consensus_confidence: float
    verdicts: List[AgentVerdict]
    summary: str
    approved_for_execution: bool


# ── Agent system prompts ──────────────────────────────────────────────────────

_WEB_SYSTEM = textwrap.dedent("""
You are the Web Research Agent in a quant trading panel.
Assess whether the current news cycle supports a long entry.
Output ONLY valid JSON: {"verdict":"BUY|PASS|INVESTIGATE",
"confidence":0.0-1.0,"reasoning":"...","flags":["..."]}
Flag "stale_catalyst" if last news > 48 h old.
Flag "negative_headline" for significant negative news.
Keep reasoning under 60 words.
""").strip()

_INST_SYSTEM = textwrap.dedent("""
You are the Institutional Knowledge Agent in a quant trading panel.
Assess macro regime, sector rotation, and institutional accumulation/distribution.
Output ONLY valid JSON: {"verdict":"BUY|PASS|INVESTIGATE",
"confidence":0.0-1.0,"reasoning":"...","flags":["..."]}
Flag "macro_headwind" for hostile rate/inflation environment.
Flag "distribution_pattern" for potential distribution price action.
Keep reasoning under 60 words.
""").strip()

_CROSS_SYSTEM = textwrap.dedent("""
You are the Cross-Checking Agent in a quant trading panel.
Identify data conflicts, model inconsistencies, or red-flags the other agents missed.
Output ONLY valid JSON: {"verdict":"BUY|PASS|INVESTIGATE",
"confidence":0.0-1.0,"reasoning":"...","flags":["..."]}
Flag "data_conflict" if signals contradict each other.
Flag "overfitting_risk" if the signal pattern looks suspiciously clean.
Keep reasoning under 60 words.
""").strip()

_ORCHESTRATOR_SYSTEM = textwrap.dedent("""
You are the Management Panel orchestrator for a quant trading system.
Synthesise three agent verdicts into a final consensus.
Output ONLY valid JSON:
{"final_verdict":"BUY|PASS|INVESTIGATE",
 "consensus_confidence":0.0-1.0,
 "summary":"...",
 "approved_for_execution":true|false}
Approve ONLY if final_verdict is BUY AND consensus_confidence >= 0.65.
Keep summary under 40 words.
""").strip()


def _run_agent(agent_name: str, system: str, brief: str) -> AgentVerdict:
    raw = call_llm(system, brief, max_tokens=256)
    d = extract_json(raw)
    return AgentVerdict(
        agent=agent_name,
        verdict=d.get("verdict", "PASS"),
        confidence=float(d.get("confidence", 0.5)),
        reasoning=d.get("reasoning", "no reasoning"),
        flags=d.get("flags", []),
    )


class MultiAgentPanel:
    """
    Routes a LightGBM-flagged breakout through three agents and returns a
    final consensus.  Works with any free LLM (Gemini / Groq) or falls back
    to keyword heuristics when no key is set.
    """

    def evaluate(self, symbol: str, signal_data: dict) -> PanelDecision:
        brief = self._build_brief(symbol, signal_data)

        web = _run_agent("WebResearchAgent", _WEB_SYSTEM, brief)
        inst = _run_agent("InstitutionalAgent", _INST_SYSTEM, brief)
        cross = _run_agent("CrossCheckAgent", _CROSS_SYSTEM, brief)

        # Build a compact orchestrator input to stay within free-tier context
        orchestrator_input = json.dumps({
            "symbol": symbol,
            "signal_summary": brief[:400],
            "agent_verdicts": [
                {"agent": v.agent, "verdict": v.verdict,
                 "confidence": v.confidence, "flags": v.flags}
                for v in [web, inst, cross]
            ],
        })

        raw = call_llm(_ORCHESTRATOR_SYSTEM, orchestrator_input, max_tokens=200)
        d = extract_json(raw)

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
        """Compress signal metadata into a compact brief to reduce token usage."""
        keys = [
            "decision", "opportunity_score", "entry_score",
            "entry", "stop", "target1", "rr_ratio",
            "vwap_dist_pct", "rel_vol", "day_change_pct",
            "s3_loophole_active", "s3_divergence",
            "lc_galaxy_score", "lc_sentiment", "fear_greed_index",
            "svc_score", "vix_regime", "lightgbm_proba",
            "simcluster_bridging", "simcluster_velocity_delta",
        ]
        subset = {k: data.get(k) for k in keys if data.get(k) is not None}
        return f"Symbol: {symbol}\nKey metrics: {json.dumps(subset)}"
