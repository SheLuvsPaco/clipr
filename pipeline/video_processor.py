"""
Video Processor — Full Phase 3 orchestrator.
Chains all 10 steps (raw cut → jump cut → layout → face track →
crop → smooth → zoom → grade → normalise → encode) with progress
reporting and edge case handling.
"""

import os
import json
import shutil
import logging
from typing import Optional, Callable

logger = logging.getLogger(__name__)


def process_clip(
    candidate: dict,
    video_path: str,
    transcript_words: list,
    output_dir: str,
    jump_cut_settings: dict,
    grade_preset: str = 'standard',
    progress_callback: Optional[Callable] = None,
) -> dict:
    """
    Process a single clip through the full Phase 3 pipeline.

    Steps:
        1. Frame-accurate raw cut (two-pass ffmpeg seek)
        2. Jump cut editing (silence/filler removal + timestamp rebase)
        3. Layout analysis (single/split/studio/no-face)
        4. Face tracking (2fps sample + interpolation)
        5. Smart vertical crop (9:16)
        6. Crop path smoothing (1.5s rolling average)
        7. Dynamic crop + zoom (OpenCV→ffmpeg pipe)
        8–10. Colour grade + Audio normalisation + Platform encode

    Args:
        candidate: Clip candidate dict from Phase 2 (with start, end, rank).
        video_path: Path to the full source video.
        transcript_words: Full word list from Phase 1 transcript.
        output_dir: Directory to write output files.
        jump_cut_settings: Dict with keys:
            enabled (bool), max_pause_ms (int), remove_fillers (bool)
        grade_preset: Colour grade name (standard, vibrant, cinematic, none).
        progress_callback: Optional callback(clip_id, stage, progress).

    Returns:
        Dict with processed clip metadata (paths, layout, durations, etc.).
    """
    from pipeline.video_cutter import (
        apply_trim_suggestions,
        cut_raw_clip,
        build_keep_segments,
        cut_and_stitch,
        rebase_word_timestamps,
    )
    from pipeline.video_analysis import (
        detect_layout,
        track_face_positions,
        get_video_dimensions,
        get_video_info,
    )
    from pipeline.video_crop import (
        compute_crop_path,
        smooth_crop_path,
        apply_dynamic_crop,
    )
    from pipeline.video_encoder import (
        get_audio_loudness,
        encode_final,
    )

    clip_id = candidate.get('rank', 1)
    os.makedirs(output_dir, exist_ok=True)

    def progress(stage: str, pct: float):
        if progress_callback:
            progress_callback(clip_id, stage, pct)

    logger.info(f"═══ Processing clip #{clip_id} ═══")

    # ── Step 1: Frame-accurate raw cut ───────────────────────────
    progress('cutting', 0.05)
    start, end = apply_trim_suggestions(candidate)
    raw_path   = os.path.join(output_dir, f'raw_{clip_id}.mp4')
    cut_raw_clip(video_path, start, end, raw_path)
    logger.info(f"  Step 1 done: raw cut {start:.1f}s–{end:.1f}s ({end-start:.1f}s)")

    # ── Step 2: Jump cut editing ─────────────────────────────────
    progress('jump_cutting', 0.15)
    jc_path       = os.path.join(output_dir, f'jc_{clip_id}.mp4')
    rebased_words = transcript_words  # default: no change

    if jump_cut_settings.get('enabled', True):
        segments = build_keep_segments(
            words          = transcript_words,
            clip_start     = start,
            clip_end       = end,
            max_pause_ms   = jump_cut_settings.get('max_pause_ms', 300),
            remove_fillers = jump_cut_settings.get('remove_fillers', True),
            pad_ms         = 50,
        )

        stitch_result = cut_and_stitch(raw_path, segments, jc_path)

        rebased_words = rebase_word_timestamps(
            words          = transcript_words,
            clip_start     = start,
            clip_end       = end,
            rebase_map     = stitch_result['rebase_map'],
            remove_fillers = jump_cut_settings.get('remove_fillers', True),
        )

        effective_duration = stitch_result['new_duration']
        time_removed       = stitch_result['time_removed']

        # Edge case: if JC removes >60% of clip, warn
        if time_removed > (end - start) * 0.6:
            logger.warning(
                f"Jump cuts removed {time_removed:.1f}s "
                f"({time_removed/(end-start)*100:.0f}%) — clip may have sparse speech"
            )

        # Edge case: if resulting clip <10s, disable JC and retry
        if effective_duration < 10.0:
            logger.warning(
                f"Clip too short after JC ({effective_duration:.1f}s) — "
                f"disabling jump cuts for this clip"
            )
            shutil.copy(raw_path, jc_path)
            effective_duration = end - start
            time_removed       = 0.0
            # Re-rebase without filler removal
            rebased_words = rebase_word_timestamps(
                words=transcript_words, clip_start=start, clip_end=end,
                rebase_map=[{
                    'original_start': 0.0,
                    'original_end': end - start,
                    'new_start': 0.0,
                    'offset': 0.0,
                }],
                remove_fillers=False,
            )

        logger.info(
            f"  Step 2 done: {effective_duration:.1f}s "
            f"(removed {time_removed:.1f}s by JC)"
        )
    else:
        shutil.copy(raw_path, jc_path)
        effective_duration = end - start
        time_removed       = 0.0
        logger.info("  Step 2 skipped: jump cuts disabled")

    # Save rebased word timestamps for Phase 4
    rebased_words_path = os.path.join(output_dir, f'rebased_words_{clip_id}.json')
    with open(rebased_words_path, 'w') as f:
        json.dump(rebased_words, f, indent=2, ensure_ascii=False)

    # ── Step 3: Layout analysis ──────────────────────────────────
    progress('analysing', 0.25)
    video_info = get_video_info(jc_path)

    # Edge case: source already vertical (9:16) — skip crop
    if video_info['is_vertical']:
        logger.info("  Source is already vertical — skipping crop, going straight to encode")
        progress('encoding', 0.85)
        loudness   = get_audio_loudness(jc_path)
        final_path = os.path.join(output_dir, f'clip_{clip_id}_processed.mp4')
        encode_final(jc_path, final_path, loudness, grade_preset)

        # Cleanup intermediates
        _cleanup_intermediates(raw_path, jc_path)
        progress('done', 1.0)

        return {
            **candidate,
            'processed_path':     final_path,
            'rebased_words_path': rebased_words_path,
            'layout':             'vertical_source',
            'original_duration':  end - start,
            'effective_duration': effective_duration,
            'time_removed_by_jc': time_removed,
        }

    layout = detect_layout(jc_path)
    logger.info(f"  Step 3 done: layout={layout['type']}")

    # ── Step 4: Face tracking ────────────────────────────────────
    progress('tracking', 0.38)
    face_positions = track_face_positions(jc_path)
    logger.info(f"  Step 4 done: {len(face_positions)} frame positions")

    # ── Steps 5–6: Crop path + smoothing ─────────────────────────
    source_w, source_h = video_info['width'], video_info['height']
    crop_path          = compute_crop_path(face_positions, source_w, source_h)
    fps                = video_info['fps'] or 30.0
    crop_path          = smooth_crop_path(crop_path, fps=fps)
    logger.info(f"  Steps 5–6 done: crop path computed and smoothed")

    # ── Step 7: Dynamic crop + zoom ──────────────────────────────
    progress('cropping', 0.50)
    cropped_path = os.path.join(output_dir, f'cropped_{clip_id}.mp4')

    # Don't apply zoom to split-screen layouts
    should_zoom = layout['strategy'] not in ('dynamic_speaker_crop',)
    apply_dynamic_crop(
        jc_path, crop_path, cropped_path,
        apply_zoom_effect=should_zoom,
    )
    logger.info(f"  Step 7 done: dynamic crop {'+ zoom' if should_zoom else '(no zoom)'}")

    # ── Step 9: Audio normalisation measurement ──────────────────
    progress('normalising', 0.78)
    loudness = get_audio_loudness(cropped_path)
    logger.info(f"  Step 9 done: loudness measured")

    # ── Step 10: Final platform encode ───────────────────────────
    progress('encoding', 0.88)
    final_path = os.path.join(output_dir, f'clip_{clip_id}_processed.mp4')
    encode_final(cropped_path, final_path, loudness, grade_preset)
    logger.info(f"  Step 10 done: final encode → {final_path}")

    # ── Cleanup intermediates ────────────────────────────────────
    _cleanup_intermediates(raw_path, jc_path, cropped_path)

    progress('done', 1.0)
    logger.info(f"═══ Clip #{clip_id} complete ═══")

    return {
        **candidate,
        'processed_path':     final_path,
        'rebased_words_path': rebased_words_path,
        'layout':             layout['type'],
        'original_duration':  round(end - start, 1),
        'effective_duration': round(effective_duration, 1),
        'time_removed_by_jc': round(time_removed, 1),
    }


