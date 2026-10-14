import inspect
import json
from pathlib import Path

import numpy as np

import speaker_lab_v2.data as data_module
import speaker_lab_v2.pipeline as pipeline_module
from speaker_lab_v2.models import InferenceConfig
from speaker_lab_v2.pipeline import run_inference


def test_inference_api_and_source_have_no_label_dependency():
    assert "manual" not in inspect.signature(run_inference).parameters
    source = Path(pipeline_module.__file__).read_text().lower()
    data_source = Path(data_module.__file__).read_text().lower()
    assert "manual-speaker-labels" not in source
    assert "manual-speaker-labels" not in data_source
    assert "from .scoring" not in source


def test_inference_writes_isolated_structured_outputs(tmp_path):
    segments = [
        {"start": index * 2.0, "end": index * 2.0 + 1.4, "text": str(index)}
        for index in range(36)
    ]
    segments_path = tmp_path / "segments.json"
    segments_path.write_text(json.dumps({"segments": segments}))
    centers = np.eye(3)
    embeddings = np.vstack(
        [centers[index % 3] + 0.01 for index in range(len(segments))]
    )
    embeddings /= np.linalg.norm(embeddings, axis=1, keepdims=True)
    embedding_path = tmp_path / "embeddings.npz"
    np.savez(embedding_path, embeddings=embeddings, indices=np.arange(len(segments)))
    output = tmp_path / "run"

    result = run_inference(
        segments_path=segments_path,
        embedding_paths={"synthetic": embedding_path},
        output_dir=output,
        config=InferenceConfig(
            window_seconds=(20, 40, 60),
            match_similarity=0.6,
            candidate_similarity=0.6,
            stable_scales=2,
        ),
    )

    assert "synthetic" in result["models"]
    assert set(path.name for path in output.iterdir()) == {
        "config.json",
        "inferred-speakers.json",
        "prototypes.json",
        "candidate-speakers.json",
        "speaker-count.json",
    }
    assert json.loads((output / "inferred-speakers.json").read_text())["models"]

