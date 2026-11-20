"""Health and runtime status endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Request

from app.schemas import StatusResponse

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    """Cheap liveness probe. Never loads the ASR model."""

    return {"status": "ok"}


@router.get("/api/status", response_model=StatusResponse)
async def status(request: Request) -> StatusResponse:
    engine = request.app.state.engine
    settings = request.app.state.settings
    info = engine.status()
    return StatusResponse(
        status="ok",
        model=str(info.get("model", settings.model_name)),
        device=str(info.get("device", settings.device)),
        compute_type=str(info.get("compute_type", settings.compute_type)),
        model_loaded=bool(info.get("model_loaded", False)),
        model_ready=bool(info.get("model_ready", False)),
        offline=bool(info.get("offline", settings.offline)),
        max_upload_mb=settings.max_upload_mb,
        max_recording_seconds=settings.max_recording_seconds,
        error=info.get("error"),
    )
