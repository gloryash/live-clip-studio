from __future__ import annotations

from copy import deepcopy
from typing import Any


def apply_text_correction(result: dict[str, Any]) -> dict[str, Any]:
    """Return a copy with strictly aligned Qwen text applied to ASR segments."""
    effective = deepcopy(result)
    correction = result.get("correction")
    source_segments = result.get("segments")
    if (
        not isinstance(correction, dict)
        or correction.get("status") != "succeeded"
        or not isinstance(source_segments, list)
        or not isinstance(correction.get("segments"), list)
    ):
        return effective

    reviewed_by_index: dict[int, dict[str, Any]] = {}
    duplicate_indexes: set[int] = set()
    for reviewed in correction["segments"]:
        if not isinstance(reviewed, dict) or type(reviewed.get("index")) is not int:
            continue
        index = reviewed["index"]
        if index in reviewed_by_index:
            duplicate_indexes.add(index)
            continue
        reviewed_by_index[index] = reviewed
    for index in duplicate_indexes:
        reviewed_by_index.pop(index, None)

    effective_segments = effective.get("segments")
    if not isinstance(effective_segments, list):
        return effective
    provider = str(correction.get("provider") or "").strip()
    model = str(correction.get("model") or "").strip()
    for index, source in enumerate(source_segments):
        if not isinstance(source, dict) or index >= len(effective_segments):
            continue
        target = effective_segments[index]
        reviewed = reviewed_by_index.get(index)
        if not isinstance(target, dict) or reviewed is None:
            continue
        original_text = str(source.get("text") or "").strip()
        reviewed_original = str(reviewed.get("original_text") or "").strip()
        corrected_text = str(reviewed.get("corrected_text") or "").strip()
        if not original_text or reviewed_original != original_text or not corrected_text:
            continue
        target["text"] = corrected_text
        target["original_text"] = original_text
        target["text_source"] = "qwen_text_correction"
        target["correction_confidence"] = _confidence_or_none(reviewed.get("confidence"))
        target["correction_reason"] = str(reviewed.get("reason") or "").strip()
        target["correction_provider"] = provider
        target["correction_model"] = model
    return effective


def clean_segments(result: dict[str, Any], duration_seconds: float) -> list[dict[str, Any]]:
    cleaned: list[dict[str, Any]] = []
    for item in result.get("segments", []):
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        try:
            start = max(0.0, float(item["start"]))
            end = float(item["end"])
        except (KeyError, TypeError, ValueError):
            continue
        if not text or end <= start:
            continue
        if start >= duration_seconds or end > duration_seconds + 3.0:
            continue
        safe_end = min(end, duration_seconds)
        if safe_end <= start:
            continue
        words = normalize_words(item.get("words"), segment_start=start, segment_end=safe_end)
        word_bounds = _word_time_bounds(words)
        if word_bounds is not None:
            start, end = word_bounds
        segment: dict[str, Any] = {
            "start": round(start, 3),
            "end": round(min(end, safe_end), 3),
            "text": text,
        }
        if words:
            segment["words"] = words
        _copy_text_review_metadata(item, segment)
        cleaned.append(segment)
    return cleaned


def _confidence_or_none(value: Any) -> float | None:
    try:
        return round(max(0.0, min(1.0, float(value))), 6) if value is not None else None
    except (TypeError, ValueError):
        return None


def _copy_text_review_metadata(source: dict[str, Any], target: dict[str, Any]) -> None:
    if source.get("text_source") != "qwen_text_correction":
        return
    target["original_text"] = str(source.get("original_text") or "")
    target["text_source"] = "qwen_text_correction"
    target["correction_confidence"] = _confidence_or_none(
        source.get("correction_confidence")
    )
    target["correction_reason"] = str(source.get("correction_reason") or "")
    target["correction_provider"] = str(source.get("correction_provider") or "")
    target["correction_model"] = str(source.get("correction_model") or "")


def normalize_words(
    words: Any,
    *,
    segment_start: float,
    segment_end: float,
) -> list[dict[str, Any]]:
    if not isinstance(words, list):
        return []
    normalized: list[dict[str, Any]] = []
    for item in words:
        if not isinstance(item, dict):
            continue
        text = str(item.get("word") or item.get("text") or "")
        if not text:
            continue
        try:
            word_start = round(float(item["start"]), 3)
            word_end = round(float(item["end"]), 3)
        except (KeyError, TypeError, ValueError):
            word_start = None
            word_end = None
        probability = item.get("probability")
        try:
            normalized_probability = round(float(probability), 6) if probability is not None else None
        except (TypeError, ValueError):
            normalized_probability = None
        valid_timing = bool(
            word_start is not None
            and word_end is not None
            and segment_start <= word_start < word_end <= segment_end
        )
        normalized.append(
            {
                "text": text,
                "start": word_start,
                "end": word_end,
                "probability": normalized_probability,
                "valid_timing": valid_timing,
            }
        )
    return normalized


def _word_time_bounds(words: list[dict[str, Any]]) -> tuple[float, float] | None:
    timed_words = [
        (float(word["start"]), float(word["end"]))
        for word in words
        if word.get("valid_timing")
    ]
    if not timed_words:
        return None
    previous_end = timed_words[0][1]
    for word_start, word_end in timed_words[1:]:
        if word_start < previous_end:
            return None
        previous_end = word_end
    if timed_words[-1][1] <= timed_words[0][0]:
        return None
    return timed_words[0][0], timed_words[-1][1]


def build_speaker_turns(
    segments: list[dict[str, Any]],
    labels: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    labels = labels or []
    speaker_names = sorted(
        {str(label.get("speaker")) for label in labels if label.get("speaker")},
    )
    display = {speaker: f"说话人 {index}" for index, speaker in enumerate(speaker_names, start=1)}
    turns: list[dict[str, Any]] = []
    for index, segment in enumerate(segments):
        label = labels[index] if index < len(labels) else {}
        speaker = str(label.get("speaker") or "UNKNOWN")
        turn = {
            "id": index + 1,
            "speaker": speaker,
            "speaker_label": display.get(speaker, "说话人未知"),
            "start": float(segment["start"]),
            "end": float(segment["end"]),
            "text": str(segment["text"]),
            "speaker_source": str(label.get("speaker_source") or "unavailable"),
        }
        _copy_text_review_metadata(segment, turn)
        turns.append(turn)
    return turns
