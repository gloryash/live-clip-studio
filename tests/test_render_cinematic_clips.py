import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "render_cinematic_clips", ROOT / "tools" / "render_cinematic_clips.py"
)


def load_module():
    module = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(module)
    return module


def test_dominant_speaker_uses_overlap_duration():
    module = load_module()
    turns = [
        {"start": 10, "end": 13, "speaker": "S000"},
        {"start": 13, "end": 18, "speaker": "S001"},
    ]
    assert module.dominant_speaker(turns, 11, 17) == "S001"


def test_shot_plan_contains_all_layouts_and_preserves_duration():
    module = load_module()
    clip = {"segments": [{"start": 100, "end": 130}]}
    turns = [
        {"start": 100, "end": 110, "speaker": "S000"},
        {"start": 110, "end": 120, "speaker": "S001"},
        {"start": 120, "end": 130, "speaker": "S000"},
    ]
    shots = module.plan_shots(clip, turns)
    assert round(sum(s["end"] - s["start"] for s in shots), 3) == 30
    assert {s["layout"] for s in shots} >= {"left", "right", "dual"}
    assert all((s["end"] - s["start"] <= 6.1) or s["layout"] == "dual" for s in shots)


def test_reaction_shots_are_short():
    module = load_module()
    clip = {"segments": [{"start": 0, "end": 40}]}
    turns = [{"start": 0, "end": 40, "speaker": "S000"}]
    shots = module.plan_shots(clip, turns)
    reactions = [s for s in shots if s.get("reaction")]
    assert reactions
    assert all(s["end"] - s["start"] <= 0.8 for s in reactions)


def test_subtitle_cleanup_removes_leading_fillers():
    module = load_module()
    assert module.clean_caption("然后其实我觉得这个机会很大") == "这个机会很大"
    assert module.clean_caption("呃2000万") == "2000万"
