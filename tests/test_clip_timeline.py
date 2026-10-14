import pytest

from test_clip_contract import document, decision


def layout():
    return {"version": 1, "source_size": [912, 1920], "scene": [0, 588, 912, 744],
        "people": {"host": {"role": "H", "wide": [0, 608, 456, 566], "close": [10, 633, 410, 509], "tag": ["主持", "访谈"]},
                   "guest": {"role": "G", "wide": [456, 608, 456, 566], "close": [482, 638, 410, 509], "tag": ["嘉宾", "访谈"]}},
        "brand": "访谈精选", "masks": []}


def test_layout_rejects_out_of_bounds_and_accepts_pip_coordinates():
    from live_clip_studio.clips.timeline import validate_layout
    l = layout()
    validate_layout(l, 912, 1920)
    l["people"]["guest"]["close"] = [850, 0, 410, 509]
    with pytest.raises(ValueError, match="RECT"):
        validate_layout(l, 912, 1920)
    l["people"]["guest"]["close"] = [700, 20, 200, 300]
    validate_layout(l, 912, 1920)


def test_timeline_preserves_words_and_unknown_does_not_inherit_previous_speaker():
    from live_clip_studio.clips.timeline import make_plan
    d = document()
    d["segments"][2]["speaker"]["id"] = "UNKNOWN"
    plan = make_plan(decision()["clips"][0], d, layout())
    # Output begins with the chosen quote, then exact selected source segments.
    assert [i["tid"] for i in plan["items"]] == [10, 20, 10, 35]
    assert plan["pieces"][0]["source_start"] <= 1
    assert plan["pieces"][0]["source_end"] >= 5
    assert plan["items"][-1]["speaker"] == "U"
    unknown_start = plan["items"][-1]["out_s"]
    assert all(s["mode"] == "duo" for s in plan["shots"] if s["a"] >= unknown_start)
    shots = plan["shots"]
    assert shots[0]["fa"] == 0
    assert shots[-1]["fb"] == plan["total_frames"]
    assert all(a["fb"] == b["fa"] for a, b in zip(shots, shots[1:]))
    assert max(s["fb"] - s["fa"] for s in shots) <= 225


def test_visual_cut_prefers_sentence_boundary_and_continues_long_sentence():
    from live_clip_studio.clips.timeline import make_plan
    plan = make_plan(decision()["clips"][0], document(), layout())
    assert all(s["fb"] > s["fa"] for s in plan["shots"])
    assert plan["duration"] >= 73
