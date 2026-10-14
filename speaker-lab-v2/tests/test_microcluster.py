import inspect

import numpy as np

from speaker_lab_v2.microcluster import build_microclusters


def _unit_rows(center, count, rng):
    rows = center + rng.normal(scale=0.02, size=(count, len(center)))
    return rows / np.linalg.norm(rows, axis=1, keepdims=True)


def test_overclustering_preserves_rare_directions_without_true_speaker_count():
    rng = np.random.default_rng(7)
    centers = np.eye(4)
    embeddings = np.vstack(
        [
            _unit_rows(centers[0], 100, rng),
            _unit_rows(centers[1], 100, rng),
            _unit_rows(centers[2], 5, rng),
            _unit_rows(centers[3], 5, rng),
        ]
    )
    rows = [
        {"index": index, "start": index * 2.0, "end": index * 2.0 + 1.5}
        for index in range(len(embeddings))
    ]

    clusters = build_microclusters(
        embeddings, rows, window_seconds=600, model_name="synthetic"
    )

    assert "speaker_count" not in inspect.signature(build_microclusters).parameters
    assert 6 <= len(clusters) <= 10
    assert all(np.isclose(np.linalg.norm(cluster.centroid), 1.0) for cluster in clusters)
    for rare_center in centers[2:]:
        assert max(float(cluster.centroid @ rare_center) for cluster in clusters) > 0.9


def test_microclusters_record_duration_compactness_and_members():
    embeddings = np.eye(6)
    rows = [
        {"index": index, "start": index * 2.0, "end": index * 2.0 + 1.25}
        for index in range(6)
    ]

    clusters = build_microclusters(
        embeddings, rows, window_seconds=300, model_name="synthetic"
    )

    assert sum(len(cluster.member_indices) for cluster in clusters) == 6
    assert np.isclose(sum(cluster.duration for cluster in clusters), 7.5)
    assert all(0.0 <= cluster.compactness <= 1.0 for cluster in clusters)
