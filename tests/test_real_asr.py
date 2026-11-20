"""Real model tests.

These are skipped by the default suite. Run with:

    python -m app.scripts.download_model
    set RUN_REAL_ASR=1
    python -m pytest -q -m real_asr
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.asr.whisper_engine import WhisperEngine
from app.audio import decode_audio
from app.config import load_settings
from app.main import create_app

pytestmark = pytest.mark.real_asr

BASE_DIR = Path(__file__).resolve().parent.parent

CASES = [
    ("chinese.wav", "zh", ["语音识别", "你好", "欢迎"]),
    ("english.wav", "en", ["speech recognition", "welcome", "hello"]),
]


@pytest.fixture(scope="module")
def real_engine() -> WhisperEngine:
    engine = WhisperEngine(load_settings())
    engine.ensure_loaded()
    return engine


@pytest.mark.parametrize("filename,language,keywords", CASES)
def test_real_model_transcribes_samples(real_engine, filename, language, keywords) -> None:
    sample = BASE_DIR / "samples" / filename
    assert sample.is_file(), f"缺少样例音频：{sample}"

    audio = decode_audio(sample.read_bytes())
    assert 3.0 <= audio.duration_seconds <= 20.0

    result = real_engine.transcribe(audio.samples, language)
    print(f"\n[{filename}] {result.text} ({audio.duration_seconds:.2f}s)")
    assert result.text.strip(), "真实模型返回了空文本"
    normalized = result.text.lower()
    assert any(keyword.lower() in normalized for keyword in keywords), (
        f"识别结果未包含预期关键词：{keywords}\n实际结果：{result.text}"
    )


def test_real_model_http_api(real_engine: WhisperEngine) -> None:
    sample = BASE_DIR / "samples" / "chinese.wav"
    assert sample.is_file()

    app = create_app(engine=real_engine, settings=load_settings())
    with TestClient(app) as client:
        response = client.post(
            "/api/transcribe",
            files={"file": ("chinese.wav", sample.read_bytes(), "audio/wav")},
            data={"language": "zh", "source": "upload"},
        )
    assert response.status_code == 200
    body = response.json()
    print(f"\n[HTTP] {body['text']}")
    assert body["text"].strip()
    assert body["language"] == "zh"
    assert body["duration_seconds"] > 3
    assert body["processing_seconds"] >= 0
