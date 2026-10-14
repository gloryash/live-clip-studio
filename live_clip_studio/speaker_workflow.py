from __future__ import annotations

from collections import Counter
from typing import Any

import numpy as np
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import pdist


EXCLUDED_CANDIDATE = "__EXCLUDED__"


def _normalize_rows(values: np.ndarray) -> np.ndarray:
    rows = np.asarray(values, dtype=np.float64)
    if rows.ndim != 2:
        raise ValueError("speaker embeddings must be a 2-D matrix")
    norms = np.linalg.norm(rows, axis=1)
    if np.any(norms <= 1e-9):
        raise ValueError("speaker embedding contains a zero-length vector")
    return rows / norms[:, None]


def _canonicalize(labels: np.ndarray) -> np.ndarray:
    mapping: dict[int, int] = {}
    canonical = np.empty_like(labels)
    for position, label in enumerate(labels.tolist()):
        mapping.setdefault(int(label), len(mapping))
        canonical[position] = mapping[int(label)]
    return canonical


def _fixed_threshold_labels(
    embeddings: np.ndarray,
    *,
    similarity_threshold: float,
    min_cluster_size: int = 4,
) -> np.ndarray:
    if len(embeddings) <= 1:
        return np.zeros(len(embeddings), dtype=int)
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
        centers = _normalize_rows(
            np.stack([np.mean(embeddings[labels == cluster_id], axis=0) for cluster_id in major])
        )
        for position, label in enumerate(labels):
            if int(label) in minor:
                labels[position] = int(major[np.argmax(embeddings[position] @ centers.T)])
    return _canonicalize(labels)


def _fill_missing_predictions(
    predictions: dict[int, dict[str, Any]],
    total: int,
    identity_key: str,
) -> dict[int, dict[str, Any]]:
    result = dict(predictions)
    known = sorted(predictions)
    for index in range(total):
        if index in result:
            continue
        left = [candidate for candidate in known if candidate < index]
        right = [candidate for candidate in known if candidate > index]
        left_value = predictions[left[-1]][identity_key] if left else None
        right_value = predictions[right[0]][identity_key] if right else None
        if left_value and left_value == right_value:
            result[index] = {
                identity_key: left_value,
                "confidence": min(
                    float(predictions[left[-1]].get("confidence", 0.0)),
                    float(predictions[right[0]].get("confidence", 0.0)),
                ),
                "source": "neighbor_agreement",
            }
        else:
            result[index] = {
                identity_key: "UNKNOWN",
                "confidence": 0.0,
                "source": "unknown",
            }
    return result


