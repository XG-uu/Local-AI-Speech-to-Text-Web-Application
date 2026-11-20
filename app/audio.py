"""Audio input validation, decoding, resampling and silence detection."""

from __future__ import annotations

import io
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from fastapi import UploadFile

from app.config import Settings
from app.errors import (
    AudioDecodeError,
    AudioTooLongError,
    EmptyFileError,
    FileTooLargeError,
    RecordingTooLongError,
    UnsupportedAudioError,
)

TARGET_SAMPLE_RATE = 16_000
_READ_CHUNK = 1024 * 1024
_SILENCE_PEAK = 1e-3


@dataclass
class DecodedAudio:
    """Decoded, mono, 16 kHz float32 audio."""

    samples: np.ndarray
    duration_seconds: float

    @property
    def sample_count(self) -> int:
        return int(self.samples.shape[0])


async def read_upload_limited(upload: UploadFile, limit_bytes: int) -> bytes:
    """Read an UploadFile without ever buffering more than limit_bytes + one chunk."""

    chunks: list[bytes] = []
    total = 0
    try:
        while True:
            chunk = await upload.read(_READ_CHUNK)
            if not chunk:
                break
            total += len(chunk)
            if total > limit_bytes:
                raise FileTooLargeError(
                    f"文件超过 {max(1, round(limit_bytes / (1024 * 1024)))} MB 上限，请压缩或裁剪后重试。"
                )
            chunks.append(chunk)
    finally:
        await upload.close()

    data = b"".join(chunks)
    if not data:
        raise EmptyFileError("上传的文件为空，请选择包含语音的音频文件。")
    return data


def _resample_linear(samples: np.ndarray, source_rate: int, target_rate: int = TARGET_SAMPLE_RATE) -> np.ndarray:
    if source_rate == target_rate or samples.size == 0:
        return samples.astype(np.float32, copy=False)
    duration = samples.shape[0] / float(source_rate)
    target_length = max(1, int(round(duration * target_rate)))
    source_positions = np.linspace(0.0, samples.shape[0] - 1, num=target_length, dtype=np.float64)
    return np.interp(source_positions, np.arange(samples.shape[0]), samples).astype(np.float32)


def _decode_wav_stdlib(data: bytes) -> np.ndarray:
    """Fallback decoder for PCM WAV, used only when PyAV cannot decode the file."""

    with wave.open(io.BytesIO(data), "rb") as reader:
        channels = reader.getnchannels()
        width = reader.getsampwidth()
        rate = reader.getframerate()
        frame_count = reader.getnframes()
        raw = reader.readframes(frame_count)

    if channels < 1 or frame_count < 1:
        raise AudioDecodeError("音频不包含可解码的采样数据。")

    if width == 1:
        values = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    elif width == 2:
        values = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    elif width == 3:
        raw_bytes = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3).astype(np.int32)
        ints = raw_bytes[:, 0] | (raw_bytes[:, 1] << 8) | (raw_bytes[:, 2] << 16)
        ints = np.where(ints & 0x800000, ints - 0x1000000, ints)
        values = ints.astype(np.float32) / 8388608.0
    elif width == 4:
        values = np.frombuffer(raw, dtype="<i4").astype(np.float32) / 2147483648.0
    else:
        raise AudioDecodeError(f"不支持的 WAV 采样位深：{width * 8} bit。")

    if channels > 1:
        usable = (values.shape[0] // channels) * channels
        values = values[:usable].reshape(-1, channels).mean(axis=1)

    return _resample_linear(values.astype(np.float32), rate)


def _decode_with_av(data: bytes) -> np.ndarray:
    import av

    try:
        container = av.open(io.BytesIO(data), mode="r")
    except Exception as exc:  # noqa: BLE001 - PyAV raises several low-level types
        raise UnsupportedAudioError(
            "无法识别该音频格式，请上传 WAV、WebM、OGG、MP3 或 M4A 文件。"
        ) from exc

    try:
        if not container.streams.audio:
            raise UnsupportedAudioError("文件中没有可用的音频流，请上传包含语音的音频文件。")

        stream = container.streams.audio[0]
        resampler = av.AudioResampler(format="s16", layout="mono", rate=TARGET_SAMPLE_RATE)
        parts: list[np.ndarray] = []

        def collect(frames) -> None:
            for frame in frames or []:
                array = frame.to_ndarray()
                if array.size:
                    parts.append(array.reshape(-1))

        try:
            for frame in container.decode(stream):
                collect(resampler.resample(frame))
            try:
                collect(resampler.resample(None))
            except Exception:  # noqa: BLE001 - flush support differs between PyAV versions
                pass
        except UnsupportedAudioError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise AudioDecodeError("音频解码失败，请确认文件未损坏后重试。") from exc
    finally:
        container.close()

    if not parts:
        raise AudioDecodeError("音频不包含可解码的采样数据。")

    int16 = np.concatenate(parts).astype(np.int16, copy=False)
    return int16.astype(np.float32) / 32768.0


def decode_audio(data: bytes) -> DecodedAudio:
    """Decode arbitrary audio bytes into 16 kHz mono float32 samples."""

    if not data:
        raise EmptyFileError("上传的文件为空，请选择包含语音的音频文件。")

    try:
        samples = _decode_with_av(data)
    except UnsupportedAudioError as av_error:
        try:
            samples = _decode_wav_stdlib(data)
        except Exception:
            raise av_error
    except AudioDecodeError as av_error:
        try:
            samples = _decode_wav_stdlib(data)
        except Exception:
            raise av_error

    samples = np.nan_to_num(samples, nan=0.0, posinf=0.0, neginf=0.0)
    samples = np.clip(samples, -1.0, 1.0).astype(np.float32, copy=False)
    if samples.size == 0:
        raise AudioDecodeError("音频不包含可解码的采样数据。")

    duration = samples.shape[0] / float(TARGET_SAMPLE_RATE)
    return DecodedAudio(samples=samples, duration_seconds=duration)


def validate_duration(audio: DecodedAudio, settings: Settings, source: str) -> None:
    if source == "recording" and audio.duration_seconds > settings.max_recording_seconds + 0.5:
        raise RecordingTooLongError(
            f"录音时长 {audio.duration_seconds:.1f} 秒，超过 {settings.max_recording_seconds:.0f} 秒上限。"
        )
    if settings.max_audio_seconds > 0 and audio.duration_seconds > settings.max_audio_seconds + 0.5:
        raise AudioTooLongError(
            f"音频时长 {audio.duration_seconds:.1f} 秒，超过 {settings.max_audio_seconds:.0f} 秒上限。"
        )


def has_speech(samples: np.ndarray, threshold: float = _SILENCE_PEAK) -> bool:
    if samples.size == 0:
        return False
    return bool(np.max(np.abs(samples)) >= threshold)


def write_wav(path: Path, samples: np.ndarray, sample_rate: int = TARGET_SAMPLE_RATE) -> None:
    """Small helper used by tests and sample generation."""

    clipped = np.clip(samples, -1.0, 1.0)
    pcm = (clipped * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(sample_rate)
        writer.writeframes(pcm.tobytes())
