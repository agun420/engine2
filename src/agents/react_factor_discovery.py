"""Phase 3 — ReAct autonomous factor discovery with economic regularisation.

Uses the free LLM abstraction (Gemini 1.5 Flash → Groq → rule-based fallback)
instead of the paid Anthropic API.  No paid key required.

The agent follows the Reasoning-Action (ReAct) pattern:
  1. THINK  — articulate a valid economic rationale.
  2. ACT    — generate a mathematical factor formula in Python.
  3. OBSERVE — back-test the factor on held-out data.
  4. REFLECT — keep only factors where |t-stat| > 3.0 AND the economic
               rationale is substantive (prevents spurious curve-fitting).
"""
from __future__ import annotations

import json
import logging
import re
import textwrap
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .free_llm import call_llm, extract_json, llm_available

log = logging.getLogger(__name__)

_SYSTEM_PROMPT = textwrap.dedent("""
You are an autonomous quantitative researcher using the ReAct framework.
For every factor you propose you MUST:
1. State a clear, falsifiable ECONOMIC RATIONALE (why this factor should
   predict future returns — not just a statistical observation).
2. Only then write Python code that computes the factor from a pandas
   DataFrame with columns: Open, High, Low, Close, Volume.
3. Enforce the "Friction Adjusted Flow Shock" principle: penalise factors
   that imply daily turnover > 100 % unless the alpha cushion exceeds
   realistic slippage (assume 10 bps round-trip).

Output format — ALWAYS a valid JSON object:
{
  "rationale": "<economic rationale, min 30 words>",
  "factor_name": "<snake_case_name>",
  "formula_code": "<python function: def factor(df): ... return pd.Series>",
  "expected_direction": "long_positive | short_positive | mixed",
  "high_turnover_risk": true | false
}
""").strip()


@dataclass
class DiscoveredFactor:
    factor_name: str
    rationale: str
    formula_code: str
    expected_direction: str
    high_turnover_risk: bool
    t_stat: Optional[float] = None
    sharpe: Optional[float] = None
    deflated_sharpe: Optional[float] = None
    accepted: bool = False
    reject_reason: str = ""


