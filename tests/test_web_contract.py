from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from live_clip_studio.app import create_app
from live_clip_studio.config import Settings


WEB_DIR = Path(__file__).resolve().parents[1] / "live_clip_studio" / "web"


class HealthyWhisper:
    def health(self) -> dict:
        return {"status": "ok", "model": "mlx-community/whisper-large-v3-turbo"}


class NoopProcessor:
    def submit_transcript(self, job_id: str) -> None:
        return None

    def submit_keyframes(self, job_id: str) -> None:
        return None


def test_upload_page_has_service_gate_and_accessible_file_control() -> None:
    html = (WEB_DIR / "index.html").read_text(encoding="utf-8")

    assert 'for="video-file"' in html
    assert 'id="video-file"' in html
    assert 'id="service-status"' in html
    assert 'id="whisper-warning"' in html
    assert "请先开启语音转录服务：本机 Whisper Large V3 Turbo" in html
    assert 'id="upload-button"' in html


def test_workspace_has_video_tabs_speaker_filters_and_matrix_controls() -> None:
    html = (WEB_DIR / "workspace.html").read_text(encoding="utf-8")

    for marker in (
        'id="source-video"',
        'id="tab-transcript"',
        'id="tab-keyframes"',
        'id="speaker-filters"',
        'id="grid-columns"',
        'id="grid-rows"',
        'id="keyframe-grid"',
        'id="page-previous"',
        'id="page-next"',
    ):
        assert marker in html
    assert "2 × 20" in html
    assert "10 × 10" in html


def test_javascript_contains_health_upload_poll_seek_and_matrix_contracts() -> None:
    script = (WEB_DIR / "app.js").read_text(encoding="utf-8")

    assert "/api/health" in script
    assert "/api/jobs" in script
    assert "XMLHttpRequest" in script
    assert "pollWorkspace" in script
    assert "loadTranscript" in script
    assert "startKeyframes" in script
    assert "activateKeyframes" in script
    assert 'if (status === "not_started") startKeyframes();' in script
    assert "video.currentTime" in script
    assert "columns * rows" in script


def test_hidden_states_cannot_be_overridden_by_component_display_rules() -> None:
    stylesheet = (WEB_DIR / "app.css").read_text(encoding="utf-8")

    assert "[hidden]{display:none!important}" in stylesheet


def test_pages_use_the_bundled_favicon() -> None:
    for page in ("index.html", "workspace.html"):
        html = (WEB_DIR / page).read_text(encoding="utf-8")
        assert '<link rel="icon" href="/assets/favicon.svg" type="image/svg+xml">' in html
    assert (WEB_DIR / "favicon.svg").is_file()


def test_history_and_explicit_reprocess_controls_exist() -> None:
    upload = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    workspace = (WEB_DIR / "workspace.html").read_text(encoding="utf-8")
    script = (WEB_DIR / "app.js").read_text(encoding="utf-8")

    assert 'id="history-list"' in upload
    assert 'id="history-empty"' in upload
    assert 'id="reuse-notice"' in workspace
    assert 'id="reprocess-transcript"' in workspace
    assert 'id="retry-failed-transcript"' in workspace
    assert 'id="reprocess-keyframes"' in workspace
    assert '"/api/jobs"' in script
    assert "/transcript/reprocess" in script
    assert 'qs("#retry-failed-transcript").hidden = false' in script
    assert "force=true" in script


def test_workspace_can_rebuild_candidates_without_regenerating_transcript() -> None:
    workspace = (WEB_DIR / "workspace.html").read_text(encoding="utf-8")
    script = (WEB_DIR / "app.js").read_text(encoding="utf-8")

    assert 'id="rebuild-speaker-candidates"' in workspace
    assert "/speaker-candidates/rebuild" in script
    assert "字幕文字和时间轴不会改变" in script
    assert "async function rebuildSpeakerCandidates()" in script
    assert "await loadCandidateReview()" in script


def test_workspace_exposes_manual_speaker_annotation_and_training_export_controls() -> None:
    workspace = (WEB_DIR / "workspace.html").read_text(encoding="utf-8")
    script = (WEB_DIR / "app.js").read_text(encoding="utf-8")

    assert 'id="annotation-progress"' in workspace
    assert 'id="export-training"' in workspace
    assert "manual-speaker-actions" in script
    assert "transcript-seek" in script
    assert "/annotations/" in script
    assert "/training-export" in script


def test_workspace_exposes_keyboard_auto_annotation_mode_and_uses_precise_turn_start() -> None:
    workspace = (WEB_DIR / "workspace.html").read_text(encoding="utf-8")
    script = (WEB_DIR / "app.js").read_text(encoding="utf-8")

    assert 'id="auto-annotation-mode"' in workspace
    assert 'id="annotation-shortcuts"' in workspace
    assert "estimatePreviewTime" not in script
    assert "const forwardOffset = 0;" in script
    assert "const target = start + forwardOffset;" in script
    assert "setActiveTurn" in script
    assert "annotateAndAdvance" in script
    assert 'ArrowLeft: "SPEAKER_00"' in script
    assert 'ArrowRight: "SPEAKER_01"' in script
    assert 'event.code === "Space"' in script


def test_workspace_exposes_candidate_review_and_separate_accuracy_metrics() -> None:
    workspace = (WEB_DIR / "workspace.html").read_text(encoding="utf-8")
    script = (WEB_DIR / "app.js").read_text(encoding="utf-8")

    for marker in (
        'id="candidate-review"',
        'id="candidate-list"',
        'id="apply-speaker-classification"',
        'id="speaker-metrics"',
        'id="held-out-accuracy"',
        'id="long-accuracy"',
        'id="short-accuracy"',
        'id="speaker-confusion"',
    ):
        assert marker in workspace
    assert "/speaker-candidates" in script
    assert "/speaker-classification" in script
    assert "/speaker-metrics" in script
    assert "playCandidateSample" in script
    assert "saveCandidateAssignment" in script
    assert 'data.speaker_count_status === "candidates"' in script
    assert "混合声音 / 错误候选（排除注册）" in script
    assert 'payload.resolution = "excluded"' in script


def test_workspace_exposes_ai_transcript_export_after_full_classification() -> None:
    workspace = (WEB_DIR / "workspace.html").read_text(encoding="utf-8")
    script = (WEB_DIR / "app.js").read_text(encoding="utf-8")

    assert 'id="export-ai-transcript"' in workspace
    assert "导出 AI 精准字幕 JSON" in workspace
    assert "/ai-transcript-export" in script
    assert "classificationReady" in script
    assert 'data.speaker_count_status === "confirmed"' in script
    assert "renderAiTranscriptExportState" in script


def test_app_serves_pages_assets_and_job_media(tmp_path: Path, sample_mp4: Path) -> None:
    app = create_app(
        settings=Settings(data_dir=tmp_path / "data"),
        whisper_client=HealthyWhisper(),
        media_probe=lambda: {"ffmpeg": True, "ffprobe": True},
        diarization_probe=lambda: {"status": "ready", "detail": None},
        processor=NoopProcessor(),
    )
    store = app.state.job_store
    job = store.create("sample.mp4")
    target = store.job_dir(job["job_id"]) / "source.mp4"
    target.write_bytes(sample_mp4.read_bytes())
    client = TestClient(app)

    assert client.get("/").status_code == 200
    workspace = client.get(f"/workspace/{job['job_id']}")
    assert workspace.status_code == 200
    assert f'data-job-id="{job["job_id"]}"' in workspace.text
    assert client.get("/assets/app.css").status_code == 200
    assert client.get(f"/media/{job['job_id']}/source.mp4").status_code == 200