def _cleanup_intermediates(*paths):
    """Remove intermediate files, ignoring errors."""
    for path in paths:
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass


# ─── Batch Processing ─────────────────────────────────────────

def process_all_clips(
    candidates: list,
    video_path: str,
    transcript_words: list,
    output_dir: str,
    jump_cut_settings: dict,
    grade_preset: str = 'standard',
    progress_callback: Optional[Callable] = None,
) -> list:
    """
    Process all approved clip candidates through Phase 3.

    Args:
        candidates: List of clip candidate dicts from Phase 2.
        video_path: Path to the full source video.
        transcript_words: Full word list from Phase 1 transcript.
        output_dir: Directory for output files.
        jump_cut_settings: Jump cut configuration.
        grade_preset: Colour grade name.
        progress_callback: Optional callback(clip_id, stage, progress).

    Returns:
        List of processed clip metadata dicts.
    """
    # Check disk space before starting
    _check_disk_space(output_dir)

    clips_dir = os.path.join(output_dir, 'clips')
    os.makedirs(clips_dir, exist_ok=True)

    results = []
    total = len(candidates)

    logger.info(f"Processing {total} clips...")

    for i, candidate in enumerate(candidates):
        logger.info(f"Clip {i+1}/{total}: rank={candidate.get('rank')}")
        try:
            result = process_clip(
                candidate=candidate,
                video_path=video_path,
                transcript_words=transcript_words,
                output_dir=clips_dir,
                jump_cut_settings=jump_cut_settings,
                grade_preset=grade_preset,
                progress_callback=progress_callback,
            )
            results.append(result)
        except Exception as e:
            logger.error(f"Failed to process clip #{candidate.get('rank')}: {e}")
            results.append({
                **candidate,
                'error': str(e),
                'processed_path': None,
            })

    # Save processing log
    log_dir = os.path.join(output_dir, 'metadata')
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, 'processing_log.json')
    with open(log_path, 'w') as f:
        # Remove face_positions from log (too large)
        log_data = []
        for r in results:
            entry = {k: v for k, v in r.items() if k != 'face_positions'}
            log_data.append(entry)
        json.dump(log_data, f, indent=2, ensure_ascii=False)

    successful = sum(1 for r in results if r.get('processed_path'))
    logger.info(
        f"Phase 3 complete: {successful}/{total} clips processed successfully"
    )

    return results


def _check_disk_space(path: str, min_gb: float = 5.0):
    """Warn if available disk space is below threshold."""
    try:
        stat = shutil.disk_usage(path if os.path.exists(path) else os.path.dirname(path))
        free_gb = stat.free / (1024 ** 3)
        if free_gb < min_gb:
            logger.warning(
                f"Low disk space: {free_gb:.1f} GB free "
                f"(recommended: >{min_gb:.0f} GB)"
            )
    except Exception:
        pass  # Non-critical
