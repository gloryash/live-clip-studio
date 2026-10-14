import inspect

import numpy as np

from speaker_lab_v2.graph_cluster import nme_spectral_cluster


def _cloud(center, count, rng):
    values = center + rng.normal(scale=0.015, size=(count, len(center)))
    return values / np.linalg.norm(values, axis=1, keepdims=True)


def test_nme_spectral_discovers_four_directions_without_count_prior():
    rng = np.random.default_rng(12)
    centers = np.eye(4)
    embeddings = np.vstack([_cloud(center, 30, rng) for center in centers])

    result = nme_spectral_cluster(embeddings, random_state=5)

    assert "speaker_count" not in inspect.signature(nme_spectral_cluster).parameters
    assert result.speaker_count == 4
    assert len(result.labels) == len(embeddings)
    assert result.neighbor_count in {5, 10, 20, 40, 80}
    assert result.eigengap > 0


def test_nme_spectral_is_deterministic_for_a_fixed_seed():
    rng = np.random.default_rng(3)
    embeddings = np.vstack([_cloud(center, 20, rng) for center in np.eye(3)])

    first = nme_spectral_cluster(embeddings, random_state=9)
    second = nme_spectral_cluster(embeddings, random_state=9)

    assert first.speaker_count == second.speaker_count
    assert np.array_equal(first.labels, second.labels)
