"""fb16d67f 直播 → 视频号传播切片（1080x1920）。

运行：
  uv run --no-project --with opencc-python-reimplemented --with pillow --with jieba \
      python editing/render_fb16_clips.py [clip_id ...]
"""
from __future__ import annotations

import json
import math
import re
import subprocess
import sys
import wave
from array import array
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import jieba
from opencc import OpenCC
from PIL import Image, ImageDraw, ImageFilter, ImageFont


ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = ROOT / "editing/fb16_clips.json"
FONT_DIR = ROOT / "editing/fonts"
HEAVY = str(FONT_DIR / "SourceHanSansSC-Heavy.otf")
BOLD = str(FONT_DIR / "SourceHanSansSC-Bold.otf")
SMILEY = str(FONT_DIR / "smiley/SmileySans-Oblique.ttf")

FPS = 30
W, H = 1080, 1920
FG_Y, FG_H = 330, 1340
BAR_Y = FG_Y + FG_H
SUB_Y = 1515
BAND_Y = 588
GOLD = (255, 214, 64, 255)
WHITE = (255, 255, 255, 255)
BLACK = (0, 0, 0, 255)
RED = (232, 69, 60, 255)

PAD_IN, PAD_OUT, TAIL = 0.10, 0.18, 0.7
MAX_JOIN_GAP = 0.6
CC = OpenCC("t2s")


# ---------------------------------------------------------------- 数据与文本

def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def char_times(text: str, words: list[dict[str, Any]]) -> list[tuple[float, float] | None]:
    times: list[tuple[float, float] | None] = [None] * len(text)
    pos = 0
    for word in words:
        token = str(word.get("text", "")).strip()
        idx = text.find(token, pos) if token else -1
        if idx < 0:
            continue
        a, b, n = float(word["start"]), float(word["end"]), len(token)
        for k in range(n):
            times[idx + k] = (a + (b - a) * k / n, a + (b - a) * (k + 1) / n)
        pos = idx + n
    return times


