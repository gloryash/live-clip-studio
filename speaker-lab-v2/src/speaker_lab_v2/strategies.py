from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .graph_cluster import SpectralResult, nme_spectral_cluster
from .microcluster import build_microclusters
from .turns import aggregate_acoustic_turns


@dataclass(frozen=True)
class StrategyResult:
    labels: np.ndarray
    speaker_count: int
    evidence: dict


def _spectral_evidence(result: SpectralResult) -> dict:
    return {
        "neighbor_count": result.neighbor_count,
        "eigengap": result.eigengap,
        "eigenvalues": list(result.eigenvalues),
    }


def raw_nme(
    embeddings: np.ndarray,
    rows: list[dict],
    *,
    model_name: str,
    random_state: int = 0,
) -> StrategyResult:
    result = nme_spectral_cluster(embeddings, random_state=random_state)
    return StrategyResult(
        labels=result.labels,
        speaker_count=result.speaker_count,
        evidence={"strategy": "raw_nme", **_spectral_evidence(result)},
    )


def turn_nme(
    embeddings: np.ndarray,
    rows: list[dict],
    *,
    model_name: str,
    random_state: int = 0,
) -> StrategyResult:
    turns = aggregate_acoustic_turns(
        embeddings,
        rows,
        random_state=random_state,
    )
    clustered = nme_spectral_cluster(turns.embeddings, random_state=random_state)
    labels = np.empty(len(embeddings), dtype=int)
    for turn_label, positions in zip(clustered.labels, turns.member_positions):
        labels[list(positions)] = int(turn_label)
    return StrategyResult(
        labels=labels,
        speaker_count=clustered.speaker_count,
        evidence={
            "strategy": "turn_nme",
            "turn_count": len(turns.embeddings),
            "adjacent_similarity_median": (
                float(np.median(turns.adjacent_similarities))
                if turns.adjacent_similarities
                else None
            ),
            **_spectral_evidence(clustered),
        },
    )


def multiscale_micro_nme(
    embeddings: np.ndarray,
    rows: list[dict],
    *,
    model_name: str,
    scales: tuple[int, ...] = (300, 600, 1200),
    random_state: int = 0,
) -> StrategyResult:
    microclusters = [
        cluster
        for scale in scales
        for cluster in build_microclusters(
            embeddings,
            rows,
            window_seconds=scale,
            model_name=model_name,
        )
    ]
    centers = np.stack([cluster.centroid for cluster in microclusters])
    clustered = nme_spectral_cluster(centers, random_state=random_state)
    global_centers: list[np.ndarray] = []
    for label in range(clustered.speaker_count):
        center = np.mean(centers[clustered.labels == label], axis=0)
        center /= float(np.linalg.norm(center)) + 1e-9
        global_centers.append(center)
    similarities = np.asarray(embeddings) @ np.stack(global_centers).T
    labels = np.argmax(similarities, axis=1).astype(int)
    return StrategyResult(
        labels=labels,
        speaker_count=clustered.speaker_count,
        evidence={
            "strategy": "multiscale_micro_nme",
            "scales": list(scales),
            "graph_node_count": len(microclusters),
            "microclusters_by_scale": {
                str(scale): sum(cluster.scale_seconds == scale for cluster in microclusters)
                for scale in scales
            },
            **_spectral_evidence(clustered),
        },
    )
