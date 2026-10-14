from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import numpy as np

from live_clip_studio.speaker_workflow import discover_candidates


def migrate_job_candidates(
    job_dir: Path,
    source_embedding_path: Path,
    *,
    model: str,
    similarity_threshold: float,
) -> dict:
    transcript_dir = Path(job_dir) / "transcript"
    segments = json.loads(
        (transcript_dir / "segments.json").read_text(encoding="utf-8")
    )["segments"]
    with np.load(source_embedding_path, allow_pickle=False) as source:
        embeddings = np.asarray(source["embeddings"], dtype=np.float32)
        indices = np.asarray(source["indices"], dtype=np.int32)
    candidates = discover_candidates(
        embeddings,
        indices,
        segments,
        model=model,
        similarity_threshold=similarity_threshold,
    )
    embedding_target = transcript_dir / "speaker-embeddings.npz"
    embedding_temporary = transcript_dir / "speaker-embeddings.npz.tmp"
    with embedding_temporary.open("wb") as target:
        np.savez_compressed(target, embeddings=embeddings, indices=indices)
    os.replace(embedding_temporary, embedding_target)
    candidate_target = transcript_dir / "speaker-candidates.json"
    candidate_temporary = transcript_dir / "speaker-candidates.json.tmp"
    candidate_temporary.write_text(
        json.dumps(candidates, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(candidate_temporary, candidate_target)
    return candidates


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate cached speaker embeddings into the candidate workflow")
    parser.add_argument("--job-dir", type=Path, required=True)
    parser.add_argument("--embeddings", type=Path, required=True)
    parser.add_argument("--model", default="CAM++")
    parser.add_argument("--similarity-threshold", type=float, default=0.4)
    args = parser.parse_args()
    result = migrate_job_candidates(
        args.job_dir,
        args.embeddings,
        model=args.model,
        similarity_threshold=args.similarity_threshold,
    )
    print(json.dumps({"speaker_count": result["speaker_count"], "model": result["model"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
