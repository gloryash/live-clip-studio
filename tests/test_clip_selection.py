import copy

import pytest

from test_clip_contract import document, decision


def test_windowing_covers_every_turn_even_long_transcripts():
    from live_clip_studio.clips.selection import transcript_windows
    rows = document()["segments"] * 15
    windows = transcript_windows(rows, max_chars=300)
    assert [r for window in windows for r in window] == rows
    assert len(windows) > 1


def test_invalid_ai_decision_gets_one_repair_then_real_validation(tmp_path):
    from live_clip_studio.clips.selection import generate_clip
    class Model:
        def __init__(self): self.calls = 0
        def request(self, prompt, schema, evidence, **kwargs):
            self.calls += 1
            if self.calls == 1:
                result = copy.deepcopy(decision())
                result["clips"][0]["body"].append(999)
                return result
            assert "UNKNOWN_TURN" in prompt
            return decision()
    model = Model()
    clip = generate_clip(model, document(), {"start_id": 10, "end_id": 35, "topic": "完整观点"}, tmp_path / "detail")
    assert clip["body"] == [20, 10, 35]
    assert (tmp_path / "detail-validation-1.json").exists()


def test_repair_is_bounded_and_does_not_silently_drop_bad_clip(tmp_path):
    from live_clip_studio.clips.selection import generate_clip
    class BadModel:
        def request(self, *args, **kwargs): return {"version": 1, "clips": []}
    with pytest.raises(ValueError, match="SCHEMA"):
        generate_clip(BadModel(), document(), {"start_id": 10, "end_id": 35, "topic": "观点"}, tmp_path / "detail")
