from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from render_viral_clips import (
    FONT_PATH,
    probe,
    read_json,
    selected_turns,
    source_hash,
    srt_time,
    wrap_text,
)


ROOT = Path(__file__).resolve().parents[1]
V2_CONFIG = ROOT / "editing/viral_clips_v2.json"


def write_srt(path: Path, turns: list[dict[str, Any]]) -> None:
    lines: list[str] = []
    for index, turn in enumerate(turns, start=1):
        lines.extend(
            [
                str(index),
                f"{srt_time(turn['start'])} --> {srt_time(turn['end'])}",
                f"{turn['speaker']}：{turn['text']}",
                "",
            ]
        )
    path.write_text("\n".join(lines), encoding="utf-8")


def shot_schedule(turns: list[dict[str, Any]], duration: float, profile: str) -> list[dict[str, Any]]:
    modes = ["wide", "left", "wide", "reaction"] if profile == "duo" else ["wide", "medium", "close", "wide"]
    boundaries = sorted({float(turn["end"]) for turn in turns if 0 < float(turn["end"]) < duration})
    shots: list[dict[str, Any]] = []
    cursor = 0.0
    mode_index = 0
    while cursor < duration - 0.02:
        mode = modes[mode_index % len(modes)]
        if mode == "reaction":
            end = min(duration, cursor + 1.35)
        else:
            candidates = [value for value in boundaries if cursor + 6.2 <= value <= cursor + 9.4]
            end = candidates[0] if candidates else min(duration, cursor + 7.6)
        if duration - end < 1.0:
            end = duration
        shots.append({"start": round(cursor, 3), "end": round(end, 3), "mode": mode})
        cursor = end
        mode_index += 1
    return shots


def render_graph(clip: dict[str, Any], shots: list[dict[str, Any]], duration: float, profile: str) -> str:
    filters: list[str] = []
    concat_inputs: list[str] = []
    for index, segment in enumerate(clip["segments"]):
        start = float(segment["start"])
        end = float(segment["end"])
        filters.append(f"[0:v]trim=start={start}:end={end},setpts=PTS-STARTPTS[srcv{index}]")
        filters.append(f"[0:a]atrim=start={start}:end={end},asetpts=PTS-STARTPTS[srca{index}]")
        concat_inputs.append(f"[srcv{index}][srca{index}]")
    filters.append("".join(concat_inputs) + f"concat=n={len(clip['segments'])}:v=1:a=1[rawv][rawa]")

    split_outputs = "".join(f"[sv{index}]" for index in range(len(shots)))
    filters.append(f"[rawv]split={len(shots)}{split_outputs}")
    shot_outputs: list[str] = []
    for index, shot in enumerate(shots):
        start = shot["start"]
        end = shot["end"]
        mode = shot["mode"]
        filters.append(f"[sv{index}]trim=start={start}:end={end},setpts=PTS-STARTPTS[st{index}]")
        if profile == "duo" and mode == "wide":
            filters.append(f"[st{index}]split=2[bg{index}][fg{index}]")
            filters.append(f"[bg{index}]crop=912:780:0:570,scale=912:1920,boxblur=24:2[blur{index}]")
            filters.append(f"[fg{index}]crop=912:780:0:570[clear{index}]")
            filters.append(f"[blur{index}][clear{index}]overlay=0:570[shot{index}]")
        elif profile == "duo" and mode == "left":
            filters.append(f"[st{index}]crop=456:960:0:480,scale=912:1920[shot{index}]")
        elif profile == "duo" and mode == "reaction":
            filters.append(f"[st{index}]crop=456:960:456:480,scale=912:1920[shot{index}]")
        elif mode == "medium":
            filters.append(f"[st{index}]crop=840:1768:36:76,scale=912:1920[shot{index}]")
        elif mode == "close":
            filters.append(f"[st{index}]crop=780:1640:66:140,scale=912:1920[shot{index}]")
        else:
            filters.append(f"[st{index}]null[shot{index}]")
        shot_outputs.append(f"[shot{index}]")
    filters.append("".join(shot_outputs) + f"concat=n={len(shots)}:v=1:a=0[styledv]")
    filters.append("[styledv][1:v]overlay=shortest=1[outv]")
    filters.append(f"anoisesrc=d={duration:.3f}:c=pink:r=48000,lowpass=f=260,volume=0.006[bed]")
    filters.append("sine=frequency=55:duration=0.42:sample_rate=48000,afade=t=out:st=0.04:d=0.38,volume=0.035[hit]")
    filters.append("[rawa]aresample=48000,loudnorm=I=-16:TP=-1.5:LRA=11[voice]")
    filters.append("[voice][bed][hit]amix=inputs=3:duration=first:dropout_transition=0:normalize=0,alimiter=limit=0.92[outa]")
    return ";\n".join(filters)


