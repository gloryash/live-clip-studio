import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "render_viral_clips", ROOT / "tools" / "render_viral_clips.py"
)


def load_module():
    module = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(module)
    return module


def test_manifest_has_three_valid_clips_under_180_seconds():
    module = load_module()
    manifest = json.loads(
        (ROOT / "edits/02a0cf90-fd57-4117-b207-df0d5b0acb6e/edit-manifest.json").read_text()
    )
    module.validate_manifest(manifest)
    assert len(manifest["clips"]) == 3
    assert all(module.clip_duration(clip) < 180 for clip in manifest["clips"])


def test_source_time_maps_to_concatenated_timeline():
    module = load_module()
    clip = {"segments": [{"start": 10, "end": 20}, {"start": 50, "end": 65}]}
    assert module.map_source_time(clip, 12) == 2
    assert module.map_source_time(clip, 55) == 15
    assert module.map_source_time(clip, 40) is None


def test_transcript_segments_are_clipped_and_remapped():
    module = load_module()
    clip = {"segments": [{"start": 10, "end": 20}, {"start": 50, "end": 60}]}
    transcript = [
        {"start": 8, "end": 12, "text": "A"},
        {"start": 18, "end": 22, "text": "B"},
        {"start": 52, "end": 54, "text": "C"},
    ]
    result = module.remap_subtitles(clip, transcript)
    assert result == [
        {"start": 0.0, "end": 2.0, "text": "A"},
        {"start": 8.0, "end": 10.0, "text": "B"},
        {"start": 12.0, "end": 14.0, "text": "C"},
    ]


def test_manifest_rejects_reversed_segment():
    module = load_module()
    manifest = {
        "source": "source.mp4",
        "transcript": "segments.json",
        "output_dir": "exports",
        "clips": [{"id": "bad", "title": "x", "hook": "x", "promise": "x", "segments": [{"start": 2, "end": 1}]}],
    }
    try:
        module.validate_manifest(manifest)
    except ValueError as exc:
        assert "end must be greater" in str(exc)
    else:
        raise AssertionError("invalid segment was accepted")
