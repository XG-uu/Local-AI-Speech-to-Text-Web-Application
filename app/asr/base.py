"""ASR engine abstraction shared by the HTTP and WebSocket layers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

import numpy as np


@dataclass
class ASRSegment:
    start: float
    end: float
    text: str


@dataclass
class ASRResult:
    text: str
    language: str
    segments: list[ASRSegment] = field(default_factory=list)


@runtime_checkable
class ASREngine(Protocol):
    name: str

    def ensure_loaded(self) -> None:
        """Load the model if needed. Raises ModelUnavailableError on failure."""

    def transcribe(self, audio: np.ndarray, language: str) -> ASRResult:
        """Transcribe mono 16 kHz float32 audio."""

    def status(self) -> dict[str, Any]:
        """Return non-sensitive runtime status for /api/status."""
