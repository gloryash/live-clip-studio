import numpy as np

from speaker_lab_v2.models import Prototype
from speaker_lab_v2.multiscale import estimate_stable_speakers


def prototype(prototype_id, center, scale):
    vector = np.asarray(center, dtype=np.float32)
    vector /= np.linalg.norm(vector)
    return Prototype(
        prototype_id=prototype_id,
        centroid=vector,
        evidence_count=3,
        duration=12.0,
        window_ids={f"{scale}:0", f"{scale}:{scale}"},
        scale_seconds={scale},
        cluster_ids=[prototype_id],
    )


def test_four_cross_scale_directions_are_counted_and_single_scale_noise_is_not():
    bases = np.eye(5)
    scales = {
        300: [prototype(f"a{index}", bases[index], 300) for index in range(4)]
        + [prototype("noise", bases[4], 300)],
        600: [
            prototype(f"b{index}", bases[index] + 0.02, 600) for index in range(4)
        ],
        1200: [
            prototype(f"c{index}", bases[index] + 0.01, 1200) for index in range(4)
        ],
    }

    result = estimate_stable_speakers(scales, similarity_threshold=0.85, min_scales=2)

    assert result.speaker_count == 4
    assert len(result.stable_prototypes) == 4
    assert all(item.scale_support >= 2 for item in result.stable_prototypes)
    assert all(0.0 <= item.confidence <= 1.0 for item in result.stable_prototypes)


def test_same_scale_prototypes_are_not_joined_directly():
    scales = {
        300: [
            prototype("a", [1.0, 0.0], 300),
            prototype("b", [0.99, 0.01], 300),
        ],
        600: [prototype("c", [0.0, 1.0], 600)],
    }

    result = estimate_stable_speakers(scales, similarity_threshold=0.8, min_scales=2)

    assert result.speaker_count == 0
