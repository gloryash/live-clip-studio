from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path

import numpy as np

from fastapi.testclient import TestClient

from live_clip_studio.app import create_app
from live_clip_studio.config import Settings
from live_clip_studio.whisper_client import WhisperServiceError


@dataclass
class FakeWhisper:
    unavailable: bool = False

    def health(self) -> dict:
        if self.unavailable:
            raise WhisperServiceError(
                code="WHISPER_UNAVAILABLE",
                message="请先开启语音转录服务：本机 Whisper Large V3 Turbo",
                detail="connection refused",
            )
        return {"status": "ok", "model": "mlx-community/whisper-large-v3-turbo"}


@dataclass
class RecordingProcessor:
    submitted: list[str] = field(default_factory=list)

    def submit_transcript(self, job_id: str) -> None:
        self.submitted.append(job_id)


def make_client(
    tmp_path: Path,
    *,
    whisper: FakeWhisper | None = None,
    processor: RecordingProcessor | None = None,
    max_upload_bytes: int = 10_000_000,
) -> tuple[TestClient, RecordingProcessor]:
    processor = processor or RecordingProcessor()
    data_dir = tmp_path / "data"
    app = create_app(
        settings=Settings(data_dir=data_dir, max_upload_bytes=max_upload_bytes),
        whisper_client=whisper or FakeWhisper(),
        media_probe=lambda: {"ffmpeg": True, "ffprobe": True},
        diarization_probe=lambda: {"status": "ready", "detail": None},
        processor=processor,
    )
    return TestClient(app), processor


def test_upload_streams_file_persists_job_and_submits_pipeline(
    tmp_path: Path,
    sample_mp4: Path,
) -> None:
    client, processor = make_client(tmp_path)

    with sample_mp4.open("rb") as source:
        response = client.post(
            "/api/jobs",
            files={"file": ("live.mp4", source, "video/mp4")},
        )

    assert response.status_code == 202
    job_id = response.json()["job_id"]
    assert (tmp_path / "data" / job_id / "source.mp4").stat().st_size == sample_mp4.stat().st_size
    assert (tmp_path / "data" / job_id / "job.json").is_file()
    assert processor.submitted == [job_id]
    restored = client.get(f"/api/jobs/{job_id}")
    assert restored.status_code == 200
    assert restored.json()["job_id"] == job_id
    assert restored.json()["status"] == "uploaded"


def test_identical_upload_reuses_existing_job(tmp_path: Path, sample_mp4: Path) -> None:
    client, processor = make_client(tmp_path)

    first = client.post(
        "/api/jobs",
        files={"file": ("first-name.mp4", sample_mp4.read_bytes(), "video/mp4")},
    )
    second = client.post(
        "/api/jobs",
        files={"file": ("renamed.mp4", sample_mp4.read_bytes(), "video/mp4")},
    )

    assert first.status_code == 202
    assert second.status_code == 200
    assert second.json()["reused"] is True
    assert second.json()["job_id"] == first.json()["job_id"]
    assert len(client.get("/api/jobs").json()["jobs"]) == 1
    assert processor.submitted == [first.json()["job_id"]]


def test_identical_upload_reprocesses_existing_failed_job(
    tmp_path: Path,
    sample_mp4: Path,
) -> None:
    client, processor = make_client(tmp_path)
    first = client.post(
        "/api/jobs",
        files={"file": ("failed.mp4", sample_mp4.read_bytes(), "video/mp4")},
    )
    job_id = first.json()["job_id"]
    client.app.state.job_store.update(
        job_id,
        status="failed",
        stage="failed",
        progress=25,
        error={"code": "WHISPER_JOB_FAILED", "message": "转录失败"},
    )

    second = client.post(
        "/api/jobs",
        files={"file": ("same-content.mp4", sample_mp4.read_bytes(), "video/mp4")},
    )

    assert second.status_code == 202
    assert second.json()["job_id"] == job_id
    assert second.json()["reused"] is True
    assert second.json()["reprocessed"] is True
    restored = client.get(f"/api/jobs/{job_id}").json()
    assert restored["status"] == "uploaded"
    assert restored["stage"] == "queued"
    assert restored["progress"] == 0
    assert restored["error"] is None
    assert processor.submitted == [job_id, job_id]


