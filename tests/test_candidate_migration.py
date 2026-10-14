from __future__ import annotations

import hashlib
import json

import numpy as np

from tools.migrate_speaker_candidates import migrate_job_candidates


def test_migration_generates_candidate_artifacts_without_changing_manual_labels(tmp_path) -> None:
    job_dir = tmp_path / "job"
    transcript_dir = job_dir / "transcript"
    transcript_dir.mkdir(parents=True)
    segments = [
        {"start": index * 2.0, "end": index * 2.0 + 1.5, "text": str(index)}
        for index in range(10)
    ]
    (transcript_dir / "segments.json").write_text(json.dumps({"segments": segments}))
    manual = transcript_dir / "manual-speaker-labels.json"
    manual.write_text(json.dumps({"annotations": {"1": "SPEAKER_00"}}))
    before = hashlib.sha256(manual.read_bytes()).hexdigest()
    source_embeddings = tmp_path / "campplus.npz"
    np.savez_compressed(
        source_embeddings,
        embeddings=np.vstack([np.tile([1.0, 0.0], (5, 1)), np.tile([0.0, 1.0], (5, 1))]),
        indices=np.arange(10),
    )

    result = migrate_job_candidates(
        job_dir,
        source_embeddings,
        model="CAM++",
        similarity_threshold=0.4,
    )

    assert result["speaker_count"] == 2
    assert (transcript_dir / "speaker-candidates.json").is_file()
    assert (transcript_dir / "speaker-embeddings.npz").is_file()
    assert hashlib.sha256(manual.read_bytes()).hexdigest() == before
