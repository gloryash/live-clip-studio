import copy
import json

import pytest


def document():
    return {"format": "live-clip-studio.ai-transcript", "version": 1,
            "job": {"id": "other-live", "duration_seconds": 150},
            "segments": [{"id": k, "start": a, "end": b, "text": text,
                          "speaker": {"id": speaker}, "characters": []}
                         for k, a, b, text, speaker in
                         [(10, 1, 5, "反常识的完整一句", "guest"),
                          (20, 10, 42, "为什么这样呢", "host"),
                          (35, 45, 78, "这是完整论证", "guest")]]}


def decision():
    return {"version": 1, "clips": [{"id": "01-example", "mode": "monologue", "title": ["一个观点", "完整论证"],
        "virality": {"score": 72, "hook_strength": 8, "audience_relevance": 7, "conflict_or_surprise": 8, "standalone_clarity": 8, "comment_potential": 6, "reason": "有冲突且能独立理解", "risk": "专业词略多"},
        "hook": ["真的如此吗", "为什么"], "cta": ["你怎么看", "留言讨论"],
        "cold": [10], "body": [20, 10, 35], "chapters": [35],
        "cards": [{"at": 35, "text": "背后的原因"}], "lists": [], "gold": [10], "fix": []}]}


def test_decision_uses_real_ids_and_duration_not_id_position():
    from live_clip_studio.clips.contract import validate_decisions
    result = validate_decisions(decision(), document())
    assert result["clips"][0]["speech_seconds"] == 73
    assert result["clips"][0]["cold_seconds"] == 4


def test_interview_decision_must_include_both_speakers():
    from live_clip_studio.clips.contract import DecisionError, validate_decisions
    d = document()
    value = decision()
    value["clips"][0]["mode"] = "dialogue"
    d["segments"].append({"id": 99, "start": 80, "end": 84, "text": "主持人提问", "speaker": {"id": "host"}, "characters": []})
    for row in d["segments"][:3]:
        row["speaker"]["id"] = "guest"
    with pytest.raises(DecisionError, match="DIALOGUE_REQUIRED"):
        validate_decisions(value, d)


@pytest.mark.parametrize("change,code", [
    (lambda c: c["body"].append(999), "UNKNOWN_TURN"),
    (lambda c: c["body"].append(10), "DUPLICATE_TURN"),
    (lambda c: c.update(cold=[20]), "COLD_DURATION"),
    (lambda c: c["cards"][0].update(at=999), "ANCHOR_OUTSIDE_BODY"),
    (lambda c: c.update(body=[10]), "CLIP_DURATION"),
    (lambda c: c.update(id="../../escape"), "SCHEMA"),
    (lambda c: c.update(retime={"10": [0, 99]}), "SCHEMA"),
    (lambda c: c.update(fix=[{"at": 10, "text": "这就是不存在的全新发言"}]), "SUBTITLE_REWRITE"),
])
def test_bad_decisions_are_rejected_before_render(change, code):
    from live_clip_studio.clips.contract import DecisionError, validate_decisions
    value = copy.deepcopy(decision())
    change(value["clips"][0])
    with pytest.raises(DecisionError) as err:
        validate_decisions(value, document())
    assert code in str(err.value)


def test_input_keeps_manual_speaker_and_deletion(tmp_path):
    from live_clip_studio.clips.input import export_job
    t = tmp_path / "transcript"
    t.mkdir()
    files = {"job.json": {"job_id": "new", "filename": "new.mp4"},
        "media.json": {"duration_seconds": 100},
        "transcript/speaker-turns.json": {"turns": [
            {"id": 10, "start": 1, "end": 5, "text": "完整一句"},
            {"id": 35, "start": 6, "end": 9, "text": "已删除"}]},
        "transcript/segments.json": {"segments": []},
        "transcript/speaker-predictions.json": {"predictions": {"10": {"speaker_id": "guest"}}},
        "transcript/manual-speakers.json": {"speakers": {"host": "主持", "guest": "嘉宾"}},
        "transcript/manual-speaker-labels.json": {"annotations": {"10": "host"}},
        "transcript/deleted-turns.json": {"deleted_turn_ids": [35]}}
    for path, value in files.items():
        (tmp_path / path).write_text(json.dumps(value))
    result = export_job(tmp_path)
    assert [s["id"] for s in result["segments"]] == [10]
    assert result["segments"][0]["speaker"]["id"] == "host"
    assert result["segments"][0]["speaker"]["manual_override"] is True


def test_input_rejects_duplicate_ids_and_out_of_source_times():
    from live_clip_studio.clips.input import validate_transcript
    d = document()
    d["segments"][1]["id"] = 10
    with pytest.raises(ValueError, match="DUPLICATE"):
        validate_transcript(d)
    d = document()
    d["segments"][1]["end"] = 200
    with pytest.raises(ValueError, match="TIME"):
        validate_transcript(d)
