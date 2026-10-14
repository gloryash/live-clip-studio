from __future__ import annotations

import numpy as np

from live_clip_studio.diarization import (
    DiarizationService,
    assign_speakers_to_segments,
    canonicalize,
    cluster_embeddings,
)


def test_auto_clustering_detects_two_clear_speaker_groups() -> None:
    embeddings = np.array(
        [
            [1.0, 0.02, 0.0],
            [0.98, 0.04, 0.01],
            [1.0, -0.03, 0.02],
            [0.01, 0.99, 0.0],
            [0.03, 1.0, 0.02],
            [-0.02, 0.98, 0.01],
        ],
        dtype=np.float32,
    )

    labels = cluster_embeddings(embeddings, speaker_count=0)

    assert len(set(labels.tolist())) == 2
    assert len(set(labels[:3].tolist())) == 1
    assert len(set(labels[3:].tolist())) == 1
    assert labels[0] != labels[3]


def test_canonical_labels_follow_first_seen_order() -> None:
    assert canonicalize(np.array([8, 8, 3, 3, 8])) == [
        "SPEAKER_00",
        "SPEAKER_00",
        "SPEAKER_01",
        "SPEAKER_01",
        "SPEAKER_00",
    ]


def test_short_unembedded_segment_inherits_nearest_speaker() -> None:
    segments = [
        {"start": 0.0, "end": 2.0, "text": "第一段"},
        {"start": 2.1, "end": 2.5, "text": "嗯"},
        {"start": 2.6, "end": 4.5, "text": "继续说"},
    ]
    rows = [
        {"index": 0, **segments[0]},
        {"index": 2, **segments[2]},
    ]

    turns = assign_speakers_to_segments(
        segments,
        rows,
        ["SPEAKER_00", "SPEAKER_00"],
    )

    assert [turn["speaker"] for turn in turns] == ["SPEAKER_00"] * 3
    assert turns[1]["speaker_source"] == "nearest"


def test_diarization_uses_finer_candidate_similarity_threshold(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        "live_clip_studio.diarization.load_audio",
        lambda path: (np.ones(16000, dtype=np.float32), 16000),
    )
    monkeypatch.setattr(
        "live_clip_studio.diarization.encode_segments",
        lambda classifier, audio, sample_rate, segments: (
            np.asarray([[1.0, 0.0]], dtype=np.float32),
            [{"index": 0, **segments[0]}],
        ),
    )
    service = DiarizationService(model_dir=tmp_path)
    monkeypatch.setattr(service, "_load_classifier", lambda: object())

    result = service.run(
        tmp_path / "audio.wav",
        [{"start": 0.0, "end": 2.0, "text": "test"}],
    )

    assert result["embedding_cache"]["similarity_threshold"] == 0.35
