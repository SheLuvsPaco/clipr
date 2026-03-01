"""
Transcriber — faster-whisper integration for speech-to-text.
Produces word-level timestamped transcripts with VAD filtering.
"""

import logging
import time
from typing import Optional, Callable

logger = logging.getLogger(__name__)


def transcribe_audio(
    audio_path: str,
    model_size: str = "large-v3",
    device: str = "cpu",
    language: str = "en",
    progress_callback: Optional[Callable[[float], None]] = None,
) -> dict:
    """
    Transcribe audio using faster-whisper with word-level timestamps.

    Args:
        audio_path: Path to the preprocessed WAV file.
        model_size: Whisper model to use (large-v3, medium, small, etc.)
        device: "cpu" or "cuda".
        language: Language code (default "en").
        progress_callback: Optional callback(progress: 0.0-1.0) for updates.

    Returns:
        dict with keys: language, duration, segments (list), words (flat list)
    """
    from faster_whisper import WhisperModel

    # Use fixed configuration as requested
    compute_type = "int8"

    logger.info(f"Loading Whisper model: {model_size} (device={device}, compute={compute_type})")
    start_time = time.time()

    model = WhisperModel(model_size, device=device, compute_type=compute_type)

    logger.info(f"Model loaded in {time.time() - start_time:.1f}s. Starting transcription...")
    transcribe_start = time.time()

    # Transcribe with all critical options from PHASE1.md
    segments_gen, info = model.transcribe(
        audio_path,
        language=language,
        word_timestamps=True,         # CRITICAL for caption sync
        vad_filter=True,              # Skip silence, prevent hallucinations
        vad_parameters={
            "min_silence_duration_ms": 500,   # 0.5s silence = chunk boundary
            "speech_pad_ms": 400,             # pad edges so words aren't cut
        },
        beam_size=5,                  # balances speed vs accuracy
        condition_on_previous_text=True,  # uses context for better accuracy
    )

    # Build structured output
    transcript = {
        "language": info.language,
        "language_probability": info.language_probability,
        "duration": info.duration,
        "segments": [],
        "words": [],  # flat word list for easy lookup
    }

    total_duration = info.duration if info.duration > 0 else 1
    segment_count = 0

    for segment in segments_gen:
        seg_data = {
            "id": segment.id,
            "start": round(segment.start, 3),
            "end": round(segment.end, 3),
            "text": segment.text.strip(),
            "words": [],
        }

        if segment.words:
            for word in segment.words:
                word_data = {
                    "word": word.word.strip(),
                    "start": round(word.start, 3),
                    "end": round(word.end, 3),
                    "probability": round(word.probability, 4),
                }
                seg_data["words"].append(word_data)
                transcript["words"].append({
                    **word_data,
                    "segment_id": segment.id,
                })

        transcript["segments"].append(seg_data)
        segment_count += 1

        # Report progress based on timestamp position relative to total duration
        if progress_callback and total_duration > 0:
            progress = min(segment.end / total_duration, 0.99)
            progress_callback(progress)

    processing_time = time.time() - transcribe_start
    transcript["processing_time_seconds"] = round(processing_time, 1)

    logger.info(
        f"Transcription complete: {segment_count} segments, "
        f"{len(transcript['words'])} words in {processing_time:.1f}s"
    )

    if progress_callback:
        progress_callback(1.0)

    return transcript
