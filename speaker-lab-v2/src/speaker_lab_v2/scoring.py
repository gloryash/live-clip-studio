from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import numpy as np
from scipy.optimize import linear_sum_assignment


def _mapping(gold: list[str], predicted: list[str]) -> dict[str, str]:
    gold_labels = sorted(set(gold))
    predicted_labels = sorted(set(label for label in predicted if label != "UNKNOWN"))
    if not gold_labels or not predicted_labels:
        return {}
    matrix = np.zeros((len(gold_labels), len(predicted_labels)), dtype=int)
    gold_index = {label: index for index, label in enumerate(gold_labels)}
    predicted_index = {label: index for index, label in enumerate(predicted_labels)}
    for truth, label in zip(gold, predicted):
        if label != "UNKNOWN":
            matrix[gold_index[truth], predicted_index[label]] += 1
    rows, columns = linear_sum_assignment(-matrix)
    return {
        predicted_labels[column]: gold_labels[row]
        for row, column in zip(rows, columns)
    }


def _score_model(
    predictions: dict[str, str],
    annotations: dict[str, str],
    segments: list[dict],
) -> dict:
    turn_ids = sorted((int(key) for key in annotations), key=int)
    gold = [annotations[str(turn_id)] for turn_id in turn_ids]
    raw_predicted = [predictions.get(str(turn_id), "UNKNOWN") for turn_id in turn_ids]
    mapping = _mapping(gold, raw_predicted)
    mapped = [
        mapping.get(label, "UNKNOWN" if label == "UNKNOWN" else f"UNMAPPED:{label}")
        for label in raw_predicted
    ]
    correct = sum(truth == label for truth, label in zip(gold, mapped))
    confusion = Counter(zip(gold, mapped))
    speakers: dict[str, dict] = {}
    f1_values: list[float] = []
    for speaker in sorted(set(gold)):
        tp = confusion[speaker, speaker]
        fp = sum(
            count
            for (truth, label), count in confusion.items()
            if label == speaker and truth != speaker
        )
        fn = sum(
            count
            for (truth, label), count in confusion.items()
            if truth == speaker and label != speaker
        )
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0.0
        f1_values.append(f1)
        speakers[speaker] = {
            "support": sum(truth == speaker for truth in gold),
            "correct": tp,
            "precision": precision,
            "recall": recall,
            "f1": f1,
        }

    def duration_score(long: bool) -> dict:
        selected = [
            position
            for position, turn_id in enumerate(turn_ids)
            if (
                float(segments[turn_id - 1]["end"])
                - float(segments[turn_id - 1]["start"])
                >= 1.0
            )
            is long
        ]
        hits = sum(gold[position] == mapped[position] for position in selected)
        return {
            "count": len(selected),
            "correct": hits,
            "accuracy": hits / len(selected) if selected else None,
        }

    return {
        "count": len(gold),
        "correct": correct,
        "accuracy": correct / len(gold) if gold else 0.0,
        "macro_f1": sum(f1_values) / len(f1_values) if f1_values else 0.0,
        "unknown_count": sum(label == "UNKNOWN" for label in raw_predicted),
        "mapping": mapping,
        "speakers": speakers,
        "long": duration_score(True),
        "short": duration_score(False),
        "confusion": {
            f"{truth}->{label}": count
            for (truth, label), count in confusion.items()
        },
    }


def score_predictions(
    prediction_path: Path,
    manual_labels_path: Path,
    segments_path: Path,
) -> dict:
    prediction_payload = json.loads(prediction_path.read_text())
    annotations = json.loads(manual_labels_path.read_text())["annotations"]
    segments = json.loads(segments_path.read_text())["segments"]
    return {
        "version": 1,
        "models": {
            name: _score_model(payload["predictions"], annotations, segments)
            for name, payload in prediction_payload["models"].items()
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Score frozen speaker predictions")
    parser.add_argument("--prediction", type=Path, required=True)
    parser.add_argument("--manual-labels", type=Path, required=True)
    parser.add_argument("--segments", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    metrics = score_predictions(args.prediction, args.manual_labels, args.segments)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(metrics, ensure_ascii=False, indent=2))
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

