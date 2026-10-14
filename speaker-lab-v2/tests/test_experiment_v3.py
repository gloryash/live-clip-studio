import inspect
import json

import numpy as np

from speaker_lab_v2.experiment_v3 import (
    run_ahc_experiment,
    run_enrollment_experiment,
)


def _fixture(tmp_path):
    segments = []
    annotations = {}
    embeddings = []
    for speaker, center in enumerate(np.eye(4)):
        for offset in range(6):
            index = len(segments)
            segments.append(
                {"start": index * 3.0, "end": index * 3.0 + 2.5}
            )
            annotations[str(index + 1)] = f"SPK{speaker}"
            embeddings.append(center)
    segments_path = tmp_path / "segments.json"
    labels_path = tmp_path / "labels.json"
    embedding_path = tmp_path / "embedding.npz"
    segments_path.write_text(json.dumps({"segments": segments}))
    labels_path.write_text(json.dumps({"annotations": annotations}))
    np.savez(
        embedding_path,
        embeddings=np.asarray(embeddings),
        indices=np.arange(len(embeddings)),
    )
    return segments_path, labels_path, embedding_path


def test_ahc_is_label_free_and_enrollment_writes_three_held_out_protocols(tmp_path):
    segments, labels, embeddings = _fixture(tmp_path)
    output = tmp_path / "run"

    assert "manual" not in inspect.signature(run_ahc_experiment).parameters
    ahc = run_ahc_experiment(
        segments_path=segments,
        embedding_paths={"ECAPA": embeddings},
        output_dir=output,
    )
    enrollment = run_enrollment_experiment(
        segments_path=segments,
        embedding_paths={"ECAPA": embeddings},
        manual_labels_path=labels,
        output_dir=output,
    )

    assert set(ahc["models"]) == {"ECAPA:official_ahc"}
    assert set(enrollment["models"]["ECAPA"]) == {"1", "3", "5"}
    assert enrollment["models"]["ECAPA"]["1"]["evaluation_count"] == 20
    assert (output / "ahc-predictions.json").is_file()
    assert (output / "enrollment-metrics.json").is_file()