def clean_text(text: str, fixes: list[tuple[str, str]]) -> str:
    for old, new in fixes:
        text = text.replace(old, new)
    text = re.sub(r"(?<![0-9A-Za-z])2([BC])(?![A-Za-z])", r"To\1", text)
    text = re.sub(r"[，。、；：,;:…]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    for _ in range(2):
        text = re.sub(r"^(就是|然后|所以说|那么|是吧)\s*(?=\S{3,})", "", text).strip()
    return re.sub(r"\s*(是吧|对吧)$", "", text).strip()


@dataclass
class Item:
    tid: int
    c0: int
    c1: int | None
    s: float
    e: float
    text: str
    speaker: str
    gold: bool
    cold: bool
    out_s: float = 0.0
    out_e: float = 0.0
    piece_out0: float = 0.0
    first_in_piece: bool = False


@dataclass
class Piece:
    items: list[Item]
    cold: bool
    chapter: bool = False
    s_q: float = 0.0
    frames: int = 0
    out0: float = 0.0


def parse_tokens(tokens: list[str]) -> list[tuple[int, int, int | None]]:
    out: list[tuple[int, int, int | None]] = []
    for token in tokens:
        if "@" in token:
            tid, rng = token.split("@")
            a, _, b = rng.partition(":")
            out.append((int(tid), int(a), int(b) if b else None))
        elif "-" in token:
            a, b = map(int, token.split("-"))
            out.extend((tid, 0, None) for tid in range(a, b + 1))
        else:
            out.append((int(token), 0, None))
    return out


class Transcript:
    def __init__(self, job_dir: Path) -> None:
        tdir = job_dir / "transcript"
        self.turns = {t["id"]: t for t in read_json(tdir / "speaker-turns.json")["turns"]}
        self.words = read_json(tdir / "segments.json")["segments"]
        self.pred = read_json(tdir / "speaker-predictions.json")["predictions"]
        self.wav = tdir / "audio-16k-mono.wav"

    def span(self, tid: int, c0: int = 0, c1: int | None = None) -> tuple[float, float]:
        turn = self.turns[tid]
        times = char_times(turn["text"], self.words[tid - 1]["words"])[c0:c1]
        valid = [t for t in times if t]
        if not valid:
            return float(turn["start"]), float(turn["end"])
        return valid[0][0], valid[-1][1]

    def quietest(self, a: float, b: float) -> float:
        """[a, b] 内 20ms 能量最低处（字间气口），作为下刀点。"""
        with wave.open(str(self.wav)) as wav:
            rate = wav.getframerate()
            wav.setpos(max(0, int(a * rate)))
            samples = array("h", wav.readframes(max(1, int((b - a) * rate) + rate // 50)))
        win, hop = rate // 50, rate // 100
        best, best_t = None, (a + b) / 2
        for k in range(0, max(1, len(samples) - win), hop):
            energy = sum(v * v for v in samples[k:k + win:4])
            if best is None or energy <= best:
                best, best_t = energy, a + (k + win / 2) / rate
        return best_t

    def speaker(self, tid: int) -> str | None:
        sid = self.pred.get(str(tid), {}).get("speaker_id")
        return {"SPEAKER_00": "H", "SPEAKER_01": "G"}.get(sid)


def build_items(tr: Transcript, clip: dict[str, Any], fixes: list[tuple[str, str]]) -> list[Item]:
    items: list[Item] = []
    gold = set(clip.get("gold", []))
    overrides = clip.get("speakers", {})
    last_speaker = "G"
    for cold, tokens in ((True, clip["cold"]), (False, clip["body"])):
        for tid, c0, c1 in parse_tokens(tokens):
            s, e = clip.get("retime", {}).get(str(tid)) or tr.span(tid, c0, c1)
            raw = CC.convert(tr.turns[tid]["text"][c0:c1])
            fixed = clip.get("fix", {}).get(str(tid))
            text = clean_text(fixed if fixed is not None else raw, fixes) if fixed != "" else ""
            speaker = overrides.get(str(tid)) or tr.speaker(tid) or last_speaker
            last_speaker = speaker
            items.append(Item(tid, c0, c1, s, e, text, speaker, tid in gold, cold))
    return items


def build_pieces(tr: Transcript, items: list[Item], chapters: set[int]) -> list[Piece]:
    pieces: list[Piece] = []
    for it in items:
        prev = pieces[-1].items[-1] if pieces else None
        joined = (
            prev is not None
            and prev.cold == it.cold
            and it.tid == prev.tid + 1
            and prev.c1 is None
            and it.c0 == 0
            and it.s - prev.e <= MAX_JOIN_GAP
            and it.tid not in chapters
        )
        if joined:
            pieces[-1].items.append(it)
        else:
            pieces.append(Piece([it], it.cold, chapter=(not it.cold and it.tid in chapters)))
    for index, piece in enumerate(pieces):
        first, last = piece.items[0], piece.items[-1]
        is_last = index == len(pieces) - 1
        prev_end = tr.span(first.tid - 1)[1] if first.c0 == 0 and first.tid - 1 in tr.turns else -1.0
        next_start = tr.span(last.tid + 1)[0] if last.c1 is None and last.tid + 1 in tr.turns else 1e9
        # 只在相邻句之间真实存在的空隙里找气口，绝不越过相邻句的时间戳
        a, b = max(first.s - 0.25, prev_end + 0.02), first.s - 0.01
        lo = tr.quietest(a, b) if b - a >= 0.04 else min(max(first.s - PAD_IN, prev_end + 0.03), first.s - 0.03)
        a, b = last.e + 0.01, min(last.e + (TAIL if is_last else 0.3), next_start - 0.02)
        if is_last:
            hi = max(b, last.e + 0.05)
        else:
            hi = tr.quietest(a, b) if b - a >= 0.04 else max(min(last.e + PAD_OUT, next_start - 0.03), last.e + 0.05)
        piece.s_q = math.floor(lo * FPS) / FPS
        piece.frames = round((math.ceil(hi * FPS) / FPS - piece.s_q) * FPS)
    out = 0.0
    for piece in pieces:
        piece.out0 = out
        for k, it in enumerate(piece.items):
            it.piece_out0, it.first_in_piece = out, k == 0
            it.out_s = out + it.s - piece.s_q
            it.out_e = out + it.e - piece.s_q
        out += piece.frames / FPS
    return pieces


# ---------------------------------------------------------------- 镜头编排

def plan_shots(items: list[Item], pieces: list[Piece], duration: float) -> list[dict[str, Any]]:
    body = [it for it in items if not it.cold]
    t0 = next(p.out0 for p in pieces if not p.cold)
    cold_speaker = next(it.speaker for it in items if it.cold)
    shots = [{"a": 0.0, "b": t0, "mode": "gc" if cold_speaker == "G" else "hc", "flash": False}]
    cut_points = sorted(p.out0 for p in pieces if not p.cold)
    item_points = sorted(it.out_s for it in body)
    chapter_points = {p.out0 for p in pieces if p.chapter}
    gold_points = [it.out_s for it in body if it.gold]

    runs: list[list[Any]] = []
    for it in body:
        boundary = it.piece_out0 if it.first_in_piece else it.out_s - 0.08
        if not runs or it.speaker != runs[-1][0] or (it.first_in_piece and boundary in chapter_points):
            if runs:
                runs[-1][2] = boundary
            runs.append([it.speaker, t0 if not runs else boundary, duration])
    cycles = {"G": ["gw", "gc", "gw", "gc", "duo"], "H": ["hw", "hc"]}
    pos = {"G": 0, "H": 0}
    prev_speaker = cold_speaker
    for speaker, a, b in runs:
        flash = True
        if speaker == "H" and b - a < 1.8:
            shots.append({"a": a, "b": b, "mode": "duo", "flash": flash and (a == t0 or a in chapter_points)})
            prev_speaker = speaker
            continue
        cursor, first = a, True
        while cursor < b - 0.01:
            if speaker == "G" and first and prev_speaker == "H":
                mode, lo, hi = "duo", 1.8, 3.0
            else:
                mode = cycles[speaker][pos[speaker] % len(cycles[speaker])]
                pos[speaker] += 1
                if mode == "duo" and any(cursor - 0.2 <= g <= cursor + 2.8 for g in gold_points):
                    mode = cycles[speaker][pos[speaker] % len(cycles[speaker])]
                    pos[speaker] += 1
                lo, hi = (1.6, 2.6) if mode == "duo" else (2.8, 7.5)
            mid = (lo + hi) / 2
            end = None
            for points in (cut_points, item_points):
                cands = [x for x in points if cursor + lo <= x <= cursor + hi and x < b - 1.5]
                if cands:
                    end = min(cands, key=lambda x: abs(x - cursor - mid))
                    break
            if end is None:
                end = b if b - cursor <= hi + 1.5 else cursor + mid
            if b - end < 1.5:
                end = b
            shots.append({"a": cursor, "b": end, "mode": mode,
                          "flash": first and (a == t0 or a in chapter_points)})
            cursor, first = end, False
        prev_speaker = speaker
    for shot in shots:
        shot["fa"], shot["fb"] = round(shot["a"] * FPS), round(shot["b"] * FPS)
    return [s for s in shots if s["fb"] > s["fa"]]


def shot_filter(index: int, shot: dict[str, Any]) -> str:
    mode = shot["mode"]
    if mode == "duo":
        bg_x, fg = 247, "delogo=x=468:y=1239:w=114:h=92,crop=912:744:0:588,scale=1080:881:flags=lanczos,unsharp=5:5:0.4"
        fg_y = FG_Y + (FG_H - 881) // 2
    else:
        px = 456 if mode[0] == "g" else 0
        bg_x = px + 19
        if mode.endswith("w"):
            crop = f"crop=456:566:{px}:{BAND_Y + 20}"
        else:
            crop = f"crop=410:509:{px + (26 if mode[0] == 'g' else 10)}:{BAND_Y + (50 if mode[0] == 'g' else 45)}"
        fg = f"{crop},hqdn3d=1.5:1.5:3:3,scale=1080:{FG_H}:flags=lanczos,unsharp=5:5:0.8:3:3:0.3"
        fg_y = FG_Y
    flash = ",fade=t=in:st=0:d=0.22:color=white" if shot["flash"] else ""
    return (
        f"[s{index}]trim=start_frame={shot['fa']}:end_frame={shot['fb']},setpts=PTS-STARTPTS,split=2[b{index}][f{index}];"
        f"[b{index}]crop=418:744:{bg_x}:{BAND_Y},scale=135:240,boxblur=6:2,scale={W}:{H},"
        f"eq=brightness=-0.10:saturation=0.85[bg{index}];"
        f"[f{index}]{fg}[fg{index}];"
        f"[bg{index}][fg{index}]overlay=0:{fg_y}{flash}[o{index}]"
    )


# ---------------------------------------------------------------- 图形层

def font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size)


def fit(path: str, text: str, size: int, max_w: int) -> ImageFont.FreeTypeFont:
    while size > 30 and font(path, size).getlength(text) > max_w:
        size -= 4
    return font(path, size)


def text_img(text: str, fnt: ImageFont.FreeTypeFont, fill: tuple, stroke: int = 6, shadow: bool = True) -> Image.Image:
    ascent, descent = fnt.getmetrics()
    pad = 16 + stroke
    w = int(fnt.getlength(text)) + 2 * pad
    h = ascent + descent + 2 * pad
    img = Image.new("RGBA", (w, h))
    if shadow:
        sh = Image.new("RGBA", (w, h))
        ImageDraw.Draw(sh).text((pad, pad + 6), text, font=fnt, fill=(0, 0, 0, 140),
                                stroke_width=stroke, stroke_fill=(0, 0, 0, 140))
        img.alpha_composite(sh.filter(ImageFilter.GaussianBlur(7)))
    ImageDraw.Draw(img).text((pad, pad), text, font=fnt, fill=fill, stroke_width=stroke, stroke_fill=BLACK)
    return img


def stack(images: list[Image.Image], gap: int = -18) -> Image.Image:
    w = max(i.width for i in images)
    h = sum(i.height for i in images) + gap * (len(images) - 1)
    out, y = Image.new("RGBA", (w, h)), 0
    for img in images:
        out.alpha_composite(img, ((w - img.width) // 2, y))
        y += img.height + gap
    return out


def panel(content: list[tuple[str, ImageFont.FreeTypeFont, tuple]], fill: tuple, border: tuple | None,
          bar: tuple | None = None, padx: int = 34, pady: int = 18, radius: int = 18) -> Image.Image:
    lines = [text_img(t, f, c, stroke=0, shadow=False) for t, f, c in content]
    inner = stack(lines, gap=-26)
    left = padx + (10 if bar else 0)
    w, h = inner.width + left + padx - 32, inner.height + 2 * pady - 32
    img = Image.new("RGBA", (w + 20, h + 20))
    shadow = Image.new("RGBA", img.size)
    ImageDraw.Draw(shadow).rounded_rectangle((10, 16, w + 10, h + 16), radius, fill=(0, 0, 0, 110))
    img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(6)))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((10, 10, w + 10, h + 10), radius, fill=fill,
                        outline=border, width=4 if border else 0)
    if bar:
        d.rounded_rectangle((10, 10, 22, h + 10), 6, fill=bar)
    img.alpha_composite(inner, (10 + left - 16, 10 + pady - 16))
    return img


def ease_out_cubic(p: float) -> float:
    return 1 - (1 - p) ** 3


def ease_out_back(p: float) -> float:
    c = 1.9
    return 1 + (c + 1) * (p - 1) ** 3 + c * (p - 1) ** 2


@dataclass
class El:
    img: Image.Image
    cx: float
    cy: float
    t0: float
    t1: float
    anim: str = "none"
    din: float = 0.3
    dout: float = 0.0
    z: int = 0
    uid: int = field(default=0)

    def key(self, t: float) -> tuple | None:
        if not self.t0 <= t < self.t1:
            return None
        if self.anim != "none" and t < self.t0 + self.din:
            return (self.uid, "in", int((t - self.t0) * FPS))
        if self.dout and t >= self.t1 - self.dout:
            return (self.uid, "out", int((self.t1 - t) * FPS))
        return (self.uid,)

    def draw(self, canvas: Image.Image, t: float) -> None:
        p = min(1.0, (t - self.t0) / self.din) if self.anim != "none" else 1.0
        scale, alpha, dx, dy = 1.0, 1.0, 0.0, 0.0
        if self.anim == "pop":
            scale, alpha = 0.55 + 0.45 * ease_out_back(p), min(1.0, p * 2.5)
        elif self.anim == "punch":
            scale = 1.18 - 0.18 * ease_out_cubic(p)
        elif self.anim == "drop":
            dy, alpha = -70 * (1 - ease_out_cubic(p)), p
        elif self.anim == "slide":
            dx, alpha = -(self.img.width + 60) * (1 - ease_out_cubic(p)), min(1.0, p * 2)
        if self.dout and t >= self.t1 - self.dout:
            alpha *= max(0.0, (self.t1 - t) / self.dout)
        img = self.img
        if abs(scale - 1) > 1e-3:
            img = img.resize((max(1, int(img.width * scale)), max(1, int(img.height * scale))), Image.LANCZOS)
        if alpha < 0.999:
            img = img.copy()
            img.putalpha(img.getchannel("A").point(lambda v: int(v * alpha)))
        paste(canvas, img, int(self.cx - img.width / 2 + dx), int(self.cy - img.height / 2 + dy))


def paste(canvas: Image.Image, img: Image.Image, x: int, y: int) -> None:
    sx, sy = max(0, -x), max(0, -y)
    if sx >= img.width or sy >= img.height:
        return
    canvas.alpha_composite(img, (max(0, x), max(0, y)), (sx, sy))


def split_cue(text: str, fnt: ImageFont.FreeTypeFont, max_w: int = 930) -> list[str]:
    if fnt.getlength(text) <= max_w:
        return [text]
    bounds, pos = [], 0
    for token in jieba.cut(text):
        pos += len(token)
        bounds.append(pos)
    n = math.ceil(fnt.getlength(text) / (max_w - 40))
    cuts = []
    for k in range(1, n):
        target = len(text) * k / n
        spaces = [i for i in bounds[:-1] if text[i - 1] == " " or text[i:i + 1] == " "]
        pool = spaces if spaces and min(abs(i - target) for i in spaces) < len(text) / n * 0.35 else bounds[:-1]
        cuts.append(min(pool, key=lambda i: abs(i - target)))
    edges = [0, *sorted(set(cuts)), len(text)]
    return [c for c in (text[a:b].strip() for a, b in zip(edges, edges[1:])) if c]


def build_cues(items: list[Item], duration: float) -> list[dict[str, Any]]:
    sub_font = font(HEAVY, 64)
    raw: list[dict[str, Any]] = []
    for it in items:
        if not re.sub(r"[\s？！?!]", "", it.text):
            continue
        chunks = split_cue(it.text, sub_font)
        total = sum(len(c.replace(" ", "")) for c in chunks)
        cursor = it.out_s
        for chunk in chunks:
            share = (it.out_e - it.out_s) * len(chunk.replace(" ", "")) / total
            raw.append({"start": cursor, "end": cursor + share, "text": chunk, "gold": it.gold})
            cursor += share
    for cue, nxt in zip(raw, raw[1:] + [None]):
        limit = nxt["start"] if nxt else duration
        cue["end"] = limit if limit - cue["end"] < 0.45 else min(cue["end"] + 0.2, limit)
    return raw


def build_elements(clip: dict[str, Any], spec: dict[str, Any], items: list[Item], pieces: list[Piece],
                   shots: list[dict[str, Any]], cues: list[dict[str, Any]], duration: float
                   ) -> tuple[list[El], list[tuple[float, str, float]]]:
    els: list[El] = []
    sfx: list[tuple[float, str, float]] = []
    t0 = next(p.out0 for p in pieces if not p.cold)
    first_out = {}
    for it in items:
        if not it.cold:
            first_out.setdefault(it.tid, it.out_s)

    hook_f = SMILEY
    hook = stack([text_img(line, fit(hook_f, line, 122, 980), WHITE if i == 0 else GOLD, stroke=10)
                  for i, line in enumerate(clip["hook"])], gap=-30)
    els.append(El(hook, W / 2, 190, 0.0, t0, "pop", 0.32, z=3))
    sfx.append((0.0, "boom", 0.45))

    title = stack([text_img(clip["title"][0], fit(HEAVY, clip["title"][0], 84, 1000), WHITE, stroke=8),
                   text_img(clip["title"][1], fit(HEAVY, clip["title"][1], 100, 1010), GOLD, stroke=9)], gap=-34)
    els.append(El(title, W / 2, 190, t0, duration, "drop", 0.4, z=3))
    sfx += [(max(0.0, t0 - 0.32), "whoosh", 0.55), (t0, "boom", 0.6)]

    brand = text_img(spec["brand"], font(BOLD, 30), (255, 255, 255, 215), stroke=3, shadow=False)
    els.append(El(brand, W / 2, BAR_Y + 34, t0, duration, "fade", 0.5, z=1))

    for tag_key, speaker in (("guest_tag", "g"), ("host_tag", "h")):
        shot = next((s for s in shots if s["a"] >= t0 - 1e-6 and s["mode"].startswith(speaker)), None)
        if not shot:
            continue
        name, role = spec[tag_key]
        tag = panel([(name, font(HEAVY, 50), WHITE), (role, font(BOLD, 30), GOLD)], (12, 12, 12, 185), None, GOLD)
        start = shot["a"] + 0.25
        els.append(El(tag, 40 + tag.width / 2, 1385, start, min(start + 3.4, duration), "slide", 0.35, 0.25, z=5))

    for card in clip.get("cards", []):
        at = first_out[card["at"]]
        img = panel([(card["text"], font(SMILEY, 76), WHITE)], RED, (255, 255, 255, 255), radius=26)
        img = img.rotate(2.5, resample=Image.BICUBIC, expand=True)
        els.append(El(img, W / 2, 1360, at, min(at + 2.4, duration), "pop", 0.28, 0.2, z=6))
        sfx.append((at, "pop", 0.4))

    for index, entry in enumerate(clip.get("lists", [])):
        at = first_out[entry["at"]]
        until_items = [it for it in items if not it.cold and it.tid == entry["until"]]
        until = until_items[-1].out_e + 0.4 if until_items else duration
        img = panel([(entry["text"], font(BOLD, 42), WHITE)], (10, 10, 10, 175), None, GOLD, padx=26, pady=12, radius=14)
        els.append(El(img, 36 + img.width / 2, 420 + index * 92, at, min(until, duration), "slide", 0.32, 0.25, z=4))
        sfx.append((at, "pop", 0.3))

    cta_start = max(t0 + 2, duration - 3.4)
    cta = panel([(clip["cta"][0], font(BOLD, 44), WHITE), (clip["cta"][1], fit(SMILEY, clip["cta"][1], 84, 900), GOLD)],
                (12, 12, 12, 200), GOLD, padx=44, pady=20, radius=26)
    els.append(El(cta, W / 2, 1300, cta_start, duration, "pop", 0.35, z=7))
    sfx.append((cta_start, "pop", 0.45))

    for cue in cues:
        fnt = font(HEAVY, 70 if cue["gold"] else 64)
        img = text_img(cue["text"], fnt, GOLD if cue["gold"] else WHITE, stroke=8 if cue["gold"] else 7)
        els.append(El(img, W / 2, SUB_Y, cue["start"], cue["end"], "punch" if cue["gold"] else "none", 0.16, z=8))

    for p in pieces:
        if p.chapter:
            sfx.append((max(0.0, p.out0 - 0.28), "whoosh", 0.4))
    for uid, el in enumerate(els):
        el.uid = uid
    return sorted(els, key=lambda e: e.z), sfx


def base_layer() -> Image.Image:
    img = Image.new("RGBA", (W, H))
    d = ImageDraw.Draw(img)
    for y in range(340):
        d.line((0, y, W, y), fill=(0, 0, 0, int(130 * (1 - y / 340) ** 1.4)))
    for y in range(BAR_Y, H):
        d.line((0, y, W, y), fill=(0, 0, 0, int(150 * ((y - BAR_Y) / (H - BAR_Y)) ** 0.8)))
    return img


# ---------------------------------------------------------------- 渲染

def run(cmd: list[str], **kwargs: Any) -> None:
    subprocess.run(cmd, check=True, **kwargs)


def make_sfx(out: Path) -> dict[str, Path]:
    out.mkdir(parents=True, exist_ok=True)
    recipes = {
        "whoosh": ["-f", "lavfi", "-i", "anoisesrc=d=0.55:c=pink:a=0.8:r=48000",
                   "-af", "highpass=f=400,lowpass=f=7000,afade=t=in:d=0.38:curve=exp,afade=t=out:st=0.38:d=0.17"],
        "boom": ["-f", "lavfi", "-i", "aevalsrc='0.9*sin(2*PI*(45+90*exp(-t*14))*t)*exp(-t*4.5)':s=48000:d=1.0",
                 "-af", "lowpass=f=320"],
        "pop": ["-f", "lavfi", "-i", "aevalsrc='0.5*sin(2*PI*(700+900*exp(-t*35))*t)*exp(-t*22)':s=48000:d=0.3"],
    }
    paths = {}
    for name, args in recipes.items():
        paths[name] = out / f"{name}.wav"
        run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *args, "-ac", "2", str(paths[name])])
    return paths


def extract_pieces(source: Path, pieces: list[Piece], work: Path) -> Path:
    work.mkdir(parents=True, exist_ok=True)

    def one(index_piece: tuple[int, Piece]) -> Path:
        index, piece = index_piece
        path = work / f"piece-{index:03d}.mkv"
        dur = piece.frames / FPS
        run([
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{piece.s_q:.4f}", "-i", str(source),
            "-vf", f"fps={FPS},trim=end_frame={piece.frames},setpts=PTS-STARTPTS",
            "-af", f"aresample=48000,apad,atrim=0:{dur:.6f},asetpts=PTS-STARTPTS,"
                   f"afade=t=in:d=0.015,afade=t=out:st={max(0.0, dur - 0.02):.4f}:d=0.02",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "12", "-g", "30", "-pix_fmt", "yuv420p",
            "-c:a", "pcm_s16le", "-ac", "2", str(path),
        ])
        return path

    with ThreadPoolExecutor(6) as pool:
        paths = list(pool.map(one, enumerate(pieces)))
    listing = work / "pieces.txt"
    listing.write_text("".join(f"file '{p.name}'\n" for p in paths), encoding="utf-8")
    cut = work / "cut.mkv"
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0",
         "-i", str(listing), "-c", "copy", str(cut)], cwd=work)
    return cut


