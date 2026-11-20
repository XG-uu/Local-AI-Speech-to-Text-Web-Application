"""Buffering and incremental transcription for the optional realtime mode."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from app.asr.base import ASREngine, ASRResult
from app.errors import RecordingTooLongError


@dataclass(frozen=True)
class RealtimeConfig:
    sample_rate: int = 16_000
    max_seconds: float = 60.0
    chunk_seconds: float = 2.5
    overlap_seconds: float = 0.4

    @property
    def chunk_samples(self) -> int:
        return max(1, int(self.chunk_seconds * self.sample_rate))

    @property
    def overlap_samples(self) -> int:
        return max(0, int(self.overlap_seconds * self.sample_rate))


def merge_text(previous: str, new: str, language: str) -> str:
    """Append a new chunk transcript, removing a repeated boundary when possible."""

    previous = previous.strip()
    new = new.strip()
    if not previous:
        return new
    if not new:
        return previous

    max_overlap = min(30, len(previous), len(new))
    overlap = 0
    for size in range(max_overlap, 1, -1):
        if previous[-size:] == new[:size]:
            overlap = size
            break
    if overlap:
        new = new[overlap:].lstrip()

    if not new:
        return previous
    if language == "en":
        if previous.endswith((" ", "-", "'")):
            return previous + new
        return previous + " " + new
    return previous + new


class RealtimeSession:
    """Accumulates PCM and periodically transcribes a short tail window."""

    def __init__(
        self,
        engine: ASREngine,
        language: str,
        config: RealtimeConfig | None = None,
    ) -> None:
        self.engine = engine
        self.language = language
        self.config = config or RealtimeConfig()
        self._parts: list[np.ndarray] = []
        self._sample_count = 0
        self._processed_samples = 0
        self._text = ""

    @property
    def duration_seconds(self) -> float:
        return self._sample_count / float(self.config.sample_rate)

    @property
    def accumulated_text(self) -> str:
        return self._text

    @property
    def sample_count(self) -> int:
        return self._sample_count

    def add_pcm(self, data: bytes) -> None:
        """Append 16-bit little-endian mono PCM. Raises when the 60s cap is exceeded."""

        if not data:
            return
        if len(data) % 2:
            data = data[:-1]
        if not data:
            return
        audio = np.frombuffer(data, dtype="<i2").astype(np.float32) / 32768.0
        self._parts.append(audio)
        self._sample_count += int(audio.shape[0])
        if self.duration_seconds > self.config.max_seconds + 0.5:
            raise RecordingTooLongError(
                f"实时录音超过 {self.config.max_seconds:.0f} 秒上限，已停止识别。"
            )

    def should_process(self) -> bool:
        return (self._sample_count - self._processed_samples) >= self.config.chunk_samples

    def _all_audio(self) -> np.ndarray:
        if not self._parts:
            return np.zeros(0, dtype=np.float32)
        if len(self._parts) == 1:
            return self._parts[0]
        return np.concatenate(self._parts)

    def process_partial(self) -> str:
        """Transcribe the new tail (plus a little overlap) and return cumulative text."""

        audio = self._all_audio()
        start = max(0, self._processed_samples - self.config.overlap_samples)
        segment = audio[start:]
        if segment.size == 0:
            return self._text

        result = self.engine.transcribe(segment, self.language)
        self._processed_samples = self._sample_count
        self._text = merge_text(self._text, result.text, self.language)
        return self._text

    def finalize(self) -> ASRResult:
        audio = self._all_audio()
        if audio.size == 0:
            language = "zh" if self.language == "auto" else self.language
            return ASRResult(text="", language=language, segments=[])
        result = self.engine.transcribe(audio, self.language)
        self._text = result.text
        return result
