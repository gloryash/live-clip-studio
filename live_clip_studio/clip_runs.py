from __future__ import annotations

import copy
import json
import threading
import uuid
from argparse import Namespace
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .clip_templates import build_layout, choose_layout, get_template
from .clips.pipeline import execute
from .jobs import JobNotFoundError, JobStore


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ClipRunManager:
    def __init__(self, *, store: JobStore, settings: Any, executor: Any | None = None) -> None:
        self.store = store
        self.settings = settings
        self.root = Path(settings.data_dir).parent / "exports" / "auto-clips"
        self.root.mkdir(parents=True, exist_ok=True)
        self.executor = executor or ThreadPoolExecutor(max_workers=1, thread_name_prefix="clip-run")
        self._lock = threading.RLock()
        self._submitted: set[str] = set()

    def _path(self, run_id: str) -> Path:
        if not run_id or any(c not in "0123456789abcdef-" for c in run_id.lower()):
            raise KeyError(run_id)
        return self.root / run_id

    def _read(self, run_id: str) -> dict[str, Any]:
        path = self._path(run_id) / "web-run.json"
        if not path.is_file():
            raise KeyError(run_id)
        return json.loads(path.read_text(encoding="utf-8"))

    def _write(self, run: dict[str, Any]) -> None:
        path = self._path(str(run["run_id"]))
        path.mkdir(parents=True, exist_ok=True)
        temp = path / "web-run.json.tmp"
        temp.write_text(json.dumps(run, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(path / "web-run.json")

    def _write_result(self, run_id: str, value: dict[str, Any]) -> None:
        path = self._path(run_id) / "result.json"
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")

    def _existing_for(self, job_id: str, template_id: str) -> dict[str, Any] | None:
        for run in self.list_runs():
            if (run.get("job_id") == job_id and run.get("template_id") == template_id
                    and run.get("status") in {"queued", "running", "completed", "needs_review"}):
                return run
        return None

    def _read_json(self, path: Path, default: Any) -> Any:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return default

    def _source_readiness(self, job: dict[str, Any]) -> tuple[bool, str]:
        job_id = str(job["job_id"])
        if job.get("status") != "ready":
            return False, "字幕和说话人识别尚未完成"
        job_dir = self.store.job_dir(job_id)
        if not (job_dir / "source.mp4").is_file():
            return False, "源视频文件不存在"
        transcript_dir = job_dir / "transcript"
        transcript = self._read_json(transcript_dir / "speaker-turns.json", {})
        turns = [row for row in transcript.get("turns", []) if isinstance(row, dict)]
        if not turns:
            return False, "没有可用字幕时间轴"
        candidates = self._read_json(transcript_dir / "speaker-candidates.json", {})
        candidate_ids = {
            str(item.get("candidate_id")) for item in candidates.get("candidates", [])
            if isinstance(item, dict) and item.get("candidate_id")
        }
        assignments = self._read_json(transcript_dir / "speaker-candidate-assignments.json", {}).get("assignments", {})
        if candidate_ids and candidate_ids - set(assignments):
            return False, "还有候选说话人未确认"
        predictions = self._read_json(transcript_dir / "speaker-predictions.json", {})
        if not isinstance(predictions.get("predictions"), dict):
            return False, "还没有应用说话人分类"
        return True, "已完成说话人标注"

    def list_sources(self) -> list[dict[str, Any]]:
        result = []
        runs = self.list_runs()
        for job in self.store.history():
            ready, reason = self._source_readiness(job)
            history = [{
                "run_id": run["run_id"], "template_id": run["template_id"],
                "status": run["status"], "clip_count": run.get("result", {}).get("count", 0),
            } for run in runs if run.get("job_id") == job["job_id"]]
            result.append({**job, "clip_ready": ready, "clip_ready_reason": reason, "clip_runs": history})
        return result

    def create(self, job_id: str, template_id: str) -> dict[str, Any]:
        template = get_template(template_id)
        try:
            job = self.store.get(job_id)
        except JobNotFoundError as exc:
            raise ValueError("JOB_NOT_FOUND: 找不到这场直播") from exc
        with self._lock:
            existing = self._existing_for(job_id, template_id)
            if existing:
                return {**existing, "reused": True}
            ready, reason = self._source_readiness(job)
            if not ready:
                raise ValueError(f"SOURCE_NOT_READY: {reason}")
            run_id = str(uuid.uuid4())
            run_dir = self._path(run_id)
            run = {
                "run_id": run_id,
                "job_id": job_id,
                "template_id": template.id,
                "template_name": template.name,
                "source_filename": job.get("filename"),
                "status": "queued",
                "stage": "queued",
                "progress": 0,
                "stages": {},
                "error": None,
                "created_at": _now(),
                "updated_at": _now(),
            }
            self._write(run)
            self._submitted.add(run_id)
            self.executor.submit(self._run, run_id, copy.deepcopy(job), template.as_dict())
            return self.public(run_id)

    def _update(self, run_id: str, **fields: Any) -> dict[str, Any]:
        with self._lock:
            run = self._read(run_id)
            run.update(fields, updated_at=_now())
            self._write(run)
            return run

    def _run(self, run_id: str, job: dict[str, Any], template: dict[str, Any]) -> None:
        run_dir = self._path(run_id)
        try:
            self._update(run_id, status="running", stage="preflight", progress=5)
            job_dir = self.store.job_dir(str(job["job_id"]))
            media = self._read_json(job_dir / "media.json", {})
            stream = next((item for item in media.get("streams", []) if item.get("codec_type") == "video"), None)
            if not stream:
                raise ValueError("SOURCE_VIDEO_STREAM: 找不到视频流")
            layout_source = choose_layout(Path(__file__).resolve().parents[1] / "editing" / "layouts",
                                          int(stream["width"]), int(stream["height"]))
            layout_path = build_layout(layout_source, run_dir / "layout.json")
            self._update(run_id, stage="ai_selection", progress=15)
            result = execute(Namespace(
                command="run",
                job_dir=str(job_dir),
                transcript=None,
                source=None,
                layout=str(layout_path),
                out=str(run_dir),
                count=int(template["count"]),
                decisions=str(run_dir / "decisions.json") if (run_dir / "decisions.json").is_file() else None,
                fresh=False,
                skip_speech=False,
                ban=[],
            ))
            self._update(run_id, stage="render", progress=70)
            self._update(run_id, stage="quality_check", progress=90)
            decisions = self._read_json(run_dir / "decisions.json", {"clips": []})
            plans = {path.stem: self._read_json(path, {}) for path in (run_dir / "plans").glob("*.json")}
            qa = self._read_json(run_dir / "qa" / "summary.json", {"clips": []})
            clips = []
            qa_by_id = {str(item.get("id")): item for item in qa.get("clips", []) if isinstance(item, dict)}
            for clip in decisions.get("clips", []):
                clip_id = str(clip.get("id"))
                plan = plans.get(clip_id, {})
                clips.append({
                    "id": clip_id,
                    "title": "".join(clip.get("title", [])),
                    "hook": "".join(clip.get("hook", [])),
                    "duration": plan.get("duration"),
                    "virality": clip.get("virality", {}),
                    "qa": qa_by_id.get(clip_id, {}),
                    "video_url": f"/clip-media/{run_id}/{clip_id}.mp4",
                    "cover_url": f"/clip-media/{run_id}/{clip_id}-cover.jpg",
                    "subtitle_url": f"/clip-media/{run_id}/{clip_id}.srt",
                })
            self._write_result(run_id, {"clips": clips, "count": len(clips)})
            final_status = "completed" if result.get("status") == "completed_pending_human_review" else "needs_review"
            self._update(run_id, status=final_status, stage="completed", progress=100, result={"count": len(clips), "clips": clips})
        except Exception as exc:
            self._update(run_id, status="failed", stage="failed", progress=100, error={"message": str(exc)})
        finally:
            with self._lock:
                self._submitted.discard(run_id)

    def public(self, run_id: str) -> dict[str, Any]:
        run = self._read(run_id)
        pipeline = self._read_json(self._path(run_id) / "run.json", {})
        if pipeline.get("stages"):
            run["pipeline_stages"] = pipeline["stages"]
            if run.get("status") == "running":
                running = next((name for name, item in pipeline["stages"].items() if item.get("status") == "running"), None)
                if running:
                    run["stage"] = running
                    run["progress"] = {
                        "preflight": 8,
                        "select": 25,
                        "plan": 42,
                        "render": 72,
                        "qa": 92,
                    }.get(running, run.get("progress", 0))
        return run

    def list_runs(self) -> list[dict[str, Any]]:
        runs = []
        for path in self.root.glob("*/web-run.json"):
            try:
                runs.append(self.public(path.parent.name))
            except (KeyError, OSError, json.JSONDecodeError):
                continue
        return sorted(runs, key=lambda item: str(item.get("updated_at") or ""), reverse=True)

    def events(self, run_id: str) -> list[dict[str, Any]]:
        self._read(run_id)
        events = []
        path = self._path(run_id) / "events.jsonl"
        if path.is_file():
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return events

    def artifact(self, run_id: str, relative_path: str) -> Path:
        self._read(run_id)
        root = self._path(run_id).resolve()
        target = (root / relative_path).resolve()
        if root not in target.parents or not target.is_file():
            raise KeyError(relative_path)
        return target

