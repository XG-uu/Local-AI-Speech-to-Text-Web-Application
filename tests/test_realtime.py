from __future__ import annotations

import numpy as np
import pytest

from app.asr.fake import FakeASREngine
from app.realtime import RealtimeConfig, RealtimeSession, merge_text
from tests.conftest import make_wav_bytes


def pcm_bytes(seconds: float = 0.5, sample_rate: int = 16_000) -> bytes:
    frames = max(1, int(seconds * sample_rate))
    timeline = np.arange(frames, dtype=np.float64) / sample_rate
    samples = (np.sin(2 * np.pi * 440 * timeline) * 0.3 * 32767).astype("<i2")
    return samples.tobytes()


def test_merge_text_chinese_without_overlap() -> None:
    assert merge_text("你好", "世界", "zh") == "你好世界"


def test_merge_text_deduplicates_overlap() -> None:
    assert merge_text("Hello world", "world again", "en") == "Hello world again"
    assert merge_text("你好世界", "世界你好", "zh") == "你好世界你好"


def test_session_partial_and_final() -> None:
    engine = FakeASREngine(text="实时测试文本。")
    session = RealtimeSession(
        engine,
        "zh",
        RealtimeConfig(chunk_seconds=0.2, overlap_seconds=0.05),
    )
    session.add_pcm(pcm_bytes(0.3))
    assert session.should_process()
    text = session.process_partial()
    assert text == "实时测试文本。"
    assert not session.should_process()

    session.add_pcm(pcm_bytes(0.3))
    assert session.should_process()
    assert session.process_partial() == "实时测试文本。"
    assert session.duration_seconds == pytest.approx(0.6, abs=0.01)

    final = session.finalize()
    assert final.text == "实时测试文本。"
    assert final.language == "zh"


def test_session_without_audio_finalizes_empty() -> None:
    session = RealtimeSession(FakeASREngine(), "en")
    final = session.finalize()
    assert final.text == ""
    assert final.language == "en"


def test_websocket_partial_and_final(client_factory) -> None:
    engine = FakeASREngine(text="实时测试文本。")
    client = client_factory(
        engine=engine,
        realtime_chunk_seconds=0.2,
        realtime_overlap_seconds=0.05,
    )
    with client.websocket_connect("/ws/transcribe?language=zh") as websocket:
        websocket.send_json({"type": "start", "language": "zh"})
        ready = websocket.receive_json()
        assert ready["type"] == "ready"
        assert ready["sample_rate"] == 16000

        websocket.send_bytes(pcm_bytes(0.5))
        partial = websocket.receive_json()
        assert partial["type"] == "partial"
        assert partial["text"] == "实时测试文本。"
        assert partial["duration_seconds"] == pytest.approx(0.5, abs=0.01)

        websocket.send_json({"type": "stop"})
        final = websocket.receive_json()
        assert final["type"] == "final"
        assert final["text"] == "实时测试文本。"
        assert final["language"] == "zh"
        assert final["duration_seconds"] == pytest.approx(0.5, abs=0.01)
        assert final["processing_seconds"] >= 0


def test_websocket_requires_start(client_factory) -> None:
    client = client_factory()
    with client.websocket_connect("/ws/transcribe?language=zh") as websocket:
        websocket.send_bytes(pcm_bytes(0.1))
        message = websocket.receive_json()
        assert message["type"] == "error"
        assert message["code"] == "not_started"


def test_websocket_invalid_language(client_factory) -> None:
    client = client_factory()
    with client.websocket_connect("/ws/transcribe?language=fr") as websocket:
        websocket.send_json({"type": "start", "language": "fr"})
        message = websocket.receive_json()
        assert message["type"] == "error"
        assert message["code"] == "invalid_language"


def test_websocket_rejects_oversized_recording(client_factory) -> None:
    client = client_factory(max_recording_seconds=0.1, realtime_chunk_seconds=0.2)
    with client.websocket_connect("/ws/transcribe?language=zh") as websocket:
        websocket.send_json({"type": "start", "language": "zh"})
        assert websocket.receive_json()["type"] == "ready"
        websocket.send_bytes(pcm_bytes(1.0))
        message = websocket.receive_json()
        assert message["type"] == "error"
        assert message["code"] == "recording_too_long"


def test_websocket_unknown_message(client_factory) -> None:
    client = client_factory()
    with client.websocket_connect("/ws/transcribe?language=zh") as websocket:
        websocket.send_json({"type": "start", "language": "zh"})
        assert websocket.receive_json()["type"] == "ready"
        websocket.send_json({"type": "pause"})
        message = websocket.receive_json()
        assert message["type"] == "error"
        assert message["code"] == "invalid_message"


def test_websocket_accepts_audio_after_start(client_factory) -> None:
    """A short final-only session should still return a result."""
    client = client_factory(realtime_chunk_seconds=10.0)
    with client.websocket_connect("/ws/transcribe?language=zh") as websocket:
        websocket.send_json({"type": "start", "language": "zh"})
        websocket.receive_json()
        websocket.send_bytes(pcm_bytes(0.2))
        websocket.send_json({"type": "stop"})
        final = websocket.receive_json()
        assert final["type"] == "final"
        assert final["duration_seconds"] == pytest.approx(0.2, abs=0.01)


def test_wav_helper_is_compatible_with_pcm_bytes() -> None:
    assert len(make_wav_bytes(0.1)) > 0
