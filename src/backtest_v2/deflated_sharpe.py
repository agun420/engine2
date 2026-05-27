"""Phase 5 / Top Tips — Deflated Sharpe Ratio and |t| > 3.0 hurdle.

Because the ReAct agent tests thousands of factor combinations, the Multiple
Testing Bias (p-hacking) inflates apparent performance.

Deflated Sharpe Ratio adjusts the observed Sharpe downward based on:
  • the number of discarded trials (n_trials)
  • the skewness and kurtosis of the return series

References:
  Bailey & López de Prado (2014), "The Deflated Sharpe Ratio"
"""
from __future__ import annotations

import math
from typing import Union

import numpy as np

_T_HURDLE = 3.0     # |t-stat| must exceed this to accept a factor


def t_stat_hurdle_passed(t_stat: float, hurdle: float = _T_HURDLE) -> bool:
    """Return True only when |t_stat| > hurdle (default 3.0)."""
    return abs(t_stat) > hurdle


def sharpe_ratio(returns: Union[np.ndarray, list], annualise: bool = True) -> float:
    """Annualised Sharpe assuming 252 trading days."""
    r = np.asarray(returns, dtype=float)
    r = r[~np.isnan(r)]
    if len(r) < 2 or r.std() == 0:
        return 0.0
    sr = r.mean() / r.std()
    if annualise:
        sr *= math.sqrt(252)
    return round(float(sr), 4)


def deflated_sharpe_ratio(
    returns: Union[np.ndarray, list],
    n_trials: int = 1,
    annualise: bool = True,
) -> float:
    """
    Compute the Deflated Sharpe Ratio (DSR).

    The benchmark Sharpe SR* represents the expected maximum Sharpe across
    n_trials independent strategies by pure luck:

      SR* = (1 - γ) * Z^{-1}(1 - 1/n_trials) + γ * Z^{-1}(1 - 1/(n_trials * e))

    where γ = 0.5772 (Euler–Mascheroni constant) and Z^{-1} is the inverse
    standard normal CDF.

    DSR = Φ[(SR_obs - SR*) * sqrt(T-1) / sqrt(1 - skew*SR_obs + (kurt-1)/4 * SR_obs^2)]
    """
    from scipy.stats import norm  # type: ignore

    r = np.asarray(returns, dtype=float)
    r = r[~np.isnan(r)]
    n = len(r)
    if n < 4:
        return 0.0

    sr_obs = sharpe_ratio(r, annualise=annualise)
    skew = float(np.mean(((r - r.mean()) / (r.std() + 1e-12)) ** 3))
    kurt = float(np.mean(((r - r.mean()) / (r.std() + 1e-12)) ** 4))

    # Expected maximum Sharpe across n_trials (Euler–Mascheroni constant γ ≈ 0.5772)
    gamma = 0.5772156649
    if n_trials <= 1:
        sr_star = 0.0
    else:
        z1 = norm.ppf(1 - 1 / n_trials)
        z2 = norm.ppf(1 - 1 / (n_trials * math.e))
        sr_star = (1 - gamma) * z1 + gamma * z2

    # Variance of the Sharpe estimate
    denom = math.sqrt(max(1e-10,
        1 - skew * sr_obs + (kurt - 1) / 4 * sr_obs ** 2
    ))
    numerator = (sr_obs - sr_star) * math.sqrt(n - 1)
    dsr = float(norm.cdf(numerator / denom))
    return round(dsr, 6)
