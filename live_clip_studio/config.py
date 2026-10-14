from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path


EXPECTED_WHISPER_MODEL = "mlx-community/whisper-large-v3-turbo"


def _default_data_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "data"


@dataclass(slots=True)
class Settings:
    data_dir: Path = field(default_factory=_default_data_dir)
    whisper_url: str = "http://127.0.0.1:8765"
    whisper_model: str = EXPECTED_WHISPER_MODEL
    whisper_timeout_seconds: float = 7200.0
    max_upload_bytes: int = 53_687_091_200
    executor_workers: int = 2
    diarization_python: str = sys.executable

    def __post_init__(self) -> None:
        self.data_dir = Path(self.data_dir).expanduser().resolve()
        self.whisper_url = self.whisper_url.rstrip("/")
        if self.executor_workers < 1:
            raise ValueError("executor_workers must be positive")
        if self.max_upload_bytes < 1:
            raise ValueError("max_upload_bytes must be positive")

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            data_dir=Path(os.environ.get("LIVE_CLIP_DATA_DIR", _default_data_dir())),
            whisper_url=os.environ.get("LIVE_CLIP_WHISPER_URL", "http://127.0.0.1:8765"),
            whisper_model=os.environ.get("LIVE_CLIP_WHISPER_MODEL", EXPECTED_WHISPER_MODEL),
            whisper_timeout_seconds=float(os.environ.get("LIVE_CLIP_WHISPER_TIMEOUT", "7200")),
            max_upload_bytes=int(os.environ.get("LIVE_CLIP_MAX_UPLOAD_BYTES", "53687091200")),
            executor_workers=int(os.environ.get("LIVE_CLIP_EXECUTOR_WORKERS", "2")),
            diarization_python=os.environ.get("LIVE_CLIP_DIARIZATION_PYTHON", sys.executable),
        )
