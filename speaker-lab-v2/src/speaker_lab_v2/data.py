from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass(frozen=True)
class EmbeddingCache:
    embeddings: np.ndarray
    indices: np.ndarray


@dataclass(frozen=True)
class InferenceInputs:
    segments: list[dict]
    caches: dict[str, EmbeddingCache]


def load_embedding_cache(path: Path) -> EmbeddingCache:
    with np.load(path) as cache:
        embeddings = np.asarray(cache["embeddings"], dtype=np.float32)
        indices = np.asarray(cache["indices"], dtype=np.int32)
    if embeddings.ndim != 2 or indices.ndim != 1:
        raise ValueError("embedding cache must contain a 2-D matrix and 1-D indices")
    if len(embeddings) != len(indices):
        raise ValueError("embedding and index counts differ")
    if len(set(indices.tolist())) != len(indices):
        raise ValueError("embedding indices must be unique")
    if not np.isfinite(embeddings).all():
        raise ValueError("embedding cache contains non-finite values")
    norms = np.linalg.norm(embeddings, axis=1)
    if np.any(norms <= 1e-9):
        raise ValueError("zero-length embedding")
    return EmbeddingCache(embeddings / norms[:, None], indices)


def load_inference_inputs(
    segments_path: Path,
    embedding_paths: dict[str, Path],
) -> InferenceInputs:
    payload = json.loads(segments_path.read_text())
    segments = payload.get("segments")
    if not isinstance(segments, list) or not segments:
        raise ValueError("segments.json must contain a non-empty segments list")
    caches = {name: load_embedding_cache(path) for name, path in embedding_paths.items()}
    for cache in caches.values():
        if np.any(cache.indices < 0) or np.any(cache.indices >= len(segments)):
            raise ValueError("embedding index is outside the segment range")
    return InferenceInputs(segments=segments, caches=caches)
