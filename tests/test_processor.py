from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np

from live_clip_studio.config import Settings
from live_clip_studio.jobs import JobProcessor, JobStore
from live_clip_studio.transcript import apply_text_correction, clean_segments


class FakeWhisper:
    def transcribe(self, audio_path: Path, **_: object) -> dict:
        assert audio_path.is_file()
        return {
            "raw_text": "你好尾部幻觉",
            "text": "你好尾部幻觉",
            "segments": [
                {"start": 0.1, "end": 0.7, "text": "你好"},
                {"start": 5.0, "end": 8.0, "text": "尾部幻觉"},
            ],
            "model": "mlx-community/whisper-large-v3-turbo",
            "whisper_job_id": "job-asr",
        }


class CorrectedWhisper:
    def transcribe(self, audio_path: Path, **_: object) -> dict:
        assert audio_path.is_file()
        return {
            "raw_text": "数字学办终端",
            "text": "数学办终端",
            "segments": [
                {
                    "start": 0.1,
                    "end": 0.7,
                    "text": "数学办终端",
                    "words": [
                        {
                            "word": "数字学办终端",
                            "start": 0.1,
                            "end": 0.7,
                            "probability": 0.82,
                        }
                    ],
                }
            ],
            "model": "mlx-community/whisper-large-v3-turbo",
            "whisper_job_id": "job-reviewed",
            "correction": {
                "type": "cloud_text_model",
                "status": "succeeded",
                "provider": "dashscope",
                "model": "qwen3.7-max",
                "segments": [
                    {
                        "index": 0,
                        "original_text": "数学办终端",
                        "corrected_text": "数学伴终端",
                        "confidence": 0.98,
                        "reason": "结合全文修正专有名词。",
                    }
                ],
            },
        }


class UnavailableDiarizer:
    def run(self, audio_path: Path, segments: list[dict]) -> dict:
        assert audio_path.is_file()
        assert len(segments) == 1
        return {
            "status": "unavailable",
            "detail": "speaker model unavailable",
            "speaker_count": None,
            "labels": [],
        }


class EmbeddingDiarizer:
    def run(self, audio_path: Path, segments: list[dict]) -> dict:
        assert audio_path.is_file()
        assert len(segments) == 1
        return {
            "status": "ready",
            "detail": None,
            "speaker_count": 1,
            "labels": [{"speaker": "SPEAKER_00", "speaker_source": "embedding"}],
            "embedding_cache": {
                "model": "ECAPA",
                "similarity_threshold": 0.25,
                "embeddings": np.asarray([[1.0, 0.0, 0.0]], dtype=np.float32),
                "indices": np.asarray([0], dtype=np.int32),
            },
        }


class InlineExecutor:
    def __init__(self) -> None:
        self.calls = 0

    def submit(self, function, *args):
        self.calls += 1
        function(*args)
        return None


def test_processor_preserves_raw_filters_tail_and_writes_honest_fallback(
    tmp_path: Path,
    sample_mp4: Path,
) -> None:
    settings = Settings(data_dir=tmp_path / "data", whisper_timeout_seconds=12)
    store = JobStore(settings.data_dir)
    job = store.create("live.mp4")
    job_dir = store.job_dir(job["job_id"])
    shutil.copy2(sample_mp4, job_dir / "source.mp4")
    (job_dir / "media.json").write_text(
        json.dumps({"duration_seconds": 1.0}),
        encoding="utf-8",
    )
    processor = JobProcessor(
        store=store,
        settings=settings,
        whisper_client=FakeWhisper(),
        diarizer=UnavailableDiarizer(),
        executor=InlineExecutor(),
    )

    processor.process_transcript(job["job_id"])

    completed = store.get(job["job_id"])
    raw = json.loads((job_dir / "transcript" / "raw.json").read_text())
    segments = json.loads((job_dir / "transcript" / "segments.json").read_text())["segments"]
    speaker_document = json.loads((job_dir / "transcript" / "speaker-turns.json").read_text())
    assert completed["status"] == "ready"
    assert completed["progress"] == 100
    assert raw["raw_text"] == "你好尾部幻觉"
    assert segments == [{"start": 0.1, "end": 0.7, "text": "你好"}]
    assert speaker_document["diarization"]["status"] == "unavailable"
    assert speaker_document["speaker_count"] is None
    assert speaker_document["turns"][0]["speaker_label"] == "说话人未知"


