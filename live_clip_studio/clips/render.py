from __future__ import annotations

import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image, ImageDraw

from .input import write_json
from .timeline import FPS, graphic_objects, graphics, validate_layout
from .visual import inspect_cut


def crop_filter(rect: list[int]) -> str:
    x, y, w, h = rect
    return f"crop={w}:{h}:{x}:{y}"


def mask_filter(layout: dict) -> str:
    return "".join(f"delogo=x={x}:y={y}:w={w}:h={h}," for x, y, w, h in layout.get("masks", []))


def shot_filter(index: int, shot: dict, layout: dict) -> str:
    mode = shot["mode"]
    person = next((p for p in layout["people"].values() if p["role"].lower() == mode[0]), None)
    rect = shot.get("foreground_rect", layout["scene"] if mode == "duo" or person is None else person["wide" if mode.endswith("w") else "close"])
    scene = shot.get("scene_rect", layout["scene"])
    mask = "" if shot.get("layout_mode") == "preserve_source" else mask_filter(layout)
    flash = ",fade=t=in:st=0:d=0.22:color=white" if shot["flash"] else ""
    return (
        f"[s{index}]trim=start_frame={shot['fa']}:end_frame={shot['fb']},setpts=PTS-STARTPTS,split=2[b{index}][f{index}];"
        f"[b{index}]{mask}{crop_filter(scene)},scale=135:240:force_original_aspect_ratio=increase,"
        f"crop=135:240,boxblur=6:2,scale=1080:1920,eq=brightness=-0.10:saturation=0.85[bg{index}];"
        f"[f{index}]{mask}{crop_filter(rect)},hqdn3d=1.5:1.5:3:3,"
        f"scale=1080:1340:force_original_aspect_ratio=decrease,pad=1080:1340:(ow-iw)/2:(oh-ih)/2:color=black@0,setsar=1[fg{index}];"
        f"[bg{index}][fg{index}]overlay=0:330{flash}[o{index}]"
    )


def extract_pieces(source: Path, plan: dict, work: Path) -> Path:
    def one(index_piece):
        index, p = index_piece
        path = work / f"piece-{index:03d}.mkv"
        duration = p["frames"] / FPS
        with (work / f"piece-{index:03d}.log").open("w") as log:
            subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{p['source_start']:.6f}",
                "-i", str(source), "-t", f"{duration:.6f}",
                "-vf", f"fps={FPS},tpad=stop_mode=clone:stop_duration=0.1,trim=end_frame={p['frames']},setpts=PTS-STARTPTS",
                "-af", f"aresample=48000,apad,atrim=0:{duration:.6f},asetpts=PTS-STARTPTS,afade=t=in:d=0.008,afade=t=out:st={max(0,duration-.01):.6f}:d=0.01",
                "-c:v", "libx264", "-threads", "2", "-preset", "veryfast", "-crf", "12", "-pix_fmt", "yuv420p",
                "-c:a", "pcm_s16le", "-ac", "2", str(path)], check=True, stderr=log, timeout=300)
        return path
    with ThreadPoolExecutor(3) as pool:
        paths = list(pool.map(one, enumerate(plan["pieces"])))
    listing = work / "pieces.txt"
    listing.write_text("".join(f"file '{p.name}'\n" for p in paths), encoding="utf-8")
    cut = work / "cut.mkv"
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(listing),
                    "-c", "copy", str(cut)], check=True, timeout=120)
    return cut


def cover_rect(plan: dict, layout: dict) -> list[int]:
    first = plan["shots"][0]
    if first.get("layout_mode") == "preserve_source":
        return first["foreground_rect"]
    speaker = plan["items"][0]["speaker"]
    person = next((p for p in layout["people"].values() if p["role"] == speaker), None)
    return person["wide"] if person else layout["scene"]


