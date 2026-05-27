"""Phase 4 — LightGBM non-linear signal aggregator.

Uses Gradient-based One-Side Sampling (GOSS) to concentrate training on the
hardest market states, and Exclusive Feature Bundling (EFB) to reduce noise
from correlated sentiment/volume indicators.

When predict_proba() exceeds a configurable threshold the signal is routed to
the MultiAgentPanel for final consensus before execution.
"""
from __future__ import annotations

import logging
import os
import pickle
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

log = logging.getLogger(__name__)

_MODEL_PATH = Path(os.getenv("LGBM_MODEL_PATH", "state/lgbm_model.pkl"))
_BREAKOUT_THRESHOLD = float(os.getenv("LGBM_BREAKOUT_THRESHOLD", "0.65"))

# Feature names expected by the model (order matters).
FEATURE_COLUMNS = [
    # Technical
    "rsi14", "vwap_dist_pct", "atr_pct", "rel_vol", "ema9_slope",
    # Momentum
    "day_change_pct", "short_momentum", "candle_strength",
    # Short data
    "s3_squeeze_risk", "s3_crowded_score", "s3_divergence",
    # Social
    "lc_galaxy_score", "lc_sentiment", "lc_social_volume",
    "svc_score", "simcluster_velocity", "simcluster_bridging",
    # NLP
    "lstm_signal", "memebert_sentiment",
    # Macro
    "vix_scaled_sentiment", "market_regime_code",
]


@dataclass
class AggregationResult:
    symbol: str
    breakout_proba: float
    feature_importances: Dict[str, float] = field(default_factory=dict)
    flagged: bool = False


class LightGBMAggregator:
    """
    Wraps a trained LightGBM model (or trains one from historical data).

    GOSS and EFB are enabled via LightGBM hyperparameters to handle the
    non-linear, high-dimensional signal matrix produced by the pipeline.
    """

    def __init__(self) -> None:
        self._model = None
        self._load_model()

    # ------------------------------------------------------------------ #
    # Public API                                                          #
    # ------------------------------------------------------------------ #

    def predict(self, symbol: str, features: Dict[str, float]) -> AggregationResult:
        """Score a single symbol's feature vector."""
        x = self._dict_to_array(features)
        model = self._model
        if model is None:
            proba = self._heuristic_fallback(features)
        else:
            try:
                proba = float(model.predict(x.reshape(1, -1))[0])
            except Exception as exc:  # noqa: BLE001
                log.warning("LightGBM predict error for %s: %s", symbol, exc)
                proba = self._heuristic_fallback(features)

        importances: Dict[str, float] = {}
        if model is not None and hasattr(model, "feature_importances_"):
            for name, imp in zip(FEATURE_COLUMNS, model.feature_importances_):
                importances[name] = round(float(imp), 4)

        return AggregationResult(
            symbol=symbol,
            breakout_proba=round(proba, 4),
            feature_importances=importances,
            flagged=proba >= _BREAKOUT_THRESHOLD,
        )

    def train(self, X: np.ndarray, y: np.ndarray) -> None:
        """
        Train (or retrain) the LightGBM model.

        GOSS: top_rate=0.2, other_rate=0.1 — focuses on hard samples.
        EFB: automatically bundles correlated sentiment/volume features.
        """
        try:
            import lightgbm as lgb  # type: ignore
        except ImportError:
            log.error("lightgbm not installed — cannot train aggregator")
            return

        params = {
            "objective": "binary",
            "metric": "auc",
            "boosting_type": "goss",     # Gradient-based One-Side Sampling
            "top_rate": 0.2,
            "other_rate": 0.1,
            "num_leaves": 63,
            "learning_rate": 0.05,
            "n_estimators": 300,
            "min_child_samples": 20,
            "feature_fraction": 0.8,
            "verbose": -1,
            # EFB is enabled automatically via max_bin and feature bundling
        }
        model = lgb.LGBMClassifier(**params)
        model.fit(X, y, feature_name=FEATURE_COLUMNS)
        self._model = model
        self._save_model()
        log.info("LightGBM model trained — AUC objective, GOSS+EFB enabled")

    # ------------------------------------------------------------------ #
    # Persistence                                                         #
    # ------------------------------------------------------------------ #

    def _load_model(self) -> None:
        if _MODEL_PATH.exists():
            try:
                with open(_MODEL_PATH, "rb") as f:
                    self._model = pickle.load(f)
                log.info("LightGBM model loaded from %s", _MODEL_PATH)
            except Exception as exc:  # noqa: BLE001
                log.warning("Failed to load LightGBM model: %s", exc)

    def _save_model(self) -> None:
        _MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_MODEL_PATH, "wb") as f:
            pickle.dump(self._model, f)
        log.info("LightGBM model saved to %s", _MODEL_PATH)

    # ------------------------------------------------------------------ #
    # Helpers                                                             #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _dict_to_array(features: Dict[str, float]) -> np.ndarray:
        return np.array(
            [float(features.get(col, 0.0)) for col in FEATURE_COLUMNS],
            dtype=np.float32,
        )

    @staticmethod
    def _heuristic_fallback(features: Dict[str, float]) -> float:
        """Simple weighted average when no trained model is available."""
        weights = {
            "rsi14": -0.003,           # overbought penalty
            "s3_divergence": 0.015,    # squeeze loophole
            "lc_sentiment": 0.10,
            "lstm_signal": 0.20,
            "svc_score": 0.05,
            "vwap_dist_pct": -0.02,    # extension penalty
            "rel_vol": 0.04,
        }
        score = 0.5
        for k, w in weights.items():
            score += w * float(features.get(k, 0.0))
        return float(min(1.0, max(0.0, score)))