def test_history_lists_newest_job_first_with_workspace_url(tmp_path: Path) -> None:
    client, _ = make_client(tmp_path)
    store = client.app.state.job_store
    older = store.create("older.mp4")
    newer = store.create("newer.mp4")
    store.update(older["job_id"], source_sha256="a", source_size=1)
    store.update(newer["job_id"], source_sha256="b", source_size=2, keyframe_count=12)

    response = client.get("/api/jobs")

    assert response.status_code == 200
    jobs = response.json()["jobs"]
    assert [job["job_id"] for job in jobs] == [newer["job_id"], older["job_id"]]
    assert jobs[0]["workspace_url"] == f"/workspace/{newer['job_id']}"
    assert jobs[0]["keyframe_count"] == 12


def test_explicit_transcript_reprocess_keeps_existing_keyframes(tmp_path: Path) -> None:
    client, processor = make_client(tmp_path)
    store = client.app.state.job_store
    job = store.create("live.mp4")
    store.update(
        job["job_id"],
        status="ready",
        stage="ready",
        progress=100,
        keyframes_status="ready",
        keyframe_count=8,
    )

    response = client.post(f"/api/jobs/{job['job_id']}/transcript/reprocess")

    assert response.status_code == 202
    assert processor.submitted == [job["job_id"]]
    preserved = store.get(job["job_id"])
    assert preserved["keyframes_status"] == "ready"
    assert preserved["keyframe_count"] == 8


def test_transcript_reprocess_clears_turn_state_but_keeps_speaker_names(tmp_path: Path) -> None:
    client, processor = make_client(tmp_path)
    store = client.app.state.job_store
    job = store.create("live.mp4")
    job_id = job["job_id"]
    transcript_dir = store.job_dir(job_id) / "transcript"
    transcript_dir.mkdir()
    stale_names = (
        "audio-16k-mono.wav",
        "raw.json",
        "raw.txt",
        "segments.json",
        "speaker-turns.json",
        "speaker-embeddings.npz",
        "speaker-candidates.json",
        "speaker-candidate-assignments.json",
        "speaker-predictions.json",
        "manual-speaker-labels.json",
        "deleted-turns.json",
    )
    for name in stale_names:
        (transcript_dir / name).write_bytes(b"stale")
    speaker_names = transcript_dir / "manual-speakers.json"
    speaker_names.write_text(
        json.dumps({"version": 1, "speakers": {"SPEAKER_00": "monica"}}),
        encoding="utf-8",
    )
    store.update(job_id, status="ready", stage="ready", progress=100, keyframes_status="ready")

    response = client.post(f"/api/jobs/{job_id}/transcript/reprocess")

    assert response.status_code == 202
    assert processor.submitted == [job_id]
    assert all(not (transcript_dir / name).exists() for name in stale_names)
    assert json.loads(speaker_names.read_text())["speakers"] == {"SPEAKER_00": "monica"}
    assert store.get(job_id)["keyframes_status"] == "ready"


