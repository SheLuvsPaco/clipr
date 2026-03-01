"""
Audio Processing — Extract, normalize, and clean audio for transcription.
Uses ffmpeg for extraction/normalization and noisereduce for optional cleanup.
"""

import os
import subprocess
import logging
from typing import Optional

import numpy as np
import soundfile as sf

logger = logging.getLogger(__name__)


def extract_audio(video_path: str, output_dir: str) -> str:
    """
    Extract audio from a video file using ffmpeg.
    Outputs 16kHz mono WAV (Whisper's native format).

    Args:
        video_path: Path to the input video/audio file.
        output_dir: Directory to save the extracted audio.

    Returns:
        Path to the extracted WAV file.
    """
    os.makedirs(output_dir, exist_ok=True)
    audio_path = os.path.join(output_dir, "audio.wav")

    cmd = [
        "ffmpeg",
        "-i", video_path,
        "-vn",                    # No video
        "-acodec", "pcm_s16le",   # Uncompressed PCM (what Whisper prefers)
        "-ar", "16000",           # 16kHz sample rate (Whisper's native rate)
        "-ac", "1",               # Mono (stereo gives no benefit for speech)
        audio_path,
        "-y",                     # Overwrite if exists
    ]

    logger.info(f"Extracting audio from: {video_path}")
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg audio extraction failed: {result.stderr}")

    file_size_mb = os.path.getsize(audio_path) / (1024 * 1024)
    logger.info(f"Audio extracted: {audio_path} ({file_size_mb:.1f} MB)")
    return audio_path


def normalize_audio(audio_path: str, output_dir: str) -> str:
    """
    Apply EBU R128 loudness normalization using ffmpeg loudnorm filter.
    Equalizes volume so quiet segments transcribe as accurately as loud ones.

    Args:
        audio_path: Path to the input WAV file.
        output_dir: Directory to save the normalized audio.

    Returns:
        Path to the normalized WAV file.
    """
    os.makedirs(output_dir, exist_ok=True)
    normalized_path = os.path.join(output_dir, "audio_normalized.wav")

    cmd = [
        "ffmpeg",
        "-i", audio_path,
        "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
        "-ar", "16000",
        "-ac", "1",
        normalized_path,
        "-y",
    ]

    logger.info("Normalizing audio volume (EBU R128)...")
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg normalization failed: {result.stderr}")

    logger.info(f"Audio normalized: {normalized_path}")
    return normalized_path


def reduce_noise(audio_path: str) -> str:
    """
    Apply noise reduction using noisereduce library.
    Uses the first 0.5 seconds as a noise profile (usually silence/room tone).

    This is OPTIONAL — toggle in settings. For clean studio podcasts it's not needed.
    For phone call recordings or noisy environments, it makes a big difference.

    Args:
        audio_path: Path to the input WAV file.

    Returns:
        Path to the cleaned audio file.
    """
    import noisereduce as nr

    logger.info("Applying noise reduction...")

    data, rate = sf.read(audio_path)

    # Use first 0.5 seconds as noise profile
    noise_sample = data[:rate // 2]
    reduced = nr.reduce_noise(y=data, sr=rate, y_noise=noise_sample)

    output_path = audio_path.replace(".wav", "_clean.wav")
    sf.write(output_path, reduced, rate)

    logger.info(f"Noise reduction complete: {output_path}")
    return output_path


def is_audio_only(file_path: str) -> bool:
    """
    Check if a file is audio-only (no video stream).

    Args:
        file_path: Path to the input file.

    Returns:
        True if the file has no video stream.
    """
    cmd = [
        "ffprobe",
        "-v", "quiet",
        "-select_streams", "v",
        "-show_entries", "stream=codec_type",
        "-of", "csv=p=0",
        file_path,
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    # If no video stream is found, output will be empty
    return result.stdout.strip() == ""


def get_audio_duration(audio_path: str) -> float:
    """
    Get the duration of an audio file in seconds.

    Args:
        audio_path: Path to the audio file.

    Returns:
        Duration in seconds.
    """
    cmd = [
        "ffprobe",
        "-v", "quiet",
        "-show_entries", "format=duration",
        "-of", "csv=p=0",
        audio_path,
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {result.stderr}")

    return float(result.stdout.strip())
