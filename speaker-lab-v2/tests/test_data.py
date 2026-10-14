import inspect
import json

import numpy as np
import pytest

from speaker_lab_v2.data import load_embedding_cache, load_inference_inputs


def test_load_embedding_cache_normalizes_vectors_and_preserves_zero_based_indexes(tmp_path):
    path = tmp_path / "embeddings.npz"
    np.savez(path, embeddings=np.array([[3.0, 4.0], [0.0, 2.0]]), indices=[0, 2])

    cache = load_embedding_cache(path)

    np.testing.assert_allclose(np.linalg.norm(cache.embeddings, axis=1), [1.0, 1.0])
    assert cache.indices.tolist() == [0, 2]


def test_load_embedding_cache_rejects_zero_vectors(tmp_path):
    path = tmp_path / "embeddings.npz"
    np.savez(path, embeddings=np.array([[0.0, 0.0]]), indices=[0])

    with pytest.raises(ValueError, match="zero-length embedding"):
        load_embedding_cache(path)


def test_inference_inputs_expose_no_manual_label_argument(tmp_path):
    assert "manual" not in inspect.signature(load_inference_inputs).parameters
    segments_path = tmp_path / "segments.json"
    segments_path.write_text(json.dumps({"segments": [{"start": 0.0, "end": 1.2}]}))
    embedding_path = tmp_path / "embeddings.npz"
    np.savez(embedding_path, embeddings=np.array([[1.0, 0.0]]), indices=[0])

    inputs = load_inference_inputs(segments_path, {"ECAPA": embedding_path})

    assert len(inputs.segments) == 1
    assert inputs.caches["ECAPA"].indices.tolist() == [0]
