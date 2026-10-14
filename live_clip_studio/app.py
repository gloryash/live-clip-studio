from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import quote

import numpy as np
from fastapi import Body, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from .ai_transcript_export import build_ai_transcript_document
from .config import Settings
from .clip_runs import ClipRunManager
from .clip_templates import list_templates
from .diarization import DiarizationService
from .jobs import JobNotFoundError, JobProcessor, JobStore
from .media import InvalidVideoError, probe_video
from .models import error_payload
from .speaker_workflow import (
    EXCLUDED_CANDIDATE,
    classify_registered_speakers,
    discover_candidates,
    score_speaker_predictions,
)
from .whisper_client import WhisperClient, WhisperServiceError, validate_health_payload


DEFAULT_MANUAL_SPEAKERS = {
    "SPEAKER_00": "说话人 1",
    "SPEAKER_01": "说话人 2",
}

TRANSCRIPT_REPROCESS_ARTIFACTS = (
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


def _speaker_number(speaker_id: str) -> int | None:
    prefix = "SPEAKER_"
    suffix = speaker_id.removeprefix(prefix)
    if not speaker_id.startswith(prefix) or not suffix.isdigit():
        return None
    return int(suffix)


def _speaker_sort_key(speaker_id: str) -> tuple[int, str]:
    number = _speaker_number(speaker_id)
    return (number if number is not None else 10_000, speaker_id)


def _next_speaker_id(speakers: dict[str, str]) -> str:
    number = 0
    while f"SPEAKER_{number:02d}" in speakers:
        number += 1
    return f"SPEAKER_{number:02d}"


def _media_probe() -> dict[str, bool]:
    return {"ffmpeg": shutil.which("ffmpeg") is not None, "ffprobe": shutil.which("ffprobe") is not None}


def _diarization_probe() -> dict[str, Any]:
    return DiarizationService.probe()


def create_app(
    *,
    settings: Settings | None = None,
    whisper_client: Any | None = None,
    media_probe: Callable[[], dict[str, bool]] | None = None,
    diarization_probe: Callable[[], dict[str, Any]] | None = None,
    processor: Any | None = None,
) -> FastAPI:
    settings = settings or Settings.from_env()
    whisper_client = whisper_client or WhisperClient(
        settings.whisper_url,
        expected_model=settings.whisper_model,
    )
    media_probe = media_probe or _media_probe
    diarization_probe = diarization_probe or _diarization_probe

    application = FastAPI(title="Live Clip Studio", version="0.1.0")
    application.state.settings = settings
    application.state.whisper_client = whisper_client
    store = JobStore(settings.data_dir)
    application.state.job_store = store
    processor = processor or JobProcessor(
        store=store,
        settings=settings,
        whisper_client=whisper_client,
        diarizer=DiarizationService(),
    )
    application.state.processor = processor
    clip_runs = ClipRunManager(store=store, settings=settings)
    application.state.clip_runs = clip_runs
    web_dir = Path(__file__).resolve().parent / "web"
    application.mount("/assets", StaticFiles(directory=web_dir), name="assets")

    @application.get("/", response_class=HTMLResponse)
    def upload_page() -> str:
        return (web_dir / "index.html").read_text(encoding="utf-8")

    @application.get("/workspace/{job_id}", response_class=HTMLResponse)
    def workspace_page(job_id: str) -> str:
        try:
            store.get(job_id)
        except JobNotFoundError as exc:
            raise HTTPException(status_code=404, detail="job not found") from exc
        return (web_dir / "workspace.html").read_text(encoding="utf-8").replace("__JOB_ID__", job_id)

    @application.get("/media/{job_id}/{relative_path:path}")
    def media_file(job_id: str, relative_path: str) -> FileResponse:
        try:
            root = store.job_dir(job_id).resolve()
            store.get(job_id)
        except JobNotFoundError as exc:
            raise HTTPException(status_code=404, detail="job not found") from exc
        target = (root / relative_path).resolve()
        if root not in target.parents or not target.is_file():
            raise HTTPException(status_code=404, detail="media not found")
        return FileResponse(target)

    @application.get("/api/health")
    def health() -> dict[str, Any]:
        media = media_probe()
        diarization = diarization_probe()
        try:
            whisper = validate_health_payload(whisper_client.health(), settings.whisper_model)
        except WhisperServiceError as exc:
            whisper = exc.as_dict()
        ready = bool(media.get("ffmpeg") and media.get("ffprobe") and whisper.get("status") == "ok")
        return {
            "ready": ready,
            "ffmpeg": {"status": "ok" if media.get("ffmpeg") else "unavailable"},
            "ffprobe": {"status": "ok" if media.get("ffprobe") else "unavailable"},
            "whisper": whisper,
            "diarization": diarization,
        }

    @application.get("/api/jobs")
    def list_jobs() -> dict[str, Any]:
        return {"jobs": store.history()}

    @application.get("/api/clip-templates")
    def get_clip_templates() -> dict[str, Any]:
        return {"templates": list_templates()}

    @application.get("/api/clip-sources")
    def get_clip_sources() -> dict[str, Any]:
        return {"sources": clip_runs.list_sources()}

    @application.get("/api/clip-runs")
    def list_clip_runs() -> dict[str, Any]:
        return {"runs": clip_runs.list_runs(), "storage_directory": str(clip_runs.root)}

    @application.post("/api/clip-runs", status_code=202)
    def create_clip_run(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        try:
            return clip_runs.create(str(payload.get("job_id") or ""), str(payload.get("template_id") or ""))
        except ValueError as exc:
            message = str(exc)
            status_code = 404 if message.startswith("JOB_NOT_FOUND") else 409 if message.startswith("SOURCE_NOT_READY") else 422
            raise HTTPException(status_code=status_code, detail=error_payload(message.split(":", 1)[0], message.split(":", 1)[-1].strip())) from exc

    @application.get("/api/clip-runs/{run_id}")
    def get_clip_run(run_id: str) -> dict[str, Any]:
        try:
            return clip_runs.public(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=error_payload("CLIP_RUN_NOT_FOUND", "找不到这个切片任务")) from exc

    @application.get("/api/clip-runs/{run_id}/events")
    def get_clip_run_events(run_id: str) -> dict[str, Any]:
        try:
            return {"events": clip_runs.events(run_id)}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=error_payload("CLIP_RUN_NOT_FOUND", "找不到这个切片任务")) from exc

    @application.get("/clip-media/{run_id}/{relative_path:path}")
    def clip_media(run_id: str, relative_path: str, download: bool = False) -> FileResponse:
        try:
            target = clip_runs.artifact(run_id, relative_path)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="clip artifact not found") from exc
        return FileResponse(target, filename=target.name if download else None)

    @application.post("/api/jobs", status_code=202)
    async def create_job(file: UploadFile = File(...)) -> dict[str, Any]:
        try:
            validate_health_payload(whisper_client.health(), settings.whisper_model)
        except WhisperServiceError as exc:
            raise HTTPException(status_code=503, detail=exc.as_dict()) from exc

        document = store.create(file.filename or "video.mp4")
        job_id = str(document["job_id"])
        job_dir = store.job_dir(job_id)
        partial = job_dir / "source.mp4.part"
        source_path = job_dir / "source.mp4"
        total = 0
        digest = hashlib.sha256()
        try:
            with partial.open("wb") as target:
                while True:
                    chunk = await file.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > settings.max_upload_bytes:
                        raise HTTPException(
                            status_code=413,
                            detail=error_payload("UPLOAD_TOO_LARGE", "视频超过本机上传限制"),
                        )
                    digest.update(chunk)
                    target.write(chunk)
            source_sha256 = digest.hexdigest()
            existing = store.find_by_fingerprint(source_sha256, total, exclude_job_id=job_id)
            if existing is not None:
                store.delete(job_id)
                existing_job_id = str(existing["job_id"])
                if existing.get("status") == "failed":
                    store.update(
                        existing_job_id,
                        status="uploaded",
                        stage="queued",
                        progress=0,
                        error=None,
                    )
                    processor.submit_transcript(existing_job_id)
                    return JSONResponse(
                        status_code=202,
                        content={
                            "job_id": existing_job_id,
                            "status": "uploaded",
                            "workspace_url": f"/workspace/{existing_job_id}",
                            "reused": True,
                            "reprocessed": True,
                        },
                    )
                return JSONResponse(
                    status_code=200,
                    content={
                        "job_id": existing_job_id,
                        "status": existing.get("status"),
                        "workspace_url": f"/workspace/{existing_job_id}",
                        "reused": True,
                        "reprocessed": False,
                    },
                )
            partial.replace(source_path)
            store.update(job_id, source_sha256=source_sha256, source_size=total)
            media = probe_video(source_path)
            (job_dir / "media.json").write_text(
                json.dumps(media, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except HTTPException:
            store.delete(job_id)
            raise
        except (OSError, InvalidVideoError) as exc:
            store.delete(job_id)
            raise HTTPException(
                status_code=422,
                detail=error_payload("INVALID_VIDEO", "无法读取这个视频文件", str(exc)),
            ) from exc
        finally:
            await file.close()
        processor.submit_transcript(job_id)
        return {
            "job_id": job_id,
            "status": "uploaded",
            "workspace_url": f"/workspace/{job_id}",
            "reused": False,
        }

    @application.get("/api/jobs/{job_id}")
    def get_job(job_id: str) -> dict[str, Any]:
        try:
            return store.get(job_id)
        except JobNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail=error_payload("JOB_NOT_FOUND", "找不到这个视频任务", job_id),
            ) from exc

    @application.get("/api/jobs/{job_id}/transcript")
    def get_transcript(job_id: str) -> Any:
        try:
            job = store.get(job_id)
        except JobNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail=error_payload("JOB_NOT_FOUND", "找不到这个视频任务", job_id),
            ) from exc
        path = store.job_dir(job_id) / "transcript" / "speaker-turns.json"
        if job.get("status") == "failed":
            raise HTTPException(status_code=409, detail=job.get("error"))
        if job.get("status") != "ready":
            return JSONResponse(
                status_code=202,
                content={
                    "status": "processing",
                    "stage": job.get("stage"),
                    "progress": job.get("progress", 0),
                    "turns": [],
                },
            )
        if path.is_file():
            document = json.loads(path.read_text(encoding="utf-8"))
            predictions = read_speaker_predictions(path.parent)
            if predictions is not None:
                speakers = read_manual_speakers(path.parent)
                predicted_speakers = {
                    str(item.get("speaker_id"))
                    for item in predictions.get("predictions", {}).values()
                    if isinstance(item, dict) and item.get("speaker_id") not in {None, "UNKNOWN"}
                }
                document["speaker_count"] = len(predicted_speakers)
                document["speaker_count_status"] = "confirmed"
                for turn in document.get("turns", []):
                    prediction = predictions.get("predictions", {}).get(str(turn.get("id")))
                    if not isinstance(prediction, dict):
                        continue
                    speaker_id = str(prediction.get("speaker_id") or "UNKNOWN")
                    turn["candidate_speaker"] = turn.get("speaker")
                    turn["speaker_source"] = str(prediction.get("source") or "registered_embedding")
                    turn["prediction_confidence"] = prediction.get("confidence")
                    if speaker_id == "UNKNOWN":
                        duration = float(turn.get("end") or 0.0) - float(turn.get("start") or 0.0)
                        turn["speaker"] = "UNKNOWN"
                        turn["speaker_label"] = "时长太小，无法判断" if duration < 1.0 else "AI 无法判断"
                        continue
                    turn["speaker"] = speaker_id
                    turn["speaker_label"] = speakers.get(speaker_id, speaker_id)
            else:
                candidates = read_speaker_candidates(path.parent)
                if candidates is not None:
                    document["speaker_count"] = int(candidates.get("speaker_count") or 0)
                    document["speaker_count_status"] = "candidates"
            return document
        return JSONResponse(
            status_code=202,
            content={
                "status": "processing",
                "stage": job.get("stage"),
                "progress": job.get("progress", 0),
                "turns": [],
            },
        )

    def annotation_context(job_id: str) -> tuple[dict[str, Any], list[dict[str, Any]], Path]:
        try:
            job = store.get(job_id)
        except JobNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail=error_payload("JOB_NOT_FOUND", "找不到这个视频任务", job_id),
            ) from exc
        transcript_path = store.job_dir(job_id) / "transcript" / "speaker-turns.json"
        if job.get("status") != "ready" or not transcript_path.is_file():
            raise HTTPException(
                status_code=409,
                detail=error_payload("TRANSCRIPT_NOT_READY", "字幕完成后才能人工标注"),
            )
        transcript = json.loads(transcript_path.read_text(encoding="utf-8"))
        turns = [turn for turn in transcript.get("turns", []) if isinstance(turn, dict)]
        return job, turns, transcript_path.parent

    def read_manual_speakers(transcript_dir: Path) -> dict[str, str]:
        path = transcript_dir / "manual-speakers.json"
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return dict(DEFAULT_MANUAL_SPEAKERS)
        stored = document.get("speakers", {}) if isinstance(document, dict) else {}
        if not isinstance(stored, dict):
            return dict(DEFAULT_MANUAL_SPEAKERS)
        speakers = {
            str(speaker_id): str(label).strip()
            for speaker_id, label in stored.items()
            if _speaker_number(str(speaker_id)) is not None and str(label).strip()
        }
        for speaker_id, label in DEFAULT_MANUAL_SPEAKERS.items():
            speakers.setdefault(speaker_id, label)
        return {
            speaker_id: speakers[speaker_id]
            for speaker_id in sorted(speakers, key=_speaker_sort_key)
        }

    def write_manual_speakers(transcript_dir: Path, speakers: dict[str, str]) -> None:
        path = transcript_dir / "manual-speakers.json"
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(
                {
                    "version": 1,
                    "speakers": {
                        speaker_id: speakers[speaker_id]
                        for speaker_id in sorted(speakers, key=_speaker_sort_key)
                    },
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        temporary.replace(path)

    def read_annotations(transcript_dir: Path) -> dict[str, str]:
        path = transcript_dir / "manual-speaker-labels.json"
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        annotations = document.get("annotations", {}) if isinstance(document, dict) else {}
        if not isinstance(annotations, dict):
            return {}
        speakers = read_manual_speakers(transcript_dir)
        return {
            str(turn_id): str(speaker)
            for turn_id, speaker in annotations.items()
            if str(speaker) in speakers
        }

    def write_annotations(transcript_dir: Path, annotations: dict[str, str]) -> None:
        path = transcript_dir / "manual-speaker-labels.json"
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps({"version": 1, "annotations": annotations}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(path)

    def read_deleted_turn_ids(transcript_dir: Path) -> set[int]:
        path = transcript_dir / "deleted-turns.json"
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return set()
        values = document.get("deleted_turn_ids", []) if isinstance(document, dict) else []
        deleted: set[int] = set()
        if isinstance(values, list):
            for value in values:
                try:
                    turn_id = int(value)
                except (TypeError, ValueError):
                    continue
                if turn_id > 0:
                    deleted.add(turn_id)
        return deleted

    def write_deleted_turn_ids(transcript_dir: Path, turn_ids: set[int]) -> None:
        path = transcript_dir / "deleted-turns.json"
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(
                {"version": 1, "deleted_turn_ids": sorted(turn_ids)},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        temporary.replace(path)

    def read_speaker_candidates(transcript_dir: Path) -> dict[str, Any] | None:
        path = transcript_dir / "speaker-candidates.json"
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return document if isinstance(document, dict) else None

    def read_speaker_predictions(transcript_dir: Path) -> dict[str, Any] | None:
        path = transcript_dir / "speaker-predictions.json"
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return document if isinstance(document, dict) else None

    def write_document(path: Path, document: dict[str, Any]) -> None:
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)

    def read_candidate_assignments(transcript_dir: Path) -> dict[str, str]:
        path = transcript_dir / "speaker-candidate-assignments.json"
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        assignments = document.get("assignments", {}) if isinstance(document, dict) else {}
        return (
            {str(candidate_id): str(speaker_id) for candidate_id, speaker_id in assignments.items()}
            if isinstance(assignments, dict)
            else {}
        )

    def write_candidate_assignments(transcript_dir: Path, assignments: dict[str, str]) -> None:
        write_document(
            transcript_dir / "speaker-candidate-assignments.json",
            {"version": 1, "assignments": dict(sorted(assignments.items()))},
        )

    def invalidate_speaker_predictions(transcript_dir: Path) -> None:
        (transcript_dir / "speaker-predictions.json").unlink(missing_ok=True)

    def candidate_context(job_id: str) -> tuple[list[dict[str, Any]], Path, dict[str, Any]]:
        _, turns, transcript_dir = annotation_context(job_id)
        candidates = read_speaker_candidates(transcript_dir)
        if candidates is None:
            raise HTTPException(
                status_code=409,
                detail=error_payload("CANDIDATES_NOT_READY", "请先重新生成字幕以提取候选说话人"),
            )
        return turns, transcript_dir, candidates

    @application.get("/api/jobs/{job_id}/annotations")
    def get_annotations(job_id: str) -> dict[str, Any]:
        _, turns, transcript_dir = annotation_context(job_id)
        annotations = read_annotations(transcript_dir)
        speakers = read_manual_speakers(transcript_dir)
        deleted = read_deleted_turn_ids(transcript_dir)
        active_ids = {str(turn.get("id")) for turn in turns if int(turn.get("id", -1)) not in deleted}
        annotated_count = sum(turn_id in annotations for turn_id in active_ids)
        return {
            "annotations": annotations,
            "annotated_count": annotated_count,
            "total_count": len(active_ids),
            "raw_total_count": len(turns),
            "active_total_count": len(active_ids),
            "deleted_count": len(deleted),
            "deleted_turn_ids": sorted(deleted),
            "speakers": speakers,
        }

    @application.get("/api/jobs/{job_id}/speaker-candidates")
    def get_speaker_candidates(job_id: str) -> dict[str, Any]:
        _, transcript_dir, document = candidate_context(job_id)
        assignments = read_candidate_assignments(transcript_dir)
        speakers = read_manual_speakers(transcript_dir)
        candidates = []
        for candidate in document.get("candidates", []):
            if not isinstance(candidate, dict):
                continue
            candidate_id = str(candidate.get("candidate_id") or "")
            assignment = assignments.get(candidate_id)
            excluded = assignment == EXCLUDED_CANDIDATE
            speaker_id = None if excluded else assignment
            candidates.append(
                {
                    **candidate,
                    "speaker_id": speaker_id,
                    "speaker_label": "已排除 · 混合声音" if excluded else speakers.get(speaker_id) if speaker_id else None,
                    "resolution": "excluded" if excluded else "speaker" if speaker_id else "pending",
                    "resolved": assignment is not None,
                }
            )
        return {
            "status": "ready",
            "model": document.get("model"),
            "speaker_count": document.get("speaker_count"),
            "candidates": candidates,
            "speakers": speakers,
            "confirmed_count": sum(candidate["resolved"] for candidate in candidates),
            "all_confirmed": bool(candidates) and all(candidate["resolved"] for candidate in candidates),
        }

    @application.post("/api/jobs/{job_id}/speaker-candidates/rebuild")
    def rebuild_speaker_candidates(job_id: str) -> dict[str, Any]:
        try:
            store.get(job_id)
        except JobNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail=error_payload("JOB_NOT_FOUND", "找不到这个视频任务", job_id),
            ) from exc
        transcript_dir = store.job_dir(job_id) / "transcript"
        segments_path = transcript_dir / "segments.json"
        embedding_path = transcript_dir / "speaker-embeddings.npz"
        if not segments_path.is_file() or not embedding_path.is_file():
            raise HTTPException(
                status_code=409,
                detail=error_payload(
                    "EMBEDDINGS_NOT_READY",
                    "候选声纹数据不完整，请使用“重新生成字幕”",
                ),
            )
        try:
            segment_document = json.loads(segments_path.read_text(encoding="utf-8"))
            segments = segment_document.get("segments") if isinstance(segment_document, dict) else None
            if not isinstance(segments, list) or not segments:
                raise ValueError("segments must be a non-empty list")
            with np.load(embedding_path, allow_pickle=False) as cache:
                embeddings = np.asarray(cache["embeddings"], dtype=np.float32)
                indices = np.asarray(cache["indices"], dtype=np.int32)
            if embeddings.ndim != 2 or indices.ndim != 1 or len(embeddings) != len(indices):
                raise ValueError("embedding cache shape mismatch")
            document = discover_candidates(
                embeddings,
                indices,
                segments,
                model="ECAPA",
                similarity_threshold=0.35,
            )
        except (OSError, KeyError, ValueError, json.JSONDecodeError) as exc:
            raise HTTPException(
                status_code=409,
                detail=error_payload("EMBEDDINGS_INVALID", "候选声纹数据无效，请重新生成字幕", str(exc)),
            ) from exc
        write_document(transcript_dir / "speaker-candidates.json", document)
        (transcript_dir / "speaker-candidate-assignments.json").unlink(missing_ok=True)
        invalidate_speaker_predictions(transcript_dir)
        return {
            "status": "ready",
            "job_id": job_id,
            "speaker_count": document["speaker_count"],
            "model": document["model"],
            "similarity_threshold": document["similarity_threshold"],
        }

    @application.put("/api/jobs/{job_id}/speaker-candidates/{candidate_id}")
    def save_candidate_assignment(
        job_id: str,
        candidate_id: str,
        payload: dict[str, Any] = Body(...),
    ) -> dict[str, Any]:
        _, transcript_dir, document = candidate_context(job_id)
        candidate_ids = {
            str(candidate.get("candidate_id"))
            for candidate in document.get("candidates", [])
            if isinstance(candidate, dict)
        }
        if candidate_id not in candidate_ids:
            raise HTTPException(
                status_code=404,
                detail=error_payload("CANDIDATE_NOT_FOUND", "找不到这个候选说话人", candidate_id),
            )
        assignments = read_candidate_assignments(transcript_dir)
        speakers = read_manual_speakers(transcript_dir)
        if str(payload.get("resolution") or "").strip() == "excluded":
            assignments[candidate_id] = EXCLUDED_CANDIDATE
            write_candidate_assignments(transcript_dir, assignments)
            invalidate_speaker_predictions(transcript_dir)
            return {
                "candidate_id": candidate_id,
                "resolution": "excluded",
                "speaker_id": None,
                "speaker_label": "已排除 · 混合声音",
            }
        requested_speaker = str(payload.get("speaker_id") or "").strip()
        if requested_speaker:
            if requested_speaker not in speakers:
                raise HTTPException(
                    status_code=422,
                    detail=error_payload("SPEAKER_NOT_FOUND", "请选择已有说话人或留空自动创建"),
                )
            speaker_id = requested_speaker
        else:
            used_speakers = set(assignments.values())
            speaker_id = next(
                (item for item in speakers if item not in used_speakers),
                _next_speaker_id(speakers),
            )
            speakers.setdefault(
                speaker_id,
                f"说话人 {_speaker_number(speaker_id) + 1}",
            )
        requested_name = str(payload.get("speaker_name") or "").strip()
        if requested_name:
            speakers[speaker_id] = requested_name
        write_manual_speakers(transcript_dir, speakers)
        assignments[candidate_id] = speaker_id
        write_candidate_assignments(transcript_dir, assignments)
        invalidate_speaker_predictions(transcript_dir)
        return {
            "candidate_id": candidate_id,
            "speaker_id": speaker_id,
            "speaker_label": speakers[speaker_id],
        }

    @application.put("/api/jobs/{job_id}/speakers/{speaker_id}")
    def rename_manual_speaker(
        job_id: str,
        speaker_id: str,
        payload: dict[str, Any] = Body(...),
    ) -> dict[str, Any]:
        _, _, transcript_dir = annotation_context(job_id)
        speakers = read_manual_speakers(transcript_dir)
        name = str(payload.get("speaker_name") or "").strip()
        if speaker_id not in speakers or not name:
            raise HTTPException(
                status_code=422,
                detail=error_payload("INVALID_SPEAKER_NAME", "请提供已有说话人的非空名称"),
            )
        speakers[speaker_id] = name
        write_manual_speakers(transcript_dir, speakers)
        return {"speaker_id": speaker_id, "speaker_label": name}

    @application.post("/api/jobs/{job_id}/speaker-classification")
    def classify_speakers(job_id: str) -> dict[str, Any]:
        _, transcript_dir, candidates = candidate_context(job_id)
        embedding_path = transcript_dir / "speaker-embeddings.npz"
        segments_path = transcript_dir / "segments.json"
        if not embedding_path.is_file() or not segments_path.is_file():
            raise HTTPException(
                status_code=409,
                detail=error_payload("EMBEDDINGS_NOT_READY", "候选声纹数据不完整，请重新生成字幕"),
            )
        assignments = read_candidate_assignments(transcript_dir)
        candidate_ids = {
            str(candidate.get("candidate_id"))
            for candidate in candidates.get("candidates", [])
            if isinstance(candidate, dict)
        }
        missing = sorted(candidate_ids - set(assignments))
        if missing:
            raise HTTPException(
                status_code=409,
                detail=error_payload("CANDIDATES_UNCONFIRMED", "请先确认全部候选说话人", ", ".join(missing)),
            )
        with np.load(embedding_path, allow_pickle=False) as cache:
            embeddings = np.asarray(cache["embeddings"], dtype=np.float32)
            indices = np.asarray(cache["indices"], dtype=np.int32)
        try:
            segments = json.loads(segments_path.read_text(encoding="utf-8"))["segments"]
            predictions = classify_registered_speakers(
                embeddings,
                indices,
                segments,
                candidates,
                assignments,
            )
        except (KeyError, OSError, ValueError) as exc:
            raise HTTPException(
                status_code=422,
                detail=error_payload("SPEAKER_CLASSIFICATION_FAILED", "说话人全量识别失败", str(exc)),
            ) from exc
        write_document(transcript_dir / "speaker-predictions.json", predictions)
        predicted_count = sum(
            item.get("speaker_id") != "UNKNOWN"
            for item in predictions.get("predictions", {}).values()
            if isinstance(item, dict)
        )
        return {
            "status": "ready",
            "predicted_count": predicted_count,
            "enrollment_turn_ids": predictions.get("enrollment_turn_ids", []),
        }

    @application.get("/api/jobs/{job_id}/speaker-metrics")
    def get_speaker_metrics(job_id: str) -> dict[str, Any]:
        _, turns, transcript_dir = annotation_context(job_id)
        predictions = read_speaker_predictions(transcript_dir)
        deleted = read_deleted_turn_ids(transcript_dir)
        annotations = read_annotations(transcript_dir)
        if predictions is None:
            active_count = sum(int(turn.get("id", -1)) not in deleted for turn in turns)
            return {
                "version": 1,
                "available": False,
                "annotated_count": sum(str(turn.get("id")) in annotations for turn in turns if int(turn.get("id", -1)) not in deleted),
                "active_total_count": active_count,
                "coverage": 0.0,
                "all_labeled": {"count": 0, "correct": 0, "accuracy": None},
                "held_out": {"count": 0, "correct": 0, "accuracy": None},
                "speakers": {},
                "long": {"count": 0, "correct": 0, "accuracy": None},
                "short": {"count": 0, "correct": 0, "accuracy": None},
                "confusion": {},
            }
        segments_path = transcript_dir / "segments.json"
        try:
            segments = json.loads(segments_path.read_text(encoding="utf-8"))["segments"]
        except (OSError, KeyError, json.JSONDecodeError) as exc:
            raise HTTPException(
                status_code=409,
                detail=error_payload("SEGMENTS_NOT_READY", "字幕时间轴数据不完整", str(exc)),
            ) from exc
        return score_speaker_predictions(
            predictions,
            annotations,
            segments,
            deleted_turn_ids=deleted,
        )

    @application.post("/api/jobs/{job_id}/speakers")
    def add_manual_speaker(job_id: str) -> dict[str, Any]:
        _, _, transcript_dir = annotation_context(job_id)
        speakers = read_manual_speakers(transcript_dir)
        next_id = _next_speaker_id(speakers)
        speakers[next_id] = f"说话人 {_speaker_number(next_id) + 1}"
        write_manual_speakers(transcript_dir, speakers)
        return {"speaker": next_id, "speaker_label": speakers[next_id], "speakers": speakers}

    @application.put("/api/jobs/{job_id}/annotations/{turn_id}")
    def save_annotation(job_id: str, turn_id: int, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        _, turns, transcript_dir = annotation_context(job_id)
        speaker = str(payload.get("speaker") or "")
        speakers = read_manual_speakers(transcript_dir)
        if speaker not in speakers:
            raise HTTPException(
                status_code=422,
                detail=error_payload("INVALID_MANUAL_SPEAKER", "请先在顶部添加这个说话人"),
            )
        if turn_id not in {int(turn.get("id", -1)) for turn in turns}:
            raise HTTPException(
                status_code=404,
                detail=error_payload("TURN_NOT_FOUND", "找不到这条字幕", str(turn_id)),
            )
        annotations = read_annotations(transcript_dir)
        annotations[str(turn_id)] = speaker
        write_annotations(transcript_dir, annotations)
        deleted = read_deleted_turn_ids(transcript_dir)
        active_ids = {str(turn.get("id")) for turn in turns if int(turn.get("id", -1)) not in deleted}
        return {
            "turn_id": turn_id,
            "speaker": speaker,
            "annotated_count": sum(active_id in annotations for active_id in active_ids),
            "total_count": len(active_ids),
        }

    @application.delete("/api/jobs/{job_id}/transcript/turns/{turn_id}")
    def delete_transcript_turn(job_id: str, turn_id: int) -> dict[str, Any]:
        _, turns, transcript_dir = annotation_context(job_id)
        all_ids = {int(turn.get("id", -1)) for turn in turns}
        if turn_id not in all_ids:
            raise HTTPException(
                status_code=404,
                detail=error_payload("TURN_NOT_FOUND", "找不到这条字幕", str(turn_id)),
            )
        deleted = read_deleted_turn_ids(transcript_dir)
        deleted.add(turn_id)
        write_deleted_turn_ids(transcript_dir, deleted)
        active_total = len(all_ids - deleted)
        annotations = read_annotations(transcript_dir)
        annotated_count = sum(str(active_id) in annotations for active_id in all_ids - deleted)
        return {
            "turn_id": turn_id,
            "deleted_turn_ids": sorted(deleted),
            "deleted_count": len(deleted),
            "annotated_count": annotated_count,
            "active_total_count": active_total,
        }

    @application.get("/api/jobs/{job_id}/training-export")
    def export_training_labels(job_id: str) -> Response:
        _, turns, transcript_dir = annotation_context(job_id)
        annotations = read_annotations(transcript_dir)
        speakers = read_manual_speakers(transcript_dir)
        deleted = read_deleted_turn_ids(transcript_dir)
        active_turns = [turn for turn in turns if int(turn.get("id", -1)) not in deleted]
        turn_ids = [str(turn.get("id")) for turn in active_turns]
        missing = [turn_id for turn_id in turn_ids if turn_id not in annotations]
        if missing:
            raise HTTPException(
                status_code=409,
                detail=error_payload(
                    "ANNOTATIONS_INCOMPLETE",
                    "请先完成全部字幕的人工说话人标注",
                    f"已标注 {sum(turn_id in annotations for turn_id in turn_ids)} / {len(active_turns)} 条",
                ),
            )
        rows = []
        for turn in active_turns:
            turn_id = str(turn["id"])
            manual_speaker = annotations[turn_id]
            rows.append(
                json.dumps(
                    {
                        "audio_path": "transcript/audio-16k-mono.wav",
                        "source_video_path": "source.mp4",
                        "start": float(turn["start"]),
                        "end": float(turn["end"]),
                        "text": str(turn.get("text") or ""),
                        "original_speaker": str(turn.get("speaker") or ""),
                        "original_speaker_label": str(turn.get("speaker_label") or ""),
                        "manual_speaker": manual_speaker,
                        "manual_speaker_label": speakers[manual_speaker],
                    },
                    ensure_ascii=False,
                )
            )
        filename = f"{job_id}-speaker-training.jsonl"
        return Response(
            content="\n".join(rows) + "\n",
            media_type="application/x-ndjson",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @application.get("/api/jobs/{job_id}/ai-transcript-export")
    def export_ai_transcript(job_id: str) -> Response:
        job, turns, transcript_dir = annotation_context(job_id)
        candidates = read_speaker_candidates(transcript_dir)
        candidate_ids = {
            str(candidate.get("candidate_id"))
            for candidate in (candidates or {}).get("candidates", [])
            if isinstance(candidate, dict) and candidate.get("candidate_id")
        }
        assignments = read_candidate_assignments(transcript_dir)
        if not candidate_ids or candidate_ids - assignments.keys():
            raise HTTPException(
                status_code=409,
                detail=error_payload("CANDIDATES_UNCONFIRMED", "请先确认全部候选说话人"),
            )
        predictions = read_speaker_predictions(transcript_dir)
        if predictions is None:
            raise HTTPException(
                status_code=409,
                detail=error_payload("SPEAKER_CLASSIFICATION_REQUIRED", "请先应用到全部字幕"),
            )

        job_dir = store.job_dir(job_id)

        def read_json_document(path: Path, default: dict[str, Any]) -> dict[str, Any]:
            try:
                document = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return default
            return document if isinstance(document, dict) else default

        transcript = read_json_document(
            transcript_dir / "speaker-turns.json",
            {"turns": turns},
        )
        segment_document = read_json_document(transcript_dir / "segments.json", {"segments": []})
        saved_segments = [
            segment
            for segment in segment_document.get("segments", [])
            if isinstance(segment, dict)
        ]
        raw = read_json_document(transcript_dir / "raw.json", {"segments": []})
        fallback_duration = max((float(turn.get("end") or 0.0) for turn in turns), default=0.0)
        media = read_json_document(
            job_dir / "media.json",
            {"duration_seconds": fallback_duration},
        )
        document = build_ai_transcript_document(
            job=job,
            media=media,
            transcript=transcript,
            saved_segments=saved_segments,
            raw=raw,
            predictions=predictions,
            speakers=read_manual_speakers(transcript_dir),
            annotations=read_annotations(transcript_dir),
            deleted_turn_ids=read_deleted_turn_ids(transcript_dir),
        )
        source_stem = Path(str(job.get("filename") or "video")).stem or "video"
        utf8_filename = f"{source_stem}-AI精准字幕.json"
        fallback_filename = f"{job_id}-ai-transcript.json"
        content_disposition = (
            f'attachment; filename="{fallback_filename}"; '
            f"filename*=UTF-8''{quote(utf8_filename)}"
        )
        return Response(
            content=json.dumps(document, ensure_ascii=False, indent=2),
            media_type="application/json",
            headers={
                "Content-Disposition": content_disposition,
                "Content-Type": "application/json; charset=utf-8",
            },
        )

    @application.post("/api/jobs/{job_id}/transcript/reprocess", status_code=202)
    def reprocess_transcript(job_id: str) -> dict[str, Any]:
        try:
            job = store.get(job_id)
        except JobNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail=error_payload("JOB_NOT_FOUND", "找不到这个视频任务", job_id),
            ) from exc
        if job.get("status") == "processing":
            return {"status": "processing", "job_id": job_id, "stage": job.get("stage")}
        store.update(job_id, status="uploaded", stage="queued", progress=0, error=None)
        transcript_dir = store.job_dir(job_id) / "transcript"
        for filename in TRANSCRIPT_REPROCESS_ARTIFACTS:
            (transcript_dir / filename).unlink(missing_ok=True)
        processor.submit_transcript(job_id)
        return {"status": "queued", "job_id": job_id, "stage": "queued"}

    @application.post("/api/jobs/{job_id}/keyframes", status_code=202)
    def start_keyframes(job_id: str, force: bool = False) -> dict[str, Any]:
        try:
            job = store.get(job_id)
        except JobNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail=error_payload("JOB_NOT_FOUND", "找不到这个视频任务", job_id),
            ) from exc
        if job.get("status") != "ready":
            raise HTTPException(
                status_code=409,
                detail=error_payload("TRANSCRIPT_NOT_READY", "字幕完成后才能提取关键帧"),
            )
        status = str(job.get("keyframes_status") or "not_started")
        if status in {"queued", "running"}:
            return {"status": status, "job_id": job_id}
        if force or status in {"not_started", "failed"}:
            store.update(job_id, keyframes_status="queued", keyframes_error=None)
            processor.submit_keyframes(job_id)
            status = "queued"
        return {"status": status, "job_id": job_id}

    @application.get("/api/jobs/{job_id}/keyframes")
    def get_keyframes(job_id: str) -> dict[str, Any]:
        try:
            job = store.get(job_id)
        except JobNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail=error_payload("JOB_NOT_FOUND", "找不到这个视频任务", job_id),
            ) from exc
        status = str(job.get("keyframes_status") or "not_started")
        path = store.job_dir(job_id) / "keyframes" / "frames.json"
        if status == "ready" and path.is_file():
            document = json.loads(path.read_text(encoding="utf-8"))
            for frame in document.get("frames", []):
                frame["image_url"] = f"/media/{job_id}/{frame['image_url']}"
            return document
        response = {
            "status": status,
            "frames": [],
        }
        if job.get("keyframes_error"):
            response["error"] = job["keyframes_error"]
        return response

    return application


app = create_app()
