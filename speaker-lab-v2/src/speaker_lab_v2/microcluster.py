from __future__ import annotations

import math

import numpy as np
from sklearn.cluster import AgglomerativeClustering

from .models import MicroCluster


def _normalized(vector: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(vector))
    if norm <= 1e-9:
        raise ValueError("cannot normalize a zero vector")
    return vector / norm


def _cluster_count(sample_count: int) -> int:
    proposed = int(round(math.sqrt(sample_count / 3.0)))
    return min(sample_count, max(6, min(10, proposed)))


def build_microclusters(
    embeddings: np.ndarray,
    rows: list[dict],
    *,
    window_seconds: int,
    model_name: str,
) -> list[MicroCluster]:
    embeddings = np.asarray(embeddings, dtype=np.float32)
    if len(embeddings) != len(rows):
        raise ValueError("embedding and row counts differ")
    if not rows:
        return []
    starts = [float(row["start"]) for row in rows]
    window_start = math.floor(min(starts) / window_seconds) * window_seconds
    max_start = max(starts)
    result: list[MicroCluster] = []
    while window_start <= max_start + 1e-9:
        positions = [
            position
            for position, row in enumerate(rows)
            if window_start <= float(row["start"]) < window_start + window_seconds
        ]
        current_start = window_start
        window_start += window_seconds
        if not positions:
            continue
        count = _cluster_count(len(positions))
        if count == 1:
            labels = np.zeros(1, dtype=int)
        else:
            labels = AgglomerativeClustering(
                n_clusters=count,
                metric="cosine",
                linkage="average",
            ).fit_predict(embeddings[positions])
        window_id = f"{window_seconds}:{int(current_start)}"
        for local_label in sorted(set(labels.tolist())):
            members = [positions[index] for index in np.where(labels == local_label)[0]]
            centroid = _normalized(np.mean(embeddings[members], axis=0))
            similarities = embeddings[members] @ centroid
            result.append(
                MicroCluster(
                    cluster_id=f"{model_name}:{window_id}:{local_label}",
                    window_id=window_id,
                    scale_seconds=window_seconds,
                    model_name=model_name,
                    centroid=centroid,
                    member_indices=tuple(int(rows[position]["index"]) for position in members),
                    duration=sum(
                        float(rows[position]["end"]) - float(rows[position]["start"])
                        for position in members
                    ),
                    compactness=float(np.clip(np.mean(similarities), 0.0, 1.0)),
                )
            )
    return result
