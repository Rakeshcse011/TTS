from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from audiogen_ai.api import MAX_API_BODY_BYTES, SlidingWindowLimiter, create_app
from audiogen_ai.config import Settings


def test_health_endpoint_needs_no_api_key(tmp_path: Path) -> None:
    client = TestClient(create_app(Settings(data_dir=tmp_path)))
    assert client.get("/health").json()["status"] == "ok"


def test_api_is_disabled_without_secret(tmp_path: Path) -> None:
    client = TestClient(create_app(Settings(data_dir=tmp_path)))
    response = client.get("/v1/voices", headers={"X-API-Key": "anything"})
    assert response.status_code == 503


def test_authenticated_api_lists_voices(tmp_path: Path) -> None:
    app = create_app(Settings(data_dir=tmp_path, api_key="long-test-secret"))
    with TestClient(app) as client:
        response = client.get(
            "/v1/voices", headers={"X-API-Key": "long-test-secret"}
        )
    assert response.status_code == 200
    assert {voice["language_code"][:2] for voice in response.json()} == {"en", "hi"}


def test_api_rejects_bad_key_and_unknown_voice(tmp_path: Path) -> None:
    client = TestClient(create_app(Settings(data_dir=tmp_path, api_key="long-test-secret")))
    assert client.get("/v1/voices").status_code == 401
    response = client.post(
        "/v1/synthesize",
        headers={"X-API-Key": "long-test-secret"},
        json={"text": "hello", "voice": "not-a-voice"},
    )
    assert response.status_code == 422


def test_api_rejects_oversized_request_body(tmp_path: Path) -> None:
    client = TestClient(create_app(Settings(data_dir=tmp_path)))
    response = client.post(
        "/v1/synthesize",
        content=b"x" * (MAX_API_BODY_BYTES + 1),
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 413


def test_authenticated_synthesis_and_audio_download(tmp_path: Path) -> None:
    app = create_app(Settings(data_dir=tmp_path, api_key="long-test-secret"))

    class FakeEngine:
        async def synthesize(self, **kwargs):
            output_path = app.state.library.audio_dir / "generated.mp3"
            output_path.write_bytes(b"fake-mp3")
            return SimpleNamespace(
                path=output_path,
                output_format=kwargs["output_format"],
                size_bytes=8,
                chunks=1,
                prepared_text="Hello",
                metadata=SimpleNamespace(
                    sample_rate=None, duration_seconds=None
                ),
            )

    with TestClient(app) as client:
        app.state.engine = FakeEngine()
        headers = {"X-API-Key": "long-test-secret"}
        response = client.post(
            "/v1/synthesize",
            headers=headers,
            json={"text": "Hello", "voice": "en-US-AvaNeural"},
        )
        assert response.status_code == 200
        audio_id = response.json()["id"]
        download = client.get(f"/v1/audio/{audio_id}", headers=headers)
    assert download.status_code == 200
    assert download.content == b"fake-mp3"


def test_rate_limiter_blocks_excess_requests_and_resets(monkeypatch) -> None:
    import audiogen_ai.api as api_module

    now = [0.0]
    monkeypatch.setattr(api_module.time, "monotonic", lambda: now[0])
    limiter = SlidingWindowLimiter(max_requests=2, period_seconds=60)
    assert limiter.check("client")
    assert limiter.check("client")
    assert not limiter.check("client")
    now[0] = 61.0
    assert limiter.check("client")


def test_rate_limiter_bounds_client_state(monkeypatch) -> None:
    import audiogen_ai.api as api_module

    now = [0.0]
    monkeypatch.setattr(api_module.time, "monotonic", lambda: now[0])
    limiter = SlidingWindowLimiter(max_clients=1)
    assert limiter.check("first")
    assert not limiter.check("second")
    now[0] = 61.0
    assert limiter.check("second")
