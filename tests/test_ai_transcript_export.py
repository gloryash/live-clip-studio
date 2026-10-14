from __future__ import annotations

from live_clip_studio.ai_transcript_export import (
    build_ai_transcript_document,
    build_character_timing,
    recover_words_by_turn,
)


def assert_character_timeline_is_valid(
    characters: list[dict],
    *,
    text: str,
    start: float,
    end: float,
) -> None:
    assert "".join(item["text"] for item in characters) == text
    previous_end = start
    for character in characters:
        assert start <= character["start"] <= character["end"] <= end
        assert character["start"] >= previous_end
        previous_end = character["end"]


def test_character_timing_distinguishes_whisper_interpolation_and_punctuation() -> None:
    words = [
        {
            "text": "好,",
            "start": 1.0,
            "end": 1.4,
            "probability": 0.9,
            "valid_timing": True,
        },
        {
            "text": "今天",
            "start": 1.6,
            "end": 2.0,
            "probability": 0.8,
            "valid_timing": True,
        },
    ]

    characters, timing_quality, warnings = build_character_timing(
        "好,今天",
        start=1.0,
        end=2.0,
        words=words,
    )

    assert_character_timeline_is_valid(characters, text="好,今天", start=1.0, end=2.0)
    assert [(item["text"], item["timing_source"]) for item in characters] == [
        ("好", "whisper_word"),
        (",", "synthetic_boundary"),
        ("今", "interpolated_within_word"),
        ("天", "interpolated_within_word"),
    ]
    assert [(item["start"], item["end"]) for item in characters] == [
        (1.0, 1.4),
        (1.4, 1.4),
        (1.6, 1.8),
        (1.8, 2.0),
    ]
    assert timing_quality == "whisper_words_with_interpolation"
    assert warnings == []


def test_character_timing_falls_back_when_word_text_does_not_align() -> None:
    characters, timing_quality, warnings = build_character_timing(
        "完全不同",
        start=2.0,
        end=4.0,
        words=[
            {
                "text": "接通",
                "start": 2.0,
                "end": 4.0,
                "probability": 0.9,
                "valid_timing": True,
            }
        ],
    )

    assert_character_timeline_is_valid(characters, text="完全不同", start=2.0, end=4.0)
    assert {item["timing_source"] for item in characters} == {"interpolated_within_segment"}
    assert timing_quality == "segment_interpolation"
    assert warnings == ["word text did not align with segment text"]


def test_character_timing_keeps_whisper_time_when_only_boundaries_differ() -> None:
    characters, timing_quality, warnings = build_character_timing(
        "你好，世界。",
        start=1.0,
        end=2.0,
        words=[
            {
                "text": "你好,",
                "start": 1.0,
                "end": 1.4,
                "probability": 0.9,
                "valid_timing": True,
            },
            {
                "text": "世界",
                "start": 1.6,
                "end": 2.0,
                "probability": 0.8,
                "valid_timing": True,
            },
        ],
    )

    assert_character_timeline_is_valid(characters, text="你好，世界。", start=1.0, end=2.0)
    assert [(item["text"], item["timing_source"]) for item in characters] == [
        ("你", "interpolated_within_word"),
        ("好", "interpolated_within_word"),
        ("，", "synthetic_boundary"),
        ("世", "interpolated_within_word"),
        ("界", "interpolated_within_word"),
        ("。", "synthetic_boundary"),
    ]
    assert [(item["start"], item["end"]) for item in characters] == [
        (1.0, 1.2),
        (1.2, 1.4),
        (1.4, 1.4),
        (1.6, 1.8),
        (1.8, 2.0),
        (2.0, 2.0),
    ]
    assert timing_quality == "whisper_words_with_interpolation"
    assert warnings == []


def test_character_timing_uses_neighbor_bounds_for_invalid_word() -> None:
    characters, timing_quality, warnings = build_character_timing(
        "字幕",
        start=28.58,
        end=29.98,
        words=[
            {
                "text": "字",
                "start": 28.58,
                "end": 29.0,
                "probability": 0.25,
                "valid_timing": True,
            },
            {
                "text": "幕",
                "start": 29.0,
                "end": 29.0,
                "probability": 0.75,
                "valid_timing": False,
            },
        ],
    )

    assert_character_timeline_is_valid(characters, text="字幕", start=28.58, end=29.98)
    assert characters[0]["timing_source"] == "whisper_word"
    assert characters[1] == {
        "index": 1,
        "text": "幕",
        "start": 29.0,
        "end": 29.98,
        "probability": 0.75,
        "timing_source": "interpolated_within_segment",
        "word_index": 1,
    }
    assert timing_quality == "mixed_with_segment_fallback"
    assert warnings == ["1 word token had invalid timing"]


def test_recover_words_uses_raw_segments_for_legacy_jobs() -> None:
    turns = [{"id": 1, "start": 212.36, "end": 213.48, "text": "接通一下"}]
    saved_segments = [{"start": 212.36, "end": 213.48, "text": "接通一下"}]
    raw_segments = [
        {
            "start": 208.24,
            "end": 214.6,
            "text": "接通一下",
            "words": [
                {"word": "接通", "start": 212.36, "end": 212.92, "probability": 0.9},
                {"word": "一下", "start": 212.92, "end": 213.48, "probability": 0.8},
            ],
        }
    ]

    recovered = recover_words_by_turn(turns, saved_segments, raw_segments)

    assert [item["text"] for item in recovered[1]] == ["接通", "一下"]
    assert all(item["valid_timing"] for item in recovered[1])


