#!/usr/bin/env python3
import argparse
import hashlib
import json
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
FONT_PATH = Path("/System/Library/Fonts/STHeiti Medium.ttc")
TEXT_FIXES = {
    "中級物鐵路": "中吉乌铁路",
    "中级物铁路": "中吉乌铁路",
    "哈拉克斯坦": "哈萨克斯坦",
    "哈斯坦": "哈萨克斯坦",
    "哈特": "哈萨克斯坦",
    "乌兹比特斯坦": "乌兹别克斯坦",
    "乌兹北克斯坦": "乌兹别克斯坦",
    "乌兹比克斯坦": "乌兹别克斯坦",
    "比阿迪": "比亚迪",
    "二人码": "二维码",
    "前置舱": "前置仓",
    "仓铺": "仓储",
    "本地话": "本地化",
    "试验": "SHEIN",
    "实验": "SHEIN",
    "岁没交": "税没交",
    "一分岁": "一分税",
    "金税市企": "金税四期",
    "用工作签": "用工签",
    "务辱工": "务工",
    "采成": "踩坑",
    "称": "坑",
    "出户": "客户",
    "分研点": "风险点",
    "博内": "国内",
    "扎扔下来": "扎根下来",
    "中央的区域": "中亚的区域",
    "呃2000万": "2000万",
    "比亚迪在这个对": "比亚迪在当地",
}


def clip_duration(clip):
    return sum(float(item["end"]) - float(item["start"]) for item in clip["segments"])


def validate_manifest(manifest):
    required = {"source", "transcript", "output_dir", "clips"}
    missing = required - set(manifest)
    if missing:
        raise ValueError(f"missing manifest fields: {sorted(missing)}")
    seen = set()
    for clip in manifest["clips"]:
        for field in ("id", "title", "hook", "promise", "segments"):
            if field not in clip:
                raise ValueError(f"clip missing field: {field}")
        if clip["id"] in seen:
            raise ValueError(f"duplicate clip id: {clip['id']}")
        seen.add(clip["id"])
        if not clip["segments"]:
            raise ValueError(f"clip has no segments: {clip['id']}")
        for segment in clip["segments"]:
            if float(segment["end"]) <= float(segment["start"]):
                raise ValueError("segment end must be greater than start")
        if clip_duration(clip) >= 180:
            raise ValueError(f"clip exceeds 180 seconds: {clip['id']}")


def map_source_time(clip, source_time):
    offset = 0.0
    for segment in clip["segments"]:
        start = float(segment["start"])
        end = float(segment["end"])
        if start <= source_time <= end:
            return offset + source_time - start
        offset += end - start
    return None


def fix_text(text):
    cleaned = text.strip()
    for wrong, right in TEXT_FIXES.items():
        cleaned = cleaned.replace(wrong, right)
    return cleaned


def remap_subtitles(clip, transcript):
    output = []
    offset = 0.0
    for source_range in clip["segments"]:
        range_start = float(source_range["start"])
        range_end = float(source_range["end"])
        for item in transcript:
            start = max(float(item["start"]), range_start)
            end = min(float(item["end"]), range_end)
            if end <= start:
                continue
            output.append(
                {
                    "start": round(offset + start - range_start, 3),
                    "end": round(offset + end - range_start, 3),
                    "text": fix_text(item["text"]),
                }
            )
        offset += range_end - range_start
    return output


