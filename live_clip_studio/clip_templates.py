from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class ClipTemplate:
    id: str
    name: str
    description: str
    count: int = 3
    revision: int = 1
    accepts_identity: bool = False
    style_summary: str = "固定访谈镜头规则"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


TEMPLATES: dict[str, ClipTemplate] = {
    "general": ClipTemplate(
        id="general",
        name="一般",
        description="访谈观点切片：冷开场、标题卡、镜头循环、金句和互动卡。",
        count=3,
    ),
    "editorial": ClipTemplate(
        id="editorial", name="观点对谈", revision=4,
        description="黑绿观点标题、自然问答、单一画面窗口、克制字幕和栏目署名。",
        accepts_identity=True, style_summary="v4 · 音画关联切换发言者 · 构图按素材分析 · 姓名身份可选填",
    ),
}


def get_template(template_id: str) -> ClipTemplate:
    try:
        return TEMPLATES[template_id]
    except KeyError as exc:
        raise ValueError(f"TEMPLATE_NOT_FOUND: {template_id}") from exc


def list_templates() -> list[dict[str, Any]]:
    return [template.as_dict() for template in TEMPLATES.values()]


def choose_layout(layout_dir: Path, width: int, height: int) -> Path:
    candidates = sorted(layout_dir.glob("*.json"))
    preferred = ["geo.json", "ai-future-720.json", "overseas-720.json", "main-pip.example.json"]
    ordered = [layout_dir / name for name in preferred if (layout_dir / name).is_file()]
    ordered.extend(path for path in candidates if path not in ordered)
    for path in ordered:
        import json

        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if document.get("source_size") == [width, height]:
            return path
    raise ValueError(f"LAYOUT_NOT_FOUND: no layout matches source size {width}x{height}")


def build_layout(layout_path: Path, target: Path) -> Path:
    """Make a run-local copy so template branding never mutates shared layouts."""
    import json

    document = json.loads(layout_path.read_text(encoding="utf-8"))
    document["brand"] = "访谈精选"
    people = document.get("people", {})
    for person in people.values():
        role = person.get("role")
        person["tag"] = ["主持人", "访谈主持"] if role == "H" else ["嘉宾", "访谈嘉宾"]
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def normalize_options(template_id: str, value: Any = None) -> dict[str, Any]:
    """Only explicit user text becomes identity/branding; never infer credentials."""
    get_template(template_id)
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise ValueError("TEMPLATE_OPTIONS: 模板资料必须是对象")
    if template_id == "general":
        if value:
            raise ValueError("TEMPLATE_OPTIONS: 一般模板不接收额外资料")
        return {}
    if set(value) - {"brand", "series", "participants"}:
        raise ValueError("TEMPLATE_OPTIONS: 未知模板资料字段")

    def text(v, limit):
        if not isinstance(v, str) or len(v.strip()) > limit or any(ord(c) < 32 for c in v):
            raise ValueError(f"TEMPLATE_OPTIONS: 请使用 {limit} 字以内的单行文字")
        return v.strip()

    people = value.get("participants", [])
    if not isinstance(people, list) or len(people) > 30:
        raise ValueError("TEMPLATE_OPTIONS: 最多填写 30 位发言者")
    normalized, seen = [], set()
    for person in people:
        if not isinstance(person, dict) or (set(person) - {"speaker_id", "name", "identity", "screen_position"} or not {"speaker_id", "name", "identity"} <= set(person)):
            raise ValueError("TEMPLATE_OPTIONS: 发言者需要 speaker_id、name、identity")
        sid = text(person["speaker_id"], 80)
        if not sid or sid == "UNKNOWN" or sid in seen:
            raise ValueError("TEMPLATE_OPTIONS: 发言者编号为空、未知或重复")
        seen.add(sid)
        name, identity = text(person["name"], 16), text(person["identity"], 32)
        if identity and not name:
            raise ValueError("TEMPLATE_OPTIONS: 填写身份时也请填写姓名或称呼")
        position = person.get("screen_position", "auto")
        if position not in ("auto", "left", "right", "main", "pip"):
            raise ValueError("TEMPLATE_OPTIONS: 出镜位置必须为 auto/left/right/main/pip")
        if name or position != "auto":
            normalized.append({"speaker_id": sid, "name": name, "identity": identity, "screen_position": position})
    return {"brand": text(value.get("brand", ""), 20), "series": text(value.get("series", ""), 32),
            "participants": sorted(normalized, key=lambda p: p["speaker_id"])}


def build_editorial_layout(layout_dir: Path, width: int, height: int, target: Path, options: dict) -> Path:
    import json
    # Matching resolution is not evidence of matching composition. All source
    # coordinates are measured by the audio/visual analysis of this recording.
    scene = [0, 0, width, height]
    full = [0, 0, width, height]
    document = {"version": 1, "source_size": [width, height], "scene": scene,
                "people": {"SOURCE": {"role": "G", "wide": full, "close": full, "tag": ["", ""]}},
                "masks": [], "brand": options["brand"], "template_id": "editorial",
                "template_options": options}
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target
