from live_clip_studio.transcript import build_speaker_turns


def test_build_speaker_turns_preserves_every_segment_and_time() -> None:
    segments = [
        {"start": 0.2, "end": 1.4, "text": "你好"},
        {"start": 1.5, "end": 3.0, "text": "欢迎来到直播间"},
    ]
    labels = [
        {"speaker": "SPEAKER_00", "speaker_source": "embedding"},
        {"speaker": "SPEAKER_01", "speaker_source": "embedding"},
    ]

    turns = build_speaker_turns(segments, labels)

    assert [turn["text"] for turn in turns] == ["你好", "欢迎来到直播间"]
    assert [turn["speaker_label"] for turn in turns] == ["说话人 1", "说话人 2"]
    assert turns[0]["start"] == 0.2
    assert turns[1]["end"] == 3.0