def make_cover(source: Path, clip: dict, plan: dict, layout: dict, target: Path, work: Path) -> None:
    rect = cover_rect(plan, layout)
    frame = work / "cover.jpg"
    mask = "" if plan["shots"][0].get("layout_mode") == "preserve_source" else mask_filter(layout)
    filters = mask + crop_filter(rect) + ",scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1"
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-ss", str(plan["items"][0]["s"]), "-i", str(source),
                    "-frames:v", "1", "-vf", filters, str(frame)], check=True, timeout=60)
    with Image.open(frame) as original:
        img = original.convert("RGBA")
    shade = Image.new("RGBA", img.size)
    draw = ImageDraw.Draw(shade)
    for y in range(760, 1920):
        draw.line((0, y, 1080, y), fill=(0, 0, 0, min(225, int((y-760)/4))))
    img.alpha_composite(shade)
    hook = graphics.stack([graphics.text_img(line, graphics.fit(graphics.SMILEY, line, 130, 970),
        graphics.WHITE if k == 0 else graphics.GOLD, stroke=10) for k, line in enumerate(clip["hook"])], gap=-28)
    graphics.paste(img, hook, (1080-hook.width)//2, 1070)
    title = graphics.text_img("".join(clip["title"]), graphics.fit(graphics.BOLD, "".join(clip["title"]), 54, 950), graphics.WHITE)
    graphics.paste(img, title, (1080-title.width)//2, 1080+hook.height)
    img.convert("RGB").save(target, quality=90)


def render_clip(source: Path, clip: dict, plan: dict, layout: dict, out: Path) -> dict:
    width, height = layout["source_size"]
    validate_layout(layout, width, height)
    work = out / "_work" / clip["id"]
    work.mkdir(parents=True, exist_ok=True)
    cut = extract_pieces(source, plan, work)
    plan["shots"], visual = inspect_cut(cut, plan, layout)
    plan["source_visual"] = visual
    write_json(out / "plans" / (clip["id"] + ".json"), plan)
    items, pieces = graphic_objects(plan)
    legacy_clip = {**clip, "fix": {str(x["at"]): x["text"] for x in clip["fix"]}}
    spec = {"brand": layout["brand"], "guest_tag": ["嘉宾", "访谈"], "host_tag": ["主持", "访谈"]}
    for person in layout["people"].values():
        spec["guest_tag" if person["role"] == "G" else "host_tag"] = person["tag"]
    editorial = layout.get("template_id") == "editorial"
    temporary = work / "final.mp4"
    if editorial:
        from . import editorial as style
        els = style.build_elements(clip, plan, layout.get("template_options", {}))
        graphics.render_final(cut, plan["shots"], els, [], {}, plan["total_frames"], temporary, work,
                              shot_filter_fn=lambda k, s: style.shot_filter(k, s, layout),
                              base_layer_fn=style.background, progress_bar=False)
    else:
        els, sfx = graphics.build_elements(legacy_clip, spec, items, pieces, plan["shots"], plan["cues"], plan["duration"])
        sfx_paths = graphics.make_sfx(out / "_work/sfx")
        graphics.render_final(cut, plan["shots"], els, sfx, sfx_paths, plan["total_frames"], temporary, work,
                              shot_filter_fn=lambda k, s: shot_filter(k, s, layout))
    target = out / (clip["id"] + ".mp4")
    temporary.replace(target)
    (out / (clip["id"] + ".srt")).write_text("".join(
        f"{k}\n{graphics.srt_time(c['start'])} --> {graphics.srt_time(c['end'])}\n{c['text']}\n\n"
        for k, c in enumerate(plan["cues"], 1)), encoding="utf-8")
    if editorial:
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", str(min(.5, plan["duration"]/2)),
                        "-i", str(target), "-frames:v", "1", str(out / (clip["id"] + "-cover.jpg"))], check=True, timeout=60)
    else:
        make_cover(source, clip, plan, layout, out / (clip["id"] + "-cover.jpg"), work)
    report = {"id": clip["id"], "duration": plan["duration"], "probe": graphics.probe(target), "log": str(work / "ffmpeg.log"),
              "source_visual": visual, "resolved_shots": plan["shots"]}
    write_json(out / (clip["id"] + "-render.json"), report)
    return report
