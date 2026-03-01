"""
Caption Renderer — Phase 4 orchestrator.
Generates ASS subtitle files and burns them into video using ffmpeg libass.
Handles face-aware positioning, filler filtering, and batch processing.
"""

import os
import json
import tempfile
import subprocess
import logging
from typing import Optional, Callable

logger = logging.getLogger(__name__)

# ─── Style Registry ──────────────────────────────────────────

from pipeline.caption_styles import (
    HormoziStyle,
    PodcastSubtitleStyle,
    KaraokeStyle,
    ReactionStyle,
    CinematicStyle,
)

STYLE_MAP = {
    'hormozi':          HormoziStyle(),
    'podcast_subtitle': PodcastSubtitleStyle(),
    'karaoke':          KaraokeStyle(),
    'reaction':         ReactionStyle(),
    'cinematic':        CinematicStyle(),
}


def get_available_caption_styles() -> list:
    """Return list of available caption style metadata."""
    return [
        {
            'id': 'hormozi',
            'label': 'Hormozi',
            'description': 'Bold, all-caps, word-by-word with orange highlight. Business/entrepreneurship.',
        },
        {
            'id': 'podcast_subtitle',
            'label': 'Podcast Subtitle',
            'description': 'Clean sentence-based captions with semi-transparent background box.',
        },
        {
            'id': 'karaoke',
            'label': 'Karaoke / Educational',
            'description': 'Word-by-word colour sweep. Follow-the-bouncing-ball reading experience.',
        },
        {
            'id': 'reaction',
            'label': 'Reaction / Casual',
            'description': 'Mid-screen, slightly rotated, energetic. Dating/entertainment content.',
        },
        {
            'id': 'cinematic',
            'label': 'Cinematic',
            'description': 'Lowercase, thin font, slow fades. Elegant and editorial.',
        },
    ]


# ─── Core Renderer ────────────────────────────────────────────

def render_captions(
    video_path: str,
    words: list,
    clip_duration: float,
    style_name: str,
    output_path: str,
    video_w: int = 1080,
    video_h: int = 1920,
) -> str:
    """
    Generate ASS subtitle file and burn it into the video using ffmpeg.

    Pipeline:
        1. Get style class from registry
        2. Generate ASS content
        3. Write to temp file
        4. ffmpeg burn with libass filter
        5. Cleanup temp file

    Args:
        video_path: Phase 3 output (clip_N_processed.mp4).
        words: Word timestamps scoped to this clip.
        clip_duration: Total clip length in seconds.
        style_name: Style key from STYLE_MAP.
        output_path: Where to write the captioned video.
        video_w: Video width (default 1080).
        video_h: Video height (default 1920).

    Returns:
        output_path on success.
    """
    style = STYLE_MAP.get(style_name)
    if not style:
        raise ValueError(
            f"Unknown caption style: {style_name}. "
            f"Choose from: {list(STYLE_MAP.keys())}"
        )

    # Generate ASS content
    ass_content = style.generate_ass(
        words=words,
        clip_duration=clip_duration,
        video_w=video_w,
        video_h=video_h,
    )

    # Write ASS to a temp file
    with tempfile.NamedTemporaryFile(
        mode='w', suffix='.ass', delete=False, encoding='utf-8'
    ) as f:
        f.write(ass_content)
        ass_path = f.name

    try:
        # Escape the path for ffmpeg filter (colons and backslashes)
        escaped_ass = ass_path.replace('\\', '/').replace(':', '\\:')

        cmd = [
            'ffmpeg',
            '-i', video_path,
            '-vf', f"ass='{escaped_ass}'",
            '-c:v', 'libx264',
            '-crf', '18',
            '-preset', 'fast',
            '-c:a', 'copy',                   # audio pass-through (already normalised)
            '-movflags', '+faststart',
            output_path,
            '-y',
        ]

        logger.info(f"Burning captions: style={style_name}, words={len(words)}")
        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            # Retry with subtitles filter as fallback
            logger.warning(
                f"ASS burn failed, retrying with subtitles filter: "
                f"{result.stderr[-200:]}"
            )
            cmd_fallback = [
                'ffmpeg',
                '-i', video_path,
                '-vf', f"subtitles='{escaped_ass}'",
                '-c:v', 'libx264',
                '-crf', '18',
                '-preset', 'fast',
                '-c:a', 'copy',
                '-movflags', '+faststart',
                output_path,
                '-y',
            ]
            result = subprocess.run(cmd_fallback, capture_output=True, text=True)
            if result.returncode != 0:
                raise RuntimeError(f"Caption burn failed: {result.stderr[-500:]}")

    finally:
        # Always clean up temp file
        if os.path.exists(ass_path):
            os.unlink(ass_path)

    logger.info(f"Captions burned → {output_path}")
    return output_path


# ─── Full Orchestration ──────────────────────────────────────

