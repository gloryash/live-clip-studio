import inspect

import numpy as np

from speaker_lab_v2.strategies import (
    multiscale_micro_nme,
    raw_nme,
    turn_nme,
)


def _fixture():
    rng = np.random.default_rng(4)
    embeddings = []
    rows = []
    for repeat in range(3):
        for speaker, center in enumerate(np.eye(4)):
            for _ in range(8):
                vector = center + rng.normal(scale=0.01, size=4)
                vector /= np.linalg.norm(vector)
                index = len(rows)
                embeddings.append(vector)
                rows.append(
                    {
                        "index": index,
                        "start": index * 2.0,
                        "end": index * 2.0 + 1.5,
                    }
                )
    return np.asarray(embeddings), rows


def test_all_strategies_are_label_free_and_return_one_label_per_embedding():
    embeddings, rows = _fixture()
    strategies = (raw_nme, turn_nme, multiscale_micro_nme)

    for strategy in strategies:
        parameters = inspect.signature(strategy).parameters
        assert "speaker_count" not in parameters
        assert "manual" not in parameters
        result = strategy(embeddings, rows, model_name="synthetic")
        assert len(result.labels) == len(embeddings)
        assert result.speaker_count >= 2
        assert result.evidence


def test_multiscale_micro_graph_uses_centers_not_repeated_members():
    embeddings, rows = _fixture()

    result = multiscale_micro_nme(embeddings, rows, model_name="synthetic")

    assert result.evidence["graph_node_count"] < len(embeddings) * 3
    assert result.evidence["scales"] == [300, 600, 1200]
