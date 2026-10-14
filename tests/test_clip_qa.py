import pytest


def test_qa_comparison_flags_multi_character_deletion_near_cut():
    from live_clip_studio.clips.qa import compare_speech
    result = compare_speech("假设你在做生意", [{"text": "做生意", "start": 3.1}], [3.0])
    assert result["status"] == "REVIEW"
    assert result["issues"][0]["expected"] == "假设你在"
    assert result["issues"][0]["near_cut"] < .6


def test_technical_qa_requires_audio_and_plan_duration():
    from live_clip_studio.clips.qa import check_probe
    good = {"streams": [{"codec_type": "video", "width": 1080, "height": 1920, "codec_name": "h264", "pix_fmt": "yuv420p", "duration": "75", "avg_frame_rate": "30/1"},
                        {"codec_type": "audio", "codec_name": "aac", "duration": "75.02"}]}
    assert check_probe(good, 75)["status"] == "PASS"
    with pytest.raises(ValueError, match="AUDIO"):
        check_probe({"streams": good["streams"][:1]}, 75)
    with pytest.raises(ValueError, match="DURATION"):
        check_probe(good, 100)
