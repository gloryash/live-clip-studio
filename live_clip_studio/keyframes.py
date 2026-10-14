from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Callable

from claude_real_video.core import dedup_frames, extract_frames


def _timestamp_label(seconds: float) -> str:
    total_ms = max(0, round(seconds * 1000))
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"


def generate_keyframes(
    video_path: Path,
    output_dir: Path,
    *,
    extractor: Callable[..., tuple[int, list[float]]] = extract_frames,
    deduplicator: Callable[..., tuple[int, list[dict[str, Any]]]] = dedup_frames,
) -> dict[str, Any]:
    keyframes_dir = Path(output_dir) / "keyframes"
    if keyframes_dir.exists():
        shutil.rmtree(keyframes_dir)
    keyframes_dir.mkdir(parents=True)
    candidate_count, times = extractor(
        str(video_path),
        str(keyframes_dir),
        scene=0.30,
        fps_floor=1.0,
    )
    frame_count, records = deduplicator(
        str(keyframes_dir),
        threshold=8,
        window=4,
        max_frames=0,
        times=times,
    )
    kept = [record for record in records if record.get("kept")]
    kept.sort(key=lambda record: str(record.get("name") or ""))
    frames: list[dict[str, Any]] = []
    for index, record in enumerate(kept, start=1):
        timestamp = float(record.get("t") or 0.0)
        frames.append(
            {
                "id": index,
                "image_url": f"keyframes/{record['name']}",
                "timestamp": round(timestamp, 3),
                "timestamp_label": _timestamp_label(timestamp),
                "dist": record.get("dist"),
                "settled": record.get("settled"),
                "via": record.get("via") or "scene",
                "capped": bool(record.get("capped", False)),
            }
        )
    document = {
        "status": "ready",
        "candidate_count": candidate_count,
        "frame_count": frame_count,
        "frames": frames,
    }
    (keyframes_dir / "frames.json").write_text(
        json.dumps(document, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return document