def discover_candidates(
    embeddings: np.ndarray,
    indices: np.ndarray,
    segments: list[dict[str, Any]],
    *,
    model: str = "ECAPA",
    similarity_threshold: float = 0.35,
    representative_count: int = 3,
) -> dict[str, Any]:
    vectors = _normalize_rows(embeddings)
    segment_indices = np.asarray(indices, dtype=int)
    if len(vectors) != len(segment_indices):
        raise ValueError("embedding and index counts differ")
    if np.any(segment_indices < 0) or np.any(segment_indices >= len(segments)):
        raise ValueError("speaker embedding index is outside the segment range")
    labels = _fixed_threshold_labels(
        vectors,
        similarity_threshold=similarity_threshold,
    )
    raw_predictions: dict[int, dict[str, Any]] = {}
    candidates: list[dict[str, Any]] = []
    for label in sorted(set(labels.tolist())):
        positions = np.flatnonzero(labels == label)
        candidate_id = f"S{int(label):03d}"
        center = np.mean(vectors[positions], axis=0)
        center /= float(np.linalg.norm(center)) + 1e-9
        similarities = vectors[positions] @ center
        ranked_positions = sorted(
            positions.tolist(),
            key=lambda position: (
                -float(vectors[position] @ center),
                -(
                    float(segments[int(segment_indices[position])]["end"])
                    - float(segments[int(segment_indices[position])]["start"])
                ),
                int(segment_indices[position]),
            ),
        )
        sample_positions = ranked_positions[: max(1, representative_count)]
        samples = []
        for position in sample_positions:
            segment_index = int(segment_indices[position])
            segment = segments[segment_index]
            samples.append(
                {
                    "turn_id": segment_index + 1,
                    "start": float(segment["start"]),
                    "end": float(segment["end"]),
                    "text": str(segment.get("text") or ""),
                    "similarity": round(float(vectors[position] @ center), 6),
                }
            )
        total_duration = sum(
            float(segments[int(segment_indices[position])]["end"])
            - float(segments[int(segment_indices[position])]["start"])
            for position in positions
        )
        candidates.append(
            {
                "candidate_id": candidate_id,
                "turn_count": len(positions),
                "total_duration": round(total_duration, 3),
                "samples": samples,
            }
        )
        for position, similarity in zip(positions.tolist(), similarities.tolist()):
            raw_predictions[int(segment_indices[position])] = {
                "candidate_id": candidate_id,
                "confidence": round(float(similarity), 6),
                "source": "embedding",
            }
    predictions = _fill_missing_predictions(
        raw_predictions,
        len(segments),
        "candidate_id",
    )
    return {
        "version": 1,
        "model": model,
        "similarity_threshold": similarity_threshold,
        "speaker_count": len(candidates),
        "candidates": candidates,
        "predictions": {
            str(index + 1): value for index, value in sorted(predictions.items())
        },
    }


def classify_registered_speakers(
    embeddings: np.ndarray,
    indices: np.ndarray,
    segments: list[dict[str, Any]],
    candidate_document: dict[str, Any],
    assignments: dict[str, str],
) -> dict[str, Any]:
    vectors = _normalize_rows(embeddings)
    segment_indices = np.asarray(indices, dtype=int)
    if len(vectors) != len(segment_indices):
        raise ValueError("embedding and index counts differ")
    candidates = candidate_document.get("candidates", [])
    candidate_ids = {
        str(candidate.get("candidate_id"))
        for candidate in candidates
        if isinstance(candidate, dict)
    }
    missing = sorted(candidate_ids - set(assignments))
    if missing:
        raise ValueError(f"unassigned speaker candidates: {', '.join(missing)}")
    position_by_turn_id = {
        int(segment_index) + 1: position
        for position, segment_index in enumerate(segment_indices.tolist())
    }
    enrollment_by_speaker: dict[str, list[int]] = {}
    excluded_candidate_ids: list[str] = []
    for candidate in candidates:
        candidate_id = str(candidate["candidate_id"])
        speaker_id = str(assignments[candidate_id])
        if speaker_id == EXCLUDED_CANDIDATE:
            excluded_candidate_ids.append(candidate_id)
            continue
        turn_ids = [
            int(sample["turn_id"])
            for sample in candidate.get("samples", [])
            if int(sample.get("turn_id", -1)) in position_by_turn_id
        ]
        enrollment_by_speaker.setdefault(speaker_id, []).extend(turn_ids)
    if not enrollment_by_speaker:
        raise ValueError("at least one confirmed speaker is required")
    speaker_ids = sorted(enrollment_by_speaker)
    centers = []
    for speaker_id in speaker_ids:
        unique_turn_ids = sorted(set(enrollment_by_speaker[speaker_id]))
        enrollment_by_speaker[speaker_id] = unique_turn_ids
        center = np.mean(
            [vectors[position_by_turn_id[turn_id]] for turn_id in unique_turn_ids],
            axis=0,
        )
        center /= float(np.linalg.norm(center)) + 1e-9
        centers.append(center)
    center_matrix = np.stack(centers)
    raw_predictions: dict[int, dict[str, Any]] = {}
    for vector, segment_index in zip(vectors, segment_indices):
        similarities = vector @ center_matrix.T
        best = int(np.argmax(similarities))
        raw_predictions[int(segment_index)] = {
            "speaker_id": speaker_ids[best],
            "confidence": round(float(similarities[best]), 6),
            "source": "registered_embedding",
        }
    predictions = _fill_missing_predictions(
        raw_predictions,
        len(segments),
        "speaker_id",
    )
    enrollment_turn_ids = sorted(
        {
            turn_id
            for turn_ids in enrollment_by_speaker.values()
            for turn_id in turn_ids
        }
    )
    return {
        "version": 1,
        "model": candidate_document.get("model", "unknown"),
        "speakers": speaker_ids,
        "assignments": dict(sorted(assignments.items())),
        "excluded_candidate_ids": sorted(excluded_candidate_ids),
        "enrollment_by_speaker": enrollment_by_speaker,
        "enrollment_turn_ids": enrollment_turn_ids,
        "predictions": {
            str(index + 1): value for index, value in sorted(predictions.items())
        },
    }


