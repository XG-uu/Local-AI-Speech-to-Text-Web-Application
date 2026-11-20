"""faster-whisper based local ASR engine."""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

import numpy as np

from app.asr.base import ASRResult, ASRSegment
from app.config import Settings
from app.errors import InferenceFailedError, ModelUnavailableError

logger = logging.getLogger(__name__)

_CHINESE_PROMPT = "以下是普通话的句子，请使用简体中文和标点符号。"


class WhisperEngine:
    """Lazy singleton wrapper around faster-whisper.

    Loading and inference are serialized with a lock: this app targets a single
    local user and CPU inference, so predictable resource use beats concurrency.
    """

    name = "whisper"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._model = None
        self._lock = threading.RLock()
        self._loaded = False
        self._load_error: str | None = None

    # ------------------------------------------------------------------ paths
    @property
    def display_name(self) -> str:
        return f"faster-whisper/{self.settings.model_name}"

    def _local_model_path(self) -> Path | None:
        raw = Path(self.settings.model_name).expanduser()
        if raw.is_absolute() or raw.exists():
            if raw.is_dir():
                return raw
            if raw.is_file():
                return raw.parent
        candidate = self.settings.model_dir / self.settings.model_name
        if candidate.is_dir():
            return candidate
        return None

    # ---------------------------------------------------------------- loading
    def ensure_loaded(self) -> None:
        with self._lock:
            if self._loaded:
                return
            self._load()

    def _load(self) -> None:
        local_path = self._local_model_path()
        if local_path is None and self.settings.offline:
            self._load_error = "离线模式已开启，但本地未找到模型权重。"
            raise ModelUnavailableError(
                "模型尚未下载。请先联网执行 python -m app.scripts.download_model，"
                "或关闭 ASR_OFFLINE 后重试。"
            )

        try:
            from faster_whisper import WhisperModel

            if local_path is not None:
                model_ref: str = str(local_path)
                local_files_only = True
                download_root = None
            else:
                model_ref = self.settings.model_name
                local_files_only = self.settings.offline
                download_root = str(self.settings.model_dir)

            self.settings.model_dir.mkdir(parents=True, exist_ok=True)
            logger.info(
                "Loading faster-whisper model=%s device=%s compute_type=%s local=%s",
                model_ref,
                self.settings.device,
                self.settings.compute_type,
                local_path is not None,
            )
            self._model = WhisperModel(
                model_ref,
                device=self.settings.device,
                compute_type=self.settings.compute_type,
                download_root=download_root,
                local_files_only=local_files_only,
            )
            self._loaded = True
            self._load_error = None
            logger.info("faster-whisper model ready")
        except Exception as exc:  # noqa: BLE001
            self._loaded = False
            self._model = None
            self._load_error = f"{type(exc).__name__}: {exc}"
            logger.exception("Failed to load faster-whisper model")
            raise ModelUnavailableError(
                "模型加载失败。请确认已执行 python -m app.scripts.download_model，"
                "并检查网络或模型目录配置。"
            ) from exc

    # ------------------------------------------------------------- inference
    def transcribe(self, audio: np.ndarray, language: str) -> ASRResult:
        with self._lock:
            self.ensure_loaded()
            assert self._model is not None

            params: dict[str, Any] = {
                "beam_size": self.settings.beam_size,
                "vad_filter": self.settings.vad_filter,
                "condition_on_previous_text": False,
            }
            if language in {"zh", "en"}:
                params["language"] = language
            if language == "zh":
                params["initial_prompt"] = _CHINESE_PROMPT

            try:
                raw_segments, info = self._model.transcribe(audio, **params)
                segments: list[ASRSegment] = []
                text_parts: list[str] = []
                for segment in raw_segments:
                    raw_text = segment.text or ""
                    text = raw_text.strip()
                    if not text:
                        continue
                    text_parts.append(raw_text)
                    segments.append(
                        ASRSegment(
                            start=round(float(segment.start), 3),
                            end=round(float(segment.end), 3),
                            text=text,
                        )
                    )
            except Exception as exc:  # noqa: BLE001
                logger.exception("faster-whisper inference failed")
                raise InferenceFailedError("语音识别失败，请重试。") from exc

            detected = getattr(info, "language", None) or (language if language in {"zh", "en"} else "zh")
            # Whisper segments already contain the right spacing (English
            # segments usually start with a space), so concatenate raw text.
            text = "".join(text_parts).strip()

            return ASRResult(text=text, language=str(detected), segments=segments)

    # ---------------------------------------------------------------- status
    def status(self) -> dict[str, Any]:
        return {
            "model": self.settings.model_name,
            "engine": self.display_name,
            "device": self.settings.device,
            "compute_type": self.settings.compute_type,
            "model_loaded": self._loaded,
            "model_ready": self._loaded,
            "offline": self.settings.offline,
            "error": self._load_error,
        }
