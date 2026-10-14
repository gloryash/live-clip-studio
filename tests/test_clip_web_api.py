from __future__ import annotations

import json
from pathlib import Path

import pytest

from fastapi.testclient import TestClient

from live_clip_studio.app import create_app
from live_clip_studio.config import Settings
from live_clip_studio.clip_runs import ClipRunManager


class HealthyWhisper:
    def health(self):
        return {"status": "ok", "model": "mlx-community/whisper-large-v3-turbo"}


class NoopProcessor:
    def submit_transcript(self, job_id):
        return None


class CapturingExecutor:
    def __init__(self):
        self.calls = []

    def submit(self, fn, *args):
        self.calls.append((fn, args))


def _job(tmp_path: Path, *, complete: bool) -> tuple[Path, str]:
    data = tmp_path / "data"
    app = create_app(
        settings=Settings(data_dir=data),
        whisper_client=HealthyWhisper(),
        media_probe=lambda: {"ffmpeg": True, "ffprobe": True},
        diarization_probe=lambda: {"status": "ready"},
        processor=NoopProcessor(),
    )
    store = app.state.job_store
    job = store.create("访谈.mp4")
    job_id = job["job_id"]
    root = store.job_dir(job_id)
    (root / "source.mp4").write_bytes(b"video")
    store.update(job_id, status="ready", stage="ready", progress=100)
    transcript = root / "transcript"
    transcript.mkdir()
    (root / "media.json").write_text(json.dumps({"duration_seconds": 100, "streams": [{"codec_type": "video", "width": 720, "height": 1512}]}))
    (transcript / "speaker-turns.json").write_text(json.dumps({"turns": [{"id": 1, "start": 0, "end": 2, "text": "你好"}]}))
    if complete:
        (transcript / "speaker-candidates.json").write_text(json.dumps({"candidates": [{"candidate_id": "S000"}]}))
        (transcript / "speaker-candidate-assignments.json").write_text(json.dumps({"assignments": {"S000": "SPEAKER_00"}}))
        (transcript / "speaker-predictions.json").write_text(json.dumps({"predictions": {"1": {"speaker_id": "SPEAKER_00"}}}))
    return app, job_id


def test_templates_and_sources_expose_general_and_readiness(tmp_path: Path):
    app, job_id = _job(tmp_path, complete=True)
    client = TestClient(app)
    templates = client.get("/api/clip-templates")
    assert templates.status_code == 200
    assert templates.json()["templates"][0]["name"] == "一般"
    sources = client.get("/api/clip-sources").json()["sources"]
    assert sources[0]["job_id"] == job_id
    assert sources[0]["clip_ready"] is True


def test_unclassified_source_cannot_start_clip_run(tmp_path: Path):
    app, job_id = _job(tmp_path, complete=False)
    response = TestClient(app).post("/api/clip-runs", json={"job_id": job_id, "template_id": "general"})
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "SOURCE_NOT_READY"


def test_clip_run_creation_is_deduplicated(tmp_path: Path):
    app, job_id = _job(tmp_path, complete=True)
    executor = CapturingExecutor()
    app.state.clip_runs.executor = executor
    client = TestClient(app)
    first = client.post("/api/clip-runs", json={"job_id": job_id, "template_id": "general"})
    second = client.post("/api/clip-runs", json={"job_id": job_id, "template_id": "general"})
    assert first.status_code == second.status_code == 202
    assert first.json()["run_id"] == second.json()["run_id"]
    assert len(executor.calls) == 1


@pytest.mark.parametrize("status", ["completed", "needs_review"])
def test_finished_run_is_reused_after_restart_and_listed_on_source(tmp_path: Path, status: str):
    app, job_id = _job(tmp_path, complete=True)
    manager = app.state.clip_runs
    executor = CapturingExecutor()
    manager.executor = executor
    run = manager.create(job_id, "general")
    result = {"count": 1, "clips": [{"id": "01-test", "title": "测试切片", "virality": {"score": 83}}]}
    manager._write_result(run["run_id"], result)
    manager._update(run["run_id"], status=status, stage="completed", progress=100, result=result)

    restarted_executor = CapturingExecutor()
    restarted = ClipRunManager(store=app.state.job_store, settings=app.state.settings, executor=restarted_executor)
    reused = restarted.create(job_id, "general")
    assert reused["run_id"] == run["run_id"]
    assert reused["reused"] is True
    assert reused["result"] == result
    assert restarted_executor.calls == []
    assert len(restarted.list_runs()) == 1
    source = restarted.list_sources()[0]
    assert source["clip_runs"][0]["run_id"] == run["run_id"]
    assert source["clip_runs"][0]["clip_count"] == 1


def test_failed_run_can_be_retried_without_removing_history(tmp_path: Path):
    app, job_id = _job(tmp_path, complete=True)
    manager = app.state.clip_runs
    manager.executor = CapturingExecutor()
    first = manager.create(job_id, "general")
    manager._update(first["run_id"], status="failed", error={"message": "选题失败"})
    second = manager.create(job_id, "general")
    assert second["run_id"] != first["run_id"]
    assert len(manager.list_runs()) == 2


def test_history_exposes_storage_and_downloads_persisted_artifact(tmp_path: Path):
    app, job_id = _job(tmp_path, complete=True)
    app.state.clip_runs.executor = CapturingExecutor()
    run = app.state.clip_runs.create(job_id, "general")
    target = app.state.clip_runs.root / run["run_id"] / "01-test.mp4"
    target.write_bytes(b"saved video")
    client = TestClient(app)
    listing = client.get("/api/clip-runs").json()
    assert listing["storage_directory"] == str(app.state.clip_runs.root)
    response = client.get(f'/clip-media/{run["run_id"]}/01-test.mp4?download=true')
    assert response.status_code == 200
    assert response.content == b"saved video"
    assert "attachment" in response.headers["content-disposition"]

