import numpy as np

from speaker_lab_v2.models import InferenceConfig, MicroCluster
from speaker_lab_v2.registry import PrototypeRegistry


def cluster(cluster_id, window_id, centroid, duration=4.0, member_count=2):
    vector = np.asarray(centroid, dtype=np.float32)
    vector /= np.linalg.norm(vector)
    return MicroCluster(
        cluster_id=cluster_id,
        window_id=window_id,
        scale_seconds=600,
        model_name="synthetic",
        centroid=vector,
        member_indices=tuple(range(member_count)),
        duration=duration,
        compactness=0.98,
    )


def test_new_voice_becomes_candidate_then_promotes_after_another_window():
    registry = PrototypeRegistry(
        InferenceConfig(match_similarity=0.80, candidate_similarity=0.80)
    )
    registry.observe(
        [
            cluster("a1", "600:0", [1.0, 0.0, 0.0]),
            cluster("b1", "600:0", [0.0, 1.0, 0.0]),
        ]
    )
    assert registry.confirmed_count == 0
    assert registry.candidate_count == 2

    registry.observe(
        [
            cluster("a2", "600:600", [0.99, 0.05, 0.0]),
            cluster("b2", "600:600", [0.03, 0.99, 0.0]),
        ]
    )
    assert registry.confirmed_count == 2
    assert registry.candidate_count == 0

    registry.observe(
        [
            cluster("a3", "600:1200", [1.0, 0.02, 0.0]),
            cluster("c1", "600:1200", [0.0, 0.0, 1.0]),
        ]
    )
    assert registry.confirmed_count == 2
    assert registry.candidate_count == 1


def test_prototype_updates_are_equal_per_microcluster_not_member_count():
    registry = PrototypeRegistry(
        InferenceConfig(match_similarity=0.0, candidate_similarity=0.0)
    )
    registry.observe([cluster("a1", "600:0", [1.0, 0.0], member_count=100)])
    registry.observe([cluster("a2", "600:600", [0.0, 1.0], member_count=1)])

    prototype = registry.confirmed[0]
    expected = np.array([1.0, 1.0]) / np.sqrt(2.0)
    np.testing.assert_allclose(prototype.centroid, expected, atol=1e-6)


def test_one_prototype_cannot_absorb_two_clusters_from_same_window():
    registry = PrototypeRegistry(
        InferenceConfig(match_similarity=0.70, candidate_similarity=0.70)
    )
    registry.observe([cluster("a1", "600:0", [1.0, 0.0])])
    registry.observe([cluster("a2", "600:600", [1.0, 0.0])])
    assert registry.confirmed_count == 1

    registry.observe(
        [
            cluster("a3", "600:1200", [1.0, 0.01]),
            cluster("a4", "600:1200", [0.99, 0.02]),
        ]
    )

    assert registry.confirmed[0].evidence_count == 3
    assert registry.candidate_count == 1
