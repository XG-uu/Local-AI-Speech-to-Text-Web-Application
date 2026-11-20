from __future__ import annotations

from fastapi.testclient import TestClient

from app.asr.fake import FakeASREngine
from tests.conftest import make_silence_wav_bytes, make_wav_bytes


def _post(
    client: TestClient,
    data: bytes,
    language: str,
    *,
    source: str | None = "upload",
    filename: str = "sample.wav",
    content_type: str = "audio/wav",
):
    values = {"language": language}
    if source is not None:
        values["source"] = source
    return client.post(
        "/api/transcribe",
        files={"file": (filename, data, content_type)},
        data=values,
    )


def test_transcribe_chinese(client: TestClient, fake_engine: FakeASREngine) -> None:
    response = _post(client, make_wav_bytes(1.0), "zh")
    assert response.status_code == 200
    body = response.json()
    assert body["text"] == fake_engine.text
    assert body["language"] == "zh"
    assert body["requested_language"] == "zh"
    assert body["duration_seconds"] == 1.0
    assert body["processing_seconds"] >= 0
    assert body["no_speech"] is False
    assert body["segments"]
    assert fake_engine.calls[-1]["language"] == "zh"


def test_transcribe_english(client_factory) -> None:
    engine = FakeASREngine(text="Hello, this is a test.", language="en")
    client = client_factory(engine=engine)
    response = _post(client, make_wav_bytes(1.0), "en")
    assert response.status_code == 200
    body = response.json()
    assert body["text"] == "Hello, this is a test."
    assert body["language"] == "en"
    assert engine.calls[-1]["language"] == "en"


def test_transcribe_auto_language(client_factory) -> None:
    engine = FakeASREngine(text="Hello.", language="en")
    client = client_factory(engine=engine)
    response = _post(client, make_wav_bytes(1.0), "auto")
    assert response.status_code == 200
    body = response.json()
    assert body["language"] == "en"
    assert body["requested_language"] == "auto"


def test_source_defaults_to_upload(client: TestClient) -> None:
    response = _post(client, make_wav_bytes(1.0), "zh", source=None)
    assert response.status_code == 200


def test_recording_source_is_accepted(client: TestClient) -> None:
    response = _post(client, make_wav_bytes(1.0), "zh", source="recording")
    assert response.status_code == 200


def test_silence_returns_no_speech(client: TestClient, fake_engine: FakeASREngine) -> None:
    response = _post(client, make_silence_wav_bytes(1.0), "zh")
    assert response.status_code == 200
    body = response.json()
    assert body["text"] == ""
    assert body["no_speech"] is True
    assert body["segments"] == []
    assert fake_engine.calls == []


def test_content_type_without_audio_prefix_still_decodes(client: TestClient) -> None:
    response = _post(
        client,
        make_wav_bytes(0.5),
        "zh",
        filename="sample.bin",
        content_type="application/octet-stream",
    )
    assert response.status_code == 200