def test_processor_uses_qwen_text_but_keeps_whisper_words_and_raw_result(
    tmp_path: Path,
    sample_mp4: Path,
) -> None:
    settings = Settings(data_dir=tmp_path / "data", whisper_timeout_seconds=12)
    store = JobStore(settings.data_dir)
    job = store.create("reviewed.mp4")
    job_dir = store.job_dir(job["job_id"])
    shutil.copy2(sample_mp4, job_dir / "source.mp4")
    (job_dir / "media.json").write_text(
        json.dumps({"duration_seconds": 1.0}),
        encoding="utf-8",
    )
    processor = JobProcessor(
        store=store,
        settings=settings,
        whisper_client=CorrectedWhisper(),
        diarizer=UnavailableDiarizer(),
        executor=InlineExecutor(),
    )

    processor.process_transcript(job["job_id"])

    raw = json.loads((job_dir / "transcript" / "raw.json").read_text())
    segment = json.loads(
        (job_dir / "transcript" / "segments.json").read_text()
    )["segments"][0]
    turn = json.loads(
        (job_dir / "transcript" / "speaker-turns.json").read_text()
    )["turns"][0]
    assert raw["segments"][0]["text"] == "数学办终端"
    assert segment["text"] == "数学伴终端"
    assert segment["original_text"] == "数学办终端"
    assert segment["text_source"] == "qwen_text_correction"
    assert segment["correction_confidence"] == 0.98
    assert segment["correction_reason"] == "结合全文修正专有名词。"
    assert segment["words"][0]["text"] == "数字学办终端"
    assert segment["words"][0]["start"] == 0.1
    assert segment["words"][0]["end"] == 0.7
    assert turn["text"] == "数学伴终端"
    assert turn["original_text"] == "数学办终端"
    assert turn["text_source"] == "qwen_text_correction"


def test_submit_transcript_uses_executor_once(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "data")
    executor = InlineExecutor()
    processor = JobProcessor(
        store=JobStore(settings.data_dir),
        settings=settings,
        whisper_client=FakeWhisper(),
        diarizer=UnavailableDiarizer(),
        executor=executor,
    )
    processor.process_transcript = lambda job_id: None

    processor.submit_transcript("abc")

    assert executor.calls == 1


def test_processor_persists_embedding_cache_and_label_free_candidates(
    tmp_path: Path,
    sample_mp4: Path,
) -> None:
    settings = Settings(data_dir=tmp_path / "data", whisper_timeout_seconds=12)
    store = JobStore(settings.data_dir)
    job = store.create("live.mp4")
    job_dir = store.job_dir(job["job_id"])
    shutil.copy2(sample_mp4, job_dir / "source.mp4")
    (job_dir / "media.json").write_text(
        json.dumps({"duration_seconds": 1.0}),
        encoding="utf-8",
    )
    processor = JobProcessor(
        store=store,
        settings=settings,
        whisper_client=FakeWhisper(),
        diarizer=EmbeddingDiarizer(),
        executor=InlineExecutor(),
    )

    processor.process_transcript(job["job_id"])

    embedding_path = job_dir / "transcript" / "speaker-embeddings.npz"
    candidate_path = job_dir / "transcript" / "speaker-candidates.json"
    assert embedding_path.is_file()
    with np.load(embedding_path) as cache:
        assert cache["embeddings"].shape == (1, 3)
        assert cache["indices"].tolist() == [0]
    candidates = json.loads(candidate_path.read_text())
    assert candidates["speaker_count"] == 1
    assert candidates["candidates"][0]["candidate_id"] == "S000"
    turns = json.loads(
        (job_dir / "transcript" / "speaker-turns.json").read_text()
    )["turns"]
    assert turns[0]["speaker"] == "S000"
    assert turns[0]["speaker_label"] == "说话人 1"


def test_clean_segments_uses_word_timestamps_to_remove_model_window_silence() -> None:
    result = {
        "segments": [
            {
                "start": 208.24,
                "end": 214.60,
                "text": "接通一下",
                "words": [
                    {"word": "接通", "start": 212.36, "end": 212.92},
                    {"word": "一下", "start": 212.92, "end": 213.48},
                ],
            }
        ]
    }

    assert clean_segments(result, duration_seconds=300.0) == [
        {
            "start": 212.36,
            "end": 213.48,
            "text": "接通一下",
            "words": [
                {
                    "text": "接通",
                    "start": 212.36,
                    "end": 212.92,
                    "probability": None,
                    "valid_timing": True,
                },
                {
                    "text": "一下",
                    "start": 212.92,
                    "end": 213.48,
                    "probability": None,
                    "valid_timing": True,
                },
            ],
        }
    ]


