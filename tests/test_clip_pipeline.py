import json

import pytest


def test_stage_failure_records_stage_and_safe_error_before_reraising(tmp_path, monkeypatch):
    from live_clip_studio.clips.pipeline import RunState
    monkeypatch.setenv("LIVE_CLIP_API_KEY", "opaque-secret")
    state = RunState(tmp_path, "input-hash")
    with pytest.raises(RuntimeError):
        with state.stage("render"):
            raise RuntimeError("failed opaque-secret")
    result = json.loads((tmp_path / "run.json").read_text())
    assert result["status"] == "failed"
    assert result["failed_stage"] == "render"
    assert result["stages"]["render"]["status"] == "failed"
    assert "opaque-secret" not in (tmp_path / "run.json").read_text()
    assert "opaque-secret" not in (tmp_path / "events.jsonl").read_text()


def test_fingerprint_ignores_export_time_but_invalidates_changed_text_layout_and_decisions():
    from live_clip_studio.clips.pipeline import fingerprint
    doc = {"generated_at": "old", "segments": [{"text": "原文"}]}
    layout = {"scene": [0, 0, 50, 50]}
    old = fingerprint(doc, layout)
    doc["generated_at"] = "new"
    assert fingerprint(doc, layout) == old
    doc["segments"][0]["text"] = "新字幕"
    assert fingerprint(doc, layout) != old
    assert fingerprint(doc, layout, {"clips": [1]}) != fingerprint(doc, layout, {"clips": [2]})
