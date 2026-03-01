"""
Video Encoder — Steps 8–10 of Phase 3.
Colour grading, EBU R128 audio normalisation, and final platform encode
(H.264, 1080×1920, CRF 18, faststart).
"""

import os
import re
import json
import subprocess
import logging

logger = logging.getLogger(__name__)


# ─── Step 8: Colour Grade Presets ─────────────────────────────

GRADE_PRESETS = {
    'standard': {
        'eq':           'saturation=1.05:contrast=1.03:brightness=0.01:gamma=1.0',
        'colorbalance': 'rs=0.02:gs=0.01:bs=-0.03',      # subtle warm push
    },
    'vibrant': {
        'eq':           'saturation=1.15:contrast=1.05:brightness=0.02:gamma=0.95',
        'colorbalance': 'rs=0.03:gs=0.02:bs=-0.05',
    },
    'cinematic': {
        'eq':           'saturation=0.92:contrast=1.08:brightness=-0.01:gamma=1.05',
        'colorbalance': 'rs=-0.02:gs=0.0:bs=0.03',        # cool push
    },
    'none': None,    # skip grading entirely
}


def get_grade_preset(name: str) -> dict:
    """
    Get a colour grade preset by name.

    Args:
        name: Preset name (standard, vibrant, cinematic, none).

    Returns:
        Grade dict or None for 'none'.
    """
    if name not in GRADE_PRESETS:
        logger.warning(f"Unknown grade preset '{name}', using 'standard'")
        name = 'standard'
    return GRADE_PRESETS[name]


# ─── Step 9: Audio Normalisation ──────────────────────────────

def get_audio_loudness(video_path: str) -> dict:
    """
    Measure audio loudness using ffmpeg loudnorm (EBU R128).
    This is the first pass — it measures actual levels without modifying.

    The measured values are then fed into the second pass during
    final encode for precise, distortion-free normalisation.

    Target: -14 LUFS (the standard for Spotify, YouTube, broadcast TV).

    Args:
        video_path: Path to the video file to measure.

    Returns:
        Dict with measured loudness values (input_i, input_tp, etc.),
        or empty dict if measurement fails.
    """
    cmd = [
        'ffmpeg', '-i', video_path,
        '-af', 'loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json',
        '-f', 'null', '-'
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)

    # Parse the JSON loudness measurements from ffmpeg stderr
    # ffmpeg outputs the loudnorm stats as a JSON block in stderr
    match = re.search(r'\{[^}]+\}', result.stderr, re.DOTALL)

    if match:
        try:
            data = json.loads(match.group())
            logger.info(
                f"Audio loudness: I={data.get('input_i')} LUFS, "
                f"TP={data.get('input_tp')} dBTP"
            )
            return data
        except json.JSONDecodeError:
            logger.warning("Failed to parse loudness JSON")
            return {}

    logger.warning("No loudness data found in ffmpeg output")
    return {}


# ─── Step 10: Final Platform Encode ──────────────────────────

def encode_final(
    input_path: str,
    output_path: str,
    loudness_data: dict,
    grade_preset: str = 'standard',
    target_w: int = 1080,
    target_h: int = 1920,
) -> str:
    """
    Final encode combining everything: colour grade + audio normalisation.

    One encode spec satisfying TikTok, Instagram Reels, and YouTube Shorts:
      - H.264, High profile, Level 4.0
      - 1080×1920, 30fps, CRF 18
      - AAC 192k, 44100 Hz, stereo
      - Moov atom front-loaded (faststart)

    CRF 18 lets the encoder allocate more bits to complex scenes and fewer
    to static talking-head frames. For podcast content this typically produces
    4–7 Mbps, well within all platform limits.

    Args:
        input_path: Path to the cropped video.
        output_path: Where to write the final encoded video.
        loudness_data: Dict from get_audio_loudness() (pass 1 measurements).
        grade_preset: Colour grade name (standard, vibrant, cinematic, none).
        target_w: Output width.
        target_h: Output height.

    Returns:
        output_path on success.
    """
    grade    = get_grade_preset(grade_preset)
    vf_parts = [f'scale={target_w}:{target_h}']

    if grade:
        vf_parts.append(f"eq={grade['eq']}")
        vf_parts.append(f"colorbalance={grade['colorbalance']}")
    vf = ','.join(vf_parts)

    # Audio filter: two-pass loudnorm if measurements available,
    # otherwise single-pass (slightly less precise but still good)
    if loudness_data:
        af = (
            f"loudnorm=I=-14:TP=-1.5:LRA=11"
            f":measured_I={loudness_data.get('input_i', -14)}"
            f":measured_TP={loudness_data.get('input_tp', -1.5)}"
            f":measured_LRA={loudness_data.get('input_lra', 11)}"
            f":measured_thresh={loudness_data.get('input_thresh', -24)}"
            f":linear=true"
        )
    else:
        af = 'loudnorm=I=-14:TP=-1.5:LRA=11'

    cmd = [
        'ffmpeg', '-i', input_path,
        '-c:v', 'libx264',
        '-profile:v', 'high',
        '-level:v', '4.0',
        '-pix_fmt', 'yuv420p',
        '-crf', '18',
        '-preset', 'slow',
        '-r', '30',
        '-vf', vf,
        '-c:a', 'aac',
        '-b:a', '192k',
        '-ar', '44100',
        '-ac', '2',
        '-af', af,
        '-movflags', '+faststart',
        output_path, '-y'
    ]

    logger.info(f"Final encode: grade={grade_preset}, loudnorm={'2-pass' if loudness_data else '1-pass'}")
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        # Retry once with ultrafast preset
        logger.warning("Encode failed, retrying with ultrafast preset...")
        cmd[cmd.index('slow')] = 'ultrafast'
        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            raise RuntimeError(f"Encode failed: {result.stderr[-500:]}")

    logger.info(f"Final encode complete → {output_path}")
    return output_path
