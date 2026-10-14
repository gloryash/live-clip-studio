from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import pdist


@dataclass(frozen=True)
class AHCResult:
    labels: np.ndarray
    speaker_count: int
    similarity_threshold: float


@dataclass(frozen=True)
class EnrollmentResult:
    enrollment_ids: dict[str, tuple[int, ...]]
    evaluation_ids: tuple[int, ...]
    evaluation_count: int
    accuracy: float
    predictions: dict[int, str]
    speakers: dict[str, dict]


def _normalize(embeddings: np.ndarray) -> np.ndarray:
    embeddings = np.asarray(embeddings, dtype=np.float64)
    norms = np.linalg.norm(embeddings, axis=1)
    if np.any(norms <= 1e-9):
        raise ValueError("zero-length embedding")
    return embeddings / norms[:, None]


def _canonical(labels: np.ndarray) -> np.ndarray:
    mapping: dict[int, int] = {}
    result = np.empty_like(labels)
    for index, label in enumerate(labels.tolist()):
        mapping.setdefault(int(label), len(mapping))
        result[index] = mapping[int(label)]
    return result


def fixed_threshold_ahc(
    embeddings: np.ndarray,
    *,
    similarity_threshold: float,
    min_cluster_size: int = 4,
) -> AHCResult:
    embeddings = _normalize(embeddings)
    if len(embeddings) <= 1:
        return AHCResult(np.zeros(len(embeddings), dtype=int), len(embeddings), similarity_threshold)
    hierarchy = linkage(pdist(embeddings, metric="cosine"), method="average")
    labels = fcluster(
        hierarchy,
        t=1.0 - similarity_threshold,
        criterion="distance",
    ).astype(int) - 1
    cluster_ids, counts = np.unique(labels, return_counts=True)
    major = cluster_ids[counts > min_cluster_size]
    minor = set(cluster_ids[counts <= min_cluster_size].tolist())
    if len(major) and minor:
        centers = np.stack(
            [
                np.mean(embeddings[labels == cluster_id], axis=0)
                for cluster_id in major
            ]
        )
        centers = _normalize(centers)
        for position, label in enumerate(labels):
            if int(label) in minor:
                labels[position] = int(major[np.argmax(embeddings[position] @ centers.T)])
    labels = _canonical(labels)
    return AHCResult(
        labels=labels,
        speaker_count=len(set(labels.tolist())),
        similarity_threshold=similarity_threshold,
    )


def evaluate_enrollment(
    embeddings: np.ndarray,
    indices: np.ndarray,
    segments: list[dict],
    annotations: dict[str, str],
    *,
    enrollment_count: int,
    min_duration: float = 2.0,
) -> EnrollmentResult:
    embeddings = _normalize(embeddings)
    indices = np.asarray(indices, dtype=int)
    if len(embeddings) != len(indices):
        raise ValueError("embedding and index counts differ")
    position_by_index = {int(index): position for position, index in enumerate(indices)}
    speakers = sorted(set(annotations.values()))
    enrollment_ids: dict[str, tuple[int, ...]] = {}
    centers: dict[str, np.ndarray] = {}
    enrolled_indexes: set[int] = set()
    for speaker in speakers:
        eligible = [
            index
            for index in indices.tolist()
            if annotations.get(str(index + 1)) == speaker
            and float(segments[index]["end"]) - float(segments[index]["start"])
            >= min_duration
        ]
        eligible.sort(key=lambda index: (float(segments[index]["start"]), index))
        selected = eligible[:enrollment_count]
        if len(selected) < enrollment_count:
            raise ValueError(f"not enough enrollment samples for {speaker}")
        enrollment_ids[speaker] = tuple(index + 1 for index in selected)
        enrolled_indexes.update(selected)
        center = np.mean(
            [embeddings[position_by_index[index]] for index in selected], axis=0
        )
        centers[speaker] = center / (float(np.linalg.norm(center)) + 1e-9)

    center_matrix = np.stack([centers[speaker] for speaker in speakers])
    predictions: dict[int, str] = {}
    gold: dict[int, str] = {}
    for embedding, index in zip(embeddings, indices):
        index = int(index)
        turn_id = index + 1
        if index in enrolled_indexes or str(turn_id) not in annotations:
            continue
        predictions[turn_id] = speakers[int(np.argmax(embedding @ center_matrix.T))]
        gold[turn_id] = annotations[str(turn_id)]
    correct = sum(predictions[turn_id] == truth for turn_id, truth in gold.items())
    per_speaker: dict[str, dict] = {}
    for speaker in speakers:
        support = sum(truth == speaker for truth in gold.values())
        predicted_count = sum(value == speaker for value in predictions.values())
        hits = sum(
            truth == speaker and predictions[turn_id] == speaker
            for turn_id, truth in gold.items()
        )
        precision = hits / predicted_count if predicted_count else 0.0
        recall = hits / support if support else 0.0
        f1 = (
            2 * precision * recall / (precision + recall)
            if precision + recall
            else 0.0
        )
        per_speaker[speaker] = {
            "support": support,
            "correct": hits,
            "precision": precision,
            "recall": recall,
            "f1": f1,
        }
    evaluation_ids = tuple(sorted(gold))
    return EnrollmentResult(
        enrollment_ids=enrollment_ids,
        evaluation_ids=evaluation_ids,
        evaluation_count=len(evaluation_ids),
        accuracy=correct / len(evaluation_ids) if evaluation_ids else 0.0,
        predictions=predictions,
        speakers=per_speaker,
    )