def ass_time(seconds):
    centiseconds = max(0, round(seconds * 100))
    hours, remainder = divmod(centiseconds, 360000)
    minutes, remainder = divmod(remainder, 6000)
    secs, cents = divmod(remainder, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{cents:02d}"


def ass_escape(text):
    return text.replace("\\", r"\\").replace("{", r"\{").replace("}", r"\}").replace("\n", r"\N")


def write_ass(path, clip, subtitles):
    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 720
PlayResY: 1512
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Subtitle,PingFang SC,42,&H00FFFFFF,&H0000FFFF,&H00101010,&H90000000,-1,0,0,0,100,100,0,0,1,3,1,2,48,48,145,1
Style: Hook,PingFang SC,54,&H0000E7FF,&H0000E7FF,&H00101010,&HC0000000,-1,0,0,0,100,100,0,0,3,2,0,8,36,36,150,1
Style: Promise,PingFang SC,46,&H00FFFFFF,&H00FFFFFF,&H00101010,&HC0000000,-1,0,0,0,100,100,0,0,3,2,0,8,44,44,165,1
Style: Label,PingFang SC,27,&H00FFFFFF,&H00FFFFFF,&H00101010,&H90000000,-1,0,0,0,100,100,0,0,3,1,0,7,24,24,32,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = [
        f"Dialogue: 3,0:00:00.00,0:00:02.20,Hook,,0,0,0,,{ass_escape(clip['hook'])}",
        f"Dialogue: 3,0:00:02.20,0:00:05.20,Promise,,0,0,0,,{ass_escape(clip['promise'])}",
        f"Dialogue: 2,0:00:00.00,{ass_time(clip_duration(clip))},Label,,0,0,0,,出海中亚 · 直播精华",
    ]
    for item in subtitles:
        if not item["text"]:
            continue
        events.append(
            f"Dialogue: 1,{ass_time(item['start'])},{ass_time(item['end'])},Subtitle,,0,0,0,,{ass_escape(item['text'])}"
        )
    path.write_text(header + "\n".join(events) + "\n", encoding="utf-8")


def wrap_text(draw, text, font, max_width):
    lines = []
    current = ""
    for char in text:
        candidate = current + char
        if current and draw.textbbox((0, 0), candidate, font=font)[2] > max_width:
            lines.append(current)
            current = char
        else:
            current = candidate
    if current:
        lines.append(current)
    return "\n".join(lines)


def draw_centered_box(draw, text, font, center_y, fill, text_fill, max_width=650, padding=20):
    wrapped = wrap_text(draw, text, font, max_width - padding * 2)
    bbox = draw.multiline_textbbox((0, 0), wrapped, font=font, spacing=10, align="center")
    width = bbox[2] - bbox[0]
    height = bbox[3] - bbox[1]
    left = (720 - width) / 2 - padding
    top = center_y - height / 2 - padding
    right = (720 + width) / 2 + padding
    bottom = center_y + height / 2 + padding
    draw.rounded_rectangle((left, top, right, bottom), radius=14, fill=fill)
    draw.multiline_text(
        (360, center_y), wrapped, font=font, fill=text_fill, anchor="mm", spacing=10, align="center",
        stroke_width=2, stroke_fill=(10, 10, 10, 255),
    )


def render_overlay_frame(clip, subtitles, moment):
    image = Image.new("RGBA", (720, 1512), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    label_font = ImageFont.truetype(str(FONT_PATH), 28)
    hook_font = ImageFont.truetype(str(FONT_PATH), 54)
    promise_font = ImageFont.truetype(str(FONT_PATH), 47)
    subtitle_font = ImageFont.truetype(str(FONT_PATH), 43)
    draw.rounded_rectangle((22, 25, 282, 73), radius=10, fill=(0, 0, 0, 165))
    draw.text((36, 49), "出海中亚 · 直播精华", font=label_font, fill=(255, 255, 255, 255), anchor="lm")
    if moment < 2.2:
        draw_centered_box(draw, clip["hook"], hook_font, 230, (0, 0, 0, 205), (0, 231, 255, 255))
    elif moment < 5.2:
        draw_centered_box(draw, clip["promise"], promise_font, 230, (0, 0, 0, 205), (255, 255, 255, 255))
    active = [item["text"] for item in subtitles if item["start"] <= moment < item["end"]]
    if active:
        draw_centered_box(
            draw, active[-1], subtitle_font, 1285, (0, 0, 0, 185), (255, 255, 255, 255), max_width=670, padding=18
        )
    return image


def make_overlay_video(output_dir, clip, subtitles):
    work_dir = output_dir / "work" / clip["id"] / "overlay"
    work_dir.mkdir(parents=True, exist_ok=True)
    duration = clip_duration(clip)
    boundaries = {0.0, duration, 2.2, 5.2}
    for item in subtitles:
        boundaries.add(max(0.0, min(duration, item["start"])))
        boundaries.add(max(0.0, min(duration, item["end"])))
    ordered = sorted(boundaries)
    concat_lines = []
    last_path = None
    for index, (start, end) in enumerate(zip(ordered, ordered[1:])):
        if end - start < 0.01:
            continue
        frame_path = work_dir / f"frame-{index:04d}.png"
        render_overlay_frame(clip, subtitles, (start + end) / 2).save(frame_path, optimize=True)
        concat_lines.append(f"file '{frame_path.resolve()}'\n")
        concat_lines.append(f"duration {end - start:.3f}\n")
        last_path = frame_path
    if last_path:
        concat_lines.append(f"file '{last_path.resolve()}'\n")
    concat_path = work_dir / "overlay-concat.txt"
    concat_path.write_text("".join(concat_lines), encoding="utf-8")
    overlay_path = work_dir / "overlay.mov"
    run(
        [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_path),
            "-vf", "format=rgba", "-c:v", "qtrle", str(overlay_path),
        ]
    )
    return overlay_path


def run(command):
    subprocess.run(command, cwd=ROOT, check=True)


def render_clip(source, output_dir, clip, subtitles):
    work_dir = output_dir / "work" / clip["id"]
    work_dir.mkdir(parents=True, exist_ok=True)
    segment_files = []
    for index, item in enumerate(clip["segments"], start=1):
        segment_path = work_dir / f"segment-{index:02d}.mp4"
        segment_files.append(segment_path)
        run(
            [
                "ffmpeg", "-y", "-ss", str(item["start"]), "-to", str(item["end"]),
                "-i", str(source), "-map", "0:v:0", "-map", "0:a:0",
                "-vf", "scale=720:1512:flags=lanczos,format=yuv420p",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                "-c:a", "aac", "-b:a", "160k", "-ar", "48000",
                "-movflags", "+faststart", str(segment_path),
            ]
        )
    concat_path = work_dir / "concat.txt"
    concat_path.write_text(
        "".join(f"file '{path.resolve()}'\n" for path in segment_files), encoding="utf-8"
    )
    joined_path = work_dir / "joined.mp4"
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_path), "-c", "copy", str(joined_path)])
    ass_path = output_dir / f"{clip['id']}.ass"
    write_ass(ass_path, clip, subtitles)
    final_path = output_dir / f"{clip['id']}.mp4"
    overlay_path = make_overlay_video(output_dir, clip, subtitles)
    run(
        [
            "ffmpeg", "-y", "-i", str(joined_path), "-i", str(overlay_path),
            "-filter_complex", "[0:v][1:v]overlay=0:0:shortest=1[v]", "-map", "[v]", "-map", "0:a:0",
            "-af", "loudnorm=I=-16:LRA=9:TP=-1.5",
            "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart",
            str(final_path),
        ]
    )
    return final_path


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--render", action="store_true")
    args = parser.parse_args()
    manifest_path = (ROOT / args.manifest).resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    validate_manifest(manifest)
    transcript_payload = json.loads((ROOT / manifest["transcript"]).read_text(encoding="utf-8"))
    transcript = transcript_payload.get("segments", transcript_payload)
    output_dir = ROOT / manifest["output_dir"]
    output_dir.mkdir(parents=True, exist_ok=True)
    summary = []
    for clip in manifest["clips"]:
        subtitles = remap_subtitles(clip, transcript)
        ass_path = output_dir / f"{clip['id']}.ass"
        write_ass(ass_path, clip, subtitles)
        item = {"id": clip["id"], "duration": round(clip_duration(clip), 3), "ass": str(ass_path)}
        if args.render:
            output = render_clip(ROOT / manifest["source"], output_dir, clip, subtitles)
            item.update({"output": str(output), "sha256": sha256(output)})
        summary.append(item)
    (output_dir / "render-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