def render_final(cut: Path, shots: list[dict[str, Any]], els: list[El], sfx: list[tuple[float, str, float]],
                 sfx_paths: dict[str, Path], total_frames: int, out_path: Path, work: Path,
                 *, shot_filter_fn=None, base_layer_fn=None, progress_bar=True) -> None:
    duration = total_frames / FPS
    names = sorted({name for _, name, _ in sfx})
    lines = [f"[0:v]split={len(shots)}" + "".join(f"[s{i}]" for i in range(len(shots)))]
    lines += [(shot_filter_fn or shot_filter)(i, s) for i, s in enumerate(shots)]
    lines.append("".join(f"[o{i}]" for i in range(len(shots))) + f"concat=n={len(shots)}:v=1:a=0[base]")
    if progress_bar:
        lines.append(f"color=c=0xFFD640:s={W}x6:r={FPS}:d={duration:.3f}[bar]")
        lines.append(f"[base][bar]overlay=x='-w+W*t/{duration:.3f}':y={BAR_Y - 6}[vb]")
    else:
        lines.append("[base]null[vb]")
    lines.append("[vb][1:v]overlay=0:0:format=yuv420,format=yuv420p[vout]")
    lines.append("[0:a]aformat=sample_fmts=fltp,volume=0.8,highpass=f=70,acompressor=threshold=0.125:ratio=3:attack=10:release=200:makeup=2,"
                 "loudnorm=I=-15:TP=-1.5:LRA=8,aresample=48000[voice]")
    mix = ["[voice]"]
    for k, name in enumerate(names):
        events = [(t, v) for t, n, v in sfx if n == name]
        lines.append(f"[{2 + k}:a]asplit={len(events)}" + "".join(f"[{name}{j}]" for j in range(len(events))))
        for j, (t, vol) in enumerate(events):
            ms = int(t * 1000)
            lines.append(f"[{name}{j}]adelay={ms}|{ms},volume={vol}[{name}d{j}]")
            mix.append(f"[{name}d{j}]")
    lines.append("".join(mix) + f"amix=inputs={len(mix)}:normalize=0:duration=first,alimiter=limit=0.95[aout]")
    graph = work / "graph.txt"
    graph.write_text(";\n".join(lines), encoding="utf-8")

    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "warning", "-reinit_filter", "0", "-i", str(cut),
           "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{W}x{H}", "-framerate", str(FPS), "-i", "pipe:0"]
    for name in names:
        cmd += ["-i", str(sfx_paths[name])]
    cmd += ["-filter_complex_script", str(graph), "-map", "[vout]", "-map", "[aout]",
            "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-profile:v", "high", "-r", str(FPS),
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", str(out_path)]
    log = (work / "ffmpeg.log").open("w")
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=log)
    base = (base_layer_fn or base_layer)()
    last_key, last_bytes = None, b""
    try:
        for f in range(total_frames):
            t = f / FPS
            active = [e for e in els if e.t0 <= t < e.t1]
            key = tuple(e.key(t) for e in active)
            if key != last_key:
                canvas = base.copy()
                for e in active:
                    e.draw(canvas, t)
                last_key, last_bytes = key, canvas.tobytes()
            proc.stdin.write(last_bytes)
    finally:
        proc.stdin.close()
        code = proc.wait()
        log.close()
    if code:
        raise RuntimeError(f"ffmpeg failed ({code}), see {work / 'ffmpeg.log'}")


