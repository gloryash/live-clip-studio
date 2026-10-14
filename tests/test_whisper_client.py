from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from live_clip_studio.whisper_client import WhisperClient, WhisperServiceError


def test_transcribe_uploads_audio_polls_and_returns_raw_result(tmp_path: Path) -> None:
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"RIFF-test-audio")
    calls: list[tuple[str, str]] = []
    job_polls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal job_polls
        calls.append((request.method, request.url.path))
        if request.url.path == "/v1/transcriptions":
            body = request.read()
            assert b'name="language"' in body
            assert b"zh" in body
            assert b'name="auto_correct"' in body
            assert b"true" in body
            assert b'name="correction_model"' in body
            assert b"qwen3.7-max" in body
            assert b"RIFF-test-audio" in body
            return httpx.Response(200, json={"job_id": "job-1"})
        if request.url.path == "/v1/jobs/job-1":
            job_polls += 1
            return httpx.Response(200, json={"status": "running" if job_polls == 1 else "succeeded"})
        if request.url.path == "/v1/jobs/job-1/result":
            return httpx.Response(
                200,
                json={
                    "raw_text": "你好",
                    "text": "你好",
                    "segments": [{"start": 0.1, "end": 1.2, "text": "你好"}],
                    "model": "mlx-community/whisper-large-v3-turbo",
                },
            )
        raise AssertionError(request.url)

    client = WhisperClient(
        "http://whisper.test",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    result = client.transcribe(audio, language="zh", timeout_seconds=5, poll_interval=0)

    assert result["raw_text"] == "你好"
    assert result["segments"][0]["start"] == 0.1
    assert result["whisper_job_id"] == "job-1"
    assert calls == [
        ("POST", "/v1/transcriptions"),
        ("GET", "/v1/jobs/job-1"),
        ("GET", "/v1/jobs/job-1"),
        ("GET", "/v1/jobs/job-1/result"),
    ]


def test_transcribe_maps_failed_job_to_stable_error(tmp_path: Path) -> None:
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"audio")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/transcriptions":
            return httpx.Response(200, json={"job_id": "bad-job"})
        return httpx.Response(200, json={"status": "failed", "error": "decoder crashed"})

    client = WhisperClient(
        "http://whisper.test",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(WhisperServiceError) as caught:
        client.transcribe(audio, timeout_seconds=5, poll_interval=0)

    assert caught.value.code == "WHISPER_JOB_FAILED"
    assert "decoder crashed" in caught.value.detail


def test_transcribe_times_out_running_job(tmp_path: Path) -> None:
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"audio")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/transcriptions":
            return httpx.Response(200, json={"job_id": "slow-job"})
        return httpx.Response(200, json={"status": "running"})

    client = WhisperClient(
        "http://whisper.test",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(WhisperServiceError) as caught:
        client.transcribe(audio, timeout_seconds=0, poll_interval=0)

    assert caught.value.code == "WHISPER_TIMEOUT"
