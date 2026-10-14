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

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


TEMPLATES: dict[str, ClipTemplate] = {
    "general": ClipTemplate(
        id="general",
        name="一般",
        description="访谈观点切片：冷开场、标题卡、镜头循环、金句和互动卡。",
        count=3,
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
