from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import time
from typing import Any

import httpx

from .config import EXPECTED_WHISPER_MODEL


WHISPER_START_MESSAGE = "请先开启语音转录服务：本机 Whisper Large V3 Turbo"
ADVANCED_CORRECTION_MODEL = "qwen3.7-max"


@dataclass(slots=True)
class WhisperServiceError(RuntimeError):
    code: str
    message: str
    detail: str

    def __str__(self) -> str:
        return f"{self.code}: {self.detail}"

    def as_dict(self) -> dict[str, str]:
        return {"status": "unavailable", "code": self.code, "message": self.message, "detail": self.detail}


def validate_health_payload(
    payload: dict[str, Any],
    expected_model: str = EXPECTED_WHISPER_MODEL,
) -> dict[str, Any]:
    if payload.get("status") != "ok":
        raise WhisperServiceError(
            code="WHISPER_UNAVAILABLE",
            message=WHISPER_START_MESSAGE,
            detail=f"unexpected health response: {payload}",
        )
    if payload.get("model") != expected_model:
        raise WhisperServiceError(
            code="WHISPER_MODEL_MISMATCH",
            message=WHISPER_START_MESSAGE,
            detail=f"expected {expected_model}, got {payload.get('model')}",
        )
    return {"status": "ok", "model": expected_model}


class WhisperClient:
    def __init__(
        self,
        base_url: str,
        *,
        expected_model: str = EXPECTED_WHISPER_MODEL,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.expected_model = expected_model
        self._client = client or httpx.Client(timeout=3.0)

    def health(self) -> dict[str, Any]:
        try:
            response = self._client.get(f"{self.base_url}/health")
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise WhisperServiceError(
                code="WHISPER_UNAVAILABLE",
                message=WHISPER_START_MESSAGE,
                detail=str(exc),
            ) from exc
        if not isinstance(payload, dict):
            raise WhisperServiceError(
                code="WHISPER_UNAVAILABLE",
                message=WHISPER_START_MESSAGE,
                detail="health response is not an object",
            )
        return validate_health_payload(payload, self.expected_model)

    def transcribe(
        self,
        audio_path: Path,
        *,
        language: str = "zh",
        timeout_seconds: float = 7200,
        poll_interval: float = 1.0,
    ) -> dict[str, Any]:
        try:
            with Path(audio_path).open("rb") as audio:
                response = self._client.post(
                    f"{self.base_url}/v1/transcriptions",
                    files={"file": (Path(audio_path).name, audio, "audio/wav")},
                    data={
                        "language": language,
                        "auto_correct": "true",
                        "correction_model": ADVANCED_CORRECTION_MODEL,
                    },
                    timeout=120.0,
                )
            response.raise_for_status()
            created = response.json()
        except (OSError, httpx.HTTPError, ValueError) as exc:
            raise WhisperServiceError(
                code="WHISPER_UPLOAD_FAILED",
                message="语音转录任务提交失败",
                detail=str(exc),
            ) from exc
        job_id = str(created.get("job_id") or "") if isinstance(created, dict) else ""
        if not job_id:
            raise WhisperServiceError(
                code="WHISPER_UPLOAD_FAILED",
                message="语音转录任务提交失败",
                detail=f"response missing job_id: {created}",
            )

        deadline = time.monotonic() + timeout_seconds
        while True:
            try:
                job_response = self._client.get(f"{self.base_url}/v1/jobs/{job_id}", timeout=30.0)
                job_response.raise_for_status()
                job = job_response.json()
            except (httpx.HTTPError, ValueError) as exc:
                raise WhisperServiceError(
                    code="WHISPER_JOB_FAILED",
                    message="语音转录任务状态读取失败",
                    detail=str(exc),
                ) from exc
            status = job.get("status") if isinstance(job, dict) else None
            if status == "succeeded":
                break
            if status == "failed":
                raise WhisperServiceError(
                    code="WHISPER_JOB_FAILED",
                    message="语音转录失败",
                    detail=str(job.get("error") or job),
                )
            if time.monotonic() >= deadline:
                raise WhisperServiceError(
                    code="WHISPER_TIMEOUT",
                    message="语音转录等待超时",
                    detail=f"job {job_id} did not finish within {timeout_seconds}s",
                )
            if poll_interval:
                time.sleep(poll_interval)

        try:
            result_response = self._client.get(
                f"{self.base_url}/v1/jobs/{job_id}/result",
                timeout=60.0,
            )
            result_response.raise_for_status()
            result = result_response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise WhisperServiceError(
                code="WHISPER_JOB_FAILED",
                message="语音转录结果读取失败",
                detail=str(exc),
            ) from exc
        if not isinstance(result, dict):
            raise WhisperServiceError(
                code="WHISPER_JOB_FAILED",
                message="语音转录结果无效",
                detail="result is not an object",
            )
        result["whisper_job_id"] = job_id
        return result
