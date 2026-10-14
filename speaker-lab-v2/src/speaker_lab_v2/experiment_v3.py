from __future__ import annotations

import argparse
import json
from pathlib import Path

from .data import load_inference_inputs
from .verification import evaluate_enrollment, fixed_threshold_ahc


OFFICIAL_THRESHOLDS = {
    "ECAPA": 0.25,
    "CAM++": 0.40,
    "ERes2NetV2": 0.40,
}


def _fill_missing(predictions: dict[int, str], total: int) -> dict[int, str]:
    result = dict(predictions)
    known = sorted(predictions)
    for index in range(total):
        if index in result:
            continue
        left = [candidate for candidate in known if candidate < index]
        right = [candidate for candidate in known if candidate > index]
        if left and right and result[left[-1]] == result[right[0]]:
            result[index] = result[left[-1]]
        else:
            result[index] = "UNKNOWN"
    return result


def run_ahc_experiment(
    *,
    segments_path: Path,
    embedding_paths: dict[str, Path],
    output_dir: Path,
) -> dict:
    inputs = load_inference_inputs(segments_path, embedding_paths)
    models: dict[str, dict] = {}
    for model_name, cache in inputs.caches.items():
        if model_name not in OFFICIAL_THRESHOLDS:
            raise ValueError(f"no frozen external threshold for {model_name}")
        result = fixed_threshold_ahc(
            cache.embeddings,
            similarity_threshold=OFFICIAL_THRESHOLDS[model_name],
        )
        predictions = {
            int(index): f"S{int(label):03d}"
            for index, label in zip(cache.indices, result.labels)
        }
        predictions = _fill_missing(predictions, len(inputs.segments))
        models[f"{model_name}:official_ahc"] = {
            "speaker_count": result.speaker_count,
            "similarity_threshold": result.similarity_threshold,
            "predictions": {
                str(index + 1): label for index, label in sorted(predictions.items())
            },
            "unknown_count": sum(label == "UNKNOWN" for label in predictions.values()),
        }
    payload = {"version": 3, "models": models}
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "ahc-predictions.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2)
    )
    return payload


def run_enrollment_experiment(
    *,
    segments_path: Path,
    embedding_paths: dict[str, Path],
    manual_labels_path: Path,
    output_dir: Path,
) -> dict:
    inputs = load_inference_inputs(segments_path, embedding_paths)
    annotations = json.loads(manual_labels_path.read_text())["annotations"]
    models: dict[str, dict] = {}
    for model_name, cache in inputs.caches.items():
        protocols: dict[str, dict] = {}
        for count in (1, 3, 5):
            result = evaluate_enrollment(
                cache.embeddings,
                cache.indices,
                inputs.segments,
                annotations,
                enrollment_count=count,
                min_duration=2.0,
            )
            macro_f1 = sum(item["f1"] for item in result.speakers.values()) / len(
                result.speakers
            )
            protocols[str(count)] = {
                "enrollment_count_per_speaker": count,
                "enrollment_ids": {
                    speaker: list(turn_ids)
                    for speaker, turn_ids in result.enrollment_ids.items()
                },
                "evaluation_count": result.evaluation_count,
                "evaluation_ids": list(result.evaluation_ids),
                "accuracy": result.accuracy,
                "macro_f1": macro_f1,
                "speakers": result.speakers,
            }
        models[model_name] = protocols
    payload = {
        "version": 3,
        "protocol": "supervised enrollment; enrollment samples excluded from evaluation",
        "models": models,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "enrollment-metrics.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2)
    )
    return payload


def _embedding_argument(value: str) -> tuple[str, Path]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("embedding must be NAME=PATH")
    name, path = value.split("=", 1)
    return name, Path(path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Verification and enrollment experiments")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("ahc", "enroll"):
        command = subparsers.add_parser(name)
        command.add_argument("--segments", type=Path, required=True)
        command.add_argument("--embedding", type=_embedding_argument, action="append", required=True)
        command.add_argument("--output", type=Path, required=True)
        if name == "enroll":
            command.add_argument("--manual-labels", type=Path, required=True)
    args = parser.parse_args()
    common = {
        "segments_path": args.segments,
        "embedding_paths": dict(args.embedding),
        "output_dir": args.output,
    }
    if args.command == "ahc":
        run_ahc_experiment(**common)
    else:
        run_enrollment_experiment(
            **common,
            manual_labels_path=args.manual_labels,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