def test_recover_words_advances_raw_cursor_after_saved_words_for_repeated_text() -> None:
    turns = [
        {"id": 1, "start": 0.0, "end": 1.0, "text": "嗯"},
        {"id": 2, "start": 1.0, "end": 2.0, "text": "嗯"},
    ]
    saved_segments = [
        {
            "start": 0.0,
            "end": 1.0,
            "text": "嗯",
            "words": [
                {"text": "嗯", "start": 0.1, "end": 0.9, "probability": 0.9, "valid_timing": True},
            ],
        },
        {"start": 1.0, "end": 2.0, "text": "嗯"},
    ]
    raw_segments = [
        {
            "start": 0.0,
            "end": 1.0,
            "text": "嗯",
            "words": [{"word": "嗯", "start": 0.1, "end": 0.9}],
        },
        {
            "start": 1.0,
            "end": 2.0,
            "text": "嗯",
            "words": [{"word": "嗯", "start": 1.1, "end": 1.9}],
        },
    ]

    recovered = recover_words_by_turn(turns, saved_segments, raw_segments)

    assert recovered[1][0]["start"] == 0.1
    assert recovered[2][0]["start"] == 1.1


def test_export_document_prefers_manual_speaker_keeps_unknown_and_excludes_deleted() -> None:
    turns = [
        {"id": 1, "start": 0.0, "end": 1.0, "text": "你好"},
        {"id": 2, "start": 1.0, "end": 2.0, "text": "收到"},
        {"id": 3, "start": 2.0, "end": 3.0, "text": "删除我"},
    ]
    saved_segments = [
        {
            **turn,
            "words": [
                {
                    "text": turn["text"],
                    "start": turn["start"],
                    "end": turn["end"],
                    "probability": 0.9,
                    "valid_timing": True,
                }
            ],
        }
        for turn in turns
    ]

    result = build_ai_transcript_document(
        job={"job_id": "abc", "filename": "整场对话.mp4"},
        media={"duration_seconds": 3.0},
        transcript={"turns": turns},
        saved_segments=saved_segments,
        raw={
            "model": "mlx-community/whisper-large-v3-turbo",
            "language": "zh",
            "segments": [],
        },
        predictions={
            "predictions": {
                "1": {"speaker_id": "SPEAKER_00", "confidence": 0.8, "source": "registered_embedding"},
                "2": {"speaker_id": "UNKNOWN", "confidence": 0.0, "source": "unknown"},
                "3": {"speaker_id": "SPEAKER_00", "confidence": 0.7, "source": "registered_embedding"},
            }
        },
        speakers={"SPEAKER_00": "monica", "SPEAKER_01": "威律师"},
        annotations={"1": "SPEAKER_01"},
        deleted_turn_ids={3},
    )

    assert result["format"] == "live-clip-studio.ai-transcript"
    assert result["version"] == 1
    assert [item["id"] for item in result["segments"]] == [1, 2]
    assert result["segments"][0]["speaker"] == {
        "id": "SPEAKER_01",
        "name": "威律师",
        "source": "manual",
        "confidence": None,
        "manual_override": True,
    }
    assert result["segments"][1]["speaker"] == {
        "id": "UNKNOWN",
        "name": "无法判断",
        "source": "unknown",
        "confidence": 0.0,
        "manual_override": False,
    }
    assert result["quality"]["segment_count"] == 2
    assert result["quality"]["deleted_segment_count"] == 1
    assert result["quality"]["unknown_speaker_count"] == 1
    assert sum(result["quality"]["character_timing_counts"].values()) == result["quality"]["character_count"]
    assert "[00:00:00.000–00:00:01.000] 威律师：你好" in result["dialogue_text"]
    assert "删除我" not in result["dialogue_text"]


def test_export_document_marks_qwen_text_and_does_not_relabel_whisper_word_time() -> None:
    turn = {
        "id": 1,
        "start": 0.0,
        "end": 1.0,
        "text": "数学伴终端",
        "original_text": "数学办终端",
        "text_source": "qwen_text_correction",
        "correction_confidence": 0.98,
        "correction_reason": "修正专有名词。",
        "correction_provider": "dashscope",
        "correction_model": "qwen3.7-max",
    }
    saved_segment = {
        **turn,
        "words": [
            {
                "text": "数学办终端",
                "start": 0.0,
                "end": 1.0,
                "probability": 0.82,
                "valid_timing": True,
            }
        ],
    }

    result = build_ai_transcript_document(
        job={"job_id": "reviewed", "filename": "插件绑定.mp4"},
        media={"duration_seconds": 1.0},
        transcript={"turns": [turn]},
        saved_segments=[saved_segment],
        raw={
            "model": "mlx-community/whisper-large-v3-turbo",
            "language": "zh",
            "correction": {
                "status": "succeeded",
                "provider": "dashscope",
                "model": "qwen3.7-max",
            },
            "segments": [],
        },
        predictions={"predictions": {}},
        speakers={},
        annotations={},
        deleted_turn_ids=set(),
    )

    segment = result["segments"][0]
    assert segment["text"] == "数学伴终端"
    assert segment["original_text"] == "数学办终端"
    assert segment["text_source"] == "qwen_text_correction"
    assert segment["correction"] == {
        "provider": "dashscope",
        "model": "qwen3.7-max",
        "confidence": 0.98,
        "reason": "修正专有名词。",
    }
    assert segment["timing_quality"] == "segment_interpolation"
    assert segment["words"][0]["text"] == "数学办终端"
    assert segment["words"][0]["timing_source"] == "whisper_word"
    assert {item["timing_source"] for item in segment["characters"]} == {
        "interpolated_within_segment"
    }
    assert "word text did not align with segment text" in segment["warnings"]
    assert result["transcription"]["text_correction"] == {
        "status": "succeeded",
        "provider": "dashscope",
        "model": "qwen3.7-max",
        "audio_sent_to_correction_model": False,
        "word_timestamps": "original_only",
    }