def test_apply_text_correction_is_strict_and_does_not_mutate_whisper_result() -> None:
    result = {
        "segments": [
            {
                "start": 1.0,
                "end": 2.0,
                "text": "你好，我是文杰列夫",
                "words": [
                    {
                        "word": "你好，我是文杰列夫",
                        "start": 1.0,
                        "end": 2.0,
                        "probability": 0.7,
                    }
                ],
            }
        ],
        "correction": {
            "status": "succeeded",
            "provider": "dashscope",
            "model": "qwen3.7-max",
            "segments": [
                {
                    "index": 0,
                    "original_text": "你好，我是文杰列夫",
                    "corrected_text": "你好，我是门捷列夫",
                    "confidence": 0.99,
                    "reason": "修正人物姓名。",
                }
            ],
        },
    }

    effective = apply_text_correction(result)

    assert result["segments"][0]["text"] == "你好，我是文杰列夫"
    assert effective["segments"][0] == {
        "start": 1.0,
        "end": 2.0,
        "text": "你好，我是门捷列夫",
        "original_text": "你好，我是文杰列夫",
        "text_source": "qwen_text_correction",
        "correction_confidence": 0.99,
        "correction_reason": "修正人物姓名。",
        "correction_provider": "dashscope",
        "correction_model": "qwen3.7-max",
        "words": [
            {
                "word": "你好，我是文杰列夫",
                "start": 1.0,
                "end": 2.0,
                "probability": 0.7,
            }
        ],
    }


def test_apply_text_correction_rejects_failed_or_misaligned_reviews() -> None:
    source = {
        "segments": [{"start": 0.0, "end": 1.0, "text": "学办"}],
        "correction": {
            "status": "succeeded",
            "segments": [
                {
                    "index": 0,
                    "original_text": "另一句",
                    "corrected_text": "学伴",
                }
            ],
        },
    }
    failed = {
        **source,
        "correction": {
            "status": "failed",
            "segments": [
                {
                    "index": 0,
                    "original_text": "学办",
                    "corrected_text": "学伴",
                }
            ],
        },
    }
    fractional_index = {
        **source,
        "correction": {
            "status": "succeeded",
            "segments": [
                {
                    "index": 0.5,
                    "original_text": "学办",
                    "corrected_text": "学伴",
                }
            ],
        },
    }

    assert apply_text_correction(source)["segments"] == source["segments"]
    assert apply_text_correction(failed)["segments"] == failed["segments"]
    assert apply_text_correction(fractional_index)["segments"] == fractional_index["segments"]


def test_clean_segments_preserves_invalid_word_timing_for_honest_export() -> None:
    result = {
        "segments": [
            {
                "start": 28.58,
                "end": 29.98,
                "text": "字幕",
                "words": [
                    {"word": "字", "start": 28.58, "end": 29.98, "probability": 0.25},
                    {"word": "幕", "start": 29.98, "end": 29.98, "probability": 0.75},
                ],
            }
        ]
    }

    segments = clean_segments(result, duration_seconds=30.0)

    assert segments[0]["words"] == [
        {
            "text": "字",
            "start": 28.58,
            "end": 29.98,
            "probability": 0.25,
            "valid_timing": True,
        },
        {
            "text": "幕",
            "start": 29.98,
            "end": 29.98,
            "probability": 0.75,
            "valid_timing": False,
        },
    ]


def test_clean_segments_does_not_reverse_range_when_words_exceed_media_end() -> None:
    result = {
        "segments": [
            {
                "start": 9.0,
                "end": 12.0,
                "text": "尾声",
                "words": [
                    {"word": "尾声", "start": 11.0, "end": 12.0, "probability": 0.9},
                ],
            }
        ]
    }

    segments = clean_segments(result, duration_seconds=10.0)

    assert segments[0]["start"] == 9.0
    assert segments[0]["end"] == 10.0
    assert segments[0]["words"][0]["valid_timing"] is False


def test_clean_segments_keeps_safe_segment_bounds_for_non_monotonic_words() -> None:
    result = {
        "segments": [
            {
                "start": 0.0,
                "end": 5.0,
                "text": "前后",
                "words": [
                    {"word": "前", "start": 3.0, "end": 4.0},
                    {"word": "后", "start": 1.0, "end": 2.0},
                ],
            }
        ]
    }

    segments = clean_segments(result, duration_seconds=10.0)

    assert segments[0]["start"] == 0.0
    assert segments[0]["end"] == 5.0
