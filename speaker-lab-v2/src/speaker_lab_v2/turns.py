from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from sklearn.mixture import GaussianMixture


@dataclass(frozen=True)
class TurnAggregation:
    embeddings: np.ndarray
    member_positions: tuple[tuple[int, ...], ...]
    adjacent_similarities: tuple[float, ...]
    same_voice_probabilities: tuple[float, ...]


def aggregate_acoustic_turns(
    embeddings: np.ndarray,
    rows: list[dict],
    *,
    random_state: int = 0,
    posterior_threshold: float = 0.8,
    max_gap_seconds: float = 0.75,
) -> TurnAggregation:
    embeddings = np.asarray(embeddings, dtype=np.float64)
    if len(embeddings) != len(rows):
        raise ValueError("embedding and row counts differ")
    if not len(embeddings):
        return TurnAggregation(
            embeddings=np.empty((0, 0)),
            member_positions=(),
            adjacent_similarities=(),
            same_voice_probabilities=(),
        )
    norms = np.linalg.norm(embeddings, axis=1)
    if np.any(norms <= 1e-9):
        raise ValueError("zero-length embedding")
    embeddings = embeddings / norms[:, None]
    similarities = np.sum(embeddings[:-1] * embeddings[1:], axis=1)
    if len(similarities) == 0:
        probabilities = np.empty(0)
    elif float(np.ptp(similarities)) <= 1e-6:
        probabilities = np.ones_like(similarities)
    else:
        mixture = GaussianMixture(
            n_components=2,
            covariance_type="full",
            random_state=random_state,
            reg_covar=1e-5,
        ).fit(similarities.reshape(-1, 1))
        high_component = int(np.argmax(mixture.means_.reshape(-1)))
        probabilities = mixture.predict_proba(similarities.reshape(-1, 1))[
            :, high_component
        ]

    groups: list[list[int]] = [[0]]
    for position in range(1, len(embeddings)):
        gap = float(rows[position]["start"]) - float(rows[position - 1]["end"])
        merge = (
            gap <= max_gap_seconds
            and probabilities[position - 1] >= posterior_threshold
        )
        if merge:
            groups[-1].append(position)
        else:
            groups.append([position])

    turn_vectors: list[np.ndarray] = []
    for group in groups:
        vector = np.mean(embeddings[group], axis=0)
        vector /= float(np.linalg.norm(vector)) + 1e-9
        turn_vectors.append(vector)
    return TurnAggregation(
        embeddings=np.stack(turn_vectors),
        member_positions=tuple(tuple(group) for group in groups),
        adjacent_similarities=tuple(float(value) for value in similarities),
        same_voice_probabilities=tuple(float(value) for value in probabilities),
    )
