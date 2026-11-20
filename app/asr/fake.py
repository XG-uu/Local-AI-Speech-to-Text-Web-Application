"""A deterministic ASR engine used by the default test suite."""

from __future__ import annotations

from typing import Any

import numpy as np

from app.asr.base import ASRResult, ASRSegment
from app.errors import ModelUnavailableError


class FakeASREngine:
    """Configurable fake engine.

    It never imports faster-whisper, so tests run without model weights.
    """

    name = "fake"

    def __init__(
        self,
        text: str = "这是一段测试语音。",
        language: str | None = None,
        *,
        load_error: Exception | None = None,
        transcribe_error: Exception | None = None,
        loaded: bool = True,
    ) -> None:
        self.text = text
        self.fixed_language = language
        self.load_error = load_error
        self.transcribe_error = transcribe_error
        self._loaded = loaded
        self.calls: list[dict[str, Any]] = []

    def ensure_loaded(self) -> None:
        if self.load_error is not None:
            raise self.load_error
        self._loaded = True

    def transcribe(self, audio: np.ndarray, language: str) -> ASRResult:
        if self.transcribe_error is not None:
            raise self.transcribe_error
        self.ensure_loaded()
        self.calls.append({"language": language, "samples": int(audio.shape[0])})
        detected = self.fixed_language or ("en" if language == "en" else "zh")
        if language == "auto":
            detected = self.fixed_language or "zh"
        duration = audio.shape[0] / 16000.0
        segments = [ASRSegment(start=0.0, end=round(duration, 3), text=self.text)] if self.text else []
        return ASRResult(text=self.text, language=detected, segments=segments)

    def status(self) -> dict[str, Any]:
        return {
            "model": self.name,
            "device": "cpu",
            "compute_type": "fake",
            "model_loaded": self._loaded,
            "model_ready": self._loaded and self.load_error is None,
            "error": None if self.load_error is None else str(self.load_error),
        }
