#!/usr/bin/env python3
import argparse
import hashlib
import json
import math
import re
import subprocess
import sys
import wave
from array import array
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from render_viral_clips import TEXT_FIXES, clip_duration, fix_text  # noqa: E402


FONT = Path("/System/Library/Fonts/STHeiti Medium.ttc")
SPEAKER_NAMES = {"S000": "Monica", "S001": "闫威律师", "UNKNOWN": "访谈现场"}
FILLER_PREFIX = re.compile(r"^(?:呃|嗯|然后|其实|我觉得|就是|对吧|那么|所以)+")
KEYWORDS = ("2000万", "8000万", "第一", "机会", "风险", "税", "用工", "数据", "25天", "一倍", "TikTok", "Kaspi")


def clean_caption(text):
    cleaned = fix_text(text).strip()
    cleaned = FILLER_PREFIX.sub("", cleaned).strip(" ，,。")
    return cleaned or fix_text(text).strip()


def dominant_speaker(turns, start, end):
    scores = {}
    for turn in turns:
        overlap = max(0.0, min(end, float(turn["end"])) - max(start, float(turn["start"])))
        if overlap:
            speaker = turn.get("speaker", "UNKNOWN")
            scores[speaker] = scores.get(speaker, 0.0) + overlap
    return max(scores, key=scores.get) if scores else "UNKNOWN"


def speaker_layout(speaker):
    return "left" if speaker == "S000" else "right" if speaker == "S001" else "dual"


def opposite_layout(layout):
    return "right" if layout == "left" else "left" if layout == "right" else "dual"


def plan_shots(clip, turns, chunk_seconds=5.0):
    shots = []
    output_offset = 0.0
    chunk_index = 0
    for segment_index, segment in enumerate(clip["segments"]):
        cursor = float(segment["start"])
        segment_end = float(segment["end"])
        first = True
        while cursor < segment_end - 0.01:
            end = min(segment_end, cursor + chunk_seconds)
            speaker = dominant_speaker(turns, cursor, end)
            main_layout = speaker_layout(speaker)
            layout = "dual" if first else main_layout
            duration = end - cursor
            if not first and chunk_index % 5 == 4 and main_layout != "dual" and duration > 1.2:
                reaction_end = cursor + 0.7
                shots.append(
                    {
                        "start": cursor,
                        "end": reaction_end,
                        "output_start": output_offset,
                        "output_end": output_offset + 0.7,
                        "layout": opposite_layout(main_layout),
                        "speaker": speaker,
                        "reaction": True,
                        "segment_index": segment_index,
                    }
                )
                output_offset += 0.7
                cursor = reaction_end
                duration = end - cursor
                layout = main_layout
            shots.append(
                {
                    "start": cursor,
                    "end": end,
                    "output_start": output_offset,
                    "output_end": output_offset + duration,
                    "layout": layout,
                    "speaker": speaker,
                    "reaction": False,
                    "segment_index": segment_index,
                }
            )
            output_offset += duration
            cursor = end
            first = False
            chunk_index += 1
    return shots


def remap_captions(clip, transcript, turns):
    captions = []
    offset = 0.0
    for source_range in clip["segments"]:
        rs = float(source_range["start"])
        re_ = float(source_range["end"])
        for item in transcript:
            start = max(rs, float(item["start"]))
            end = min(re_, float(item["end"]))
            if end <= start:
                continue
            captions.append(
                {
                    "start": round(offset + start - rs, 3),
                    "end": round(offset + end - rs, 3),
                    "text": clean_caption(item["text"]),
                    "speaker": dominant_speaker(turns, start, end),
                }
            )
        offset += re_ - rs
    return captions


def run(command):
    subprocess.run(command, cwd=ROOT, check=True)


def layout_filter(layout):
    background = (
        "split=2[bgsrc][fgsrc];"
        "[bgsrc]crop=720:588:0:464,scale=720:1512:force_original_aspect_ratio=increase,"
        "crop=720:1512,gblur=sigma=28,eq=brightness=-0.20:saturation=0.65[bg];"
    )
    if layout == "left":
        foreground = "[fgsrc]crop=360:588:0:464,scale=720:1176:flags=lanczos,eq=contrast=1.04:saturation=1.03[fg];[bg][fg]overlay=0:168"
    elif layout == "right":
        foreground = "[fgsrc]crop=360:520:360:464,scale=720:1040:flags=lanczos,eq=contrast=1.04:saturation=1.03[fg];[bg][fg]overlay=0:230"
    else:
        foreground = "[fgsrc]crop=720:588:0:464,scale=720:588:flags=lanczos,eq=contrast=1.04:saturation=1.03[fg];[bg][fg]overlay=0:462"
    return background + foreground + ",vignette=PI/7,noise=alls=1.5:allf=t+u,format=yuv420p"


