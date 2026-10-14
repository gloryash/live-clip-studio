from pathlib import Path


def test_launcher_is_safe_and_starts_local_app() -> None:
    launcher = (Path(__file__).resolve().parents[1] / "start.command").read_text(encoding="utf-8")

    assert "lsof" in launcher
    assert "8788" in launcher
    assert "uv sync --extra diarization" in launcher
    assert "uvicorn live_clip_studio.app:app" in launcher
    assert "open http://127.0.0.1:8788" in launcher
    assert "kill " not in launcher
    assert "kill -9" not in launcher
