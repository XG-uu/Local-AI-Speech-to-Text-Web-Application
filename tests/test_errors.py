from __future__ import annotations

from fastapi.testclient import TestClient

from app.asr.fake import FakeASREngine
from app.errors import ModelUnavailableError
from tests.conftest import make_wav_bytes


def _post(
    client: TestClient,
    data: bytes,
    language: str = "zh",
    *,
    source: str = "upload",
    filename: str = "sample.wav",
):
    return client.post(
        "/api/transcribe",
        files={"file": (filename, data, "audio/wav")},
        data={"language": language, "source": source},
    )


def _assert_error(response, status: int, code: str) -> None:
    assert response.status_code == status
    body = response.json()
    assert body["code"] == code
    assert body["detail"]


def test_invalid_language(client: TestClient) -> None:
    response = _post(client, make_wav_bytes(0.5), "fr")
    _assert_error(response, 400, "invalid_language")


def test_invalid_source(client: TestClient) -> None:
    response = _post(client, make_wav_bytes(0.5), "zh", source="microphone")
    _assert_error(response, 400, "invalid_source")


def test_missing_file(client: TestClient) -> None:
    response = client.post("/api/transcribe", data={"language": "zh"})
    _assert_error(response, 422, "validation_error")


def test_missing_language(client: TestClient) -> None:
    response = client.post(
        "/api/transcribe",
        files={"file": ("sample.wav", make_wav_bytes(0.5), "audio/wav")},
    )
    _assert_error(response, 422, "validation_error")


def test_empty_file(client: TestClient) -> None:
    response = _post(client, b"")
    _assert_error(response, 400, "empty_file")


def test_corrupt_file(client: TestClient) -> None:
    response = _post(client, b"not an audio file at all")
    assert response.status_code == 400
    body = response.json()
    assert body["code"] in {"unsupported_audio", "decode_failed"}
    assert body["detail"]


def test_file_too_large(client_factory) -> None:
    client = client_factory(max_upload_bytes=1024)
    response = _post(client, make_wav_bytes(1.0))
    _assert_error(response, 413, "file_too_large")


def test_recording_too_long(client_factory) -> None:
    client = client_factory(max_recording_seconds=0.5)
    response = _post(client, make_wav_bytes(2.0), "zh", source="recording")
    _assert_error(response, 400, "recording_too_long")


def test_upload_duration_unlimited_by_default(client_factory) -> None:
    client = client_factory(max_audio_seconds=0.0)
    response = _post(client, make_wav_bytes(2.0), "zh", source="upload")
    assert response.status_code == 200


def test_optional_upload_duration_limit(client_factory) -> None:
    client = client_factory(max_audio_seconds=0.5)
    response = _post(client, make_wav_bytes(2.0), "zh", source="upload")
    _assert_error(response, 400, "audio_too_long")


def test_model_unavailable(client_factory) -> None:
    engine = FakeASREngine(load_error=ModelUnavailableError("模型尚未下载。"))
    client = client_factory(engine=engine)
    response = _post(client, make_wav_bytes(0.5))
    _assert_error(response, 503, "model_unavailable")


def test_inference_failure(client_factory) -> None:
    engine = FakeASREngine(transcribe_error=RuntimeError("boom"))
    client = client_factory(engine=engine)
    response = _post(client, make_wav_bytes(0.5))
    _assert_error(response, 500, "inference_failed")


def test_unknown_route_returns_json_error(client: TestClient) -> None:
    response = client.get("/api/does-not-exist")
    assert response.status_code == 404
    assert response.json()["code"] == "http_error"
