from fastapi.testclient import TestClient


def test_health_returns_ok(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_status_reports_model_and_limits(client: TestClient) -> None:
    response = client.get("/api/status")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["model"]
    assert body["max_upload_mb"] == 10
    assert body["max_recording_seconds"] == 60
    assert "model_ready" in body


def test_vllm_discovery_sees_no_chat_models(client: TestClient) -> None:
    response = client.get("/v1/models")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {"object": "list", "data": []}


def test_index_serves_web_page(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "本地语音识别" in response.text
    assert "/static/js/app.js" in response.text


def test_static_assets_are_served(client: TestClient) -> None:
    script = client.get("/static/js/app.js")
    assert script.status_code == 200
    assert "startRecording" in script.text

    stylesheet = client.get("/static/css/app.css")
    assert stylesheet.status_code == 200
    assert ":root" in stylesheet.text

    worklet = client.get("/static/js/pcm-worklet.js")
    assert worklet.status_code == 200
    assert "registerProcessor" in worklet.text
