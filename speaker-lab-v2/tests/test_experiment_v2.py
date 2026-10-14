import inspect
import json

import numpy as np

from speaker_lab_v2.experiment_v2 import run_experiment


def test_batch_experiment_flattens_three_label_free_strategies_per_model(tmp_path):
    segments = [
        {"start": index * 1.5, "end": index * 1.5 + 1.2}
        for index in range(48)
    ]
    segments_path = tmp_path / "segments.json"
    segments_path.write_text(json.dumps({"segments": segments}))
    rng = np.random.default_rng(2)
    centers = np.eye(4)
    embeddings = np.vstack(
        [centers[index % 4] + rng.normal(scale=0.01, size=4) for index in range(48)]
    )
    embeddings /= np.linalg.norm(embeddings, axis=1, keepdims=True)
    embedding_path = tmp_path / "embedding.npz"
    np.savez(embedding_path, embeddings=embeddings, indices=np.arange(48))
    output = tmp_path / "run"

    assert "manual" not in inspect.signature(run_experiment).parameters
    result = run_experiment(
        segments_path=segments_path,
        embedding_paths={"M": embedding_path},
        output_dir=output,
        random_state=0,
    )

    assert set(result["models"]) == {
        "M:raw_nme",
        "M:turn_nme",
        "M:multiscale_micro_nme",
    }
    assert all(len(item["predictions"]) == 48 for item in result["models"].values())
    assert (output / "inferred-speakers.json").is_file()
    assert (output / "diagnostics.json").is_file()
