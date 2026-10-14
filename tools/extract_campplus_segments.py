from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import torch


ROOT = Path(__file__).resolve().parents[1]
JOB = ROOT / "data/f03d40e1-0f06-4454-a83f-1a512c7e4ae2"
TRANSCRIPT = JOB / "transcript"
OUTPUT = JOB / "speaker-experiments/campplus-embeddings.npz"
THREE_D_SPEAKER = Path("/tmp/3D-Speaker")
MODEL_DIR = (
    Path.home()
    / ".cache/modelscope/models/iic--speech_campplus_sv_zh_en_16k-common_advanced/snapshots/v1.0.0"
)

sys.path.insert(0, str(THREE_D_SPEAKER))

from speakerlab.models.campplus.DTDNN import CAMPPlus  # noqa: E402
from speakerlab.process.processor import FBank  # noqa: E402

from live_clip_studio.diarization import load_audio  # noqa: E402


def main() -> None:
    segments = json.loads((TRANSCRIPT / "segments.json").read_text())["segments"]
    audio, sample_rate = load_audio(TRANSCRIPT / "audio-16k-mono.wav")

    model = CAMPPlus(feat_dim=80, embedding_size=192)
    checkpoint = MODEL_DIR / "campplus_cn_en_common.pt"
    model.load_state_dict(torch.load(checkpoint, map_location="cpu"))
    model.eval()
    feature_extractor = FBank(80, sample_rate=16000, mean_nor=True)

    embeddings: list[np.ndarray] = []
    indexes: list[int] = []
    for index, segment in enumerate(segments):
        start = float(segment["start"])
        end = float(segment["end"])
        if end - start < 1.0:
            continue
        chunk = audio[int(start * sample_rate) : int(end * sample_rate)]
        if len(chunk) < sample_rate:
            continue
        waveform = torch.tensor(chunk, dtype=torch.float32).unsqueeze(0)
        with torch.no_grad():
            feature = feature_extractor(waveform).unsqueeze(0)
            vector = model(feature).squeeze().cpu().numpy()
        vector = vector / (float(np.linalg.norm(vector)) + 1e-9)
        embeddings.append(vector)
        indexes.append(index)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        OUTPUT,
        embeddings=np.asarray(embeddings, dtype=np.float32),
        indices=np.asarray(indexes, dtype=np.int32),
    )
    print(f"saved {len(embeddings)} embeddings to {OUTPUT}")


if __name__ == "__main__":
    main()
