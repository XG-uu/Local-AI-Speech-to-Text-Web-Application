"""Application configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _env_str(name: str, default: str) -> str:
    value = os.getenv(name)
    return value.strip() if value is not None and value.strip() else default


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return int(raw)


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return float(raw)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    """Runtime settings. Tests may build a modified copy with dataclasses.replace."""

    base_dir: Path = BASE_DIR
    static_dir: Path = BASE_DIR / "static"
    model_name: str = "small"
    model_dir: Path = BASE_DIR / "models"
    device: str = "cpu"
    compute_type: str = "int8"
    beam_size: int = 1
    offline: bool = False
    vad_filter: bool = True
    max_upload_bytes: int = 10 * 1024 * 1024
    max_recording_seconds: float = 60.0
    max_audio_seconds: float = 0.0
    realtime_chunk_seconds: float = 2.5
    realtime_overlap_seconds: float = 0.4
    log_level: str = "INFO"

    @property
    def max_upload_mb(self) -> int:
        return max(1, round(self.max_upload_bytes / (1024 * 1024)))

    @classmethod
    def from_env(cls) -> "Settings":
        model_dir = Path(_env_str("ASR_MODEL_DIR", str(BASE_DIR / "models"))).expanduser()
        return cls(
            base_dir=BASE_DIR,
            static_dir=BASE_DIR / "static",
            model_name=_env_str("ASR_MODEL", "small"),
            model_dir=model_dir,
            device=_env_str("ASR_DEVICE", "cpu"),
            compute_type=_env_str("ASR_COMPUTE_TYPE", "int8"),
            beam_size=_env_int("ASR_BEAM_SIZE", 1),
            offline=_env_bool("ASR_OFFLINE", False),
            vad_filter=_env_bool("ASR_VAD_FILTER", True),
            max_upload_bytes=_env_int("MAX_UPLOAD_MB", 10) * 1024 * 1024,
            max_recording_seconds=_env_float("MAX_RECORDING_SECONDS", 60.0),
            max_audio_seconds=_env_float("MAX_AUDIO_SECONDS", 0.0),
            realtime_chunk_seconds=_env_float("REALTIME_CHUNK_SECONDS", 2.5),
            realtime_overlap_seconds=_env_float("REALTIME_OVERLAP_SECONDS", 0.4),
            log_level=_env_str("ASR_LOG_LEVEL", "INFO").upper(),
        )


def load_settings() -> Settings:
    """Load settings from the current environment.

    Deliberately not cached: the app factory and tests can each get a fresh view.
    """

    return Settings.from_env()
