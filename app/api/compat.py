"""Compatibility endpoints for local tooling probes.

OpenCode ships a built-in vLLM provider whose local discovery probes
``http://127.0.0.1:8000``: it checks ``/health`` first, then reads
``/v1/models``. This project is a speech-to-text service, not an LLM
provider, so the model list is intentionally empty. Returning a valid empty
OpenAI-style list keeps that probe from producing a misleading 404 while
still making it clear that no chat models are available here.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/v1/models", include_in_schema=False)
async def list_models() -> dict[str, object]:
    """Answer local vLLM/LM Studio style discovery with an empty model list."""

    return {"object": "list", "data": []}
