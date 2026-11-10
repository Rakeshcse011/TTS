"""Optional authenticated FastAPI interface."""

from __future__ import annotations

import logging
import secrets
import threading
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from audiogen_ai.config import Settings, VOICES
from audiogen_ai.engine import SpeechEngine
from audiogen_ai.library import AudioLibrary
from audiogen_ai.validation import validate_adjustment, validate_voice

logger = logging.getLogger(__name__)

MAX_API_BODY_BYTES = 512 * 1024


class SynthesisRequest(BaseModel):
    text: str = Field(min_length=1, max_length=100_000)
    voice: str
    filename: str = "speech"
    output_format: Literal["mp3", "wav"] = "mp3"
    rate: int = Field(default=0, ge=-50, le=50)
    pitch: int = Field(default=0, ge=-50, le=50)
    volume: int = Field(default=100, ge=0, le=100)
    narration_style: Literal[
        "Classroom Teacher",
        "Friendly Teacher",
        "Professional Narrator",
        "Confident Presenter",
    ] = "Classroom Teacher"
    sentence_pause_ms: int = Field(default=350, ge=0, le=2000)
    paragraph_pause_ms: int = Field(default=700, ge=0, le=5000)
    normalize_audio: bool = False


class SlidingWindowLimiter:
    def __init__(
        self, max_requests: int = 30, period_seconds: int = 60, max_clients: int = 10_000
    ) -> None:
        self.max_requests = max_requests
        self.period_seconds = period_seconds
        self.max_clients = max_clients
        self._requests: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            requests = self._requests.get(key)
            if requests is None:
                if len(self._requests) >= self.max_clients:
                    expired = [
                        client
                        for client, events in self._requests.items()
                        if not events or now - events[-1] >= self.period_seconds
                    ]
                    for client in expired:
                        del self._requests[client]
                    if len(self._requests) >= self.max_clients:
                        return False
                requests = self._requests[key]
            while requests and now - requests[0] >= self.period_seconds:
                requests.popleft()
            if len(requests) >= self.max_requests:
                return False
            requests.append(now)
            return True


class RequestSizeLimitMiddleware:
    def __init__(self, app: ASGIApp, max_body_bytes: int) -> None:
        self.app = app
        self.max_body_bytes = max_body_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_error(status_code: int, payload: bytes) -> None:
            await send(
                {
                    "type": "http.response.start",
                    "status": status_code,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(payload)).encode("ascii")),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": payload})

        content_length = next(
            (value for name, value in scope["headers"] if name.lower() == b"content-length"),
            None,
        )
        if content_length is not None:
            try:
                declared_length = int(content_length)
            except ValueError:
                await send_error(400, b'{"detail":"Invalid Content-Length."}')
                return
            if declared_length < 0:
                await send_error(400, b'{"detail":"Invalid Content-Length."}')
                return
            if declared_length > self.max_body_bytes:
                await send_error(413, b'{"detail":"Request body is too large."}')
                return

        body = bytearray()
        message_count = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            message_count += 1
            chunk = message.get("body", b"")
            if len(body) + len(chunk) > self.max_body_bytes or message_count > 1024:
                await send_error(413, b'{"detail":"Request body is too large."}')
                return
            body.extend(chunk)
            if not message.get("more_body", False):
                break

        sent = False

        async def replay_body() -> Message:
            nonlocal sent
            if sent:
                return await receive()
            sent = True
            return {"type": "http.request", "body": bytes(body), "more_body": False}

        await self.app(scope, replay_body, send)


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        application.state.library = AudioLibrary(config.data_dir)
        application.state.engine = SpeechEngine(config)
        yield

    app = FastAPI(title="AUDIOGEN AI", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        RequestSizeLimitMiddleware, max_body_bytes=MAX_API_BODY_BYTES
    )
    app.state.settings = config
    app.state.rate_limiter = SlidingWindowLimiter()

    async def authorize(
        request: Request, x_api_key: str | None = Header(default=None)
    ) -> None:
        configured_key = request.app.state.settings.api_key
        if not configured_key:
            raise HTTPException(
                status_code=503, detail="API is disabled. Configure AUDIOGEN_API_KEY to enable it."
            )
        if not x_api_key or not secrets.compare_digest(x_api_key, configured_key):
            raise HTTPException(status_code=401, detail="Invalid or missing API key.")
        client = request.client.host if request.client else "unknown"
        if not request.app.state.rate_limiter.check(client):
            raise HTTPException(status_code=429, detail="Rate limit exceeded.")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "name": "AUDIOGEN AI"}

    @app.get("/v1/voices")
    async def voices(_: None = Depends(authorize)) -> list[dict[str, str]]:
        return [
            {
                "id": voice_id,
                "name": voice.name,
                "language": voice.language,
                "language_code": voice.language_code,
                "gender": voice.gender,
                "provider": voice.provider,
                "accent": voice.accent,
            }
            for voice_id, voice in VOICES.items()
        ]

    @app.post("/v1/synthesize", dependencies=[Depends(authorize)])
    async def synthesize(body: SynthesisRequest, request: Request) -> dict[str, object]:
        try:
            validate_voice(body.voice)
            for value, name in ((body.rate, "Speed"), (body.pitch, "Pitch")):
                validate_adjustment(value, name)
            result = await request.app.state.engine.synthesize(
                text=body.text,
                voice=body.voice,
                filename=body.filename,
                output_format=body.output_format,
                rate=body.rate,
                pitch=body.pitch,
                volume=body.volume,
                narration_style=body.narration_style,
                sentence_pause_ms=body.sentence_pause_ms,
                paragraph_pause_ms=body.paragraph_pause_ms,
                pronunciations=request.app.state.library.pronunciations(),
                normalize_audio=body.normalize_audio,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            logger.exception("API speech generation failed")
            raise HTTPException(status_code=502, detail="Speech generation failed.") from exc
        record = request.app.state.library.record(
            result.path.name, body.voice, result.output_format, result.size_bytes
        )
        return {
            "id": record.id,
            "filename": record.filename,
            "format": record.output_format,
            "size_bytes": record.size_bytes,
            "chunks": result.chunks,
            "prepared_text": result.prepared_text,
            "sample_rate": result.metadata.sample_rate,
            "duration_seconds": result.metadata.duration_seconds,
            "download_url": f"/v1/audio/{record.id}",
        }

    @app.get("/v1/audio/{audio_id}", dependencies=[Depends(authorize)])
    async def download(audio_id: str, request: Request) -> FileResponse:
        try:
            path = request.app.state.library.audio_path(audio_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return FileResponse(path, filename=path.name)

    return app


app = create_app()
