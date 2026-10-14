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


@pytest.mark.parametrize("failure", [False, True])
def test_processing_time_is_persisted_on_success_and_failure(tmp_path, monkeypatch, failure):
    from types import SimpleNamespace
    from live_clip_studio import clip_runs
    app, job_id = _job(tmp_path, complete=True)
    manager = app.state.clip_runs
    manager.executor = CapturingExecutor()
    run = manager.create(job_id, "general")
    # Queue age must not count as processing time.
    manager._update(run["run_id"], created_at="2020-01-01T00:00:00+00:00")
    ticks = iter([100.0, 112.75])
    monkeypatch.setattr(clip_runs, "time", SimpleNamespace(monotonic=lambda: next(ticks)))

    def execute(args):
        current = manager.public(run["run_id"])
        assert current["timing"]["finished_at"] is None
        if failure:
            raise ValueError("test failure")
        (Path(args.out) / "decisions.json").write_text(json.dumps({"clips": [{"id": "01-test"}]}))
        return {"status": "completed_pending_human_review"}

    monkeypatch.setattr(clip_runs, "execute", execute)
    manager._run(run["run_id"], app.state.job_store.get(job_id), {"count": 1})
    restarted = ClipRunManager(store=app.state.job_store, settings=app.state.settings, executor=CapturingExecutor())
    saved = restarted.public(run["run_id"])
    assert saved["timing"]["elapsed_seconds"] == 12.75
    assert saved["timing"]["finished_at"] is not None
    assert saved["timing"]["selection_mode"] == "new_selection"
    assert saved["status"] == ("failed" if failure else "completed")
    if not failure:
        assert restarted.create(job_id, "general")["timing"] == saved["timing"]
        assert saved["result"]["count"] == 1


def test_historical_timing_uses_latest_pipeline_span_and_persists(tmp_path):
    app, job_id = _job(tmp_path, complete=True)
    manager = app.state.clip_runs
    manager.executor = CapturingExecutor()
    run = manager.create(job_id, "general")
    manager._update(run["run_id"], status="needs_review", created_at="2020-01-01T00:00:00+00:00")
    updated = manager._read(run["run_id"])["updated_at"]
    (manager._path(run["run_id"]) / "run.json").write_text(json.dumps({
        "status": "needs_review", "stages": {
            "preflight": {"status": "completed", "started_at": 100, "elapsed_seconds": 2},
            "render": {"status": "completed", "started_at": 105, "elapsed_seconds": 15},
            "qa": {"status": "completed", "started_at": 120, "elapsed_seconds": 10},
        }}))
    timing = manager.public(run["run_id"])["timing"]
    assert timing["elapsed_seconds"] == 30
    assert timing["origin"] == "pipeline_history"
    assert timing["selection_mode"] == "unknown"
    assert manager._read(run["run_id"])["timing"] == timing
    assert manager._read(run["run_id"])["updated_at"] == updated


def test_missing_or_interrupted_history_does_not_invent_duration(tmp_path):
    app, job_id = _job(tmp_path, complete=True)
    manager = app.state.clip_runs
    manager.executor = CapturingExecutor()
    run = manager.create(job_id, "general")
    assert not manager.public(run["run_id"]).get("timing")
    manager._update(run["run_id"], status="failed")
    assert not manager.public(run["run_id"]).get("timing")
    (manager._path(run["run_id"]) / "run.json").write_text(json.dumps({
        "status": "failed", "stages": {"render": {"status": "running", "started_at": 100}}}))
    assert not manager.public(run["run_id"]).get("timing")