def _score_subset(
    turn_ids: list[int],
    annotations: dict[str, str],
    predicted: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    correct = sum(
        str(predicted.get(str(turn_id), {}).get("speaker_id", "UNKNOWN"))
        == str(annotations[str(turn_id)])
        for turn_id in turn_ids
    )
    return {
        "count": len(turn_ids),
        "correct": correct,
        "accuracy": correct / len(turn_ids) if turn_ids else None,
    }


def score_speaker_predictions(
    prediction_document: dict[str, Any],
    annotations: dict[str, str],
    segments: list[dict[str, Any]],
    *,
    deleted_turn_ids: set[int] | None = None,
) -> dict[str, Any]:
    deleted = deleted_turn_ids or set()
    active_ids = [
        turn_id
        for turn_id in range(1, len(segments) + 1)
        if turn_id not in deleted
    ]
    labeled_ids = [turn_id for turn_id in active_ids if str(turn_id) in annotations]
    predictions = prediction_document.get("predictions", {})
    enrollment = {int(value) for value in prediction_document.get("enrollment_turn_ids", [])}
    held_out_ids = [turn_id for turn_id in labeled_ids if turn_id not in enrollment]
    all_labeled = _score_subset(labeled_ids, annotations, predictions)
    held_out = _score_subset(held_out_ids, annotations, predictions)
    confusion = Counter(
        (
            str(annotations[str(turn_id)]),
            str(predictions.get(str(turn_id), {}).get("speaker_id", "UNKNOWN")),
        )
        for turn_id in labeled_ids
    )
    speakers: dict[str, dict[str, Any]] = {}
    for speaker_id in sorted({str(annotations[str(turn_id)]) for turn_id in labeled_ids}):
        support = sum(str(annotations[str(turn_id)]) == speaker_id for turn_id in labeled_ids)
        predicted_count = sum(
            str(predictions.get(str(turn_id), {}).get("speaker_id", "UNKNOWN")) == speaker_id
            for turn_id in labeled_ids
        )
        correct = confusion[speaker_id, speaker_id]
        precision = correct / predicted_count if predicted_count else 0.0
        recall = correct / support if support else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        speakers[speaker_id] = {
            "support": support,
            "correct": correct,
            "precision": precision,
            "recall": recall,
            "f1": f1,
        }

    def duration_score(long: bool) -> dict[str, Any]:
        turn_ids = [
            turn_id
            for turn_id in labeled_ids
            if (
                float(segments[turn_id - 1]["end"])
                - float(segments[turn_id - 1]["start"])
                >= 1.0
            )
            is long
        ]
        return _score_subset(turn_ids, annotations, predictions)

    return {
        "version": 1,
        "available": bool(labeled_ids),
        "annotated_count": len(labeled_ids),
        "active_total_count": len(active_ids),
        "coverage": len(labeled_ids) / len(active_ids) if active_ids else 0.0,
        "all_labeled": all_labeled,
        "held_out": held_out,
        "speakers": speakers,
        "long": duration_score(True),
        "short": duration_score(False),
        "confusion": {
            f"{truth}->{label}": count
            for (truth, label), count in sorted(confusion.items())
        },
    }
