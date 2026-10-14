from __future__ import annotations

import importlib.util
import math
import wave
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.cluster import AgglomerativeClustering
from sklearn.metrics import silhouette_score


MODEL_SOURCE = "speechbrain/spkrec-ecapa-voxceleb"


def choose_speaker_count(embeddings: np.ndarray, requested: int = 0) -> int:
    if requested > 0:
        return min(requested, len(embeddings))
    max_speakers = min(6, len(embeddings) - 1)
    if max_speakers < 2:
        return 1
    best_k = 1
    best_score = 0.2
    for count in range(2, max_speakers + 1):
        labels = AgglomerativeClustering(
            n_clusters=count,
            metric="cosine",
            linkage="average",
        ).fit_predict(embeddings)
        score = float(silhouette_score(embeddings, labels, metric="cosine"))
        adjusted = score - 0.025 * (count - 2)
        if adjusted > best_score:
            best_k = count
            best_score = adjusted
    return best_k


def cluster_embeddings(embeddings: np.ndarray, speaker_count: int = 0) -> np.ndarray:
    embeddings = np.asarray(embeddings, dtype=np.float32)
    if len(embeddings) == 0:
        return np.empty(0, dtype=int)
    count = choose_speaker_count(embeddings, speaker_count)
    if count <= 1 or len(embeddings) < count:
        return np.zeros(len(embeddings), dtype=int)
    return np.asarray(
        AgglomerativeClustering(
            n_clusters=count,
            metric="cosine",
            linkage="average",
        ).fit_predict(embeddings),
        dtype=int,
    )


def canonicalize(labels: np.ndarray) -> list[str]:
    if len(labels) == 0:
        return []
    first_seen = {int(label): int(np.where(labels == label)[0][0]) for label in set(labels.tolist())}
    mapping = {label: index for index, label in enumerate(sorted(first_seen, key=first_seen.get))}
    return [f"SPEAKER_{mapping[int(label)]:02d}" for label in labels]


def nearest_speaker(row: dict[str, Any], labeled_turns: list[dict[str, Any]]) -> str | None:
    if not labeled_turns:
        return None
    previous = [turn for turn in labeled_turns if float(turn["end"]) <= float(row["start"])]
    following = [turn for turn in labeled_turns if float(turn["start"]) >= float(row["end"])]
    left = previous[-1] if previous else None
    right = following[0] if following else None
    if left and right and left["speaker"] == right["speaker"]:
        return str(left["speaker"])
    if left and not right:
        return str(left["speaker"])
    if right and not left:
        return str(right["speaker"])
    if left and right:
        left_gap = abs(float(row["start"]) - float(left["end"]))
        right_gap = abs(float(right["start"]) - float(row["end"]))
        return str(left["speaker"] if left_gap <= right_gap else right["speaker"])
    return str(labeled_turns[0]["speaker"])


def assign_speakers_to_segments(
    segments: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    speakers: list[str],
) -> list[dict[str, Any]]:
    labeled = [
        {**row, "speaker": speaker, "speaker_source": "embedding"}
        for row, speaker in zip(rows, speakers)
    ]
    by_index = {int(turn["index"]): turn for turn in labeled}
    turns: list[dict[str, Any]] = []
    for index, segment in enumerate(segments):
        row = {
            "index": index,
            "start": float(segment["start"]),
            "end": float(segment["end"]),
            "text": str(segment.get("text") or "").strip(),
        }
        if not row["text"]:
            continue
        if index in by_index:
            turns.append(by_index[index])
            continue
        speaker = nearest_speaker(row, labeled)
        if speaker is not None:
            turns.append({**row, "speaker": speaker, "speaker_source": "nearest"})
    return turns


def load_audio(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as wav:
        channels = wav.getnchannels()
        sample_rate = wav.getframerate()
        samples = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2")
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1).astype(np.int16)
    return samples.astype(np.float32) / 32768.0, sample_rate


def _rms(samples: np.ndarray) -> float:
    return float(np.sqrt(np.mean(samples * samples))) if len(samples) else 0.0


def encode_segments(
    classifier: Any,
    audio: np.ndarray,
    sample_rate: int,
    segments: list[dict[str, Any]],
) -> tuple[np.ndarray, list[dict[str, Any]]]:
    import torch

    embeddings: list[np.ndarray] = []
    rows: list[dict[str, Any]] = []
    for index, segment in enumerate(segments):
        start = float(segment["start"])
        end = float(segment["end"])
        if end - start < 1.0:
            continue
        chunk = audio[max(0, int(start * sample_rate)) : min(len(audio), int(end * sample_rate))]
        if len(chunk) < sample_rate or _rms(chunk) < 0.004:
            continue
        waveform = torch.tensor(chunk, dtype=torch.float32).unsqueeze(0)
        with torch.no_grad():
            vector = classifier.encode_batch(waveform).squeeze().cpu().numpy()
        norm = float(np.linalg.norm(vector))
        embeddings.append(vector / (norm if norm > 1e-9 else 1.0))
        rows.append(
            {
                "index": index,
                "start": start,
                "end": end,
                "text": str(segment.get("text") or "").strip(),
            }
        )
    if not embeddings:
        return np.empty((0, 0), dtype=np.float32), rows
    return np.stack(embeddings), rows


class DiarizationService:
    def __init__(self, model_dir: Path | None = None, speaker_count: int = 0) -> None:
        self.model_dir = model_dir or Path.home() / ".cache/live-clip-studio/speechbrain-spkrec-ecapa"
        self.speaker_count = speaker_count
        self._classifier: Any | None = None

    @staticmethod
    def probe() -> dict[str, Any]:
        required = ("speechbrain", "sklearn", "numpy", "torch", "soundfile")
        missing = [name for name in required if importlib.util.find_spec(name) is None]
        return {
            "status": "ready" if not missing else "unavailable",
            "detail": None if not missing else f"missing: {', '.join(missing)}",
        }

    def _load_classifier(self) -> Any:
        if self._classifier is None:
            from speechbrain.inference.classifiers import EncoderClassifier

            self._classifier = EncoderClassifier.from_hparams(
                source=MODEL_SOURCE,
                savedir=str(self.model_dir),
                run_opts={"device": "cpu"},
            )
        return self._classifier

    def run(self, audio_path: Path, segments: list[dict[str, Any]]) -> dict[str, Any]:
        try:
            audio, sample_rate = load_audio(audio_path)
            embeddings, rows = encode_segments(
                self._load_classifier(),
                audio,
                sample_rate,
                segments,
            )
            if len(rows) == 0:
                raise RuntimeError("no usable speech segments for speaker embeddings")
            labels = cluster_embeddings(embeddings, self.speaker_count)
            speakers = canonicalize(labels)
            turns = assign_speakers_to_segments(segments, rows, speakers)
            by_index = {int(turn["index"]): turn for turn in turns}
            ordered_labels = [
                {
                    "speaker": by_index[index]["speaker"],
                    "speaker_source": by_index[index]["speaker_source"],
                }
                for index in range(len(segments))
            ]
            return {
                "status": "ready",
                "detail": None,
                "speaker_count": len(set(speakers)),
                "labels": ordered_labels,
                "usable_segments": len(rows),
                "model": MODEL_SOURCE,
                "embedding_cache": {
                    "model": "ECAPA",
                    "similarity_threshold": 0.35,
                    "embeddings": embeddings,
                    "indices": np.asarray([int(row["index"]) for row in rows], dtype=np.int32),
                },
            }
        except Exception as exc:
            return {
                "status": "unavailable",
                "detail": str(exc),
                "speaker_count": None,
                "labels": [],
            }
