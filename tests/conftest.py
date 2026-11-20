"""Shared test fixtures. The default suite never loads a real model."""

from __future__ import annotations

import io
import math
import os
import wave
from dataclasses import replace
from pathlib import Path
from typing import Callable

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.asr.fake import FakeASREngine
from app.config import load_settings
from app.main import create_app

BASE_DIR = Path(__file__).resolve().parent.parent


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if os.getenv("RUN_REAL_ASR") == "1":
        return
    skip_real = pytest.mark.skip(
        reason="真实模型测试默认跳过；设置 RUN_REAL_ASR=1 并先下载模型后执行 pytest -m real_asr"
    )
    for item in items:
        if "real_asr" in item.keywords:
            item.add_marker(skip_real)


def make_wav_bytes(
    seconds: float = 1.0,
    sample_rate: int = 16_000,
    frequency: float = 440.0,
    channels: int = 1,
    amplitude: float = 0.35,
) -> bytes:
    frames = max(1, int(round(seconds * sample_rate)))
    timeline = np.arange(frames, dtype=np.float64) / sample_rate
    mono = (np.sin(2 * math.pi * frequency * timeline) * amplitude * 32767).astype("<i2")
    if channels > 1:
        mono = np.repeat(mono[:, None], channels, axis=1).reshape(-1)

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(channels)
        writer.setsampwidth(2)
        writer.setframerate(sample_rate)
        writer.writeframes(mono.tobytes())
    return buffer.getvalue()


def make_silence_wav_bytes(seconds: float = 1.0, sample_rate: int = 16_000) -> bytes:
    frames = max(1, int(round(seconds * sample_rate)))
    silence = np.zeros(frames, dtype="<i2")
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(sample_rate)
        writer.writeframes(silence.tobytes())
    return buffer.getvalue()


@pytest.fixture
def wav_bytes() -> bytes:
    return make_wav_bytes(1.0)


@pytest.fixture
def silence_wav_bytes() -> bytes:
    return make_silence_wav_bytes(1.0)


@pytest.fixture
def fake_engine() -> FakeASREngine:
    return FakeASREngine(text="这是一段测试语音。")


@pytest.fixture
def test_settings():
    return replace(
        load_settings(),
        max_upload_bytes=10 * 1024 * 1024,
        max_recording_seconds=60.0,
        max_audio_seconds=0.0,
        realtime_chunk_seconds=0.2,
        realtime_overlap_seconds=0.05,
    )


@pytest.fixture
def client(fake_engine: FakeASREngine, test_settings) -> TestClient:
    app = create_app(engine=fake_engine, settings=test_settings)
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


@pytest.fixture
def client_factory() -> Callable[..., TestClient]:
    created: list[TestClient] = []

    def factory(engine: FakeASREngine | None = None, **overrides) -> TestClient:
        settings = replace(load_settings(), **overrides)
        app = create_app(engine=engine or FakeASREngine(), settings=settings)
        test_client = TestClient(app, raise_server_exceptions=False)
        created.append(test_client)
        return test_client

    yield factory

    for test_client in created:
        test_client.close()
