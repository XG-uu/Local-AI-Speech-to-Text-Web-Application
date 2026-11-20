"""FastAPI application entry point."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import compat as compat_api
from app.api import health as health_api
from app.api import realtime as realtime_api
from app.api import transcribe as transcribe_api
from app.asr.base import ASREngine
from app.asr.whisper_engine import WhisperEngine
from app.config import Settings, load_settings
from app.errors import AppError

logger = logging.getLogger(__name__)


def create_app(
    engine: ASREngine | None = None,
    settings: Settings | None = None,
) -> FastAPI:
    """Application factory. Tests inject a FakeASREngine and custom settings."""

    settings = settings or load_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

    app = FastAPI(
        title="本地语音识别 Web 系统",
        description="Local Chinese/English speech-to-text with faster-whisper.",
        version="1.0.0",
        docs_url="/docs",
        redoc_url=None,
    )
    app.state.settings = settings
    app.state.engine = engine or WhisperEngine(settings)

    @app.exception_handler(AppError)
    async def _app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.message, "code": exc.code},
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error_handler(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        errors = exc.errors()
        if errors:
            first = errors[0]
            location = ".".join(str(item) for item in first.get("loc", ()) if item != "body")
            message = f"请求参数错误：{first.get('msg', '参数无效')}"
            if location:
                message += f"（字段：{location}）"
        else:
            message = "请求参数错误。"
        return JSONResponse(
            status_code=422,
            content={"detail": message, "code": "validation_error"},
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_exception_handler(
        _request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": str(exc.detail), "code": "http_error"},
        )

    @app.exception_handler(Exception)
    async def _unhandled_exception_handler(
        _request: Request, exc: Exception
    ) -> JSONResponse:
        logger.exception("Unhandled exception", exc_info=exc)
        return JSONResponse(
            status_code=500,
            content={"detail": "服务器内部错误，请稍后重试。", "code": "internal_error"},
        )

    app.include_router(compat_api.router)
    app.include_router(health_api.router)
    app.include_router(transcribe_api.router)
    app.include_router(realtime_api.router)
    app.mount("/static", StaticFiles(directory=str(settings.static_dir)), name="static")

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(settings.static_dir / "index.html")

    return app


app = create_app()
