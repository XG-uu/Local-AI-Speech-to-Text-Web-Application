"""HTTP transcription endpoint."""

from __future__ import annotations

import asyncio
import logging
import time

from fastapi import APIRouter, File, Form, Request, UploadFile

from app.asr.base import ASRResult
from app.audio import decode_audio, has_speech, read_upload_limited, validate_duration
from app.errors import (
    AppError,
    InferenceFailedError,
    InvalidLanguageError,
    InvalidSourceError,
)
from app.schemas import ASRSegmentModel, TranscribeResponse

logger = logging.getLogger(__name__)
router = APIRouter()

_ALLOWED_LANGUAGES = {"zh", "en", "auto"}
_ALLOWED_SOURCES = {"recording", "upload"}


def _normalize_language(value: str) -> str:
    language = (value or "").strip().lower()
    if language not in _ALLOWED_LANGUAGES:
        raise InvalidLanguageError("不支持的识别语言，请选择 zh（中文）或 en（英文）。")
    return language


@router.post("/api/transcribe", response_model=TranscribeResponse)
async def transcribe(
    request: Request,
    file: UploadFile = File(..., description="Audio file, max 10 MB"),
    language: str = Form(..., description="zh, en or auto"),
    source: str = Form("upload", description="recording or upload"),
) -> TranscribeResponse:
    settings = request.app.state.settings
    engine = request.app.state.engine

    language = _normalize_language(language)
    source = (source or "upload").strip().lower()
    if source not in _ALLOWED_SOURCES:
        raise InvalidSourceError("source 参数仅支持 recording 或 upload。")

    data = await read_upload_limited(file, settings.max_upload_bytes)

    decode_started = time.perf_counter()
    audio = await asyncio.to_thread(decode_audio, data)
    decode_elapsed = time.perf_counter() - decode_started
    validate_duration(audio, settings, source)

    if not has_speech(audio.samples):
        logger.info("Decoded audio contains no speech (duration=%.3fs)", audio.duration_seconds)
        return TranscribeResponse(
            text="",
            language=language if language != "auto" else "zh",
            duration_seconds=round(audio.duration_seconds, 3),
            processing_seconds=round(decode_elapsed, 3),
            model=str(engine.status().get("model", settings.model_name)),
            requested_language=language,
            no_speech=True,
            segments=[],
        )

    await asyncio.to_thread(engine.ensure_loaded)

    infer_started = time.perf_counter()
    try:
        result = await asyncio.to_thread(engine.transcribe, audio.samples, language)
    except AppError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("Unexpected ASR failure")
        raise InferenceFailedError("语音识别失败，请重试。") from exc
    infer_elapsed = time.perf_counter() - infer_started

    if not isinstance(result, ASRResult):
        raise InferenceFailedError("语音识别返回了无效结果。")

    actual_language = result.language if language == "auto" else language
    no_speech = not result.text.strip()
    processing_seconds = round(decode_elapsed + infer_elapsed, 3)
    logger.info(
        "Transcribed language=%s duration=%.3fs processing=%.3fs chars=%d",
        actual_language,
        audio.duration_seconds,
        processing_seconds,
        len(result.text),
    )

    return TranscribeResponse(
        text=result.text,
        language=actual_language,
        duration_seconds=round(audio.duration_seconds, 3),
        processing_seconds=processing_seconds,
        model=str(engine.status().get("model", settings.model_name)),
        requested_language=language,
        no_speech=no_speech,
        segments=[
            ASRSegmentModel(start=s.start, end=s.end, text=s.text)
            for s in result.segments
        ],
    )