def srt_time(seconds: float) -> str:
    ms = max(0, round(seconds * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def probe(path: Path) -> dict[str, Any]:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration,size:stream=codec_name,width,height",
                          "-of", "json", str(path)], check=True, capture_output=True, text=True).stdout
    return json.loads(out)


def main() -> None:
    spec = read_json(SPEC_PATH)
    job_dir = ROOT / "data" / spec["job_id"]
    source = job_dir / "source.mp4"
    out_dir = ROOT / spec["output_dir"]
    out_dir.mkdir(parents=True, exist_ok=True)
    fixes = sorted(spec["fixes"].items(), key=lambda kv: -len(kv[0]))
    tr = Transcript(job_dir)
    sfx_paths = make_sfx(out_dir / "_work/sfx")
    wanted = set(sys.argv[1:])
    report_path = out_dir / "render-report.json"
    report = read_json(report_path) if report_path.exists() else {}

    for clip in spec["clips"]:
        if wanted and clip["id"] not in wanted:
            continue
        work = out_dir / "_work" / clip["id"]
        items = build_items(tr, clip, fixes)
        pieces = build_pieces(tr, items, set(clip.get("chapters", [])))
        total_frames = sum(p.frames for p in pieces)
        duration = total_frames / FPS
        shots = plan_shots(items, pieces, duration)
        cues = build_cues(items, duration)
        els, sfx = build_elements(clip, spec, items, pieces, shots, cues, duration)
        print(f"[{clip['id']}] {duration:.1f}s, {len(pieces)} pieces, {len(shots)} shots, {len(cues)} cues", flush=True)
        cut = extract_pieces(source, pieces, work)
        out_path = out_dir / f"{clip['id']}.mp4"
        render_final(cut, shots, els, sfx, sfx_paths, total_frames, out_path, work)
        (out_dir / f"{clip['id']}.srt").write_text("".join(
            f"{i}\n{srt_time(c['start'])} --> {srt_time(c['end'])}\n{c['text']}\n\n" for i, c in enumerate(cues, 1)
        ), encoding="utf-8")
        report[clip["id"]] = {
            "title": "".join(clip["title"]),
            "duration": round(duration, 3),
            "title_at": round(next(p.out0 for p in pieces if not p.cold), 3),
            "pieces": [{"src": round(p.s_q, 3), "frames": p.frames, "out": round(p.out0, 3),
                        "turns": [it.tid for it in p.items], "chapter": p.chapter} for p in pieces],
            "shots": [{k: (round(v, 3) if isinstance(v, float) else v) for k, v in s.items()} for s in shots],
            "max_shot": round(max(s["b"] - s["a"] for s in shots), 3),
            "cues": len(cues),
            "probe": probe(out_path),
        }
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"[{clip['id']}] done -> {out_path}", flush=True)


if __name__ == "__main__":
    main()
