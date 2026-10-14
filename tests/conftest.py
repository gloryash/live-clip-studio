from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def sample_mp4(tmp_path: Path) -> Path:
    target = tmp_path / "sample.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=navy:s=320x180:d=1",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=16000:cl=mono",
            "-shortest",
            "-pix_fmt",
            "yuv420p",
            str(target),
        ],
        check=True,
    )
    return target
