from __future__ import annotations

import argparse
import bisect
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def probe_json(arguments: list[str]) -> dict[str, Any]:
    result = subprocess.run(arguments, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "ffprobe failed")
    return json.loads(result.stdout)


def media_timeline(source: Path) -> tuple[list[float], list[float], float, float]:
    stream_document = probe_json(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=sample_rate,duration",
            "-of",
            "json",
            str(source),
        ]
    )
    stream = stream_document["streams"][0]
    sample_rate = float(stream["sample_rate"])
    media_duration = float(stream["duration"])
    frame_document = probe_json(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_frames",
            "-show_entries",
            "frame=best_effort_timestamp_time,nb_samples",
            "-of",
            "json",
            str(source),
        ]
    )

    decoded_times: list[float] = []
    media_times: list[float] = []
    decoded_cursor = 0.0
    for frame in frame_document.get("frames", []):
        timestamp = frame.get("best_effort_timestamp_time")
        samples = frame.get("nb_samples")
        if timestamp is None or samples is None:
            continue
        decoded_times.append(decoded_cursor)
        media_times.append(float(timestamp))
        decoded_cursor += int(samples) / sample_rate
    if len(decoded_times) < 2:
        raise RuntimeError("source audio has no usable timestamped frames")
    decoded_times.append(decoded_cursor)
    media_times.append(media_duration)
    return decoded_times, media_times, decoded_cursor, media_duration


def align_time(value: float, decoded: list[float], media: list[float]) -> float:
    value = max(0.0, min(float(value), decoded[-1]))
    index = max(0, min(len(decoded) - 2, bisect.bisect_right(decoded, value) - 1))
    width = decoded[index + 1] - decoded[index]
    ratio = 0.0 if width <= 0 else (value - decoded[index]) / width
    return media[index] + ratio * (media[index + 1] - media[index])


def aligned_document(document: dict[str, Any], key: str, decoded: list[float], media: list[float]) -> dict[str, Any]:
    updated = json.loads(json.dumps(document, ensure_ascii=False))
    for item in updated.get(key, []):
        if not isinstance(item, dict):
            continue
        item["start"] = round(align_time(float(item["start"]), decoded, media), 3)
        item["end"] = round(align_time(float(item["end"]), decoded, media), 3)
    return updated


def atomic_write_json(path: Path, document: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def realign(job_dir: Path, aligned_audio: Path) -> dict[str, Any]:
    transcript_dir = job_dir / "transcript"
    source = job_dir / "source.mp4"
    segments_path = transcript_dir / "segments.json"
    turns_path = transcript_dir / "speaker-turns.json"
    audio_path = transcript_dir / "audio-16k-mono.wav"
    backups = {
        segments_path: transcript_dir / "segments.pre-timeline-fix.json",
        turns_path: transcript_dir / "speaker-turns.pre-timeline-fix.json",
        audio_path: transcript_dir / "audio-16k-mono.pre-timeline-fix.wav",
    }
    required = [source, segments_path, turns_path, audio_path, aligned_audio]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise RuntimeError(f"missing required files: {missing}")
    existing_backups = [str(path) for path in backups.values() if path.exists()]
    if existing_backups:
        raise RuntimeError(f"timeline migration was already prepared: {existing_backups}")

    decoded, media, decoded_duration, media_duration = media_timeline(source)
    segments = json.loads(segments_path.read_text(encoding="utf-8"))
    turns = json.loads(turns_path.read_text(encoding="utf-8"))
    aligned_segments = aligned_document(segments, "segments", decoded, media)
    aligned_turns = aligned_document(turns, "turns", decoded, media)

    for original, backup in backups.items():
        shutil.copy2(original, backup)
    atomic_write_json(segments_path, aligned_segments)
    atomic_write_json(turns_path, aligned_turns)
    shutil.move(str(aligned_audio), str(audio_path))

    audit = {
        "version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "method": "ffprobe decoded-sample cursor to source audio PTS interpolation",
        "decoded_audio_duration_seconds": round(decoded_duration, 6),
        "source_audio_duration_seconds": round(media_duration, 6),
        "maximum_correction_seconds": round(media_duration - decoded_duration, 6),
        "segment_count": len(aligned_segments.get("segments", [])),
        "turn_count": len(aligned_turns.get("turns", [])),
        "raw_whisper_result_modified": False,
        "manual_speaker_labels_modified": False,
        "deleted_turns_modified": False,
    }
    atomic_write_json(transcript_dir / "timeline-correction.json", audit)
    return audit


def main() -> int:
    parser = argparse.ArgumentParser(description="Realign a legacy transcript from decoded-sample time to source media PTS.")
    parser.add_argument("job_dir", type=Path)
    parser.add_argument("--aligned-audio", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(realign(args.job_dir, args.aligned_audio), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
