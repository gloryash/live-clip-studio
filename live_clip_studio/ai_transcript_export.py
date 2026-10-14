from __future__ import annotations

import unicodedata
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from .transcript import normalize_words


def _round_time(value: float) -> float:
    return round(float(value), 3)


def _is_boundary_character(character: str) -> bool:
    return character.isspace() or unicodedata.category(character).startswith("P")


def _spoken_text(text: str) -> str:
    return "".join(character for character in text if not _is_boundary_character(character))


def _probability(value: Any) -> float | None:
    try:
        return round(float(value), 6) if value is not None else None
    except (TypeError, ValueError):
        return None


def _character_rows(
    entries: list[tuple[str, int | None, float | None]],
    *,
    start: float,
    end: float,
    spoken_source: str,
) -> list[dict[str, Any]]:
    spoken_total = sum(not _is_boundary_character(character) for character, _, _ in entries)
    spoken_index = 0
    last_end = start
    rows: list[dict[str, Any]] = []
    for character, word_index, probability in entries:
        if _is_boundary_character(character) or spoken_total == 0:
            character_start = last_end
            character_end = last_end
            source = "synthetic_boundary"
        else:
            character_start = start + ((end - start) * spoken_index / spoken_total)
            spoken_index += 1
            character_end = start + ((end - start) * spoken_index / spoken_total)
            last_end = character_end
            source = spoken_source
        row: dict[str, Any] = {
            "text": character,
            "start": _round_time(character_start),
            "end": _round_time(character_end),
            "probability": probability,
            "timing_source": source,
        }
        if word_index is not None:
            row["word_index"] = word_index
        rows.append(row)
    return rows


def _segment_fallback(
    text: str,
    *,
    start: float,
    end: float,
) -> list[dict[str, Any]]:
    entries = [(character, None, None) for character in text]
    return _character_rows(
        entries,
        start=start,
        end=end,
        spoken_source="interpolated_within_segment",
    )


def _valid_word_timing(word: dict[str, Any], *, start: float, end: float) -> bool:
    if not word.get("valid_timing"):
        return False
    try:
        word_start = float(word["start"])
        word_end = float(word["end"])
    except (KeyError, TypeError, ValueError):
        return False
    return start <= word_start < word_end <= end


def _with_indexes(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for index, row in enumerate(rows):
        row["index"] = index
    return rows


def _realign_boundary_characters(
    text: str,
    rows: list[dict[str, Any]],
    *,
    start: float,
) -> list[dict[str, Any]]:
    spoken_rows = [
        row for row in rows if not _is_boundary_character(str(row.get("text") or ""))
    ]
    spoken_cursor = 0
    last_end = start
    aligned: list[dict[str, Any]] = []
    for character in text:
        if _is_boundary_character(character):
            aligned.append(
                {
                    "text": character,
                    "start": _round_time(last_end),
                    "end": _round_time(last_end),
                    "probability": None,
                    "timing_source": "synthetic_boundary",
                }
            )
            continue
        row = dict(spoken_rows[spoken_cursor])
        spoken_cursor += 1
        row["text"] = character
        aligned.append(row)
        last_end = float(row["end"])
    return aligned


def build_character_timing(
    text: str,
    *,
    start: float,
    end: float,
    words: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], str, list[str]]:
    start = _round_time(start)
    end = _round_time(end)
    if not text:
        return [], "empty", []
    if not words:
        return (
            _with_indexes(_segment_fallback(text, start=start, end=end)),
            "segment_interpolation",
            ["word timing unavailable"],
        )
    word_text = "".join(str(word.get("text") or "") for word in words)
    boundary_realign = word_text != text
    if boundary_realign and _spoken_text(word_text) != _spoken_text(text):
        return (
            _with_indexes(_segment_fallback(text, start=start, end=end)),
            "segment_interpolation",
            ["word text did not align with segment text"],
        )

    valid_flags = [_valid_word_timing(word, start=start, end=end) for word in words]
    previous_valid_end = start
    for index, word in enumerate(words):
        if not valid_flags[index]:
            continue
        word_start = float(word["start"])
        word_end = float(word["end"])
        if word_start < previous_valid_end:
            return (
                _with_indexes(_segment_fallback(text, start=start, end=end)),
                "segment_interpolation",
                ["word timing was not monotonic"],
            )
        previous_valid_end = word_end

    invalid_count = sum(not valid for valid in valid_flags)
    rows: list[dict[str, Any]] = []
    word_index = 0
    while word_index < len(words):
        word = words[word_index]
        if valid_flags[word_index]:
            word_text = str(word["text"])
            spoken_count = sum(not _is_boundary_character(character) for character in word_text)
            spoken_source = "whisper_word" if spoken_count == 1 else "interpolated_within_word"
            rows.extend(
                _character_rows(
                    [
                        (character, word_index, _probability(word.get("probability")))
                        for character in word_text
                    ],
                    start=float(word["start"]),
                    end=float(word["end"]),
                    spoken_source=spoken_source,
                )
            )
            word_index += 1
            continue

        run_start = word_index
        while word_index < len(words) and not valid_flags[word_index]:
            word_index += 1
        run_end = word_index
        fallback_start = rows[-1]["end"] if rows else start
        fallback_end = float(words[run_end]["start"]) if run_end < len(words) else end
        fallback_end = max(float(fallback_start), fallback_end)
        entries: list[tuple[str, int | None, float | None]] = []
        for invalid_index in range(run_start, run_end):
            invalid_word = words[invalid_index]
            entries.extend(
                (
                    character,
                    invalid_index,
                    _probability(invalid_word.get("probability")),
                )
                for character in str(invalid_word["text"])
            )
        rows.extend(
            _character_rows(
                entries,
                start=float(fallback_start),
                end=fallback_end,
                spoken_source="interpolated_within_segment",
            )
        )

    if boundary_realign:
        rows = _realign_boundary_characters(text, rows, start=start)

    sources = {row["timing_source"] for row in rows}
    if "interpolated_within_segment" in sources:
        timing_quality = "mixed_with_segment_fallback"
    elif "interpolated_within_word" in sources:
        timing_quality = "whisper_words_with_interpolation"
    else:
        timing_quality = "whisper_words"
    warnings = []
    if invalid_count:
        noun = "word token" if invalid_count == 1 else "word tokens"
        warnings.append(f"{invalid_count} {noun} had invalid timing")
    return _with_indexes(rows), timing_quality, warnings


