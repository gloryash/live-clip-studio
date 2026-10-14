from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass(frozen=True)
class MicroCluster:
    cluster_id: str
    window_id: str
    scale_seconds: int
    model_name: str
    centroid: np.ndarray
    member_indices: tuple[int, ...]
    duration: float
    compactness: float


@dataclass
class Prototype:
    prototype_id: str
    centroid: np.ndarray
    evidence_count: int = 1
    duration: float = 0.0
    window_ids: set[str] = field(default_factory=set)
    scale_seconds: set[int] = field(default_factory=set)
    cluster_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class InferenceConfig:
    window_seconds: tuple[int, ...] = (300, 600, 1200)
    match_similarity: float = 0.72
    candidate_similarity: float = 0.78
    promotion_windows: int = 2
    stable_scales: int = 2
    unknown_similarity: float = 0.60

