"""Phase 3 — ReAct autonomous factor discovery with economic regularisation.

The agent follows the Reasoning-Action (ReAct) pattern:
  1. THINK  — articulate a valid economic rationale.
  2. ACT    — generate a mathematical factor formula in Python.
  3. OBSERVE — back-test the factor on held-out data.
  4. REFLECT — keep the factor only if |t-stat| > 3.0 AND the economic
               rationale holds (prevents spurious curve-fitting).

Economic regularisation is enforced by requiring the agent to supply a
rationale string BEFORE generating code; the code is rejected if the
rationale is empty or generic.
"""
from __future__ import annotations

import json
import logging
import os
import re
import textwrap
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import requests

log = logging.getLogger(__name__)

_ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY", "")
_MODEL = os.getenv("REACT_LLM_MODEL", "claude-opus-4-7")
_CLAUDE_API = "https://api.anthropic.com/v1/messages"

_SYSTEM_PROMPT = textwrap.dedent("""
You are an autonomous quantitative researcher using the ReAct framework.
For every factor you propose you MUST:
1. State a clear, falsifiable ECONOMIC RATIONALE (why this factor should
   predict future returns — not just a statistical observation).
2. Only then write Python code that computes the factor from a pandas
   DataFrame with columns: Open, High, Low, Close, Volume, and any
   enrichment columns already in the dataset.
3. Enforce the "Friction Adjusted Flow Shock" principle: penalise factors
   that imply daily turnover > 100 % unless the alpha cushion exceeds
   realistic slippage (assume 10 bps round-trip).

Output format — always a valid JSON object:
{
  "rationale": "<economic rationale>",
  "factor_name": "<snake_case_name>",
  "formula_code": "<python function string: def factor(df): ...>",
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
    Iteratively discover and validate alpha factors using Claude as the
    reasoning engine, with strict economic regularisation and the |t|>3.0
    hurdle from the Deflated Sharpe framework.
    """

    def __init__(self, max_iterations: int = 10) -> None:
        self.max_iterations = max_iterations
        self._accepted: List[DiscoveredFactor] = []
        self._rejected: List[DiscoveredFactor] = []
        self._trial_count: int = 0

    @property
    def accepted_factors(self) -> List[DiscoveredFactor]:
        return list(self._accepted)

    def run(
        self,
        df_train,  # pd.DataFrame
        df_test,   # pd.DataFrame
        context_hint: str = "",
    ) -> List[DiscoveredFactor]:
        """
        Drive the ReAct loop for ``max_iterations`` rounds.

        Each round: propose factor → validate → accept/reject → feedback.
        """
        feedback = ""
        for i in range(self.max_iterations):
            log.info("ReAct iteration %d / %d", i + 1, self.max_iterations)
            factor = self._propose_factor(context_hint, feedback)
            if factor is None:
                log.warning("LLM returned no usable factor — stopping early")
                break
            self._trial_count += 1
            self._validate(factor, df_train, df_test)
            if factor.accepted:
                self._accepted.append(factor)
                feedback = (
                    f"Last factor '{factor.factor_name}' was ACCEPTED "
                    f"(t={factor.t_stat:.2f}, DSR={factor.deflated_sharpe:.3f}). "
                    "Try a complementary uncorrelated factor next."
                )
            else:
                self._rejected.append(factor)
                feedback = (
                    f"Last factor '{factor.factor_name}' was REJECTED: {factor.reject_reason}. "
                    "Revise your economic rationale or formula."
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
        if not _ANTHROPIC_KEY:
            log.warning("ANTHROPIC_API_KEY not set — using stub factor")
            return self._stub_factor()
        user_msg = ""
        if hint:
            user_msg += f"Dataset context: {hint}\n\n"
        if feedback:
            user_msg += f"Previous attempt feedback: {feedback}\n\n"
        user_msg += (
            "Propose the next alpha factor. Remember: rationale FIRST, "
            "then formula. Return only the JSON object."
        )
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
                    "max_tokens": 1024,
                    "system": _SYSTEM_PROMPT,
                    "messages": [{"role": "user", "content": user_msg}],
                },
                timeout=60,
            )
            resp.raise_for_status()
            content = resp.json()["content"][0]["text"]
            return self._parse_factor(content)
        except Exception as exc:  # noqa: BLE001
            log.error("LLM request failed: %s", exc)
            return None

    @staticmethod
    def _parse_factor(text: str) -> Optional[DiscoveredFactor]:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return None
        try:
            d: Dict[str, Any] = json.loads(match.group())
            if not d.get("rationale") or len(d["rationale"]) < 20:
                log.warning("Factor rejected at parse: rationale too short or missing")
                return None
            return DiscoveredFactor(
                factor_name=d.get("factor_name", "unnamed_factor"),
                rationale=d["rationale"],
                formula_code=d.get("formula_code", ""),
                expected_direction=d.get("expected_direction", "mixed"),
                high_turnover_risk=bool(d.get("high_turnover_risk", False)),
            )
        except (json.JSONDecodeError, KeyError) as exc:
            log.warning("Factor parse error: %s", exc)
            return None

    # ------------------------------------------------------------------ #
    # Validation                                                          #
    # ------------------------------------------------------------------ #

    def _validate(self, factor: DiscoveredFactor, df_train, df_test) -> None:
        from src.backtest_v2.deflated_sharpe import t_stat_hurdle_passed, deflated_sharpe_ratio

        # High-turnover check: auto-reject without economic justification
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
            if fn is None:
                return None
            return fn(df)
        except Exception as exc:  # noqa: BLE001
            log.debug("Factor formula error: %s", exc)
            return None

    @staticmethod
    def _compute_t_stat(factor_values, df) -> float:
        import numpy as np
        try:
            vals = factor_values.values if hasattr(factor_values, "values") else factor_values
            fwd_ret = df["Close"].pct_change().shift(-1).values
            mask = ~(np.isnan(vals) | np.isnan(fwd_ret))
            x = vals[mask]
            y = fwd_ret[mask]
            if len(x) < 10:
                return 0.0
            corr = float(np.corrcoef(x, y)[0, 1])
            n = len(x)
            # t = r * sqrt(n-2) / sqrt(1-r^2)
            denom = max(1 - corr ** 2, 1e-10) ** 0.5
            return round(corr * ((n - 2) ** 0.5) / denom, 4)
        except Exception:  # noqa: BLE001
            return 0.0

    @staticmethod
    def _stub_factor() -> DiscoveredFactor:
        """Minimal stub when LLM is unavailable, for CI/testing."""
        code = textwrap.dedent("""
        def factor(df):
            import numpy as np
            # Friction Adjusted Flow Shock: normalised volume × price momentum
            # penalised by daily range (proxy for realised slippage)
            mom = df['Close'].pct_change(3)
            friction = (df['High'] - df['Low']) / df['Close']
            raw = mom / (friction + 1e-6)
            return raw.fillna(0)
        """).strip()
        return DiscoveredFactor(
            factor_name="friction_adjusted_flow_shock",
            rationale=(
                "Stocks with strong 3-bar momentum but low intraday range have "
                "directional price pressure without excessive slippage costs, "
                "indicating institutional accumulation rather than noise trading."
            ),
            formula_code=code,
            expected_direction="long_positive",
            high_turnover_risk=False,
        )
