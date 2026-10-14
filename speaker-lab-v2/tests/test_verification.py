import inspect

import numpy as np

from speaker_lab_v2.verification import evaluate_enrollment, fixed_threshold_ahc


def test_fixed_threshold_ahc_discovers_two_compact_groups_without_count_prior():
    rng = np.random.default_rng(1)
    left = np.array([1.0, 0.0]) + rng.normal(scale=0.01, size=(6, 2))
    right = np.array([0.0, 1.0]) + rng.normal(scale=0.01, size=(6, 2))
    embeddings = np.vstack([left, right])
    embeddings /= np.linalg.norm(embeddings, axis=1, keepdims=True)

    result = fixed_threshold_ahc(embeddings, similarity_threshold=0.4)

    assert "speaker_count" not in inspect.signature(fixed_threshold_ahc).parameters
    assert "manual" not in inspect.signature(fixed_threshold_ahc).parameters
    assert result.speaker_count == 2
    assert len(set(result.labels[:6])) == 1
    assert len(set(result.labels[6:])) == 1
    assert result.labels[0] != result.labels[6]


def test_enrollment_uses_earliest_eligible_turns_and_excludes_them_from_evaluation():
    segments = [
        {"start": 0.0, "end": 1.5},
        {"start": 2.0, "end": 4.5},
        {"start": 5.0, "end": 7.5},
        {"start": 8.0, "end": 10.5},
        {"start": 11.0, "end": 13.5},
        {"start": 14.0, "end": 16.5},
    ]
    annotations = {
        "1": "A",
        "2": "A",
        "3": "A",
        "4": "B",
        "5": "B",
        "6": "B",
    }
    base = np.array(
        [[1.0, 0.0], [1.0, 0.0], [1.0, 0.0], [0.0, 1.0], [0.0, 1.0], [0.0, 1.0]]
    )
    order = np.array([4, 1, 5, 2, 0, 3])

    result = evaluate_enrollment(
        base[order],
        order,
        segments,
        annotations,
        enrollment_count=1,
        min_duration=2.0,
    )

    assert result.enrollment_ids == {"A": (2,), "B": (4,)}
    assert 2 not in result.evaluation_ids
    assert 4 not in result.evaluation_ids
    assert result.evaluation_count == 4
    assert result.accuracy == 1.0
