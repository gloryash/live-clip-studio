from __future__ import annotations

from dataclasses import replace

import numpy as np
from scipy.optimize import linear_sum_assignment

from .models import InferenceConfig, MicroCluster, Prototype


def _normalize(vector: np.ndarray) -> np.ndarray:
    return vector / (float(np.linalg.norm(vector)) + 1e-9)


def _new_prototype(prototype_id: str, cluster: MicroCluster) -> Prototype:
    return Prototype(
        prototype_id=prototype_id,
        centroid=cluster.centroid.copy(),
        evidence_count=1,
        duration=cluster.duration,
        window_ids={cluster.window_id},
        scale_seconds={cluster.scale_seconds},
        cluster_ids=[cluster.cluster_id],
    )


def _update_prototype(prototype: Prototype, cluster: MicroCluster) -> None:
    prototype.centroid = _normalize(
        prototype.centroid * prototype.evidence_count + cluster.centroid
    )
    prototype.evidence_count += 1
    prototype.duration += cluster.duration
    prototype.window_ids.add(cluster.window_id)
    prototype.scale_seconds.add(cluster.scale_seconds)
    prototype.cluster_ids.append(cluster.cluster_id)


def _match(
    clusters: list[MicroCluster],
    prototypes: list[Prototype],
    threshold: float,
) -> tuple[list[tuple[int, int]], list[int]]:
    if not clusters or not prototypes:
        return [], list(range(len(clusters)))
    similarities = np.asarray(
        [[float(cluster.centroid @ proto.centroid) for proto in prototypes] for cluster in clusters]
    )
    cluster_indexes, prototype_indexes = linear_sum_assignment(-similarities)
    matched: list[tuple[int, int]] = []
    used_clusters: set[int] = set()
    for cluster_index, prototype_index in zip(cluster_indexes, prototype_indexes):
        if similarities[cluster_index, prototype_index] >= threshold:
            matched.append((int(cluster_index), int(prototype_index)))
            used_clusters.add(int(cluster_index))
    return matched, [index for index in range(len(clusters)) if index not in used_clusters]


class PrototypeRegistry:
    def __init__(self, config: InferenceConfig | None = None) -> None:
        self.config = config or InferenceConfig()
        self.confirmed: list[Prototype] = []
        self.candidates: list[Prototype] = []
        self.assignments: dict[str, str] = {}
        self._next_id = 0

    @property
    def confirmed_count(self) -> int:
        return len(self.confirmed)

    @property
    def candidate_count(self) -> int:
        return len(self.candidates)

    def _allocate_id(self) -> str:
        prototype_id = f"P{self._next_id:03d}"
        self._next_id += 1
        return prototype_id

    def observe(self, clusters: list[MicroCluster]) -> None:
        remaining = list(clusters)
        matched, unmatched = _match(
            remaining, self.confirmed, self.config.match_similarity
        )
        for cluster_index, prototype_index in matched:
            cluster = remaining[cluster_index]
            prototype = self.confirmed[prototype_index]
            _update_prototype(prototype, cluster)
            self.assignments[cluster.cluster_id] = prototype.prototype_id
        remaining = [remaining[index] for index in unmatched]

        candidate_matches, candidate_unmatched = _match(
            remaining, self.candidates, self.config.candidate_similarity
        )
        promote: list[Prototype] = []
        for cluster_index, prototype_index in candidate_matches:
            cluster = remaining[cluster_index]
            prototype = self.candidates[prototype_index]
            _update_prototype(prototype, cluster)
            self.assignments[cluster.cluster_id] = prototype.prototype_id
            if len(prototype.window_ids) >= self.config.promotion_windows:
                promote.append(prototype)
        if promote:
            promote_ids = {prototype.prototype_id for prototype in promote}
            self.candidates = [
                prototype
                for prototype in self.candidates
                if prototype.prototype_id not in promote_ids
            ]
            self.confirmed.extend(promote)

        for index in candidate_unmatched:
            cluster = remaining[index]
            prototype = _new_prototype(self._allocate_id(), cluster)
            self.candidates.append(prototype)
            self.assignments[cluster.cluster_id] = prototype.prototype_id
