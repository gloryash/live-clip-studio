from __future__ import annotations

import copy
import difflib
import re

from jsonschema import Draft202012Validator

from .input import validate_transcript


def obj(properties: dict) -> dict:
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


IDS = {"type": "array", "items": {"type": "integer", "minimum": 1}, "uniqueItems": True}
LINES = {"type": "array", "minItems": 2, "maxItems": 2, "items": {"type": "string", "minLength": 1, "maxLength": 12}}
VIRALITY = obj({
    "score": {"type": "integer", "minimum": 0, "maximum": 100},
    "hook_strength": {"type": "integer", "minimum": 1, "maximum": 10},
    "audience_relevance": {"type": "integer", "minimum": 1, "maximum": 10},
    "conflict_or_surprise": {"type": "integer", "minimum": 1, "maximum": 10},
    "standalone_clarity": {"type": "integer", "minimum": 1, "maximum": 10},
    "comment_potential": {"type": "integer", "minimum": 1, "maximum": 10},
    "reason": {"type": "string", "minLength": 8, "maxLength": 240},
    "risk": {"type": "string", "minLength": 1, "maxLength": 160}
})
CLIP_SCHEMA = obj({
    "id": {"type": "string", "pattern": "^[0-9]{2}-[a-z0-9][a-z0-9-]{0,55}$"},
    "mode": {"type": "string", "enum": ["dialogue", "monologue"]},
    "title": LINES, "hook": LINES, "cta": LINES,
    "virality": VIRALITY,
    "cold": {**IDS, "minItems": 1, "maxItems": 5},
    "body": {**IDS, "minItems": 1, "maxItems": 160}, "chapters": IDS,
    "cards": {"type": "array", "maxItems": 4, "items": obj({"at": {"type": "integer"}, "text": {"type": "string", "minLength": 1, "maxLength": 14}})},
    "lists": {"type": "array", "maxItems": 4, "items": obj({"at": {"type": "integer"}, "until": {"type": "integer"}, "text": {"type": "string", "minLength": 1, "maxLength": 22}})},
    "gold": IDS,
    "fix": {"type": "array", "items": obj({"at": {"type": "integer"}, "text": {"type": "string", "minLength": 1, "maxLength": 120}})},
})
DECISION_SCHEMA = obj({"version": {"type": "integer", "const": 1}, "clips": {"type": "array", "minItems": 1, "maxItems": 30, "items": CLIP_SCHEMA}})


def decision_schema(template_id: str = "general") -> dict:
    if template_id == "general":
        return DECISION_SCHEMA
    if template_id != "editorial":
        raise ValueError("TEMPLATE_NOT_FOUND: " + template_id)
    schema = copy.deepcopy(DECISION_SCHEMA)
    clip = schema["properties"]["clips"]["items"]
    clip["properties"]["cold"] = {**IDS, "maxItems": 0}
    clip["properties"]["title"] = copy.deepcopy(LINES)
    clip["properties"]["title"]["items"]["maxLength"] = 24
    clip["properties"]["title_highlights"] = {"type": "array", "maxItems": 4,
        "items": {"type": "string", "minLength": 1, "maxLength": 20}}
    clip["required"].append("title_highlights")
    return schema


class DecisionError(ValueError):
    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("; ".join(errors))


def normalized(text: str) -> str:
    return re.sub(r"[^\w]", "", text).lower()


