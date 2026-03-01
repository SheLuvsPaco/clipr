"""
Modal Transcriber — Wrapper for Modal cloud GPU transcription.

This module provides a local interface that calls the Modal GPU function
for Whisper transcription. It returns the same format as the local
transcriber for seamless integration.
"""

import logging
import os
import time
from typing import Optional, Callable

from config import USE_MODAL

logger = logging.getLogger(__name__)

# Lazy import of Modal — only imported when USE_MODAL is True
_transcribe_modal = None


def _get_modal_function():
    """Lazy import and cache the Modal transcribe function."""
    global _transcribe_modal
    if _transcribe_modal is None:
        try:
            from modal_transcribe import transcribe_audio
            _transcribe_modal = transcribe_audio
        except ImportError as e:
            logger.error(f"Failed to import Modal transcribe function: {e}")
            raise
    return _transcribe_modal


def transcribe_with_modal(
    audio_path: str,
    model_size: str = "large-v3-turbo",
    language: str = "en",
    progress_callback: Optional[Callable[[float], None]] = None,
) -> dict:
    """
    Transcribe audio using Modal cloud GPU.

    This function reads the audio file, sends it to Modal for GPU
    transcription, and returns the result in the same format as the
    local transcriber.

    Args:
        audio_path: Path to the preprocessed WAV file.
        model_size: Whisper model to use (large-v3-turbo, medium, small, etc.)
        language: Language code (default "en").
        progress_callback: Optional callback(progress: 0.0-1.0) for updates.

    Returns:
        dict with keys: language, language_probability, duration, segments, words
    """
    if progress_callback:
        progress_callback(0.0)

    logger.info(f"Using Modal GPU for transcription (model: {model_size})")

    # Read audio file as bytes
    with open(audio_path, "rb") as f:
        audio_bytes = f.read()

    size_mb = len(audio_bytes) / 1024 / 1024
    logger.info(f"Sending {size_mb:.1f} MB to Modal GPU...")

    if progress_callback:
        progress_callback(0.1)

    # Get Modal function and call it
    transcribe_fn = _get_modal_function()

    start_time = time.time()
    result = transcribe_fn.remote(
        audio_bytes,
        os.path.basename(audio_path),
        model_size=model_size,
        language=language,
    )
    elapsed = time.time() - start_time

    logger.info(
        f"Modal transcription complete in {elapsed:.1f}s: "
        f"{len(result.get('words', []))} words, "
        f"{result.get('duration', 0):.0f}s duration"
    )

    if progress_callback:
        progress_callback(1.0)

    return result


def transcribe_audio(
    audio_path: str,
    model_size: str = "large-v3-turbo",
    device: str = "auto",
    language: str = "en",
    progress_callback: Optional[Callable[[float], None]] = None,
) -> dict:
    """
    Transcribe audio using Modal GPU or local CPU based on USE_MODAL config.

    This is the main entry point for transcription. It routes to either
    the Modal GPU function or the local CPU transcriber based on the
    USE_MODAL configuration.

    Args:
        audio_path: Path to the preprocessed WAV file.
        model_size: Whisper model to use.
        device: Ignored for Modal, used for local fallback.
        language: Language code (default "en").
        progress_callback: Optional callback for progress updates.

    Returns:
        dict with keys: language, language_probability, duration, segments, words
    """
    if USE_MODAL:
        try:
            return transcribe_with_modal(
                audio_path=audio_path,
                model_size=model_size,
                language=language,
                progress_callback=progress_callback,
            )
        except Exception as e:
            logger.error(f"Modal transcription failed: {e}")
            logger.info("Falling back to local transcription...")
            # Fall through to local transcription

    # Local fallback
    from pipeline.transcriber import transcribe_audio as transcribe_local
    return transcribe_local(
        audio_path=audio_path,
        model_size=model_size,
        device=device,
        language=language,
        progress_callback=progress_callback,
    )