def test_rebuild_speaker_candidates_reuses_embeddings_without_whisper(tmp_path: Path) -> None:
    client, processor = make_client(tmp_path)
    store = client.app.state.job_store
    job = store.create("live.mp4")
    job_id = job["job_id"]
    store.update(job_id, status="ready", stage="ready", progress=100)
    transcript_dir = store.job_dir(job_id) / "transcript"
    transcript_dir.mkdir()
    segments_path = transcript_dir / "segments.json"
    turns_path = transcript_dir / "speaker-turns.json"
    segments_path.write_text(
        json.dumps({"segments": [{"start": 0.0, "end": 2.0, "text": "hello"}]}),
        encoding="utf-8",
    )
    turns_path.write_text(json.dumps({"turns": [{"id": 1, "text": "hello"}]}), encoding="utf-8")
    np.savez_compressed(
        transcript_dir / "speaker-embeddings.npz",
        embeddings=np.asarray([[1.0, 0.0]], dtype=np.float32),
        indices=np.asarray([0], dtype=np.int32),
    )
    (transcript_dir / "speaker-candidates.json").write_text('{"old": true}', encoding="utf-8")
    assignments_path = transcript_dir / "speaker-candidate-assignments.json"
    predictions_path = transcript_dir / "speaker-predictions.json"
    assignments_path.write_text('{"assignments": {"S000": "SPEAKER_00"}}', encoding="utf-8")
    predictions_path.write_text('{"predictions": {}}', encoding="utf-8")
    manual_speakers_path = transcript_dir / "manual-speakers.json"
    manual_labels_path = transcript_dir / "manual-speaker-labels.json"
    manual_speakers_path.write_text('{"speakers": {"SPEAKER_00": "Michael"}}', encoding="utf-8")
    manual_labels_path.write_text('{"annotations": {"1": "SPEAKER_00"}}', encoding="utf-8")
    segments_before = segments_path.read_bytes()
    turns_before = turns_path.read_bytes()

    response = client.post(f"/api/jobs/{job_id}/speaker-candidates/rebuild")

    assert response.status_code == 200
    assert response.json()["similarity_threshold"] == 0.35
    assert response.json()["speaker_count"] == 1
    assert processor.submitted == []
    assert segments_path.read_bytes() == segments_before
    assert turns_path.read_bytes() == turns_before
    assert not assignments_path.exists()
    assert not predictions_path.exists()
    assert manual_speakers_path.exists()
    assert manual_labels_path.exists()
    rebuilt = json.loads((transcript_dir / "speaker-candidates.json").read_text())
    assert rebuilt["similarity_threshold"] == 0.35


def test_rebuild_candidates_keeps_existing_result_when_embeddings_missing(tmp_path: Path) -> None:
    client, processor = make_client(tmp_path)
    store = client.app.state.job_store
    job = store.create("live.mp4")
    job_id = job["job_id"]
    store.update(job_id, status="ready", stage="ready", progress=100)
    transcript_dir = store.job_dir(job_id) / "transcript"
    transcript_dir.mkdir()
    (transcript_dir / "segments.json").write_text('{"segments": []}', encoding="utf-8")
    candidate_path = transcript_dir / "speaker-candidates.json"
    candidate_path.write_text('{"old": true}', encoding="utf-8")
    old_candidate_bytes = candidate_path.read_bytes()

    response = client.post(f"/api/jobs/{job_id}/speaker-candidates/rebuild")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "EMBEDDINGS_NOT_READY"
    assert candidate_path.read_bytes() == old_candidate_bytes
    assert processor.submitted == []


def test_job_can_be_restored_by_a_new_app_instance(tmp_path: Path, sample_mp4: Path) -> None:
    first, _ = make_client(tmp_path)
    response = first.post(
        "/api/jobs",
        files={"file": ("reload.mp4", sample_mp4.read_bytes(), "video/mp4")},
    )
    job_id = response.json()["job_id"]

    second, _ = make_client(tmp_path)

    assert second.get(f"/api/jobs/{job_id}").json()["filename"] == "reload.mp4"


def test_upload_is_blocked_before_writing_when_whisper_is_down(
    tmp_path: Path,
    sample_mp4: Path,
) -> None:
    client, processor = make_client(tmp_path, whisper=FakeWhisper(unavailable=True))

    response = client.post(
        "/api/jobs",
        files={"file": ("live.mp4", sample_mp4.read_bytes(), "video/mp4")},
    )

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "WHISPER_UNAVAILABLE"
    data_dir = tmp_path / "data"
    assert not data_dir.exists() or list(data_dir.iterdir()) == []
    assert processor.submitted == []


