from __future__ import annotations

import json
import os
import shutil
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from .config import Settings
from .media import extract_audio
from .keyframes import generate_keyframes
from .speaker_workflow import discover_candidates
from .transcript import apply_text_correction, build_speaker_turns, clean_segments
from .whisper_client import WhisperServiceError


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobNotFoundError(KeyError):
    pass


class JobStore:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = Path(data_dir)
        self._lock = threading.RLock()

    def job_dir(self, job_id: str) -> Path:
        if not job_id or any(char not in "0123456789abcdef-" for char in job_id.lower()):
            raise JobNotFoundError(job_id)
        return self.data_dir / job_id

    def _path(self, job_id: str) -> Path:
        return self.job_dir(job_id) / "job.json"

    def create(self, filename: str) -> dict[str, Any]:
        with self._lock:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            job_id = str(uuid.uuid4())
            now = _now()
            document: dict[str, Any] = {
                "job_id": job_id,
                "filename": Path(filename).name or "video.mp4",
                "status": "uploaded",
                "stage": "uploaded",
                "progress": 0,
                "error": None,
                "keyframes_status": "not_started",
                "keyframes_error": None,
                "created_at": now,
                "updated_at": now,
            }
            self.job_dir(job_id).mkdir(parents=True)
            self._write(document)
            return document

    def _write(self, document: dict[str, Any]) -> None:
        path = self._path(str(document["job_id"]))
        temp = path.with_suffix(".json.tmp")
        temp.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temp, path)

    def get(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            path = self._path(job_id)
            if not path.is_file():
                raise JobNotFoundError(job_id)
            return json.loads(path.read_text(encoding="utf-8"))

    def update(self, job_id: str, **fields: Any) -> dict[str, Any]:
        with self._lock:
            document = self.get(job_id)
            document.update(fields)
            document["updated_at"] = _now()
            self._write(document)
            return document

    def delete(self, job_id: str) -> None:
        with self._lock:
            path = self.job_dir(job_id)
            if path.parent == self.data_dir and path.exists():
                shutil.rmtree(path)

    def list(self) -> list[dict[str, Any]]:
        if not self.data_dir.is_dir():
            return []
        documents = []
        for path in sorted(self.data_dir.glob("*/job.json")):
            try:
                documents.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                continue
        return documents

    def find_by_fingerprint(
        self,
        source_sha256: str,
        source_size: int,
        *,
        exclude_job_id: str | None = None,
    ) -> dict[str, Any] | None:
        with self._lock:
            for document in self.list():
                if document.get("job_id") == exclude_job_id:
                    continue
                if (
                    document.get("source_sha256") == source_sha256
                    and document.get("source_size") == source_size
                ):
                    return document
        return None

    def history(self) -> list[dict[str, Any]]:
        summaries: list[dict[str, Any]] = []
        for job in sorted(self.list(), key=lambda item: str(item.get("updated_at") or ""), reverse=True):
            job_dir = self.job_dir(str(job["job_id"]))
            media: dict[str, Any] = {}
            transcript: dict[str, Any] = {}
            try:
                media = json.loads((job_dir / "media.json").read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                pass
            try:
                transcript = json.loads(
                    (job_dir / "transcript" / "speaker-turns.json").read_text(encoding="utf-8")
                )
            except (OSError, json.JSONDecodeError):
                pass
            summaries.append(
                {
                    "job_id": job["job_id"],
                    "filename": job.get("filename"),
                    "status": job.get("status"),
                    "stage": job.get("stage"),
                    "progress": job.get("progress", 0),
                    "duration_seconds": media.get("duration_seconds"),
                    "speaker_count": transcript.get("speaker_count"),
                    "turn_count": len(transcript.get("turns", [])),
                    "keyframes_status": job.get("keyframes_status", "not_started"),
                    "keyframe_count": job.get("keyframe_count"),
                    "created_at": job.get("created_at"),
                    "updated_at": job.get("updated_at"),
                    "workspace_url": f"/workspace/{job['job_id']}",
                }
            )
        return summaries


class UnavailableDiarizer:
    def run(self, audio_path: Path, segments: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "status": "unavailable",
            "detail": "speaker diarization is not configured",
            "speaker_count": None,
            "labels": [],
        }


class JobProcessor:
    def __init__(
        self,
        *,
        store: JobStore,
        settings: Settings,
        whisper_client: Any,
        diarizer: Any,
        executor: Any | None = None,
    ) -> None:
        self.store = store
        self.settings = settings
        self.whisper_client = whisper_client
        self.diarizer = diarizer
        self.executor = executor or ThreadPoolExecutor(
            max_workers=settings.executor_workers,
            thread_name_prefix="live-clip",
        )
        self._submitted: set[str] = set()
        self._keyframes_submitted: set[str] = set()
        self._submit_lock = threading.Lock()

    def submit_transcript(self, job_id: str) -> None:
        with self._submit_lock:
            if job_id in self._submitted:
                return
            self._submitted.add(job_id)
        self.executor.submit(self.process_transcript, job_id)

    def process_transcript(self, job_id: str) -> None:
        job_dir = self.store.job_dir(job_id)
        transcript_dir = job_dir / "transcript"
        transcript_dir.mkdir(parents=True, exist_ok=True)
        audio_path = transcript_dir / "audio-16k-mono.wav"
        try:
            self.store.update(job_id, status="processing", stage="transcribing", progress=10, error=None)
            extract_audio(job_dir / "source.mp4", audio_path)
            self.store.update(job_id, progress=25)
            result = self.whisper_client.transcribe(
                audio_path,
                language="zh",
                timeout_seconds=self.settings.whisper_timeout_seconds,
            )
            (transcript_dir / "raw.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            raw_text = str(result.get("raw_text") or result.get("text") or "").strip()
            (transcript_dir / "raw.txt").write_text(raw_text + "\n", encoding="utf-8")
            media = json.loads((job_dir / "media.json").read_text(encoding="utf-8"))
            duration = float(media["duration_seconds"])
            effective_result = apply_text_correction(result)
            segments = clean_segments(effective_result, duration)
            if not segments:
                raise RuntimeError("Whisper returned no usable timed segments")
            (transcript_dir / "segments.json").write_text(
                json.dumps({"segments": segments}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            self.store.update(job_id, stage="diarizing", progress=70)
            diarization = self.diarizer.run(audio_path, segments)
            labels = diarization.get("labels") if isinstance(diarization, dict) else []
            speaker_count = diarization.get("speaker_count") if isinstance(diarization, dict) else None
            candidate_document: dict[str, Any] | None = None
            embedding_cache = diarization.get("embedding_cache") if isinstance(diarization, dict) else None
            if isinstance(embedding_cache, dict):
                embeddings = np.asarray(embedding_cache.get("embeddings"), dtype=np.float32)
                indices = np.asarray(embedding_cache.get("indices"), dtype=np.int32)
                if embeddings.ndim == 2 and indices.ndim == 1 and len(embeddings) == len(indices):
                    np.savez_compressed(
                        transcript_dir / "speaker-embeddings.npz",
                        embeddings=embeddings,
                        indices=indices,
                    )
                    candidate_document = discover_candidates(
                        embeddings,
                        indices,
                        segments,
                        model=str(embedding_cache.get("model") or "ECAPA"),
                        similarity_threshold=float(embedding_cache.get("similarity_threshold") or 0.35),
                    )
                    (transcript_dir / "speaker-candidates.json").write_text(
                        json.dumps(candidate_document, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                    labels = [
                        {
                            "speaker": str(candidate_document["predictions"].get(str(index + 1), {}).get("candidate_id") or "UNKNOWN"),
                            "speaker_source": str(candidate_document["predictions"].get(str(index + 1), {}).get("source") or "unknown"),
                        }
                        for index in range(len(segments))
                    ]
                    speaker_count = candidate_document["speaker_count"]
            turns = build_speaker_turns(segments, labels)
            speaker_document = {
                "status": "ready",
                "speaker_count": speaker_count,
                "diarization": {
                    "status": diarization.get("status", "unavailable"),
                    "detail": diarization.get("detail"),
                },
                "candidate_status": "ready" if candidate_document is not None else "unavailable",
                "turns": turns,
            }
            (transcript_dir / "speaker-turns.json").write_text(
                json.dumps(speaker_document, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            self.store.update(
                job_id,
                status="ready",
                stage="ready",
                progress=100,
                transcript_url=f"/api/jobs/{job_id}/transcript",
            )
        except WhisperServiceError as exc:
            self.store.update(
                job_id,
                status="failed",
                stage="failed",
                error={"code": exc.code, "message": exc.message, "detail": exc.detail},
            )
        except Exception as exc:
            self.store.update(
                job_id,
                status="failed",
                stage="failed",
                error={"code": "TRANSCRIPT_PIPELINE_FAILED", "message": "字幕处理失败", "detail": str(exc)},
            )
        finally:
            with self._submit_lock:
                self._submitted.discard(job_id)

    def submit_keyframes(self, job_id: str) -> None:
        with self._submit_lock:
            if job_id in self._keyframes_submitted:
                return
            self._keyframes_submitted.add(job_id)
        self.executor.submit(self.process_keyframes, job_id)

    def process_keyframes(self, job_id: str) -> None:
        try:
            self.store.update(job_id, keyframes_status="running", keyframes_error=None)
            job_dir = self.store.job_dir(job_id)
            document = generate_keyframes(job_dir / "source.mp4", job_dir)
            self.store.update(
                job_id,
                keyframes_status="ready",
                keyframe_count=document["frame_count"],
            )
        except Exception as exc:
            self.store.update(
                job_id,
                keyframes_status="failed",
                keyframes_error={
                    "code": "KEYFRAME_PIPELINE_FAILED",
                    "message": "关键帧处理失败",
                    "detail": str(exc),
                },
            )
        finally:
            with self._submit_lock:
                self._keyframes_submitted.discard(job_id)
