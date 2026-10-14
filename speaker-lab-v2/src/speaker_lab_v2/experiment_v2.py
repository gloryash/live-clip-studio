from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from .data import load_inference_inputs
from .strategies import multiscale_micro_nme, raw_nme, turn_nme


STRATEGIES = {
    "raw_nme": raw_nme,
    "turn_nme": turn_nme,
    "multiscale_micro_nme": multiscale_micro_nme,
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


def run_experiment(
    *,
    segments_path: Path,
    embedding_paths: dict[str, Path],
    output_dir: Path,
    random_state: int = 0,
) -> dict:
    inputs = load_inference_inputs(segments_path, embedding_paths)
    flattened: dict[str, dict] = {}
    diagnostics: dict[str, dict] = {}
    for model_name, cache in inputs.caches.items():
        rows = [
            {
                "index": int(index),
                "start": float(inputs.segments[int(index)]["start"]),
                "end": float(inputs.segments[int(index)]["end"]),
            }
            for index in cache.indices
        ]
        for strategy_name, strategy in STRATEGIES.items():
            started = time.perf_counter()
            strategy_result = strategy(
                cache.embeddings,
                rows,
                model_name=model_name,
                random_state=random_state,
            )
            elapsed = time.perf_counter() - started
            predictions = {
                int(index): f"S{int(label):03d}"
                for index, label in zip(cache.indices, strategy_result.labels)
            }
            predictions = _fill_missing(predictions, len(inputs.segments))
            key = f"{model_name}:{strategy_name}"
            flattened[key] = {
                "speaker_count": strategy_result.speaker_count,
                "predictions": {
                    str(index + 1): label for index, label in sorted(predictions.items())
                },
                "unknown_count": sum(label == "UNKNOWN" for label in predictions.values()),
            }
            diagnostics[key] = {
                "speaker_count": strategy_result.speaker_count,
                "elapsed_seconds": elapsed,
                **strategy_result.evidence,
            }
    result = {"version": 2, "models": flattened}
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "config.json").write_text(
        json.dumps(
            {
                "random_state": random_state,
                "strategies": list(STRATEGIES),
                "labels_or_speaker_count_prior": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    (output_dir / "inferred-speakers.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2)
    )
    (output_dir / "diagnostics.json").write_text(
        json.dumps(diagnostics, ensure_ascii=False, indent=2)
    )
    return result


def _embedding_argument(value: str) -> tuple[str, Path]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("embedding must be NAME=PATH")
    name, raw_path = value.split("=", 1)
    return name, Path(raw_path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Frozen graph-clustering experiment")
    parser.add_argument("--segments", type=Path, required=True)
    parser.add_argument("--embedding", type=_embedding_argument, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--random-state", type=int, default=0)
    args = parser.parse_args()
    run_experiment(
        segments_path=args.segments,
        embedding_paths=dict(args.embedding),
        output_dir=args.output,
        random_state=args.random_state,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
