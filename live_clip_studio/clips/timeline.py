from __future__ import annotations

import math
from dataclasses import asdict

from editing import render_fb16_clips as graphics

FPS = 30


def validate_layout(layout: dict, width: int, height: int) -> None:
    if layout.get("version") != 1 or layout.get("source_size") != [width, height]:
        raise ValueError("LAYOUT_SIZE: source_size must match actual source")
    def rect(v):
        if not isinstance(v, list) or len(v) != 4 or not all(type(x) is int for x in v):
            raise ValueError("LAYOUT_RECT: [x,y,width,height] integers required")
        x, y, w, h = v
        if min(x, y) < 0 or min(w, h) < 2 or x + w > width or y + h > height:
            raise ValueError(f"LAYOUT_RECT: outside source: {v}")
    rect(layout.get("scene"))
    people = layout.get("people", {})
    if not isinstance(people, dict) or not people:
        raise ValueError("LAYOUT_PEOPLE: at least one labeled person required")
    roles = []
    for sid, person in people.items():
        if sid == "UNKNOWN" or person.get("role") not in ("H", "G"):
            raise ValueError("LAYOUT_ROLE: map named speaker IDs to H/G, not UNKNOWN")
        roles.append(person["role"])
        rect(person.get("wide"))
        rect(person.get("close"))
        tag = person.get("tag")
        if not isinstance(tag, list) or len(tag) != 2 or any(not isinstance(x, str) or len(x) > 24 for x in tag):
            raise ValueError("LAYOUT_TAG: two short strings required")
    if len(set(roles)) != len(roles):
        raise ValueError("LAYOUT_ROLE: one person per H/G role")
    for mask in layout.get("masks", []):
        rect(mask)
        if mask[0] < 1 or mask[1] < 1 or mask[0]+mask[2] >= width or mask[1]+mask[3] >= height:
            raise ValueError("LAYOUT_MASK: delogo requires a one-pixel source border")
    if not isinstance(layout.get("brand"), str) or len(layout["brand"]) > 32:
        raise ValueError("LAYOUT_BRAND: short brand string required")


def plan_shots(items: list[graphics.Item], pieces: list[graphics.Piece], total_frames: int) -> list[dict]:
    t0 = next(p.out0 for p in pieces if not p.cold)
    first = items[0].speaker
    shots = [{"fa": 0, "fb": round(t0 * FPS), "mode": {"G": "gc", "H": "hc"}.get(first, "duo"), "flash": False}]
    body = [it for it in items if not it.cold]
    chapters = {round(p.out0 * FPS) for p in pieces if p.chapter}
    boundaries = sorted({round(p.out0 * FPS) for p in pieces} | {round(it.out_s * FPS) for it in body})
    runs = []
    for it in body:
        boundary = round((it.piece_out0 if it.first_in_piece else it.out_s) * FPS)
        if not runs or runs[-1][0] != it.speaker or boundary in chapters:
            if runs:
                runs[-1][2] = boundary
            runs.append([it.speaker, round(t0 * FPS) if not runs else boundary, total_frames])
    previous, positions = first, {"G": 0, "H": 0}
    gold_spans = [(round(it.out_s * FPS), round(it.out_e * FPS)) for it in body if it.gold]
    for speaker, a, b in runs:
        cursor = a
        while cursor < b:
            if speaker == "U" or (speaker == "H" and b - a < 54):
                mode = "duo"
            elif speaker == "G" and previous == "H" and cursor == a:
                mode = "duo"
            else:
                prefix = speaker.lower()
                mode = prefix + ("w" if positions[speaker] % 2 == 0 else "c")
                positions[speaker] += 1
            max_frames = 78 if mode == "duo" and speaker != "U" else 225
            end = min(b, cursor + max_frames)
            if end < b:
                candidates = [p for p in boundaries if cursor + 84 <= p <= end]
                if candidates:
                    end = min(candidates, key=lambda p: abs(p - (cursor + 150)))
            if mode == "duo" and speaker in ("H", "G") and any(cursor < gb and end > ga for ga, gb in gold_spans):
                mode = speaker.lower() + "c"
            shots.append({"fa": cursor, "fb": end, "mode": mode, "flash": cursor == a and (a == round(t0 * FPS) or a in chapters)})
            cursor = end
        previous = speaker
    for shot in shots:
        shot.update(a=shot["fa"] / FPS, b=shot["fb"] / FPS)
    return [s for s in shots if s["fb"] > s["fa"]]


def make_plan(clip: dict, doc: dict, layout: dict) -> dict:
    rows = sorted(doc["segments"], key=lambda r: (r["start"], r["id"]))
    turns = {r["id"]: r for r in rows}
    position = {r["id"]: k for k, r in enumerate(rows)}
    fixes = {x["at"]: x["text"] for x in clip["fix"]}
    items, pieces = [], []
    for cold, ids in ((True, clip["cold"]), (False, clip["body"])):
        for tid in ids:
            r = turns[tid]
            role = layout["people"].get(r["speaker"]["id"], {}).get("role", "U")
            # Preserve complete sentence audio; timestamps are never supplied by AI.
            item = graphics.Item(tid, 0, None, float(r["start"]), float(r["end"]),
                                 graphics.CC.convert(fixes.get(tid, r["text"])).strip(), role,
                                 tid in clip["gold"], cold)
            previous = items[-1] if items else None
            if (previous and previous.cold == cold and position[tid] == position[previous.tid] + 1
                    and 0 <= item.s - previous.e <= .6 and tid not in clip["chapters"]):
                pieces[-1].items.append(item)
            else:
                pieces.append(graphics.Piece([item], cold, chapter=not cold and tid in clip["chapters"]))
            items.append(item)
    out = 0.0
    for piece in pieces:
        first, last = piece.items[0], piece.items[-1]
        before = rows[position[first.tid] - 1]["end"] if position[first.tid] else 0.0
        after = rows[position[last.tid] + 1]["start"] if position[last.tid] + 1 < len(rows) else doc["job"]["duration_seconds"]
        lo = max(0, first.s - min(.12, max(0, first.s - before) / 2))
        hi = min(doc["job"]["duration_seconds"], last.e + min(.18, max(0, after - last.e) / 2))
        piece.s_q = math.floor(lo * FPS) / FPS
        piece.frames = math.ceil(hi * FPS) - round(piece.s_q * FPS)
        piece.out0 = out
        for k, item in enumerate(piece.items):
            item.out_s, item.out_e = out + item.s - piece.s_q, out + item.e - piece.s_q
            item.piece_out0, item.first_in_piece = out, k == 0
        out += piece.frames / FPS
    total_frames = sum(p.frames for p in pieces)
    shots = plan_shots(items, pieces, total_frames)
    cues = graphics.build_cues(items, out)
    return {"id": clip["id"], "duration": round(out, 6), "total_frames": total_frames,
            "items": [asdict(i) for i in items],
            "pieces": [{"source_start": p.s_q, "source_end": p.s_q + p.frames / FPS,
                        "frames": p.frames, "out": p.out0, "cold": p.cold, "chapter": p.chapter,
                        "turns": [i.tid for i in p.items]} for p in pieces], "shots": shots, "cues": cues}


def graphic_objects(plan: dict):
    items = [graphics.Item(**r) for r in plan["items"]]
    pieces = []
    cursor = 0
    for p in plan["pieces"]:
        count = len(p["turns"])
        pieces.append(graphics.Piece(items[cursor:cursor+count], p["cold"], p["chapter"], p["source_start"], p["frames"], p["out"]))
        cursor += count
    return items, pieces