def render_overlay(
    output_dir: Path,
    clip: dict[str, Any],
    v2: dict[str, Any],
    turns: list[dict[str, Any]],
    duration: float,
) -> Path:
    frame_dir = output_dir / f"{clip['id']}-overlay-frames"
    frame_dir.mkdir(parents=True, exist_ok=True)
    events: list[dict[str, Any]] = [
        {"start": 0.0, "end": min(3.0, duration), "kind": "title", "text": clip["title"]},
        {"start": 0.12, "end": min(2.65, duration), "kind": "hook", "text": clip["hook"]},
    ]
    gold_lines = set(v2.get("subtitle_gold", []))
    for turn in turns:
        events.append(
            {
                "start": turn["start"],
                "end": turn["end"],
                "kind": "gold" if turn["text"] in gold_lines else "subtitle",
                "text": wrap_text(turn["text"], 14),
            }
        )
    for card in v2.get("cards", []):
        events.append({**card, "kind": "card"})

    boundaries = sorted({0.0, duration, *(e["start"] for e in events), *(e["end"] for e in events)})
    concat_lines: list[str] = []
    for index, (start, end) in enumerate(zip(boundaries, boundaries[1:])):
        if end - start < 0.01:
            continue
        midpoint = (start + end) / 2
        active = [event for event in events if event["start"] <= midpoint < event["end"]]
        if any(event["kind"] == "hook" for event in active):
            active = [event for event in active if event["kind"] in {"title", "hook"}]
        frame_path = frame_dir / f"frame-{index:04d}.png"
        command = ["magick", "-size", "912x1920", "xc:none", "-font", FONT_PATH]
        for event in active:
            text = event["text"].replace(r"\N", "\n")
            if event["kind"] == "title":
                command += [
                    "-fill", "#E2B54A", "-stroke", "none", "-draw", "roundrectangle 56,86 68,190 5,5",
                    "-fill", "white", "-stroke", "#000000B0", "-strokewidth", "1", "-gravity", "northwest",
                    "-pointsize", "42", "-annotate", "+86+105", event["text"],
                ]
            elif event["kind"] == "hook":
                command += [
                    "-fill", "#000000B0", "-stroke", "none", "-gravity", "north",
                    "-pointsize", "62", "-annotate", "+3+1373", event["text"],
                    "-fill", "#F1C75B", "-stroke", "#000000B8", "-strokewidth", "2", "-gravity", "north",
                    "-pointsize", "62", "-annotate", "+0+1370", event["text"],
                ]
            elif event["kind"] == "card":
                command += [
                    "-fill", "#000000B8", "-stroke", "#E2B54A", "-strokewidth", "2", "-draw", "roundrectangle 150,1140 762,1325 24,24",
                    "-fill", "#F1C75B", "-stroke", "none", "-gravity", "north",
                    "-pointsize", "70", "-annotate", "+0+1185", event["text"],
                ]
            else:
                color = "#F1C75B" if event["kind"] == "gold" else "white"
                command += [
                    "-fill", "#000000B0", "-stroke", "none", "-gravity", "south",
                    "-pointsize", "62", "-interline-spacing", "10", "-annotate", "+3+212", text,
                    "-fill", color, "-stroke", "#000000B8", "-strokewidth", "2", "-gravity", "south",
                    "-pointsize", "62", "-interline-spacing", "10", "-annotate", "+0+215", text,
                ]
        command.append(str(frame_path))
        subprocess.run(command, check=True)
        concat_lines.extend([f"file '{frame_path.name}'", f"duration {end - start:.6f}"])
    concat_lines.append(concat_lines[-2])
    concat_path = frame_dir / "concat.txt"
    concat_path.write_text("\n".join(concat_lines) + "\n", encoding="utf-8")
    overlay_path = output_dir / f"{clip['id']}-overlay.mov"
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "warning", "-f", "concat", "-safe", "0",
            "-i", str(concat_path), "-fps_mode", "vfr", "-c:v", "qtrle", "-pix_fmt", "argb", str(overlay_path),
        ],
        check=True,
        cwd=frame_dir,
    )
    return overlay_path


def main() -> None:
    v2_config = read_json(V2_CONFIG)
    base = read_json(ROOT / v2_config["base_config"])
    source = ROOT / base["source"]
    transcript = read_json(ROOT / base["transcript"])["turns"]
    speakers = read_json(ROOT / base["speakers"])["speakers"]
    annotations = read_json(ROOT / base["annotations"])["annotations"]
    deleted = set(read_json(ROOT / base["deleted_turns"])["deleted_turn_ids"])
    output_dir = ROOT / v2_config["output_dir"]
    output_dir.mkdir(parents=True, exist_ok=True)
    original_hash = source_hash(source)
    report: dict[str, Any] = {"source_sha256": original_hash, "clips": []}

    for clip in base["clips"]:
        v2 = v2_config["clips"][clip["id"]]
        timeline = selected_turns(transcript, clip, annotations, speakers, deleted)
        duration = sum(float(s["end"]) - float(s["start"]) for s in clip["segments"])
        shots = shot_schedule(timeline, duration, v2["shot_profile"])
        srt_path = output_dir / f"{clip['id']}.srt"
        write_srt(srt_path, timeline)
        overlay_path = render_overlay(output_dir, clip, v2, timeline, duration)
        graph_path = output_dir / f"{clip['id']}.filter.txt"
        graph_path.write_text(render_graph(clip, shots, duration, v2["shot_profile"]), encoding="utf-8")
        output_path = output_dir / f"{clip['id']}.mp4"
        command = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "warning", "-i", str(source), "-i", str(overlay_path),
            "-filter_complex_script", str(graph_path), "-map", "[outv]", "-map", "[outa]",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "19", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-movflags", "+faststart", str(output_path),
        ]
        print(f"Rendering interview V2: {clip['id']}...")
        subprocess.run(command, check=True)
        report["clips"].append(
            {
                "id": clip["id"],
                "output": str(output_path),
                "shots": shots,
                "max_shot_duration": max(shot["end"] - shot["start"] for shot in shots),
                "probe": probe(output_path),
            }
        )

    report["source_sha256_after"] = source_hash(source)
    report["source_unchanged"] = report["source_sha256_after"] == original_hash
    (output_dir / "render-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