def render_shots(source, output_dir, clip, shots):
    work = output_dir / "work" / clip["id"] / "shots"
    work.mkdir(parents=True, exist_ok=True)
    files = []
    for index, shot in enumerate(shots):
        path = work / f"shot-{index:03d}-{shot['layout']}.mp4"
        files.append(path)
        run(
            [
                "ffmpeg", "-loglevel", "error", "-y", "-ss", f"{shot['start']:.3f}", "-to", f"{shot['end']:.3f}",
                "-i", str(source), "-vf", layout_filter(shot["layout"]),
                "-map", "0:v:0", "-map", "0:a:0", "-c:v", "libx264", "-preset", "veryfast", "-crf", "19",
                "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-avoid_negative_ts", "make_zero", str(path),
            ]
        )
    concat = work / "concat.txt"
    concat.write_text("".join(f"file '{p.resolve()}'\n" for p in files), encoding="utf-8")
    joined = work.parent / "joined.mp4"
    run(["ffmpeg", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(concat), "-c", "copy", str(joined)])
    return joined


def wrap(draw, text, font, max_width):
    lines, current = [], ""
    for char in text:
        candidate = current + char
        if current and draw.textbbox((0, 0), candidate, font=font)[2] > max_width:
            lines.append(current)
            current = char
        else:
            current = candidate
    if current:
        lines.append(current)
    if len(lines) > 2:
        lines = [lines[0], "".join(lines[1:])]
    return "\n".join(lines)


def keyword(text):
    for item in KEYWORDS:
        if item in text:
            return item
    match = re.search(r"\d+(?:万|%|天|年)?", text)
    return match.group(0) if match else None