def _float_or(value: Any, fallback: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _find_raw_match(
    turn: dict[str, Any],
    raw_segments: list[dict[str, Any]],
    raw_cursor: int,
) -> tuple[int, dict[str, Any]] | None:
    turn_text = str(turn.get("text") or "").strip()
    turn_start = _float_or(turn.get("start"), 0.0)
    turn_end = _float_or(turn.get("end"), turn_start)
    best: tuple[tuple[float, float, int], int, dict[str, Any]] | None = None
    for index in range(raw_cursor, len(raw_segments)):
        candidate = raw_segments[index]
        candidate_start = _float_or(candidate.get("start"), 0.0)
        candidate_end = _float_or(candidate.get("end"), candidate_start)
        if candidate_start >= turn_end:
            break
        if str(candidate.get("text") or "").strip() != turn_text:
            continue
        overlap = min(candidate_end, turn_end) - max(candidate_start, turn_start)
        if overlap <= 0:
            continue
        midpoint_distance = abs(
            (candidate_start + candidate_end) - (turn_start + turn_end)
        )
        score = (overlap, -midpoint_distance, -index)
        if best is None or score > best[0]:
            best = (score, index, candidate)
    return (best[1], best[2]) if best is not None else None


def _advance_past_turn(
    raw_segments: list[dict[str, Any]],
    raw_cursor: int,
    turn: dict[str, Any],
) -> int:
    turn_end = _float_or(turn.get("end"), 0.0)
    while raw_cursor < len(raw_segments):
        candidate = raw_segments[raw_cursor]
        candidate_end = _float_or(candidate.get("end"), 0.0)
        if candidate_end > turn_end:
            break
        raw_cursor += 1
    return raw_cursor


def recover_words_by_turn(
    turns: list[dict[str, Any]],
    saved_segments: list[dict[str, Any]],
    raw_segments: list[dict[str, Any]],
) -> dict[int, list[dict[str, Any]]]:
    recovered: dict[int, list[dict[str, Any]]] = {}
    raw_cursor = 0
    for position, turn in enumerate(turns):
        turn_id = int(turn.get("id") or position + 1)
        saved = saved_segments[position] if position < len(saved_segments) else {}
        saved_words = saved.get("words") if isinstance(saved, dict) else None
        raw_match = _find_raw_match(turn, raw_segments, raw_cursor)
        if isinstance(saved_words, list) and saved_words:
            saved_start = _float_or(saved.get("start"), _float_or(turn.get("start"), 0.0))
            saved_end = _float_or(saved.get("end"), _float_or(turn.get("end"), saved_start))
            recovered[turn_id] = normalize_words(
                saved_words,
                segment_start=saved_start,
                segment_end=saved_end,
            )
            raw_cursor = (
                raw_match[0] + 1
                if raw_match is not None
                else _advance_past_turn(raw_segments, raw_cursor, turn)
            )
            continue

        if raw_match is None:
            recovered[turn_id] = []
            raw_cursor = _advance_past_turn(raw_segments, raw_cursor, turn)
            continue
        matched_index, match = raw_match
        raw_cursor = matched_index + 1
        raw_start = _float_or(match.get("start"), _float_or(turn.get("start"), 0.0))
        raw_end = _float_or(match.get("end"), _float_or(turn.get("end"), raw_start))
        recovered[turn_id] = normalize_words(
            match.get("words"),
            segment_start=raw_start,
            segment_end=raw_end,
        )
    return recovered


def _speaker_confidence(value: Any) -> float | None:
    try:
        return round(float(value), 6) if value is not None else None
    except (TypeError, ValueError):
        return None


def _text_review_metadata(
    turn: dict[str, Any],
    saved_segment: dict[str, Any],
) -> dict[str, Any] | None:
    source = turn if turn.get("text_source") == "qwen_text_correction" else saved_segment
    if source.get("text_source") != "qwen_text_correction":
        return None
    return {
        "original_text": str(source.get("original_text") or ""),
        "text_source": "qwen_text_correction",
        "correction": {
            "provider": str(source.get("correction_provider") or ""),
            "model": str(source.get("correction_model") or ""),
            "confidence": _speaker_confidence(source.get("correction_confidence")),
            "reason": str(source.get("correction_reason") or ""),
        },
    }


def _resolve_speaker(
    turn: dict[str, Any],
    *,
    predictions: dict[str, Any],
    speakers: dict[str, str],
    annotations: dict[str, str],
) -> dict[str, Any]:
    turn_id = str(turn.get("id"))
    manual_speaker = annotations.get(turn_id)
    if manual_speaker:
        return {
            "id": manual_speaker,
            "name": speakers.get(manual_speaker, manual_speaker),
            "source": "manual",
            "confidence": None,
            "manual_override": True,
        }
    prediction_rows = predictions.get("predictions", {}) if isinstance(predictions, dict) else {}
    prediction = prediction_rows.get(turn_id, {}) if isinstance(prediction_rows, dict) else {}
    if not isinstance(prediction, dict):
        prediction = {}
    speaker_id = str(prediction.get("speaker_id") or "UNKNOWN")
    return {
        "id": speaker_id,
        "name": "无法判断" if speaker_id == "UNKNOWN" else speakers.get(speaker_id, speaker_id),
        "source": str(prediction.get("source") or "unknown"),
        "confidence": _speaker_confidence(prediction.get("confidence")),
        "manual_override": False,
    }


def _format_timestamp(seconds: float) -> str:
    milliseconds = max(0, round(float(seconds) * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, milliseconds = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d}.{milliseconds:03d}"


def _export_words(words: list[dict[str, Any]]) -> list[dict[str, Any]]:
    exported = []
    for index, word in enumerate(words):
        valid_timing = bool(word.get("valid_timing"))
        exported.append(
            {
                "index": index,
                "text": str(word.get("text") or ""),
                "start": word.get("start"),
                "end": word.get("end"),
                "probability": _probability(word.get("probability")),
                "timing_source": "whisper_word" if valid_timing else "invalid_whisper_word",
                "valid_timing": valid_timing,
            }
        )
    return exported


def build_ai_transcript_document(
    *,
    job: dict[str, Any],
    media: dict[str, Any],
    transcript: dict[str, Any],
    saved_segments: list[dict[str, Any]],
    raw: dict[str, Any],
    predictions: dict[str, Any],
    speakers: dict[str, str],
    annotations: dict[str, str],
    deleted_turn_ids: set[int],
) -> dict[str, Any]:
    turns = [turn for turn in transcript.get("turns", []) if isinstance(turn, dict)]
    raw_segments = [item for item in raw.get("segments", []) if isinstance(item, dict)]
    words_by_turn = recover_words_by_turn(turns, saved_segments, raw_segments)
    exported_segments: list[dict[str, Any]] = []
    dialogue_lines: list[str] = []
    character_sources: Counter[str] = Counter()
    warning_counts: Counter[str] = Counter()
    word_count = 0
    invalid_word_count = 0
    unknown_speaker_count = 0
    segment_fallback_count = 0
    deleted_segment_count = 0

    for position, turn in enumerate(turns):
        turn_id = int(turn.get("id") or position + 1)
        if turn_id in deleted_turn_ids:
            deleted_segment_count += 1
            continue
        start = _round_time(float(turn["start"]))
        end = _round_time(float(turn["end"]))
        text = str(turn.get("text") or "")
        saved_segment = (
            saved_segments[position]
            if position < len(saved_segments) and isinstance(saved_segments[position], dict)
            else {}
        )
        text_review = _text_review_metadata(turn, saved_segment)
        words = words_by_turn.get(turn_id, [])
        characters, timing_quality, warnings = build_character_timing(
            text,
            start=start,
            end=end,
            words=words,
        )
        speaker = _resolve_speaker(
            turn,
            predictions=predictions,
            speakers=speakers,
            annotations=annotations,
        )
        if speaker["id"] == "UNKNOWN":
            unknown_speaker_count += 1
        word_count += len(words)
        invalid_word_count += sum(not word.get("valid_timing") for word in words)
        character_sources.update(str(character["timing_source"]) for character in characters)
        if any(character["timing_source"] == "interpolated_within_segment" for character in characters):
            segment_fallback_count += 1
        warning_counts.update(warnings)
        segment_document = {
            "id": turn_id,
            "start": start,
            "end": end,
            "duration": _round_time(end - start),
            "text": text,
            "text_source": (
                text_review["text_source"] if text_review is not None else "whisper"
            ),
            "speaker": speaker,
            "timing_quality": timing_quality,
            "words": _export_words(words),
            "characters": characters,
        }
        if text_review is not None:
            segment_document.update(text_review)
        if warnings:
            segment_document["warnings"] = warnings
        exported_segments.append(segment_document)
        dialogue_lines.append(
            f"[{_format_timestamp(start)}–{_format_timestamp(end)}] {speaker['name']}：{text}"
        )

    timing_keys = (
        "whisper_word",
        "interpolated_within_word",
        "synthetic_boundary",
        "interpolated_within_segment",
    )
    character_timing_counts = {key: character_sources.get(key, 0) for key in timing_keys}
    speaker_rows = [
        {"id": speaker_id, "name": name}
        for speaker_id, name in sorted(speakers.items())
    ]
    if unknown_speaker_count:
        speaker_rows.append({"id": "UNKNOWN", "name": "无法判断"})
    quality_warnings = [
        f"{message}: {count} segment{'s' if count != 1 else ''}"
        for message, count in sorted(warning_counts.items())
    ]
    transcription = {
        "model": str(raw.get("model") or "unknown"),
        "language": str(raw.get("language") or "unknown"),
        "timing_unit": "seconds",
        "timing_precision": 0.001,
    }
    raw_correction = raw.get("correction")
    if isinstance(raw_correction, dict):
        alignment = raw_correction.get("alignment")
        transcription["text_correction"] = {
            "status": str(raw_correction.get("status") or "unknown"),
            "provider": str(raw_correction.get("provider") or "unknown"),
            "model": str(raw_correction.get("model") or "unknown"),
            "audio_sent_to_correction_model": False,
            "word_timestamps": (
                str(alignment.get("word_timestamps") or "original_only")
                if isinstance(alignment, dict)
                else "original_only"
            ),
        }
    return {
        "format": "live-clip-studio.ai-transcript",
        "version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "job": {
            "id": str(job.get("job_id") or ""),
            "source_filename": str(job.get("filename") or "source.mp4"),
            "duration_seconds": _round_time(float(media.get("duration_seconds") or 0.0)),
        },
        "transcription": transcription,
        "speakers": speaker_rows,
        "quality": {
            "segment_count": len(exported_segments),
            "deleted_segment_count": deleted_segment_count,
            "unknown_speaker_count": unknown_speaker_count,
            "word_count": word_count,
            "invalid_word_timing_count": invalid_word_count,
            "character_count": sum(character_timing_counts.values()),
            "character_timing_counts": character_timing_counts,
            "segment_fallback_count": segment_fallback_count,
            "warnings": quality_warnings,
        },
        "dialogue_text": "\n".join(dialogue_lines),
        "segments": exported_segments,
    }