def test_invalid_video_is_removed(tmp_path: Path) -> None:
    client, processor = make_client(tmp_path)

    response = client.post(
        "/api/jobs",
        files={"file": ("broken.mp4", b"not a video", "video/mp4")},
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "INVALID_VIDEO"
    assert list((tmp_path / "data").iterdir()) == []
    assert processor.submitted == []


def test_upload_limit_removes_partial_job(tmp_path: Path, sample_mp4: Path) -> None:
    client, processor = make_client(tmp_path, max_upload_bytes=32)

    response = client.post(
        "/api/jobs",
        files={"file": ("large.mp4", sample_mp4.read_bytes(), "video/mp4")},
    )

    assert response.status_code == 413
    assert response.json()["detail"]["code"] == "UPLOAD_TOO_LARGE"
    assert list((tmp_path / "data").iterdir()) == []
    assert processor.submitted == []


def test_transcript_endpoint_reports_processing_then_returns_persisted_turns(tmp_path: Path) -> None:
    client, _ = make_client(tmp_path)
    store = client.app.state.job_store
    job = store.create("live.mp4")
    job_id = job["job_id"]
    store.update(job_id, status="processing", stage="diarizing", progress=70)

    pending = client.get(f"/api/jobs/{job_id}/transcript")

    assert pending.status_code == 202
    assert pending.json()["stage"] == "diarizing"

    transcript_dir = store.job_dir(job_id) / "transcript"
    transcript_dir.mkdir()
    document = {
        "status": "ready",
        "speaker_count": 2,
        "diarization": {"status": "ready", "detail": None},
        "turns": [
            {
                "id": 1,
                "speaker": "SPEAKER_00",
                "speaker_label": "说话人 1",
                "start": 0.1,
                "end": 1.2,
                "text": "你好",
                "speaker_source": "embedding",
            }
        ],
    }
    (transcript_dir / "speaker-turns.json").write_text(json.dumps(document), encoding="utf-8")
    store.update(job_id, status="processing", stage="transcribing", progress=10)

    reprocessing = client.get(f"/api/jobs/{job_id}/transcript")

    assert reprocessing.status_code == 202
    assert reprocessing.json()["stage"] == "transcribing"
    store.update(job_id, status="ready", stage="ready", progress=100)

    ready = client.get(f"/api/jobs/{job_id}/transcript")

    assert ready.status_code == 200
    assert ready.json() == document


def test_transcript_explains_unknown_short_speaker_predictions(tmp_path: Path) -> None:
    client, _ = make_client(tmp_path)
    store = client.app.state.job_store
    job = store.create("live.mp4")
    job_id = job["job_id"]
    transcript_dir = store.job_dir(job_id) / "transcript"
    transcript_dir.mkdir()
    (transcript_dir / "speaker-turns.json").write_text(
        json.dumps(
            {
                "status": "ready",
                "speaker_count": 1,
                "turns": [
                    {"id": 1, "speaker": "SPEAKER_00", "speaker_label": "说话人 1", "start": 0.0, "end": 0.4, "text": "好"},
                    {"id": 2, "speaker": "SPEAKER_00", "speaker_label": "说话人 1", "start": 1.0, "end": 2.2, "text": "背景声音太小"},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (transcript_dir / "speaker-predictions.json").write_text(
        json.dumps(
            {
                "version": 1,
                "predictions": {
                    "1": {"speaker_id": "UNKNOWN", "confidence": 0.0, "source": "unknown"},
                    "2": {"speaker_id": "UNKNOWN", "confidence": 0.0, "source": "unknown"},
                },
            }
        ),
        encoding="utf-8",
    )
    store.update(job_id, status="ready", stage="ready", progress=100)

    transcript = client.get(f"/api/jobs/{job_id}/transcript").json()

    assert transcript["turns"][0]["speaker"] == "UNKNOWN"
    assert transcript["turns"][0]["speaker_label"] == "时长太小，无法判断"
    assert transcript["turns"][1]["speaker"] == "UNKNOWN"
    assert transcript["turns"][1]["speaker_label"] == "AI 无法判断"


def test_manual_speaker_annotation_is_persisted_and_returned(tmp_path: Path) -> None:
    client, _ = make_client(tmp_path)
    store = client.app.state.job_store
    job = store.create("live.mp4")
    job_id = job["job_id"]
    transcript_dir = store.job_dir(job_id) / "transcript"
    transcript_dir.mkdir()
    (transcript_dir / "speaker-turns.json").write_text(
        json.dumps(
            {
                "status": "ready",
                "speaker_count": 2,
                "turns": [
                    {"id": 1, "speaker": "SPEAKER_00", "speaker_label": "说话人 1", "start": 0.0, "end": 1.0, "text": "第一句"},
                    {"id": 2, "speaker": "SPEAKER_01", "speaker_label": "说话人 2", "start": 1.0, "end": 2.0, "text": "第二句"},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    store.update(job_id, status="ready", stage="ready", progress=100)

    saved = client.put(
        f"/api/jobs/{job_id}/annotations/1",
        json={"speaker": "SPEAKER_01"},
    )

    assert saved.status_code == 200
    assert saved.json() == {"turn_id": 1, "speaker": "SPEAKER_01", "annotated_count": 1, "total_count": 2}
    restored = client.get(f"/api/jobs/{job_id}/annotations")
    assert restored.status_code == 200
    assert restored.json()["annotations"] == {"1": "SPEAKER_01"}
    assert (transcript_dir / "manual-speaker-labels.json").is_file()


def test_training_export_requires_complete_manual_labels_then_returns_jsonl(tmp_path: Path) -> None:
    client, _ = make_client(tmp_path)
    store = client.app.state.job_store
    job = store.create("live.mp4")
    job_id = job["job_id"]
    transcript_dir = store.job_dir(job_id) / "transcript"
    transcript_dir.mkdir()
    (transcript_dir / "speaker-turns.json").write_text(
        json.dumps(
            {
                "status": "ready",
                "speaker_count": 2,
                "turns": [
                    {"id": 1, "speaker": "SPEAKER_00", "speaker_label": "说话人 1", "start": 0.0, "end": 1.0, "text": "第一句"},
                    {"id": 2, "speaker": "SPEAKER_01", "speaker_label": "说话人 2", "start": 1.0, "end": 2.0, "text": "第二句"},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    store.update(job_id, status="ready", stage="ready", progress=100)

    incomplete = client.get(f"/api/jobs/{job_id}/training-export")

    assert incomplete.status_code == 409
    assert incomplete.json()["detail"]["code"] == "ANNOTATIONS_INCOMPLETE"
    for turn_id, speaker in ((1, "SPEAKER_00"), (2, "SPEAKER_01")):
        assert client.put(f"/api/jobs/{job_id}/annotations/{turn_id}", json={"speaker": speaker}).status_code == 200

    exported = client.get(f"/api/jobs/{job_id}/training-export")

    assert exported.status_code == 200
    assert exported.headers["content-type"].startswith("application/x-ndjson")
    assert "attachment" in exported.headers["content-disposition"]
    rows = [json.loads(line) for line in exported.text.splitlines()]
    assert [row["manual_speaker"] for row in rows] == ["SPEAKER_00", "SPEAKER_01"]
    assert rows[0]["audio_path"] == "transcript/audio-16k-mono.wav"
    assert rows[0]["original_speaker"] == "SPEAKER_00"


def _write_candidate_fixture(client: TestClient) -> str:
    store = client.app.state.job_store
    job = store.create("candidate.mp4")
    job_id = job["job_id"]
    transcript_dir = store.job_dir(job_id) / "transcript"
    transcript_dir.mkdir()
    segments = [
        {"start": index * 2.0, "end": index * 2.0 + 1.5, "text": f"第 {index + 1} 句"}
        for index in range(6)
    ]
    turns = [
        {
            "id": index + 1,
            "speaker": f"S00{index // 2}",
            "speaker_label": f"候选人物 {index // 2 + 1}",
            **segment,
            "speaker_source": "embedding",
        }
        for index, segment in enumerate(segments)
    ]
    (transcript_dir / "segments.json").write_text(json.dumps({"segments": segments}, ensure_ascii=False))
    (transcript_dir / "speaker-turns.json").write_text(
        json.dumps({"status": "ready", "speaker_count": 3, "turns": turns}, ensure_ascii=False),
        encoding="utf-8",
    )
    candidates = {
        "version": 1,
        "model": "ECAPA",
        "speaker_count": 3,
        "candidates": [
            {"candidate_id": "S000", "turn_count": 2, "total_duration": 3.0, "samples": [{"turn_id": 1, **segments[0]}]},
            {"candidate_id": "S001", "turn_count": 2, "total_duration": 3.0, "samples": [{"turn_id": 3, **segments[2]}]},
            {"candidate_id": "S002", "turn_count": 2, "total_duration": 3.0, "samples": [{"turn_id": 5, **segments[4]}]},
        ],
        "predictions": {},
    }
    (transcript_dir / "speaker-candidates.json").write_text(json.dumps(candidates, ensure_ascii=False))
    np.savez_compressed(
        transcript_dir / "speaker-embeddings.npz",
        embeddings=np.asarray(
            [[1.0, 0.0], [0.99, 0.1], [0.98, 0.18], [0.97, 0.2], [0.0, 1.0], [0.1, 0.99]],
            dtype=np.float32,
        ),
        indices=np.arange(6, dtype=np.int32),
    )
    (transcript_dir / "manual-speaker-labels.json").write_text(
        json.dumps(
            {"version": 1, "annotations": {**{str(index): "SPEAKER_00" for index in range(1, 5)}, "5": "SPEAKER_01", "6": "SPEAKER_01"}},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    store.update(job_id, status="ready", stage="ready", progress=100)
    return job_id


def test_candidate_confirmation_merges_speakers_classifies_turns_and_scores_partial_labels(tmp_path: Path) -> None:
    client, _ = make_client(tmp_path)
    job_id = _write_candidate_fixture(client)

    initial = client.get(f"/api/jobs/{job_id}/speaker-candidates")
    assert initial.status_code == 200
    assert initial.json()["confirmed_count"] == 0
    initial_transcript = client.get(f"/api/jobs/{job_id}/transcript").json()
    assert initial_transcript["speaker_count"] == 3
    assert initial_transcript["speaker_count_status"] == "candidates"
    assert client.post(f"/api/jobs/{job_id}/speaker-classification").status_code == 409

    first = client.put(f"/api/jobs/{job_id}/speaker-candidates/S000", json={})
    merged = client.put(
        f"/api/jobs/{job_id}/speaker-candidates/S001",
        json={"speaker_id": "SPEAKER_00"},
    )
    named = client.put(
        f"/api/jobs/{job_id}/speaker-candidates/S002",
        json={"speaker_name": "嘉宾"},
    )

    assert first.json()["speaker_id"] == "SPEAKER_00"
    assert merged.json()["speaker_id"] == "SPEAKER_00"
    assert named.json() == {"candidate_id": "S002", "speaker_id": "SPEAKER_01", "speaker_label": "嘉宾"}
    classified = client.post(f"/api/jobs/{job_id}/speaker-classification")
    assert classified.status_code == 200
    assert classified.json()["predicted_count"] == 6
    transcript = client.get(f"/api/jobs/{job_id}/transcript").json()
    assert transcript["speaker_count"] == 2
    assert transcript["speaker_count_status"] == "confirmed"
    assert [turn["speaker"] for turn in transcript["turns"]] == ["SPEAKER_00"] * 4 + ["SPEAKER_01"] * 2
    assert transcript["turns"][4]["speaker_label"] == "嘉宾"
    metrics = client.get(f"/api/jobs/{job_id}/speaker-metrics").json()
    assert metrics["available"] is True
    assert metrics["coverage"] == 1.0
    assert metrics["all_labeled"]["accuracy"] == 1.0
    assert metrics["held_out"] == {"count": 3, "correct": 3, "accuracy": 1.0}


def test_mixed_candidate_can_be_excluded_without_blocking_classification(tmp_path: Path) -> None:
    client, _ = make_client(tmp_path)
    job_id = _write_candidate_fixture(client)

    assert client.put(f"/api/jobs/{job_id}/speaker-candidates/S000", json={}).status_code == 200
    excluded = client.put(
        f"/api/jobs/{job_id}/speaker-candidates/S001",
        json={"resolution": "excluded"},
    )
    assert client.put(
        f"/api/jobs/{job_id}/speaker-candidates/S002",
        json={"speaker_name": "嘉宾"},
    ).status_code == 200

    assert excluded.status_code == 200
    assert excluded.json() == {
        "candidate_id": "S001",
        "resolution": "excluded",
        "speaker_id": None,
        "speaker_label": "已排除 · 混合声音",
    }
    candidates = client.get(f"/api/jobs/{job_id}/speaker-candidates").json()
    assert candidates["confirmed_count"] == 3
    assert candidates["all_confirmed"] is True
    mixed = next(item for item in candidates["candidates"] if item["candidate_id"] == "S001")
    assert mixed["resolved"] is True
    assert mixed["resolution"] == "excluded"

    classified = client.post(f"/api/jobs/{job_id}/speaker-classification")
    assert classified.status_code == 200
    prediction_path = client.app.state.job_store.job_dir(job_id) / "transcript" / "speaker-predictions.json"
    predictions = json.loads(prediction_path.read_text())
    assert predictions["excluded_candidate_ids"] == ["S001"]
    assert 3 not in predictions["enrollment_turn_ids"]
    assert {
        item["speaker_id"] for item in predictions["predictions"].values()
    } <= {"SPEAKER_00", "SPEAKER_01"}


def _write_ai_export_state(client: TestClient, job_id: str) -> Path:
    store = client.app.state.job_store
    job_dir = store.job_dir(job_id)
    transcript_dir = job_dir / "transcript"
    (transcript_dir / "speaker-candidate-assignments.json").write_text(
        json.dumps(
            {
                "version": 1,
                "assignments": {
                    "S000": "SPEAKER_00",
                    "S001": "SPEAKER_00",
                    "S002": "SPEAKER_01",
                },
            }
        ),
        encoding="utf-8",
    )
    (transcript_dir / "speaker-predictions.json").write_text(
        json.dumps(
            {
                "version": 1,
                "predictions": {
                    str(turn_id): {
                        "speaker_id": "UNKNOWN" if turn_id == 2 else "SPEAKER_00" if turn_id < 5 else "SPEAKER_01",
                        "confidence": 0.0 if turn_id == 2 else 0.8,
                        "source": "unknown" if turn_id == 2 else "registered_embedding",
                    }
                    for turn_id in range(1, 7)
                },
            }
        ),
        encoding="utf-8",
    )
    (transcript_dir / "manual-speakers.json").write_text(
        json.dumps(
            {"version": 1, "speakers": {"SPEAKER_00": "monica", "SPEAKER_01": "威律师"}},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (transcript_dir / "manual-speaker-labels.json").write_text(
        json.dumps({"version": 1, "annotations": {"1": "SPEAKER_01"}}),
        encoding="utf-8",
    )
    (transcript_dir / "deleted-turns.json").write_text(
        json.dumps({"version": 1, "deleted_turn_ids": [6]}),
        encoding="utf-8",
    )
    segments = json.loads((transcript_dir / "segments.json").read_text())["segments"]
    (transcript_dir / "raw.json").write_text(
        json.dumps(
            {
                "model": "mlx-community/whisper-large-v3-turbo",
                "language": "zh",
                "segments": [
                    {
                        **segment,
                        "words": [
                            {
                                "word": segment["text"],
                                "start": segment["start"],
                                "end": segment["end"],
                                "probability": 0.9,
                            }
                        ],
                    }
                    for segment in segments
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (job_dir / "media.json").write_text(
        json.dumps({"duration_seconds": 12.0}),
        encoding="utf-8",
    )
    return transcript_dir


def test_ai_transcript_export_requires_confirmed_candidates_and_classification(tmp_path: Path) -> None:
    client, _ = make_client(tmp_path)
    job_id = _write_candidate_fixture(client)

    unconfirmed = client.get(f"/api/jobs/{job_id}/ai-transcript-export")

    assert unconfirmed.status_code == 409
    assert unconfirmed.json()["detail"]["code"] == "CANDIDATES_UNCONFIRMED"
    transcript_dir = client.app.state.job_store.job_dir(job_id) / "transcript"
    (transcript_dir / "speaker-candidate-assignments.json").write_text(
        json.dumps(
            {
                "version": 1,
                "assignments": {
                    "S000": "SPEAKER_00",
                    "S001": "SPEAKER_00",
                    "S002": "SPEAKER_01",
                },
            }
        ),
        encoding="utf-8",
    )

    not_classified = client.get(f"/api/jobs/{job_id}/ai-transcript-export")

    assert not_classified.status_code == 409
    assert not_classified.json()["detail"]["code"] == "SPEAKER_CLASSIFICATION_REQUIRED"


def test_ai_transcript_export_returns_json_without_complete_manual_annotations(tmp_path: Path) -> None:
    client, _ = make_client(tmp_path)
    job_id = _write_candidate_fixture(client)
    _write_ai_export_state(client, job_id)

    response = client.get(f"/api/jobs/{job_id}/ai-transcript-export")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json; charset=utf-8"
    assert "attachment" in response.headers["content-disposition"]
    assert "filename*=UTF-8''" in response.headers["content-disposition"]
    document = response.json()
    assert document["format"] == "live-clip-studio.ai-transcript"
    assert document["quality"]["segment_count"] == 5
    assert document["quality"]["deleted_segment_count"] == 1
    assert document["segments"][0]["speaker"]["name"] == "威律师"
    assert document["segments"][0]["speaker"]["manual_override"] is True
    assert document["segments"][1]["speaker"]["id"] == "UNKNOWN"
    assert all(
        "".join(character["text"] for character in segment["characters"]) == segment["text"]
        for segment in document["segments"]
    )


def test_changing_candidate_assignment_invalidates_previous_ai_export(tmp_path: Path) -> None:
    client, _ = make_client(tmp_path)
    job_id = _write_candidate_fixture(client)
    transcript_dir = _write_ai_export_state(client, job_id)
    assert client.get(f"/api/jobs/{job_id}/ai-transcript-export").status_code == 200

    changed = client.put(
        f"/api/jobs/{job_id}/speaker-candidates/S000",
        json={"speaker_id": "SPEAKER_01"},
    )

    assert changed.status_code == 200
    assert not (transcript_dir / "speaker-predictions.json").exists()
    stale_export = client.get(f"/api/jobs/{job_id}/ai-transcript-export")
    assert stale_export.status_code == 409
    assert stale_export.json()["detail"]["code"] == "SPEAKER_CLASSIFICATION_REQUIRED"