class ReActFactorAgent:
    """
    Iteratively discover and validate alpha factors using a free LLM
    (Gemini 1.5 Flash or Groq), with strict economic regularisation and
    the |t|>3.0 Deflated Sharpe hurdle.
    """

    def __init__(self, max_iterations: int = 10) -> None:
        self.max_iterations = max_iterations
        self._accepted: List[DiscoveredFactor] = []
        self._rejected: List[DiscoveredFactor] = []
        self._trial_count: int = 0

    @property
    def accepted_factors(self) -> List[DiscoveredFactor]:
        return list(self._accepted)

    def run(self, df_train, df_test, context_hint: str = "") -> List[DiscoveredFactor]:
        feedback = ""
        for i in range(self.max_iterations):
            log.info("ReAct iteration %d / %d", i + 1, self.max_iterations)
            factor = self._propose_factor(context_hint, feedback)
            if factor is None:
                log.warning("No usable factor returned — stopping early")
                break
            self._trial_count += 1
            self._validate(factor, df_train, df_test)
            if factor.accepted:
                self._accepted.append(factor)
                feedback = (
                    f"Factor '{factor.factor_name}' ACCEPTED "
                    f"(t={factor.t_stat:.2f}, DSR={factor.deflated_sharpe:.3f}). "
                    "Propose an uncorrelated complementary factor next."
                )
            else:
                self._rejected.append(factor)
                feedback = (
                    f"Factor '{factor.factor_name}' REJECTED: {factor.reject_reason}. "
                    "Revise the economic rationale or formula."
                )
        log.info(
            "ReAct complete — %d accepted, %d rejected across %d trials",
            len(self._accepted), len(self._rejected), self._trial_count,
        )
        return self._accepted

    # ------------------------------------------------------------------ #
    # LLM interaction                                                     #
    # ------------------------------------------------------------------ #

    def _propose_factor(self, hint: str, feedback: str) -> Optional[DiscoveredFactor]:
        user_msg = ""
        if hint:
            user_msg += f"Dataset context: {hint}\n\n"
        if feedback:
            user_msg += f"Previous attempt feedback: {feedback}\n\n"
        user_msg += "Propose the next alpha factor. Return ONLY the JSON object."

        raw = call_llm(_SYSTEM_PROMPT, user_msg, max_tokens=800)
        if not raw:
            return self._stub_factor()
        factor = self._parse_factor(raw)
        return factor if factor else self._stub_factor()

    @staticmethod
    def _parse_factor(text: str) -> Optional[DiscoveredFactor]:
        d = extract_json(text)
        if not d:
            return None
        rationale = d.get("rationale", "")
        if len(str(rationale).split()) < 10:
            log.warning("Factor rejected at parse: rationale too short")
            return None
        return DiscoveredFactor(
            factor_name=d.get("factor_name", "unnamed_factor"),
            rationale=str(rationale),
            formula_code=d.get("formula_code", ""),
            expected_direction=d.get("expected_direction", "mixed"),
            high_turnover_risk=bool(d.get("high_turnover_risk", False)),
        )

    # ------------------------------------------------------------------ #
    # Validation                                                          #
    # ------------------------------------------------------------------ #

    def _validate(self, factor: DiscoveredFactor, df_train, df_test) -> None:
        from src.backtest_v2.deflated_sharpe import t_stat_hurdle_passed, deflated_sharpe_ratio

        if factor.high_turnover_risk and "friction" not in factor.rationale.lower():
            factor.reject_reason = "High-turnover factor without friction analysis in rationale"
            return

        values_train = self._compute_factor(factor.formula_code, df_train)
        values_test = self._compute_factor(factor.formula_code, df_test)

        if values_train is None or values_test is None:
            factor.reject_reason = "Formula execution error"
            return

        t_stat = self._compute_t_stat(values_test, df_test)
        factor.t_stat = t_stat
        factor.deflated_sharpe = deflated_sharpe_ratio(
            values_test, n_trials=self._trial_count
        )

        if not t_stat_hurdle_passed(t_stat):
            factor.reject_reason = f"|t-stat|={abs(t_stat):.2f} < 3.0 hurdle"
            return

        factor.accepted = True

    @staticmethod
    def _compute_factor(code: str, df) -> Optional[object]:
        try:
            ns: Dict[str, Any] = {}
            exec(code, ns)  # noqa: S102
            fn = ns.get("factor")
            return fn(df) if fn else None
        except Exception as exc:  # noqa: BLE001
            log.debug("Factor formula error: %s", exc)
            return None

    @staticmethod
    def _compute_t_stat(factor_values, df) -> float:
        import numpy as np
        try:
            vals = factor_values.values if hasattr(factor_values, "values") else factor_values
            fwd_ret = df["Close"].pct_change().shift(-1).values
            import numpy as np
            mask = ~(np.isnan(vals) | np.isnan(fwd_ret))
            x, y = vals[mask], fwd_ret[mask]
            if len(x) < 10:
                return 0.0
            corr = float(np.corrcoef(x, y)[0, 1])
            n = len(x)
            denom = max(1 - corr ** 2, 1e-10) ** 0.5
            return round(corr * ((n - 2) ** 0.5) / denom, 4)
        except Exception:  # noqa: BLE001
            return 0.0

    @staticmethod
    def _stub_factor() -> DiscoveredFactor:
        code = textwrap.dedent("""
        def factor(df):
            import numpy as np
            # Friction Adjusted Flow Shock: 3-bar momentum normalised by
            # intraday range (slippage proxy). High momentum + low range =
            # institutional flow with minimal noise trading friction.
            mom = df['Close'].pct_change(3)
            friction = (df['High'] - df['Low']) / df['Close'].replace(0, np.nan)
            return (mom / (friction + 1e-6)).fillna(0)
        """).strip()
        return DiscoveredFactor(
            factor_name="friction_adjusted_flow_shock",
            rationale=(
                "Stocks with strong 3-bar price momentum but low intraday range "
                "exhibit directional institutional flow without excessive noise. "
                "Low range is a proxy for tight bid-ask spread and low realised "
                "slippage, so the alpha cushion survives round-trip friction costs."
            ),
            formula_code=code,
            expected_direction="long_positive",
            high_turnover_risk=False,
        )