def overlay_frame(clip, captions, moment):
    image = Image.new("RGBA", (720, 1512), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    brand_font = ImageFont.truetype(str(FONT), 25)
    hook_font = ImageFont.truetype(str(FONT), 47)
    subtitle_font = ImageFont.truetype(str(FONT), 42)
    tag_font = ImageFont.truetype(str(FONT), 25)
    draw.rounded_rectangle((24, 26, 300, 70), radius=12, fill=(8, 12, 18, 145))
    draw.text((39, 49), "FIELD NOTES · 中亚现场", font=brand_font, fill=(235, 239, 244, 255), anchor="lm")
    if moment < 2.2:
        text, color = clip["hook"], (62, 224, 214, 255)
    elif moment < 5.2:
        text, color = clip["promise"], (255, 207, 92, 255)
    else:
        text = None
    if text:
        wrapped = wrap(draw, text, hook_font, 620)
        box = draw.multiline_textbbox((0, 0), wrapped, font=hook_font, spacing=8, align="center")
        w, h = box[2] - box[0], box[3] - box[1]
        draw.rounded_rectangle((360 - w / 2 - 22, 115, 360 + w / 2 + 22, 115 + h + 36), radius=18, fill=(7, 10, 15, 190))
        draw.multiline_text((360, 133 + h / 2), wrapped, font=hook_font, fill=color, anchor="mm", spacing=8, align="center")
    active = [c for c in captions if c["start"] <= moment < c["end"] and c["text"]]
    if active:
        caption = active[-1]
        wrapped = wrap(draw, caption["text"], subtitle_font, 600)
        box = draw.multiline_textbbox((0, 0), wrapped, font=subtitle_font, spacing=9, align="center")
        w, h = box[2] - box[0], box[3] - box[1]
        left, top = 360 - w / 2 - 28, 1268 - h / 2 - 24
        right, bottom = 360 + w / 2 + 28, 1268 + h / 2 + 24
        draw.rounded_rectangle((left, top, right, bottom), radius=18, fill=(5, 8, 12, 190), outline=(255, 255, 255, 35), width=1)
        accent = (62, 224, 214, 255) if caption["speaker"] == "S000" else (255, 180, 72, 255)
        draw.rounded_rectangle((left, top, left + 6, bottom), radius=3, fill=accent)
        draw.multiline_text((360, 1268), wrapped, font=subtitle_font, fill=(248, 248, 246, 255), anchor="mm", spacing=9, align="center")
        name = SPEAKER_NAMES.get(caption["speaker"], "访谈现场")
        draw.rounded_rectangle((left + 16, top - 39, left + 16 + 22 * len(name) + 25, top - 6), radius=9, fill=(5, 8, 12, 205))
        draw.text((left + 28, top - 22), name, font=tag_font, fill=accent, anchor="lm")
        key = keyword(caption["text"])
        if key:
            kw = f"KEY  {key}"
            kw_box = draw.textbbox((0, 0), kw, font=tag_font)
            kw_w = kw_box[2] - kw_box[0]
            draw.rounded_rectangle((right - kw_w - 32, top - 39, right, top - 6), radius=9, fill=(5, 8, 12, 205))
            draw.text((right - 16, top - 22), kw, font=tag_font, fill=(255, 207, 92, 255), anchor="rm")
    return image


def make_overlay(output_dir, clip, captions):
    work = output_dir / "work" / clip["id"] / "overlay"
    work.mkdir(parents=True, exist_ok=True)
    duration = clip_duration(clip)
    boundaries = {0.0, 2.2, 5.2, duration}
    for caption in captions:
        boundaries.update((max(0.0, caption["start"]), min(duration, caption["end"])))
    ordered = sorted(boundaries)
    lines, last = [], None
    for index, (start, end) in enumerate(zip(ordered, ordered[1:])):
        if end - start < 0.01:
            continue
        path = work / f"frame-{index:04d}.png"
        overlay_frame(clip, captions, (start + end) / 2).save(path, optimize=True)
        lines.extend((f"file '{path.resolve()}'\n", f"duration {end - start:.3f}\n"))
        last = path
    lines.append(f"file '{last.resolve()}'\n")
    concat = work / "concat.txt"
    concat.write_text("".join(lines), encoding="utf-8")
    output = work / "overlay.mov"
    run(["ffmpeg", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(concat), "-vf", "format=rgba", "-c:v", "qtrle", str(output)])
    return output


def make_score(path, duration, mood, cue_times):
    sample_rate = 48000
    base = {"01-central-asia-window": 70.0, "02-ecommerce-shovels": 82.0, "03-compliance-traps": 52.0}.get(mood, 65.0)
    total = int(duration * sample_rate)
    data = array("h")
    for index in range(total):
        t = index / sample_rate
        sample = 145 * math.sin(2 * math.pi * base * t) * (0.75 + 0.25 * math.sin(2 * math.pi * 0.09 * t))
        sample += 70 * math.sin(2 * math.pi * base * 2.01 * t)
        for cue in cue_times:
            delta = t - cue
            if 0 <= delta < 0.18:
                sample += 1150 * (1 - delta / 0.18) * math.sin(2 * math.pi * (95 - 35 * delta / 0.18) * delta)
        value = max(-32767, min(32767, int(sample)))
        data.extend((value, value))
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(data.tobytes())


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def render_clip(source, output_dir, clip, shots, captions):
    joined = render_shots(source, output_dir, clip, shots)
    overlay = make_overlay(output_dir, clip, captions)
    score = output_dir / "work" / clip["id"] / "score.wav"
    cues = [0.0, 2.2, 5.2]
    offset = 0.0
    for segment in clip["segments"][:-1]:
        offset += float(segment["end"]) - float(segment["start"])
        cues.append(offset)
    make_score(score, clip_duration(clip) + 0.5, clip["id"], cues)
    output = output_dir / f"{clip['id']}-v2.mp4"
    run(
        [
            "ffmpeg", "-loglevel", "error", "-y", "-i", str(joined), "-i", str(overlay), "-i", str(score),
            "-filter_complex",
            "[0:v][1:v]overlay=0:0:shortest=1[v];[0:a]volume=1.0[a0];[2:a]volume=0.72[a1];[a0][a1]amix=inputs=2:duration=first:normalize=0,loudnorm=I=-16:LRA=9:TP=-1.5[a]",
            "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-t", f"{clip_duration(clip):.3f}",
            "-movflags", "+faststart", str(output),
        ]
    )
    return output


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--render", action="store_true")
    args = parser.parse_args()
    manifest = json.loads((ROOT / args.manifest).read_text(encoding="utf-8"))
    transcript_payload = json.loads((ROOT / manifest["transcript"]).read_text(encoding="utf-8"))
    transcript = transcript_payload.get("segments", transcript_payload)
    turns_payload = json.loads((ROOT / "data/02a0cf90-fd57-4117-b207-df0d5b0acb6e/transcript/speaker-turns.json").read_text(encoding="utf-8"))
    turns = turns_payload["turns"]
    output_dir = ROOT / "data/02a0cf90-fd57-4117-b207-df0d5b0acb6e/exports-v2"
    output_dir.mkdir(parents=True, exist_ok=True)
    summary = []
    for clip in manifest["clips"]:
        shots = plan_shots(clip, turns)
        captions = remap_captions(clip, transcript, turns)
        shots_path = output_dir / f"{clip['id']}-shots.json"
        shots_path.write_text(json.dumps(shots, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        item = {"id": clip["id"], "duration": clip_duration(clip), "shots": len(shots)}
        if args.render:
            output = render_clip(ROOT / manifest["source"], output_dir, clip, shots, captions)
            item.update({"output": str(output), "sha256": sha256(output)})
        summary.append(item)
    (output_dir / "render-summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
