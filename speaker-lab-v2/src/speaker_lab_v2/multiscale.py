from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .models import Prototype


@dataclass(frozen=True)
class StablePrototype:
    stable_id: str
    centroid: np.ndarray
    member_ids: tuple[str, ...]
    scale_support: int
    confidence: float


@dataclass(frozen=True)
class StableSpeakerResult:
    speaker_count: int
    stable_prototypes: tuple[StablePrototype, ...]


def estimate_stable_speakers(
    prototypes_by_scale: dict[int, list[Prototype]],
    *,
    similarity_threshold: float,
    min_scales: int,
) -> StableSpeakerResult:
    nodes = [
        (scale, prototype)
        for scale, prototypes in sorted(prototypes_by_scale.items())
        for prototype in prototypes
    ]
    parent = list(range(len(nodes)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    for left in range(len(nodes)):
        left_scale, left_prototype = nodes[left]
        for right in range(left + 1, len(nodes)):
            right_scale, right_prototype = nodes[right]
            if left_scale == right_scale:
                continue
            if float(left_prototype.centroid @ right_prototype.centroid) >= similarity_threshold:
                union(left, right)

    components: dict[int, list[int]] = {}
    for index in range(len(nodes)):
        components.setdefault(find(index), []).append(index)

    stable: list[StablePrototype] = []
    total_scales = max(1, len(prototypes_by_scale))
    for indexes in components.values():
        scales = {nodes[index][0] for index in indexes}
        if len(scales) < min_scales:
            continue
        vectors = np.stack([nodes[index][1].centroid for index in indexes])
        centroid = np.mean(vectors, axis=0)
        centroid /= float(np.linalg.norm(centroid)) + 1e-9
        compactness = float(np.mean(vectors @ centroid))
        scale_fraction = len(scales) / total_scales
        stable.append(
            StablePrototype(
                stable_id=f"S{len(stable):03d}",
                centroid=centroid,
                member_ids=tuple(nodes[index][1].prototype_id for index in indexes),
                scale_support=len(scales),
                confidence=float(np.clip(compactness * scale_fraction, 0.0, 1.0)),
            )
        )
    stable.sort(key=lambda item: (-item.scale_support, -item.confidence, item.stable_id))
    return StableSpeakerResult(
        speaker_count=len(stable),
        stable_prototypes=tuple(stable),
    )
