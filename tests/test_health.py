from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from fastapi.testclient import TestClient

from live_clip_studio.app import create_app
from live_clip_studio.config import Settings
from live_clip_studio.whisper_client import WhisperServiceError


@dataclass
class FakeWhisper:
    result: dict | None = None
    error: WhisperServiceError | None = None

    def health(self) -> dict:
        if self.error:
            raise self.error
        return self.result or {
            "status": "ok",
            "model": "mlx-community/whisper-large-v3-turbo",
        }


def make_client(
    tmp_path: Path,
    *,
    whisper: FakeWhisper | None = None,
    diarization_available: bool = True,
) -> TestClient:
    app = create_app(
        settings=Settings(data_dir=tmp_path),
        whisper_client=whisper or FakeWhisper(),
        media_probe=lambda: {"ffmpeg": True, "ffprobe": True},
        diarization_probe=lambda: {
            "status": "ready" if diarization_available else "unavailable",
            "detail": None if diarization_available else "SpeechBrain dependencies missing",
        },
    )
    return TestClient(app)


def test_health_accepts_expected_whisper_model(tmp_path: Path) -> None:
    data = make_client(tmp_path).get("/api/health").json()

    assert data["ready"] is True
    assert data["whisper"]["status"] == "ok"
    assert data["whisper"]["model"] == "mlx-community/whisper-large-v3-turbo"


def test_health_rejects_wrong_whisper_model(tmp_path: Path) -> None:
    client = make_client(
        tmp_path,
        whisper=FakeWhisper(result={"status": "ok", "model": "small"}),
    )

    data = client.get("/api/health").json()

    assert data["ready"] is False
    assert data["whisper"]["code"] == "WHISPER_MODEL_MISMATCH"


def test_health_reports_whisper_connection_failure(tmp_path: Path) -> None:
    client = make_client(
        tmp_path,
        whisper=FakeWhisper(
            error=WhisperServiceError(
                code="WHISPER_UNAVAILABLE",
                message="请先开启语音转录服务：本机 Whisper Large V3 Turbo",
                detail="connection refused",
            )
        ),
    )

    data = client.get("/api/health").json()

    assert data["ready"] is False
    assert data["whisper"]["code"] == "WHISPER_UNAVAILABLE"
    assert "请先开启语音转录服务" in data["whisper"]["message"]


def test_missing_diarization_does_not_hide_healthy_whisper(tmp_path: Path) -> None:
    data = make_client(tmp_path, diarization_available=False).get("/api/health").json()

    assert data["ready"] is True
    assert data["diarization"]["status"] == "unavailable"
    assert data["whisper"]["status"] == "ok"
