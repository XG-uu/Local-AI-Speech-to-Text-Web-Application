"""WebSocket endpoint for near-realtime transcription."""

from __future__ import annotations

import asyncio
import json
import logging
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.errors import AppError, InvalidLanguageError
from app.realtime import RealtimeConfig, RealtimeSession

logger = logging.getLogger(__name__)
router = APIRouter()

_ALLOWED_LANGUAGES = {"zh", "en", "auto"}


def _normalize_language(value: str | None) -> str:
    language = (value or "").strip().lower()
    if language not in _ALLOWED_LANGUAGES:
        raise InvalidLanguageError("不支持的识别语言，请选择 zh（中文）或 en（英文）。")
    return language


async def _send_error(websocket: WebSocket, exc: AppError) -> None:
    await websocket.send_json(
        {"type": "error", "code": exc.code, "message": exc.message}
    )


@router.websocket("/ws/transcribe")
async def realtime_transcribe(websocket: WebSocket) -> None:
    await websocket.accept()
    settings = websocket.app.state.settings
    engine = websocket.app.state.engine

    language = "zh"
    session: RealtimeSession | None = None
    started = False

    try:
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                return

            text = message.get("text")
            if text is not None:
                try:
                    payload = json.loads(text)
                except json.JSONDecodeError:
                    await websocket.send_json(
                        {"type": "error", "code": "invalid_message", "message": "无法解析控制消息。"}
                    )
                    continue

                msg_type = str(payload.get("type", "")).lower()
                if msg_type == "start":
                    language = _normalize_language(
                        payload.get("language") or websocket.query_params.get("language")
                    )
                    session = RealtimeSession(
                        engine,
                        language,
                        RealtimeConfig(
                            sample_rate=16_000,
                            max_seconds=settings.max_recording_seconds,
                            chunk_seconds=settings.realtime_chunk_seconds,
                            overlap_seconds=settings.realtime_overlap_seconds,
                        ),
                    )
                    started = True
                    await websocket.send_json(
                        {"type": "ready", "sample_rate": 16_000, "language": language}
                    )
                elif msg_type == "stop":
                    if session is None:
                        session = RealtimeSession(
                            engine,
                            language,
                            RealtimeConfig(
                                sample_rate=16_000,
                                max_seconds=settings.max_recording_seconds,
                                chunk_seconds=settings.realtime_chunk_seconds,
                                overlap_seconds=settings.realtime_overlap_seconds,
                            ),
                        )
                    final_started = time.perf_counter()
                    result = await asyncio.to_thread(session.finalize)
                    elapsed = time.perf_counter() - final_started
                    await websocket.send_json(
                        {
                            "type": "final",
                            "text": result.text,
                            "language": result.language,
                            "requested_language": language,
                            "duration_seconds": round(session.duration_seconds, 3),
                            "processing_seconds": round(elapsed, 3),
                            "no_speech": not result.text.strip(),
                        }
                    )
                    return
                else:
                    await websocket.send_json(
                        {
                            "type": "error",
                            "code": "invalid_message",
                            "message": "未知控制消息，type 仅支持 start 或 stop。",
                        }
                    )
                continue

            data = message.get("bytes")
            if data is None:
                continue
            if not started or session is None:
                await websocket.send_json(
                    {"type": "error", "code": "not_started", "message": "请先发送 start 消息。"}
                )
                continue

            session.add_pcm(data)
            if session.should_process():
                partial_text = await asyncio.to_thread(session.process_partial)
                await websocket.send_json(
                    {
                        "type": "partial",
                        "text": partial_text,
                        "duration_seconds": round(session.duration_seconds, 3),
                    }
                )
    except WebSocketDisconnect:
        logger.info("Realtime websocket disconnected")
    except AppError as exc:
        logger.warning("Realtime session error: %s", exc.message)
        try:
            await _send_error(websocket, exc)
        except Exception:  # noqa: BLE001
            pass
    except Exception:  # noqa: BLE001
        logger.exception("Unexpected realtime failure")
        try:
            await websocket.send_json(
                {"type": "error", "code": "inference_failed", "message": "实时识别失败，请重试。"}
            )
        except Exception:  # noqa: BLE001
            pass
    finally:
        try:
            await websocket.close()
        except Exception:  # noqa: BLE001
            pass
