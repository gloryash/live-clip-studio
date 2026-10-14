from __future__ import annotations

import json
import math
from pathlib import Path

from ..ai_transcript_export import build_ai_transcript_document


def read_json(path: Path, default=None):
    if not path.exists() and default is not None:
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temp.replace(path)


def export_job(job_dir: Path) -> dict:
    tdir = job_dir / "transcript"
    result = build_ai_transcript_document(
        job=read_json(job_dir / "job.json"), media=read_json(job_dir / "media.json"),
        transcript=read_json(tdir / "speaker-turns.json"),
        saved_segments=read_json(tdir / "segments.json", {"segments": []})["segments"],
        raw=read_json(tdir / "raw.json", {"segments": []}),
        predictions=read_json(tdir / "speaker-predictions.json", {}),
        speakers=read_json(tdir / "manual-speakers.json", {"speakers": {}}).get("speakers", {}),
        annotations=read_json(tdir / "manual-speaker-labels.json", {}).get("annotations", {}),
        deleted_turn_ids=set(read_json(tdir / "deleted-turns.json", {}).get("deleted_turn_ids", [])),
    )
    validate_transcript(result)
    return result


def validate_transcript(doc: dict) -> dict:
    if doc.get("format") != "live-clip-studio.ai-transcript" or doc.get("version") != 1:
        raise ValueError("INPUT_FORMAT: expected ai-transcript v1")
    duration = doc.get("job", {}).get("duration_seconds")
    if not isinstance(duration, (int, float)) or not math.isfinite(duration) or duration <= 0:
        raise ValueError("INPUT_TIME: invalid source duration")
    segments = doc.get("segments")
    if not isinstance(segments, list) or not segments:
        raise ValueError("INPUT_EMPTY: no segments")
    ids = set()
    warnings = []
    previous_end = -1.0
    for row in segments:
        tid = row.get("id")
        if type(tid) is not int or tid <= 0:
            raise ValueError("INPUT_ID: positive integer required")
        if tid in ids:
            raise ValueError(f"INPUT_DUPLICATE_ID: {tid}")
        ids.add(tid)
        a, b = row.get("start"), row.get("end")
        if not all(type(v) in (int, float) and math.isfinite(v) for v in (a, b)) or not 0 <= a < b <= duration + .1:
            raise ValueError(f"INPUT_TIME: turn {tid}")
        if a < previous_end:
            raise ValueError(f"INPUT_OVERLAP_OR_ORDER: turn {tid}")
        previous_end = b
        if not isinstance(row.get("text"), str) or not row["text"].strip():
            raise ValueError(f"INPUT_TEXT: turn {tid}")
        if not isinstance(row.get("speaker"), dict) or not isinstance(row["speaker"].get("id"), str):
            raise ValueError(f"INPUT_SPEAKER: turn {tid}")
        if row.get("timing_quality") in ("segment_fallback", "mixed_with_segment_fallback") or not row.get("words"):
            warnings.append({"turn": tid, "code": "SEGMENT_TIMING_FALLBACK"})
        if row["speaker"]["id"] == "UNKNOWN":
            warnings.append({"turn": tid, "code": "UNKNOWN_SPEAKER"})
    return {"segments": len(segments), "duration_seconds": duration, "warnings": warnings}


def compact_rows(rows: list[dict]) -> str:
    return "\n".join(f"{r['id']}|{r['start']:.2f}-{r['end']:.2f}|{r['speaker']['id']}|{r['text']}" for r in rows)
