"""Phase 2 / Top Tips — SBERT k-means narrative clustering.

Instead of counting keywords, Sentence-BERT (SBERT) generates dense embeddings
for each post.  K-means then groups similar narratives so the AI can quantify
*what* is being discussed (e.g. "technical breakout", "short squeeze thesis",
"macro fear"), not just whether it is positive or negative.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

log = logging.getLogger(__name__)

_SBERT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


@dataclass
class Cluster:
    cluster_id: int
    label: str              # auto-assigned keyword label
    size: int               # number of posts in cluster
    centroid: np.ndarray    # embedding centroid
    representative_texts: List[str] = field(default_factory=list)
    avg_sentiment: float = 0.0


@dataclass
class ClusteringResult:
    symbol: str
    clusters: List[Cluster]
    dominant_cluster: Optional[Cluster]
    narrative_diversity: float  # normalised entropy over cluster sizes


class SBERTClusterer:
    """
    1. Encode a batch of text posts with SBERT.
    2. Run k-means to group into ``n_clusters`` narrative buckets.
    3. Label each cluster by its most frequent meaningful token.
    4. Return cluster statistics for downstream signal generation.
    """

    def __init__(self, n_clusters: int = 8) -> None:
        self.n_clusters = n_clusters
        self._model = None

    def _load_model(self):
        if self._model is not None:
            return self._model
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore
            self._model = SentenceTransformer(_SBERT_MODEL)
            log.info("SBERT model loaded: %s", _SBERT_MODEL)
        except ImportError:
            log.warning("sentence-transformers not installed — SBERT fallback active")
            self._model = "fallback"
        return self._model

    def _embed(self, texts: List[str]) -> np.ndarray:
        model = self._load_model()
        if model == "fallback":
            # TF-IDF-style bag-of-char-bigrams as a lightweight substitute
            vocab: Dict[str, int] = {}
            rows = []
            for t in texts:
                bigrams = [t[i : i + 2] for i in range(len(t) - 1)]
                rows.append(bigrams)
            all_bg = sorted({bg for row in rows for bg in row})
            idx = {bg: i for i, bg in enumerate(all_bg)}
            mat = np.zeros((len(texts), len(idx) or 1), dtype=np.float32)
            for r, bigrams in enumerate(rows):
                for bg in bigrams:
                    if bg in idx:
                        mat[r, idx[bg]] += 1
            norms = np.linalg.norm(mat, axis=1, keepdims=True) + 1e-8
            return mat / norms
        return np.array(model.encode(texts, show_progress_bar=False))

    def cluster(self, symbol: str, texts: List[str]) -> ClusteringResult:
        if len(texts) < self.n_clusters:
            k = max(1, len(texts))
        else:
            k = self.n_clusters

        embeddings = self._embed(texts)
        labels, centroids = self._kmeans(embeddings, k)

        clusters: List[Cluster] = []
        for cid in range(k):
            mask = labels == cid
            c_texts = [texts[i] for i in range(len(texts)) if mask[i]]
            clusters.append(Cluster(
                cluster_id=cid,
                label=self._auto_label(c_texts),
                size=int(mask.sum()),
                centroid=centroids[cid],
                representative_texts=c_texts[:3],
            ))

        clusters.sort(key=lambda c: -c.size)
        dominant = clusters[0] if clusters else None
        diversity = self._entropy([c.size for c in clusters])

        return ClusteringResult(
            symbol=symbol,
            clusters=clusters,
            dominant_cluster=dominant,
            narrative_diversity=round(diversity, 4),
        )

    # ------------------------------------------------------------------ #
    # Helpers                                                              #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _kmeans(X: np.ndarray, k: int) -> Tuple[np.ndarray, np.ndarray]:
        """Simple numpy k-means++ init then Lloyd iterations."""
        rng = np.random.default_rng(42)
        n = len(X)
        # k-means++ seed
        centers = [X[rng.integers(0, n)]]
        for _ in range(k - 1):
            dists = np.array([min(np.linalg.norm(x - c) ** 2 for c in centers) for x in X])
            probs = dists / dists.sum()
            centers.append(X[rng.choice(n, p=probs)])
        centroids = np.array(centers)
        labels = np.zeros(n, dtype=int)
        for _ in range(50):
            dists = np.linalg.norm(X[:, None] - centroids[None], axis=2)
            new_labels = np.argmin(dists, axis=1)
            if np.all(new_labels == labels):
                break
            labels = new_labels
            for c in range(k):
                mask = labels == c
                if mask.any():
                    centroids[c] = X[mask].mean(axis=0)
        return labels, centroids

    @staticmethod
    def _auto_label(texts: List[str]) -> str:
        if not texts:
            return "unknown"
        _STOP = {"the", "a", "is", "in", "it", "i", "to", "and", "of", "for", "on", "at"}
        freq: Dict[str, int] = {}
        for t in texts:
            for w in t.lower().split():
                w = w.strip(".,!?#@$")
                if len(w) > 2 and w not in _STOP:
                    freq[w] = freq.get(w, 0) + 1
        if not freq:
            return "misc"
        return max(freq, key=freq.get)

    @staticmethod
    def _entropy(sizes: List[int]) -> float:
        total = sum(sizes)
        if total == 0:
            return 0.0
        probs = np.array(sizes) / total
        probs = probs[probs > 0]
        return float(-np.sum(probs * np.log(probs)) / np.log(len(probs) + 1))
