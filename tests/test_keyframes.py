from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from live_clip_studio.app import create_app
from live_clip_studio.config import Settings
from live_clip_studio.keyframes import generate_keyframes


def make_scene_video(path: Path) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=red:s=320x180:d=1:r=25",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=320x180:d=1:r=25",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=320x180:d=1:r=25",
            "-filter_complex",
            "[0:v][1:v][2:v]concat=n=3:v=1:a=0,format=yuv420p[v]",
            "-map",
            "[v]",
            str(path),
        ],
        check=True,
    )


def test_generate_keyframes_keeps_scene_change_and_drops_duplicate(tmp_path: Path) -> None:
    video = tmp_path / "scenes.mp4"
    make_scene_video(video)

    document = generate_keyframes(video, tmp_path / "output")

    assert document["candidate_count"] >= 3
    assert document["frame_count"] == 2
    assert [frame["timestamp"] for frame in document["frames"]] == sorted(
        frame["timestamp"] for frame in document["frames"]
    )
    colors = []
    for frame in document["frames"]:
        image_path = tmp_path / "output" / "keyframes" / Path(frame["image_url"]).name
        assert image_path.stat().st_size > 0
        colors.append(Image.open(image_path).resize((1, 1)).getpixel((0, 0)))
    assert any(red > blue for red, _, blue in colors)
    assert any(blue > red for red, _, blue in colors)


def test_generate_keyframes_disables_frame_cap(tmp_path: Path) -> None:
    video = tmp_path / "source.mp4"
    video.write_bytes(b"video")
    captured: dict = {}

    def extractor(video_path: str, frames_dir: str, scene: float, fps_floor: float):
        frames = Path(frames_dir)
        frames.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (16, 16), "red").save(frames / "raw_00001.jpg")
        return 1, [0.0]

    def deduplicator(frames_dir: str, threshold: float, window: int, max_frames: int, times):
        captured.update(
            threshold=threshold,
            window=window,
            max_frames=max_frames,
            times=times,
        )
        source = Path(frames_dir) / "raw_00001.jpg"
        source.rename(Path(frames_dir) / "frame_001.jpg")
        return 1, [
            {"name": "frame_001.jpg", "dist": None, "settled": None, "via": "first", "kept": True, "t": 0.0}
        ]

    document = generate_keyframes(
        video,
        tmp_path / "output",
        extractor=extractor,
        deduplicator=deduplicator,
    )

    assert captured == {"threshold": 8, "window": 4, "max_frames": 0, "times": [0.0]}
    assert document["frame_count"] == 1
    assert all(not frame.get("capped") for frame in document["frames"])


@dataclass
class FakeWhisper:
    def health(self) -> dict:
        return {"status": "ok", "model": "mlx-community/whisper-large-v3-turbo"}


@dataclass
class KeyframeProcessor:
    submitted: list[str] = field(default_factory=list)

    def submit_transcript(self, job_id: str) -> None:
        return None

    def submit_keyframes(self, job_id: str) -> None:
        self.submitted.append(job_id)


def make_api(tmp_path: Path) -> tuple[TestClient, KeyframeProcessor]:
    processor = KeyframeProcessor()
    app = create_app(
        settings=Settings(data_dir=tmp_path / "data"),
        whisper_client=FakeWhisper(),
        media_probe=lambda: {"ffmpeg": True, "ffprobe": True},
        diarization_probe=lambda: {"status": "ready", "detail": None},
        processor=processor,
    )
    return TestClient(app), processor


def test_keyframe_start_is_ready_only_and_idempotent(tmp_path: Path) -> None:
    client, processor = make_api(tmp_path)
    store = client.app.state.job_store
    pending = store.create("pending.mp4")

    blocked = client.post(f"/api/jobs/{pending['job_id']}/keyframes")

    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "TRANSCRIPT_NOT_READY"

    store.update(pending["job_id"], status="ready", stage="ready", progress=100)
    first = client.post(f"/api/jobs/{pending['job_id']}/keyframes")
    second = client.post(f"/api/jobs/{pending['job_id']}/keyframes")

    assert first.status_code == 202
    assert second.status_code == 202
    assert processor.submitted == [pending["job_id"]]
    assert second.json()["status"] == "queued"


def test_keyframe_get_returns_not_started_shape(tmp_path: Path) -> None:
    client, _ = make_api(tmp_path)
    store = client.app.state.job_store
    job = store.create("video.mp4")
    store.update(job["job_id"], status="ready", stage="ready", progress=100)

    response = client.get(f"/api/jobs/{job['job_id']}/keyframes")

    assert response.status_code == 200
    assert response.json() == {"status": "not_started", "frames": []}


def test_force_keyframes_requeues_a_ready_result(tmp_path: Path) -> None:
    client, processor = make_api(tmp_path)
    store = client.app.state.job_store
    job = store.create("video.mp4")
    store.update(
        job["job_id"],
        status="ready",
        stage="ready",
        progress=100,
        keyframes_status="ready",
        keyframe_count=9,
    )

    response = client.post(f"/api/jobs/{job['job_id']}/keyframes?force=true")

    assert response.status_code == 202
    assert response.json()["status"] == "queued"
    assert processor.submitted == [job["job_id"]]
