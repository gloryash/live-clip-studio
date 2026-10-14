from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any


class InvalidVideoError(ValueError):
    pass


def _audio_duration(path: Path) -> float:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise RuntimeError("ffprobe is unavailable")
    result = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
    )
    try:
        return float(result.stdout.strip())
    except ValueError as exc:
        raise RuntimeError(result.stderr.strip() or "cannot read audio duration") from exc


def probe_video(path: Path) -> dict[str, Any]:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise InvalidVideoError("ffprobe is unavailable")
    result = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration,size:stream=codec_type,codec_name,width,height,avg_frame_rate",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise InvalidVideoError(result.stderr.strip() or "ffprobe rejected the file")
    try:
        document = json.loads(result.stdout)
        duration = float(document.get("format", {}).get("duration", 0))
        has_video = any(stream.get("codec_type") == "video" for stream in document.get("streams", []))
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise InvalidVideoError("invalid ffprobe response") from exc
    if not has_video or duration <= 0:
        raise InvalidVideoError("file has no playable video stream")
    document["duration_seconds"] = round(duration, 3)
    return document


def extract_audio(video_path: Path, audio_path: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg is unavailable")
    audio_path.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(video_path),
            "-vn",
            "-af",
            "aresample=async=1000:first_pts=0",
            "-ac",
            "1",
            "-ar",
            "16000",
            str(audio_path),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "audio extraction failed")
    source_duration = _audio_duration(video_path)
    extracted_duration = _audio_duration(audio_path)
    difference = abs(source_duration - extracted_duration)
    if difference > 0.25:
        audio_path.unlink(missing_ok=True)
        raise RuntimeError(
            "audio timeline mismatch after extraction: "
            f"source={source_duration:.3f}s, extracted={extracted_duration:.3f}s, difference={difference:.3f}s"
        )
