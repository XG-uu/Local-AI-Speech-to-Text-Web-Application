"""Domain errors and their HTTP mapping."""

from __future__ import annotations


class AppError(Exception):
    """An expected error that can be returned to the client as JSON."""

    status_code: int = 400
    code: str = "bad_request"

    def __init__(self, message: str, *, code: str | None = None, status_code: int | None = None):
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
        if status_code is not None:
            self.status_code = status_code


class EmptyFileError(AppError):
    status_code = 400
    code = "empty_file"


class FileTooLargeError(AppError):
    status_code = 413
    code = "file_too_large"


class UnsupportedAudioError(AppError):
    status_code = 400
    code = "unsupported_audio"


class AudioDecodeError(AppError):
    status_code = 400
    code = "decode_failed"


class InvalidLanguageError(AppError):
    status_code = 400
    code = "invalid_language"


class InvalidSourceError(AppError):
    status_code = 400
    code = "invalid_source"


class RecordingTooLongError(AppError):
    status_code = 400
    code = "recording_too_long"


class AudioTooLongError(AppError):
    status_code = 400
    code = "audio_too_long"


class ModelUnavailableError(AppError):
    status_code = 503
    code = "model_unavailable"


class InferenceFailedError(AppError):
    status_code = 500
    code = "inference_failed"


class InferenceTimeoutError(AppError):
    status_code = 504
    code = "inference_timeout"
