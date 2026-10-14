from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "editing/viral_clips.json"
FONT_NAME = "Arial Unicode MS"
FONT_PATH = "/Library/Fonts/Arial Unicode.ttf"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def ass_time(seconds: float) -> str:
    centiseconds = max(0, round(seconds * 100))
    hours, remainder = divmod(centiseconds, 360000)
    minutes, remainder = divmod(remainder, 6000)
    secs, cs = divmod(remainder, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{cs:02d}"


def srt_time(seconds: float) -> str:
    milliseconds = max(0, round(seconds * 1000))
    hours, remainder = divmod(milliseconds, 3600000)
    minutes, remainder = divmod(remainder, 60000)
    secs, ms = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def escape_ass(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")


def wrap_text(text: str, width: int = 15) -> str:
    clean = "".join(text.strip().split())
    if len(clean) <= width:
        return clean
    split_at = min(width, max(8, len(clean) // 2))
    return clean[:split_at] + r"\N" + clean[split_at:]


def source_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def selected_turns(
    turns: list[dict[str, Any]],
    clip: dict[str, Any],
    annotations: dict[str, str],
    speakers: dict[str, str],
    deleted: set[int],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    offset = 0.0
    for segment in clip["segments"]:
        start = float(segment["start"])
        end = float(segment["end"])
        for turn in turns:
            turn_id = int(turn["id"])
            if turn_id in deleted:
                continue
            turn_start = float(turn["start"])
            turn_end = float(turn["end"])
            if turn_end <= start or turn_start >= end:
                continue
            local_start = offset + max(turn_start, start) - start
            local_end = offset + min(turn_end, end) - start
            speaker_id = annotations.get(str(turn_id), str(turn.get("speaker") or ""))
            output.append(
                {
                    "start": local_start,
                    "end": local_end,
                    "speaker": speakers.get(speaker_id, str(turn.get("speaker_label") or "")),
                    "text": str(turn.get("text") or "").strip(),
                }
            )
        offset += end - start
    return output


def write_subtitles(output_dir: Path, clip: dict[str, Any], turns: list[dict[str, Any]]) -> Path:
    srt_path = output_dir / f"{clip['id']}.srt"
    srt_lines: list[str] = []
    for index, turn in enumerate(turns, start=1):
        srt_lines.extend(
            [
                str(index),
                f"{srt_time(turn['start'])} --> {srt_time(turn['end'])}",
                f"{turn['speaker']}：{turn['text']}",
                "",
            ]
        )
    srt_path.write_text("\n".join(srt_lines), encoding="utf-8")
    return srt_path


def render_overlay(output_dir: Path, clip: dict[str, Any], turns: list[dict[str, Any]], duration: float) -> Path:
    frame_dir = output_dir / f"{clip['id']}-overlay-frames"
    frame_dir.mkdir(parents=True, exist_ok=True)
    events = [
        {"start": 0.0, "end": min(5.2, duration), "kind": "title", "text": clip["title"]},
        {"start": 0.0, "end": min(2.8, duration), "kind": "hook", "text": clip["hook"]},
    ]
    keywords = clip.get("keywords", [])
    for turn in turns:
        events.append(
            {
                "start": turn["start"],
                "end": turn["end"],
                "kind": "keyword" if any(k.lower() in turn["text"].lower() for k in keywords) else "subtitle",
                "text": wrap_text(turn["text"]),
            }
        )
    boundaries = sorted({0.0, duration, *(event["start"] for event in events), *(event["end"] for event in events)})
    concat_lines: list[str] = []
    for index, (start, end) in enumerate(zip(boundaries, boundaries[1:])):
        if end - start < 0.01:
            continue
        midpoint = (start + end) / 2
        active = [event for event in events if event["start"] <= midpoint < event["end"]]
        frame_path = frame_dir / f"frame-{index:04d}.png"
        command = ["magick", "-size", "912x1920", "xc:none", "-font", FONT_PATH]
        for event in active:
            if event["kind"] == "title":
                command += [
                    "-fill", "#00000099", "-stroke", "none", "-draw", "roundrectangle 42,72 870,232 18,18",
                    "-fill", "white", "-stroke", "#101010", "-strokewidth", "3", "-gravity", "north",
                    "-pointsize", "54", "-annotate", "+0+105", event["text"],
                ]
            elif event["kind"] == "hook":
                command += [
                    "-fill", "#000000B0", "-stroke", "none", "-draw", "roundrectangle 35,1030 877,1235 22,22",
                    "-fill", "#FFD700", "-stroke", "#101010", "-strokewidth", "4", "-gravity", "north",
                    "-pointsize", "68", "-annotate", "+0+1072", event["text"],
                ]
            else:
                color = "#FFD700" if event["kind"] == "keyword" else "white"
                command += [
                    "-fill", "#0000008F", "-stroke", "none", "-draw", "roundrectangle 38,1390 874,1738 18,18",
                    "-fill", color, "-stroke", "#101010", "-strokewidth", "4", "-gravity", "south",
                    "-pointsize", "64", "-interline-spacing", "12", "-annotate", "+0+245", event["text"].replace(r"\N", "\n"),
                ]
        command.append(str(frame_path))
        subprocess.run(command, check=True)
        concat_lines.append(f"file '{frame_path.name}'")
        concat_lines.append(f"duration {end - start:.6f}")
    if concat_lines:
        concat_lines.append(concat_lines[-2])
    concat_path = frame_dir / "concat.txt"
    concat_path.write_text("\n".join(concat_lines) + "\n", encoding="utf-8")
    overlay_path = output_dir / f"{clip['id']}-overlay.mov"
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "warning", "-f", "concat", "-safe", "0",
            "-i", str(concat_path), "-vsync", "vfr", "-c:v", "qtrle", "-pix_fmt", "argb", str(overlay_path),
        ],
        check=True,
        cwd=frame_dir,
    )
    return overlay_path


def filter_graph(clip: dict[str, Any]) -> str:
    filters: list[str] = []
    concat_inputs: list[str] = []
    for index, segment in enumerate(clip["segments"]):
        start = float(segment["start"])
        end = float(segment["end"])
        filters.append(
            f"[0:v]trim=start={start}:end={end},setpts=PTS-STARTPTS[v{index}]"
        )
        filters.append(
            f"[0:a]atrim=start={start}:end={end},asetpts=PTS-STARTPTS[a{index}]"
        )
        concat_inputs.append(f"[v{index}][a{index}]")
    count = len(clip["segments"])
    filters.append("".join(concat_inputs) + f"concat=n={count}:v=1:a=1[basev][basea]")
    filters.append("[basev][1:v]overlay=shortest=1[outv]")
    filters.append("[basea]loudnorm=I=-16:TP=-1.5:LRA=11[outa]")
    return ";\n".join(filters)


def probe(path: Path) -> dict[str, Any]:
    command = [
        "ffprobe", "-v", "error", "-show_entries", "format=duration,size",
        "-show_entries", "stream=codec_type,codec_name,width,height",
        "-of", "json", str(path),
    ]
    return json.loads(subprocess.run(command, check=True, capture_output=True, text=True).stdout)


def main() -> None:
    config = read_json(CONFIG_PATH)
    source = ROOT / config["source"]
    transcript_doc = read_json(ROOT / config["transcript"])
    speaker_doc = read_json(ROOT / config["speakers"])
    annotation_doc = read_json(ROOT / config["annotations"])
    deleted_doc = read_json(ROOT / config["deleted_turns"])
    output_dir = ROOT / config["output_dir"]
    output_dir.mkdir(parents=True, exist_ok=True)
    turns = transcript_doc["turns"]
    speakers = speaker_doc["speakers"]
    annotations = annotation_doc["annotations"]
    deleted = set(deleted_doc["deleted_turn_ids"])
    original_hash = source_hash(source)
    report: dict[str, Any] = {"source": str(source), "source_sha256": original_hash, "clips": []}

    for clip in config["clips"]:
        timeline = selected_turns(turns, clip, annotations, speakers, deleted)
        srt_path = write_subtitles(output_dir, clip, timeline)
        expected_duration = sum(float(segment["end"]) - float(segment["start"]) for segment in clip["segments"])
        overlay_path = render_overlay(output_dir, clip, timeline, expected_duration)
        graph_path = output_dir / f"{clip['id']}.filter.txt"
        graph_path.write_text(filter_graph(clip), encoding="utf-8")
        output_path = output_dir / f"{clip['id']}.mp4"
        command = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "warning", "-i", str(source), "-i", str(overlay_path),
            "-filter_complex_script", str(graph_path), "-map", "[outv]", "-map", "[outa]",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(output_path),
        ]
        print(f"Rendering {clip['id']}...")
        subprocess.run(command, check=True)
        metadata = probe(output_path)
        report["clips"].append(
            {
                "id": clip["id"],
                "title": clip["title"],
                "output": str(output_path),
                "srt": str(srt_path),
                "segments": clip["segments"],
                "probe": metadata,
            }
        )

    final_hash = source_hash(source)
    report["source_sha256_after"] = final_hash
    report["source_unchanged"] = final_hash == original_hash
    (output_dir / "render-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
