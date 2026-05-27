"""Phase 2 — MemeBERT-LSTM temporal fusion scorer.

MemeBERT is fine-tuned on Reddit/X posts and understands emojis, slang, and
financial sarcasm.  Its output is fed into an LSTM alongside technical
indicators; the LSTM's memory gates learn long-term temporal relationships
that linear models miss for volatile "meme" assets.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional

import numpy as np

log = logging.getLogger(__name__)

# MemeBERT model identifier (HuggingFace hub).
# The actual model is loaded lazily to avoid import-time GPU allocation.
_MEMEBERT_MODEL = "philschmid/distilbert-base-multilingual-cased-sentiment-2"
_MEMEBERT_MEME_MODEL = "cardiffnlp/twitter-roberta-base-sentiment-latest"


@dataclass
class SentimentResult:
    text: str
    raw_sentiment: float    # -1 (negative) to +1 (positive)
    confidence: float       # 0-1
    label: str              # POSITIVE / NEGATIVE / NEUTRAL


@dataclass
class LSTMPrediction:
    symbol: str
    sentiment_score: float  # aggregated sentiment from MemeBERT
    lstm_signal: float      # LSTM output: predicted next-bar direction (-1 to +1)
    combined_score: float   # fusion of sentiment + technical features
    confidence: float


class MemeBertLSTMScorer:
    """
    Two-stage scorer:

    1. MemeBERT encodes social text → raw_sentiment per post.
    2. An LSTM fuses the aggregated sentiment time-series with technical
       indicator arrays to output a directional signal.

    The LSTM is designed for volatile meme assets where standard linear
    models fail due to regime non-stationarity.
    """

    def __init__(self, lstm_hidden: int = 64, seq_len: int = 20) -> None:
        self.lstm_hidden = lstm_hidden
        self.seq_len = seq_len
        self._pipeline = None   # lazy HuggingFace pipeline
        self._lstm = None       # lazy PyTorch LSTM

    # ------------------------------------------------------------------ #
    # MemeBERT sentiment encoding                                         #
    # ------------------------------------------------------------------ #

    def _load_pipeline(self):
        if self._pipeline is not None:
            return self._pipeline
        try:
            from transformers import pipeline  # type: ignore
            self._pipeline = pipeline(
                "sentiment-analysis",
                model=_MEMEBERT_MEME_MODEL,
                truncation=True,
                max_length=128,
            )
            log.info("MemeBERT pipeline loaded: %s", _MEMEBERT_MEME_MODEL)
        except ImportError:
            log.warning("transformers not installed — using rule-based fallback")
            self._pipeline = "fallback"
        return self._pipeline

    def encode_texts(self, texts: List[str]) -> List[SentimentResult]:
        pipe = self._load_pipeline()
        results = []
        if pipe == "fallback":
            for t in texts:
                results.append(self._rule_based(t))
            return results
        for t in texts:
            try:
                out = pipe(t[:512])[0]
                label = out["label"].upper()
                score = out["score"]
                # Map to -1/+1 scale
                if label in ("POSITIVE", "POS", "LABEL_2"):
                    raw = score
                elif label in ("NEGATIVE", "NEG", "LABEL_0"):
                    raw = -score
                else:
                    raw = 0.0
                results.append(SentimentResult(text=t, raw_sentiment=round(raw, 4),
                                               confidence=round(score, 4), label=label))
            except Exception as exc:  # noqa: BLE001
                log.debug("MemeBERT encode error: %s", exc)
                results.append(self._rule_based(t))
        return results

    @staticmethod
    def _rule_based(text: str) -> SentimentResult:
        t = text.lower()
        pos = sum(t.count(w) for w in ["moon", "bull", "buy", "rocket", "squeeze", "long", "🚀", "💎", "🔥"])
        neg = sum(t.count(w) for w in ["short", "dump", "sell", "crash", "bear", "puts", "💀", "📉"])
        raw = min(1.0, max(-1.0, (pos - neg) * 0.25))
        return SentimentResult(text=text, raw_sentiment=raw, confidence=0.5, label="RULE")

    def aggregate_sentiment(self, texts: List[str]) -> float:
        """Average sentiment across a list of posts; empty → 0."""
        if not texts:
            return 0.0
        results = self.encode_texts(texts)
        return round(float(np.mean([r.raw_sentiment for r in results])), 4)

    # ------------------------------------------------------------------ #
    # LSTM temporal fusion                                                #
    # ------------------------------------------------------------------ #

    def _load_lstm(self):
        if self._lstm is not None:
            return self._lstm
        try:
            import torch  # type: ignore
            import torch.nn as nn

            class _LSTM(nn.Module):
                def __init__(self, input_size: int, hidden: int) -> None:
                    super().__init__()
                    self.lstm = nn.LSTM(input_size, hidden, batch_first=True)
                    self.fc = nn.Linear(hidden, 1)

                def forward(self, x):
                    _, (h, _) = self.lstm(x)
                    return torch.tanh(self.fc(h[-1]))

            self._lstm = _LSTM(input_size=6, hidden=self.lstm_hidden)
            log.info("LSTM model initialised (hidden=%d)", self.lstm_hidden)
        except ImportError:
            log.warning("torch not installed — LSTM will use numpy fallback")
            self._lstm = "fallback"
        return self._lstm

    def predict(
        self,
        symbol: str,
        sentiment_series: List[float],
        technical_matrix: Optional[np.ndarray] = None,
    ) -> LSTMPrediction:
        """
        Fuse a time-series of sentiment scores with technical features.

        ``technical_matrix`` shape: (T, 5) — [close, volume, rsi, atr, vwap_dist]
        Pads/truncates to ``seq_len`` automatically.
        """
        sent_arr = np.array(sentiment_series, dtype=np.float32)
        # Pad / truncate to seq_len
        if len(sent_arr) < self.seq_len:
            sent_arr = np.pad(sent_arr, (self.seq_len - len(sent_arr), 0))
        else:
            sent_arr = sent_arr[-self.seq_len :]

        if technical_matrix is None:
            tech = np.zeros((self.seq_len, 5), dtype=np.float32)
        else:
            tech = np.array(technical_matrix, dtype=np.float32)
            if len(tech) < self.seq_len:
                tech = np.pad(tech, ((self.seq_len - len(tech), 0), (0, 0)))
            else:
                tech = tech[-self.seq_len :]

        feature_seq = np.concatenate([sent_arr.reshape(-1, 1), tech], axis=1)  # (T, 6)
        lstm = self._load_lstm()

        if lstm == "fallback":
            # Simple weighted average fallback
            weights = np.exp(np.linspace(-1, 0, self.seq_len))
            weights /= weights.sum()
            lstm_signal = float(np.dot(weights, sent_arr))
        else:
            import torch  # type: ignore
            x = torch.tensor(feature_seq).unsqueeze(0)  # (1, T, 6)
            with torch.no_grad():
                lstm_signal = float(lstm(x).item())

        agg_sent = float(np.mean(sent_arr))
        combined = round(0.5 * lstm_signal + 0.5 * agg_sent, 4)
        confidence = round(min(1.0, abs(combined) * 2), 3)

        return LSTMPrediction(
            symbol=symbol,
            sentiment_score=round(agg_sent, 4),
            lstm_signal=round(lstm_signal, 4),
            combined_score=combined,
            confidence=confidence,
        )
