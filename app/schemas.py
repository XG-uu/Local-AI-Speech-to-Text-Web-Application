"""Pydantic response models."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ASRSegmentModel(BaseModel):
    start: float
    end: float
    text: str


class TranscribeResponse(BaseModel):
    text: str
    language: str
    duration_seconds: float
    processing_seconds: float
    model: str
    requested_language: str | None = None
    no_speech: bool = False
    segments: list[ASRSegmentModel] = Field(default_factory=list)


class StatusResponse(BaseModel):
    status: str
    model: str
    device: str
    compute_type: str
    model_loaded: bool
    model_ready: bool
    offline: bool
    max_upload_mb: int
    max_recording_seconds: float
    error: str | None = None
