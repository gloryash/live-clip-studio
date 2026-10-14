from __future__ import annotations

import numpy as np

from live_clip_studio.speaker_workflow import (
    classify_registered_speakers,
    discover_candidates,
    score_speaker_predictions,
)


def _normalized_cloud(center: np.ndarray, count: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    values = center + rng.normal(scale=0.01, size=(count, len(center)))
    return values / np.linalg.norm(values, axis=1, keepdims=True)


def _segments(count: int) -> list[dict]:
    return [
        {
            "start": index * 2.5,
            "end": index * 2.5 + 2.0,
            "text": f"第 {index + 1} 句",
        }
        for index in range(count)
    ]


def test_discovers_four_candidates_without_a_speaker_count_prior() -> None:
    embeddings = np.vstack(
        [
            _normalized_cloud(center, 6, seed)
            for seed, center in enumerate(np.eye(4), start=1)
        ]
    )
    segments = _segments(len(embeddings))

    result = discover_candidates(
        embeddings,
        np.arange(len(embeddings)),
        segments,
        model="CAM++",
        similarity_threshold=0.4,
    )

    assert result["speaker_count"] == 4
    assert [candidate["candidate_id"] for candidate in result["candidates"]] == [
        "S000",
        "S001",
        "S002",
        "S003",
    ]
    assert all(len(candidate["samples"]) == 3 for candidate in result["candidates"])
    assert result["candidates"][0]["samples"][0]["start"] >= 0
    assert set(result["predictions"]) == {str(index) for index in range(1, 25)}


def test_registration_can_merge_two_candidates_into_one_real_speaker() -> None:
    speaker_one_a = _normalized_cloud(np.array([1.0, 0.0, 0.0]), 6, 2)
    speaker_one_b = _normalized_cloud(np.array([0.96, 0.18, 0.0]), 6, 3)
    speaker_two = _normalized_cloud(np.array([0.0, 1.0, 0.0]), 6, 4)
    embeddings = np.vstack([speaker_one_a, speaker_one_b, speaker_two])
    indices = np.arange(len(embeddings))
    segments = _segments(len(embeddings))
    candidates = discover_candidates(
        embeddings,
        indices,
        segments,
        similarity_threshold=0.995,
    )

    result = classify_registered_speakers(
        embeddings,
        indices,
        segments,
        candidates,
        {
            "S000": "SPEAKER_00",
            "S001": "SPEAKER_00",
            "S002": "SPEAKER_01",
        },
    )

    assert set(result["speakers"]) == {"SPEAKER_00", "SPEAKER_01"}
    assert len(result["enrollment_turn_ids"]) == 9
    assert {
        prediction["speaker_id"]
        for prediction in result["predictions"].values()
    } == {"SPEAKER_00", "SPEAKER_01"}
    assert all(
        result["predictions"][str(turn_id)]["speaker_id"] == "SPEAKER_00"
        for turn_id in range(1, 13)
    )


def test_excluded_mixed_candidate_is_not_used_for_enrollment_but_its_turns_are_classified() -> None:
    speaker_one = _normalized_cloud(np.array([1.0, 0.0, 0.0]), 6, 12)
    mixed = _normalized_cloud(np.array([0.72, 0.68, 0.0]), 6, 13)
    speaker_two = _normalized_cloud(np.array([0.0, 1.0, 0.0]), 6, 14)
    embeddings = np.vstack([speaker_one, mixed, speaker_two])
    indices = np.arange(len(embeddings))
    segments = _segments(len(embeddings))
    candidates = discover_candidates(
        embeddings,
        indices,
        segments,
        similarity_threshold=0.995,
    )
    excluded_samples = {
        sample["turn_id"]
        for sample in candidates["candidates"][1]["samples"]
    }

    result = classify_registered_speakers(
        embeddings,
        indices,
        segments,
        candidates,
        {
            "S000": "SPEAKER_00",
            "S001": "__EXCLUDED__",
            "S002": "SPEAKER_01",
        },
    )

    assert result["speakers"] == ["SPEAKER_00", "SPEAKER_01"]
    assert result["excluded_candidate_ids"] == ["S001"]
    assert excluded_samples.isdisjoint(result["enrollment_turn_ids"])
    assert all(
        result["predictions"][str(turn_id)]["speaker_id"] in {"SPEAKER_00", "SPEAKER_01"}
        for turn_id in range(7, 13)
    )


def test_metrics_use_only_labeled_active_turns_and_hold_out_enrollment() -> None:
    predictions = {
        "version": 1,
        "enrollment_turn_ids": [1, 3],
        "predictions": {
            "1": {"speaker_id": "SPEAKER_00", "confidence": 0.99},
            "2": {"speaker_id": "SPEAKER_01", "confidence": 0.80},
            "3": {"speaker_id": "SPEAKER_01", "confidence": 0.99},
            "4": {"speaker_id": "SPEAKER_00", "confidence": 0.70},
            "5": {"speaker_id": "SPEAKER_00", "confidence": 0.70},
        },
    }
    annotations = {
        "1": "SPEAKER_00",
        "2": "SPEAKER_00",
        "3": "SPEAKER_01",
        "4": "SPEAKER_00",
        "5": "SPEAKER_01",
    }
    segments = _segments(6)

    metrics = score_speaker_predictions(
        predictions,
        annotations,
        segments,
        deleted_turn_ids={5},
    )

    assert metrics["annotated_count"] == 4
    assert metrics["active_total_count"] == 5
    assert metrics["coverage"] == 0.8
    assert metrics["all_labeled"] == {"count": 4, "correct": 3, "accuracy": 0.75}
    assert metrics["held_out"] == {"count": 2, "correct": 1, "accuracy": 0.5}
    assert metrics["speakers"]["SPEAKER_00"]["support"] == 3
    assert metrics["confusion"]["SPEAKER_00->SPEAKER_01"] == 1
