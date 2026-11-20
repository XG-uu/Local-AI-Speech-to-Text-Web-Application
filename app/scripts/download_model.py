"""Pre-download the local ASR model weights.

Usage:
    python -m app.scripts.download_model
"""

from __future__ import annotations

import sys
from pathlib import Path

from app.config import load_settings


def main() -> int:
    settings = load_settings()
    model_name = settings.model_name
    target = settings.model_dir / model_name
    target.mkdir(parents=True, exist_ok=True)

    print(f"Downloading faster-whisper model: {model_name}")
    print(f"Target directory: {target.resolve()}")
    print("This may take several minutes on the first run.")

    try:
        from faster_whisper.utils import download_model

        path = download_model(model_name, output_dir=str(target))
    except Exception as exc:  # noqa: BLE001
        print(f"Download failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        print(
            "Check your network connection, or download the model manually and place "
            "model.bin/config.json/tokenizer.json/vocabulary.txt in the target directory.",
            file=sys.stderr,
        )
        print(
            "If HF_ENDPOINT points to a failing mirror, try setting "
            "HF_ENDPOINT=https://huggingface.co and/or HTTPS_PROXY before retrying.",
            file=sys.stderr,
        )
        return 1

    print(f"Model ready: {Path(path).resolve()}")
    print("You can now start the server with: python -m uvicorn app.main:app --host 127.0.0.1 --port 8000")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