def validate_decisions(value: dict, transcript: dict, *, min_seconds: float = 60, max_seconds: float = 180,
                       banned_terms: tuple[str, ...] = (), require_dialogue: bool = True, template_id: str = "general") -> dict:
    validate_transcript(transcript)
    schema_errors = list(Draft202012Validator(decision_schema(template_id)).iter_errors(value))
    if schema_errors:
        raise DecisionError([("SCHEMA DUPLICATE_TURN " if e.validator == "uniqueItems" else "SCHEMA ") + "/".join(map(str, e.path)) + ": " + e.message for e in schema_errors][:15])
    if template_id == "editorial":
        max_seconds = 300
    turns = {r["id"]: r for r in transcript["segments"]}
    errors, reports, clip_ids = [], [], set()
    for clip in value["clips"]:
        cid, body, cold = clip["id"], clip["body"], clip["cold"]
        if template_id == "editorial":
            if any(not any(word in line for line in clip["title"]) for word in clip["title_highlights"]):
                errors.append(f"TITLE_HIGHLIGHT {cid}: highlight must occur in a title line")
            ordered = sorted(body, key=lambda tid: turns.get(tid, {}).get("start", 0))
            if ordered != body:
                errors.append(f"BODY_ORDER {cid}: preserve chronological argument")
            if clip["cards"] or clip["lists"]:
                errors.append(f"EDITORIAL_CARDS {cid}: use empty cards/lists")
        if cid in clip_ids:
            errors.append(f"DUPLICATE_CLIP {cid}")
        clip_ids.add(cid)
        if len(body) != len(set(body)):
            errors.append(f"DUPLICATE_TURN {cid}")
        unknown = set(body + cold) - turns.keys()
        if unknown:
            errors.append(f"UNKNOWN_TURN {cid}: {sorted(unknown)}")
        if set(cold) - set(body):
            errors.append(f"COLD_OUTSIDE_BODY {cid}")
        if require_dialogue and clip.get("mode", "monologue") == "dialogue" and len({turns[t].get("speaker", {}).get("id") for t in body if t in turns}) >= 2:
            # This branch is intentionally permissive for mixed/unknown diarization.
            pass
        elif require_dialogue and clip.get("mode", "monologue") == "dialogue" and len({r.get("speaker", {}).get("id") for r in transcript["segments"]}) >= 2:
            errors.append(f"DIALOGUE_REQUIRED {cid}: body must include both sides of the interview")
        for group_name, group in (("cold", cold), ("body", body)):
            indexes = sorted(position for position, tid in enumerate(body) if tid in group)
            if group_name == "cold" and indexes and indexes != list(range(indexes[0], indexes[-1] + 1)):
                errors.append(f"COLD_NOT_CONTIGUOUS {cid}")
        anchors = clip["chapters"] + clip["gold"] + [x["at"] for x in clip["cards"] + clip["lists"] + clip["fix"]] + [x["until"] for x in clip["lists"]]
        if set(anchors) - set(body):
            errors.append(f"ANCHOR_OUTSIDE_BODY {cid}: {sorted(set(anchors) - set(body))}")
        for entry in clip["lists"]:
            if entry["at"] in body and entry["until"] in body and body.index(entry["until"]) < body.index(entry["at"]):
                errors.append(f"LIST_ORDER {cid}")
        for entry in clip["fix"]:
            if entry["at"] in turns:
                a, b = normalized(turns[entry["at"]]["text"]), normalized(entry["text"])
                if difflib.SequenceMatcher(None, a, b, autojunk=False).ratio() < .65:
                    errors.append(f"SUBTITLE_REWRITE {cid}/{entry['at']}: only typo corrections allowed")
        texts = clip["title"] + clip["hook"] + clip["cta"] + [x["text"] for x in clip["cards"] + clip["lists"] + clip["fix"]] + [turns[t]["text"] for t in body if t in turns]
        for term in banned_terms:
            if any(term in text for text in texts):
                errors.append(f"BANNED_TERM {cid}: {term}")
        if unknown:
            continue
        duration = lambda ids: sum(turns[t]["end"] - turns[t]["start"] for t in ids)
        total, hook_duration = duration(body + cold), duration(cold)
        if not min_seconds <= total <= max_seconds:
            errors.append(f"CLIP_DURATION {cid}: {total:.2f}s outside {min_seconds}-{max_seconds}")
        if template_id == "general" and not 3 <= hook_duration <= 7:
            errors.append(f"COLD_DURATION {cid}: {hook_duration:.2f}s outside 3-7")
        reports.append({"id": cid, "speech_seconds": round(total, 3), "cold_seconds": round(hook_duration, 3)})
    if errors:
        raise DecisionError(errors)
    return {"status": "PASS", "clips": reports}
