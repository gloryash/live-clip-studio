from __future__ import annotations

import argparse
import json
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path

import numpy as np

from .data import EmbeddingCache, load_inference_inputs
from .microcluster import build_microclusters
from .models import InferenceConfig, Prototype
from .multiscale import estimate_stable_speakers
from .registry import PrototypeRegistry


def _prototype_copy(prototype: Prototype, prefix: str) -> Prototype:
    return Prototype(
        prototype_id=f"{prefix}:{prototype.prototype_id}",
        centroid=prototype.centroid.copy(),
        evidence_count=prototype.evidence_count,
        duration=prototype.duration,
        window_ids=set(prototype.window_ids),
        scale_seconds=set(prototype.scale_seconds),
        cluster_ids=list(prototype.cluster_ids),
    )


def _serialize_prototype(prototype: Prototype) -> dict:
    return {
        "prototype_id": prototype.prototype_id,
        "centroid": prototype.centroid.tolist(),
        "evidence_count": prototype.evidence_count,
        "duration": prototype.duration,
        "window_ids": sorted(prototype.window_ids),
        "scale_seconds": sorted(prototype.scale_seconds),
        "cluster_ids": prototype.cluster_ids,
    }


def _fill_missing(predictions: dict[int, str], total: int) -> dict[int, str]:
    result = dict(predictions)
    known = sorted(index for index, label in predictions.items() if label != "UNKNOWN")
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


def _run_model(
    model_name: str,
    cache: EmbeddingCache,
    segments: list[dict],
    config: InferenceConfig,
) -> dict:
    rows = [
        {
            "index": int(index),
            "start": float(segments[int(index)]["start"]),
            "end": float(segments[int(index)]["end"]),
        }
        for index in cache.indices
    ]
    confirmed_by_scale: dict[int, list[Prototype]] = {}
    candidates_by_scale: dict[int, list[Prototype]] = {}
    scale_diagnostics: dict[str, dict] = {}
    for scale in config.window_seconds:
        microclusters = build_microclusters(
            cache.embeddings,
            rows,
            window_seconds=scale,
            model_name=model_name,
        )
        grouped = defaultdict(list)
        for cluster in microclusters:
            grouped[cluster.window_id].append(cluster)
        registry = PrototypeRegistry(config)
        for window_id in sorted(
            grouped,
            key=lambda value: int(value.split(":", 1)[1]),
        ):
            registry.observe(grouped[window_id])
        confirmed_by_scale[scale] = [
            _prototype_copy(prototype, f"{model_name}:{scale}")
            for prototype in registry.confirmed
        ]
        candidates_by_scale[scale] = [
            _prototype_copy(prototype, f"{model_name}:{scale}")
            for prototype in registry.candidates
        ]
        scale_diagnostics[str(scale)] = {
            "microcluster_count": len(microclusters),
            "confirmed_count": len(registry.confirmed),
            "candidate_count": len(registry.candidates),
        }

    stable = estimate_stable_speakers(
        confirmed_by_scale,
        similarity_threshold=config.candidate_similarity,
        min_scales=config.stable_scales,
    )
    predictions: dict[int, str] = {}
    stable_vectors = [prototype.centroid for prototype in stable.stable_prototypes]
    for embedding, index in zip(cache.embeddings, cache.indices):
        if not stable_vectors:
            predictions[int(index)] = "UNKNOWN"
            continue
        similarities = [float(embedding @ vector) for vector in stable_vectors]
        best = int(np.argmax(similarities))
        predictions[int(index)] = (
            stable.stable_prototypes[best].stable_id
            if similarities[best] >= config.unknown_similarity
            else "UNKNOWN"
        )
    predictions = _fill_missing(predictions, len(segments))
    stable_payload = [
        {
            "stable_id": item.stable_id,
            "centroid": item.centroid.tolist(),
            "member_ids": list(item.member_ids),
            "scale_support": item.scale_support,
            "confidence": item.confidence,
        }
        for item in stable.stable_prototypes
    ]
    return {
        "speaker_count": stable.speaker_count,
        "predictions": {str(index + 1): label for index, label in sorted(predictions.items())},
        "unknown_count": sum(label == "UNKNOWN" for label in predictions.values()),
        "stable_prototypes": stable_payload,
        "confirmed_by_scale": {
            str(scale): [_serialize_prototype(item) for item in items]
            for scale, items in confirmed_by_scale.items()
        },
        "candidates_by_scale": {
            str(scale): [_serialize_prototype(item) for item in items]
            for scale, items in candidates_by_scale.items()
        },
        "scale_diagnostics": scale_diagnostics,
    }


def run_inference(
    *,
    segments_path: Path,
    embedding_paths: dict[str, Path],
    output_dir: Path,
    config: InferenceConfig | None = None,
) -> dict:
    config = config or InferenceConfig()
    inputs = load_inference_inputs(segments_path, embedding_paths)
    models = {
        model_name: _run_model(model_name, cache, inputs.segments, config)
        for model_name, cache in inputs.caches.items()
    }
    result = {"version": 1, "models": models}
    output_dir.mkdir(parents=True, exist_ok=True)
    config_payload = asdict(config)
    config_payload["window_seconds"] = list(config.window_seconds)
    (output_dir / "config.json").write_text(
        json.dumps(config_payload, ensure_ascii=False, indent=2)
    )
    (output_dir / "inferred-speakers.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2)
    )
    (output_dir / "prototypes.json").write_text(
        json.dumps(
            {
                name: payload["stable_prototypes"]
                for name, payload in models.items()
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    (output_dir / "candidate-speakers.json").write_text(
        json.dumps(
            {
                name: payload["candidates_by_scale"]
                for name, payload in models.items()
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    (output_dir / "speaker-count.json").write_text(
        json.dumps(
            {
                name: {
                    "speaker_count": payload["speaker_count"],
                    "unknown_count": payload["unknown_count"],
                    "scale_diagnostics": payload["scale_diagnostics"],
                }
                for name, payload in models.items()
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return result


def _embedding_argument(value: str) -> tuple[str, Path]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("embedding must be NAME=PATH")
    name, raw_path = value.split("=", 1)
    return name, Path(raw_path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Rare-speaker discovery experiment")
    subparsers = parser.add_subparsers(dest="command", required=True)
    infer = subparsers.add_parser("infer")
    infer.add_argument("--segments", type=Path, required=True)
    infer.add_argument("--embedding", type=_embedding_argument, action="append", required=True)
    infer.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "infer":
        run_inference(
            segments_path=args.segments,
            embedding_paths=dict(args.embedding),
            output_dir=args.output,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

