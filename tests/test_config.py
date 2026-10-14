from pathlib import Path

from live_clip_studio.config import Settings


def test_settings_default_to_local_services(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path)

    assert settings.whisper_url == "http://127.0.0.1:8765"
    assert settings.whisper_model == "mlx-community/whisper-large-v3-turbo"
    assert settings.data_dir == tmp_path


def test_settings_support_explicit_runtime_overrides(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path,
        whisper_url="http://127.0.0.1:9876",
        executor_workers=1,
    )

    assert settings.whisper_url.endswith(":9876")
    assert settings.executor_workers == 1
