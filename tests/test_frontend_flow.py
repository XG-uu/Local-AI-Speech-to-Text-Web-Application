from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import make_wav_bytes


def test_page_and_assets_form_a_complete_flow(client: TestClient) -> None:
    page = client.get("/")
    assert page.status_code == 200
    assert "开始录音" in page.text
    assert "上传并识别" in page.text
    assert "识别结果" in page.text

    payload = make_wav_bytes(seconds=1.0)
    response = client.post(
        "/api/transcribe",
        files={"file": ("recording.webm", payload, "audio/webm")},
        data={"language": "zh", "source": "recording"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["text"]
    assert body["duration_seconds"] == 1.0
    assert body["processing_seconds"] >= 0

    status = client.get("/api/status").json()
    assert status["max_upload_mb"] == 10
    assert status["max_recording_seconds"] == 60


def test_upload_flow_accepts_english(client_factory) -> None:
    from app.asr.fake import FakeASREngine

    engine = FakeASREngine(text="The quick brown fox.", language="en")
    client = client_factory(engine=engine)
    response = client.post(
        "/api/transcribe",
        files={"file": ("chinese.wav", make_wav_bytes(1.0), "audio/wav")},
        data={"language": "en", "source": "upload"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["text"] == "The quick brown fox."
    assert body["language"] == "en"