def run_phase_4(
    clip: dict,
    rebased_words: list,
    caption_style: str,
    output_dir: str,
    remove_fillers: bool = False,
    progress_callback: Optional[Callable] = None,
) -> dict:
    """
    Process a single clip through Phase 4 caption rendering.

    Args:
        clip: Phase 3 output dict (with processed_path, rank, etc.).
        rebased_words: Rebased word timestamps from Phase 3
                       (rebased_words_{id}.json content).
        caption_style: Style name from STYLE_MAP.
        output_dir: Directory for output files.
        remove_fillers: Whether to remove filler words from captions.
        progress_callback: Optional callback(clip_id, stage, progress).

    Returns:
        Updated clip dict with final_path, ass_path, caption metadata.
    """
    from pipeline.caption_utils import (
        filter_words_for_captions,
        compute_caption_position,
        get_position_y,
    )

    clip_id    = clip.get('rank', 1)
    video_path = clip['processed_path']
    os.makedirs(output_dir, exist_ok=True)

    def progress(stage: str, pct: float):
        if progress_callback:
            progress_callback(clip_id, stage, pct)

    logger.info(f"═══ Phase 4 — Clip #{clip_id} ═══")

    # ── Filter words for display ─────────────────────────────
    progress('filtering', 0.10)
    words = filter_words_for_captions(
        rebased_words,
        remove_fillers=remove_fillers,
    )

    if not words:
        logger.warning(f"Clip #{clip_id}: no words found — skipping captions")
        return {
            **clip,
            'final_path': video_path,  # return uncaptioned video
            'caption_style': caption_style,
            'word_count': 0,
            'warning': 'No words found, captions skipped',
        }

    # ── Compute face-aware position ──────────────────────────
    placement = compute_caption_position(clip.get('face_positions', []))
    logger.info(f"  Caption placement: {placement}")

    # ── Generate ASS + burn captions ─────────────────────────
    progress('rendering', 0.30)
    clip_duration = clip.get('effective_duration', clip.get('end', 0) - clip.get('start', 0))
    output_path   = os.path.join(output_dir, f'clip_{clip_id}_final.mp4')

    render_captions(
        video_path=video_path,
        words=words,
        clip_duration=clip_duration,
        style_name=caption_style,
        output_path=output_path,
    )

    # ── Save ASS file for manual editing ─────────────────────
    progress('saving', 0.90)
    ass_debug_path = os.path.join(output_dir, f'clip_{clip_id}.ass')
    style = STYLE_MAP[caption_style]
    ass_content = style.generate_ass(words, clip_duration)
    with open(ass_debug_path, 'w', encoding='utf-8') as f:
        f.write(ass_content)

    progress('done', 1.0)
    logger.info(f"═══ Clip #{clip_id} captioned ═══")

    return {
        **clip,
        'final_path':    output_path,
        'ass_path':      ass_debug_path,
        'caption_style': caption_style,
        'word_count':    len(words),
        'placement':     placement,
    }


# ─── Batch Processing ────────────────────────────────────────

def run_phase_4_batch(
    clips: list,
    caption_style: str,
    output_dir: str,
    remove_fillers: bool = False,
    progress_callback: Optional[Callable] = None,
) -> list:
    """
    Process all clips through Phase 4 caption rendering.

    Args:
        clips: List of Phase 3 output dicts. Each must have a
               'rebased_words_path' pointing to the JSON file.
        caption_style: Style name to use for all clips.
        output_dir: Directory for output files.
        remove_fillers: Whether to remove fillers from captions.
        progress_callback: Optional callback.

    Returns:
        List of clip dicts with final_path and caption metadata.
    """
    clips_dir = os.path.join(output_dir, 'clips')
    os.makedirs(clips_dir, exist_ok=True)

    results = []
    total   = len(clips)

    logger.info(f"Phase 4: Captioning {total} clips (style={caption_style})")

    for i, clip in enumerate(clips):
        logger.info(f"Clip {i + 1}/{total}")

        try:
            # Load rebased words from Phase 3
            rebased_path = clip.get('rebased_words_path', '')
            if rebased_path and os.path.exists(rebased_path):
                with open(rebased_path, 'r') as f:
                    rebased_words = json.load(f)
            else:
                logger.warning(
                    f"No rebased words file for clip #{clip.get('rank')} — "
                    f"skipping captions"
                )
                results.append({**clip, 'warning': 'Missing rebased_words file'})
                continue

            result = run_phase_4(
                clip=clip,
                rebased_words=rebased_words,
                caption_style=caption_style,
                output_dir=clips_dir,
                remove_fillers=remove_fillers,
                progress_callback=progress_callback,
            )
            results.append(result)

        except Exception as e:
            logger.error(f"Phase 4 failed for clip #{clip.get('rank')}: {e}")
            results.append({
                **clip,
                'error': str(e),
                'final_path': None,
            })

    # Save captioning log
    log_dir  = os.path.join(output_dir, 'metadata')
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, 'caption_log.json')
    with open(log_path, 'w') as f:
        # Strip face_positions (too large)
        log_data = [
            {k: v for k, v in r.items() if k != 'face_positions'}
            for r in results
        ]
        json.dump(log_data, f, indent=2, ensure_ascii=False)

    successful = sum(1 for r in results if r.get('final_path'))
    logger.info(f"Phase 4 complete: {successful}/{total} clips captioned")

    return results
