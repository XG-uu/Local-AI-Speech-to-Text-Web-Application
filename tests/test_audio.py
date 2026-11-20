from __future__ import annotations

import io
from dataclasses import replace

import av
import numpy as np
import pytest

from app.audio import (
    _decode_wav_stdlib,
    decode_audio,
    has_speech,
    validate_duration,
    write_wav,
)
from app.config import load_settings
from app.errors import (
    AppError,
    AudioTooLongError,
    EmptyFileError,
    RecordingTooLongError,
)
from tests.conftest import make_wav_bytes


def make_webm_opus_bytes(seconds: float = 0.5, sample_rate: int = 48_000) -> bytes:
    timeline = np.arange(int(sample_rate * seconds)) / sample_rate
    pcm = (np.sin(2 * np.pi * 440 * timeline) * 0.3 * 32767).astype("<i2")
    buffer = io.BytesIO()
    container = av.open(buffer, mode="w", format="webm")
    stream = container.add_stream("libopus", rate=sample_rate, layout="mono")
    frame = av.AudioFrame.from_ndarray(pcm.reshape(1, -1), format="s16", layout="mono")
    frame.sample_rate = sample_rate
    frame.pts = 0
    for packet in stream.encode(frame):
        container.mux(packet)
    for packet in stream.encode(None):
        container.mux(packet)
    container.close()
    return buffer.getvalue()


def test_decode_wav_16k() -> None:
    audio = decode_audio(make_wav_bytes(seconds=1.0, sample_rate=16_000))
    assert audio.samples.dtype == np.float32
    assert audio.sample_count == 16_000
    assert audio.duration_seconds == pytest.approx(1.0, abs=0.01)
    assert has_speech(audio.samples)


def test_decode_wav_8k_is_resampled() -> None:
    audio = decode_audio(make_wav_bytes(seconds=1.0, sample_rate=8_000))
    assert audio.duration_seconds == pytest.approx(1.0, abs=0.02)
    assert audio.sample_count == pytest.approx(16_000, abs=200)


def test_decode_stereo_wav() -> None:
    audio = decode_audio(make_wav_bytes(seconds=0.5, sample_rate=16_000, channels=2))
    assert audio.duration_seconds == pytest.approx(0.5, abs=0.01)
    assert has_speech(audio.samples)


def test_decode_webm_opus_from_browser_recording() -> None:
    data = make_webm_opus_bytes(seconds=0.5)
    assert data[:4] == b"\x1aE\xdf\xa3"
    audio = decode_audio(data)
    assert audio.duration_seconds == pytest.approx(0.5, abs=0.05)
    assert audio.sample_count == pytest.approx(8_000, abs=400)
    assert has_speech(audio.samples)


def test_empty_bytes_rejected() -> None:
    with pytest.raises(EmptyFileError):
        decode_audio(b"")


def test_corrupt_bytes_rejected() -> None:
    with pytest.raises(AppError) as exc_info:
        decode_audio(b"this is definitely not an audio file")
    assert exc_info.value.status_code == 400
    assert exc_info.value.code in {"unsupported_audio", "decode_failed"}


def test_wav_stdlib_fallback_decodes_pcm() -> None:
    samples = _decode_wav_stdlib(make_wav_bytes(seconds=0.25, sample_rate=16_000))
    assert samples.dtype == np.float32
    assert samples.shape[0] == pytest.approx(4_000, abs=100)


def test_silence_detection() -> None:
    audio = decode_audio(make_wav_bytes(seconds=0.2, amplitude=0.0))
    assert not has_speech(audio.samples)


def test_duration_validation_for_recording() -> None:
    settings = replace(load_settings(), max_recording_seconds=0.5)
    audio = decode_audio(make_wav_bytes(seconds=2.0))
    with pytest.raises(RecordingTooLongError):
        validate_duration(audio, settings, "recording")
    validate_duration(audio, settings, "upload")


def test_optional_upload_duration_limit() -> None:
    settings = replace(load_settings(), max_audio_seconds=0.5)
    audio = decode_audio(make_wav_bytes(seconds=2.0))
    with pytest.raises(AudioTooLongError):
        validate_duration(audio, settings, "upload")


def test_write_wav_helper(tmp_path) -> None:
    target = tmp_path / "tone.wav"
    timeline = np.arange(16_000) / 16_000.0
    samples = (np.sin(2 * np.pi * 440 * timeline) * 0.2).astype(np.float32)
    write_wav(target, samples)
    decoded = decode_audio(target.read_bytes())
    assert decoded.duration_seconds == pytest.approx(1.0, abs=0.01)
