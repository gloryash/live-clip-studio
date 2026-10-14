"""Check source framing and motion before adding animated graphics.

Letterbox boundaries can verify a configured split scene, but cannot locate
faces in a new layout. When those boundaries change, preserve the whole source.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from PIL import Image, ImageChops, ImageStat

from .timeline import FPS

RENDER_REVISION = "source-framing-guard-v1"


def layout_matches_frame(frame: Image.Image, layout: dict) -> bool:
    width, height = layout["source_size"]
    x, y, w, h = layout["scene"]
    # A full-source scene has no letterbox boundary to check.
    if [x, y, w, h] == [0, 0, width, height]:
        return True
    # For an inset scene, require the area outside it to actually be dark.
    sx, sy = frame.width / width, frame.height / height
    margin = 2
    boxes = [(0, 0, frame.width, max(0, int(y * sy) - margin)),
             (0, min(frame.height, round((y + h) * sy) + margin), frame.width, frame.height),
             (0, 0, max(0, int(x * sx) - margin), frame.height),
             (min(frame.width, round((x + w) * sx) + margin), 0, frame.width, frame.height)]
    for box in boxes:
        if box[2] > box[0] and box[3] > box[1]:
            patch = frame.crop(box)
            hist = patch.histogram()
            if sum(hist[16:]) / (patch.width * patch.height) > .03:
                return False
    return True


def foreground_rect(mode: str, layout: dict) -> list[int]:
    person = next((p for p in layout["people"].values() if p["role"].lower() == mode[0]), None)
    return layout["scene"] if mode == "duo" or person is None else person["wide" if mode.endswith("w") else "close"]


def resolve_shots(shots: list[dict], matches: list[bool], layout: dict) -> list[dict]:
    full = [0, 0, *layout["source_size"]]
    result = []
    for shot in shots:
        a = shot["fa"]
        while a < shot["fb"]:
            matched = matches[a]
            b = a + 1
            while b < shot["fb"] and matches[b] == matched:
                b += 1
            result.append({**shot, "fa": a, "fb": b, "a": a / FPS, "b": b / FPS,
                           "flash": shot["flash"] and a == shot["fa"],
                           "layout_mode": "template" if matched else "preserve_source",
                           "scene_rect": layout["scene"] if matched else full,
                           "foreground_rect": foreground_rect(shot["mode"], layout) if matched else full})
            a = b
    return result


def find_holds(differences: list[float], resets: list[bool], *, minimum_frames: int = 45) -> list[dict]:
    spans, start = [], None
    for i in range(len(differences) + 1):
        stop = i == len(differences) or resets[i] or differences[i] >= .08
        if stop and start is not None:
            if i - start >= minimum_frames:
                spans.append({"start": round(start / FPS, 3), "end": round(i / FPS, 3),
                              "duration": round((i - start) / FPS, 3)})
            start = None
        if i < len(differences) and not resets[i] and differences[i] < .08 and start is None:
            start = i
    return spans


def inspect_cut(cut: Path, plan: dict, layout: dict) -> tuple[list[dict], dict]:
    width, height = layout["source_size"]
    sw, sh = 96, max(64, round(96 * height / width))
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(cut), "-an", "-vf",
                          f"scale={sw}:{sh}:flags=area,format=gray", "-frames:v", str(plan["total_frames"]),
                          "-f", "rawvideo", "-threads", "1", "-"],
                         check=True, capture_output=True, timeout=120).stdout
    stride = sw * sh
    if len(raw) != stride * plan["total_frames"]:
        raise ValueError("VISUAL_FRAMES: cut frame count differs from plan")
    matches, differences, resets = [], [], []
    piece_cuts = {round(p["out"] * FPS) for p in plan["pieces"]}
    shot_index, previous, previous_key = 0, None, None
    for i in range(plan["total_frames"]):
        frame = Image.frombytes("L", (sw, sh), raw[i * stride:(i + 1) * stride])
        matched = layout_matches_frame(frame, layout)
        matches.append(matched)
        while i >= plan["shots"][shot_index]["fb"]:
            shot_index += 1
        mode = plan["shots"][shot_index]["mode"]
        # Check the speaking person's wide source region, independent of zoom
        # changes in the final edit. Skip duo shots where the listener may sit still.
        rect = foreground_rect(mode[0] + "w", layout)
        if not matched:
            # Diagnose the same horizontal speaker region in an expanded
            # source. This is only a review hint; render still keeps everything.
            scene_x, _, scene_w, _ = layout["scene"]
            rect = [max(0, round((rect[0] - scene_x) * width / scene_w)), 0,
                    min(width, round(rect[2] * width / scene_w)), height]
            rect[2] = min(rect[2], width - rect[0])
        x, y, w, h = rect
        actor = frame.crop((round(x * sw / width), round(y * sh / height),
                            round((x + w) * sw / width), round((y + h) * sh / height)))
        key = (mode[0], matched, tuple(rect))
        reset = i in piece_cuts or key != previous_key or mode == "duo"
        diff = ImageStat.Stat(ImageChops.difference(previous, actor)).mean[0] if previous is not None and not reset else 255.
        differences.append(diff)
        resets.append(reset)
        previous, previous_key = actor, key
    shots = resolve_shots(plan["shots"], matches, layout)
    holds = find_holds(differences, resets)
    for hold in holds:
        piece = next(p for p in reversed(plan["pieces"]) if p["out"] <= hold["start"])
        hold.update(source_start=round(piece["source_start"] + hold["start"] - piece["out"], 3),
                    source_end=round(piece["source_start"] + hold["end"] - piece["out"], 3))
    return shots, {"revision": RENDER_REVISION, "preserved_source_seconds": round(matches.count(False) / FPS, 3),
                   "preserved_ranges": [{"start": s["a"], "end": s["b"]} for s in shots if s["layout_mode"] == "preserve_source"],
                   "source_holds": holds,
                   "note": "源画面近似静止检测只供复核，不等同于网络故障或人脸识别。"}
