from __future__ import annotations

import importlib.util
import itertools
import json
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.cluster import AgglomerativeClustering
from sklearn.metrics import silhouette_score


ROOT = Path(__file__).resolve().parents[1]
JOB = ROOT / "data/f03d40e1-0f06-4454-a83f-1a512c7e4ae2"
TRANSCRIPT = JOB / "transcript"
EXPERIMENTS = JOB / "speaker-experiments"


def load_window_helpers():
    path = Path.home() / ".codex/skills/video-copy-extractor/scripts/diarize_speechbrain.py"
    spec = importlib.util.spec_from_file_location("windowed_diarization", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def load_cache(path: Path) -> tuple[np.ndarray, np.ndarray]:
    cache = np.load(path)
    return cache["embeddings"], cache["indices"].astype(int)


def automatic_speaker_count(embeddings: np.ndarray) -> tuple[int, dict[str, float]]:
    scores: dict[str, float] = {}
    best = (-1e9, 1)
    for count in range(2, 7):
        labels = AgglomerativeClustering(
            n_clusters=count, metric="cosine", linkage="average"
        ).fit_predict(embeddings)
        raw = float(silhouette_score(embeddings, labels, metric="cosine"))
        adjusted = raw - 0.025 * (count - 2)
        scores[str(count)] = raw
        if adjusted > best[0]:
            best = (adjusted, count)
    return best[1], scores


def best_mapping(
    gold: list[str], predicted: list[int]
) -> tuple[dict[int, str], int]:
    gold_labels = sorted(set(gold))
    predicted_labels = sorted(set(predicted))
    winner: tuple[int, dict[int, str]] = (-1, {})
    for values in itertools.permutations(gold_labels, len(predicted_labels)):
        mapping = dict(zip(predicted_labels, values))
        correct = sum(mapping[pred] == truth for truth, pred in zip(gold, predicted))
        if correct > winner[0]:
            winner = (correct, mapping)
    return winner[1], winner[0]


def fill_short_turns(known: dict[int, int], total: int) -> dict[int, int]:
    result = dict(known)
    known_ids = sorted(known)
    for turn_id in range(1, total + 1):
        if turn_id in result:
            continue
        left = [item for item in known_ids if item < turn_id]
        right = [item for item in known_ids if item > turn_id]
        if left and right and known[left[-1]] == known[right[0]]:
            result[turn_id] = known[left[-1]]
        elif left and (not right or turn_id - left[-1] <= right[0] - turn_id):
            result[turn_id] = known[left[-1]]
        elif right:
            result[turn_id] = known[right[0]]
    return result


def score(
    predictions: dict[int, int],
    segments: list[dict[str, Any]],
    manual: dict[str, str],
    deleted: set[int],
) -> dict[str, Any]:
    rows = [
        (
            turn_id,
            manual[str(turn_id)],
            prediction,
            float(segments[turn_id - 1]["end"])
            - float(segments[turn_id - 1]["start"]),
        )
        for turn_id, prediction in predictions.items()
        if str(turn_id) in manual and turn_id not in deleted
    ]
    mapping, correct = best_mapping(
        [row[1] for row in rows], [row[2] for row in rows]
    )
    mapped = [(truth, mapping[prediction], duration) for _, truth, prediction, duration in rows]
    confusion = Counter((truth, prediction) for truth, prediction, _ in mapped)
    result: dict[str, Any] = {
        "count": len(mapped),
        "correct": correct,
        "accuracy": correct / len(mapped),
        "mapping": {str(key): value for key, value in mapping.items()},
        "confusion": {
            f"{truth}->{prediction}": count
            for (truth, prediction), count in confusion.items()
        },
        "speakers": {},
    }
    for speaker in sorted(set(manual.values())):
        speaker_rows = [row for row in mapped if row[0] == speaker]
        details: dict[str, Any] = {}
        for label, predicate in (
            ("all", lambda duration: True),
            ("long", lambda duration: duration >= 1.0),
            ("short", lambda duration: duration < 1.0),
        ):
            selected = [row for row in speaker_rows if predicate(row[2])]
            hits = sum(truth == prediction for truth, prediction, _ in selected)
            details[label] = {
                "count": len(selected),
                "correct": hits,
                "accuracy": hits / len(selected) if selected else None,
            }
        result["speakers"][speaker] = details
    return result


def main() -> None:
    helpers = load_window_helpers()
    segments = json.loads((TRANSCRIPT / "segments.json").read_text())["segments"]
    manual = json.loads((TRANSCRIPT / "manual-speaker-labels.json").read_text())[
        "annotations"
    ]
    deleted = set(
        json.loads((TRANSCRIPT / "deleted-turns.json").read_text()).get("ids", [])
    )
    sources = {
        "ECAPA": EXPERIMENTS / "ecapa-embeddings.npz",
        "CAM++": EXPERIMENTS / "campplus-embeddings.npz",
        "ERes2NetV2": EXPERIMENTS / "eres2netv2-embeddings.npz",
    }
    caches = {name: load_cache(path) for name, path in sources.items()}
    common = set.intersection(*(set(indexes.tolist()) for _, indexes in caches.values()))
    common = {
        index
        for index in common
        if str(index + 1) in manual and index + 1 not in deleted
    }
    common_indexes = np.asarray(sorted(common), dtype=int)
    rows = [
        {
            "index": int(index),
            "start": float(segments[index]["start"]),
            "end": float(segments[index]["end"]),
        }
        for index in common_indexes
    ]

    report: dict[str, Any] = {
        "definition": {"long": ">= 1.0 seconds", "short": "< 1.0 seconds"},
        "common_long_count": len(common_indexes),
        "total_manual_count": len(manual),
        "models": {},
    }
    for model_name, (all_embeddings, all_indexes) in caches.items():
        lookup = {int(index): position for position, index in enumerate(all_indexes)}
        embeddings = np.stack([all_embeddings[lookup[int(index)]] for index in common_indexes])
        auto_count, auto_scores = automatic_speaker_count(embeddings)
        model_result: dict[str, Any] = {
            "automatic_global_speaker_count": auto_count,
            "automatic_global_silhouette": auto_scores,
            "windows": {},
        }
        for label, seconds in (
            ("5min", 300.0),
            ("10min", 600.0),
            ("20min", 1200.0),
            ("global", None),
        ):
            if seconds is None:
                labels = AgglomerativeClustering(
                    n_clusters=4, metric="cosine", linkage="average"
                ).fit_predict(embeddings)
                metadata = {"strategy": "global"}
            else:
                labels, metadata = helpers.windowed_cluster_labels(
                    embeddings, rows, 4, seconds
                )
            long_predictions = {
                int(index) + 1: int(prediction)
                for index, prediction in zip(common_indexes, labels)
            }
            full_predictions = fill_short_turns(long_predictions, len(segments))
            model_result["windows"][label] = {
                "metadata": metadata,
                "common_long": score(long_predictions, segments, manual, deleted),
                "full": score(full_predictions, segments, manual, deleted),
            }
        report["models"][model_name] = model_result

    output = EXPERIMENTS / "window-benchmark.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(output)
    for model, result in report["models"].items():
        print(model, "auto", result["automatic_global_speaker_count"])
        for window, values in result["windows"].items():
            print(
                window,
                f"long={values['common_long']['accuracy']:.6f}",
                f"full={values['full']['accuracy']:.6f}",
            )


if __name__ == "__main__":
    main()
