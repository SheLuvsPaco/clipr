"""
Video Cutter — Steps 1–2 of Phase 3.
Frame-accurate raw cutting, jump cut editing (silence/filler removal),
and word timestamp rebasing for Phase 4 caption sync.
"""

import os
import subprocess
import tempfile
import logging

logger = logging.getLogger(__name__)


# ─── Step 1: Frame-Accurate Raw Cut ──────────────────────────

def apply_trim_suggestions(candidate: dict) -> tuple:
    """
    Adjust candidate timestamps for Phase 2 trim suggestions.
    Safety: never trim more than 5 seconds from either end.

    Args:
        candidate: Clip candidate dict with start, end, and optional
                   suggested_trim_start, suggested_trim_end.

    Returns:
        (start, end) tuple with trims applied.
    """
    start = candidate['start'] + candidate.get('suggested_trim_start', 0)
    end   = candidate['end']   - candidate.get('suggested_trim_end',   0)

    # Safety cap — never trim more than 5 seconds from either end
    start = min(start, candidate['start'] + 5.0)
    end   = max(end,   candidate['end']   - 5.0)

    return start, end


def cut_raw_clip(
    video_path: str,
    start: float,
    end: float,
    output_path: str,
    pre_seek_buffer: float = 30.0,
) -> str:
    """
    Extract a clip from the source video using two-pass ffmpeg seeking
    for frame-accurate cutting.

    Pass 1: -ss before -i → fast keyframe seek to (start - 30s)
    Pass 2: -ss after  -i → precise frame-level seek within that window

    This gives frame-accurate results with only ~30s of decoding overhead
    regardless of where in a 2-hour file the clip lives.

    Args:
        video_path: Path to the full source video.
        start: Start timestamp in seconds.
        end: End timestamp in seconds.
        output_path: Where to write the cut clip.
        pre_seek_buffer: Seconds to seek before the clip for accuracy.

    Returns:
        output_path on success.
    """
    duration     = end - start
    fast_seek    = max(0, start - pre_seek_buffer)
    precise_seek = start - fast_seek

    cmd = [
        'ffmpeg',
        '-ss', str(fast_seek),          # fast keyframe seek
        '-i', video_path,
        '-ss', str(precise_seek),       # precise frame-level seek
        '-t', str(duration),
        '-c:v', 'libx264',
        '-c:a', 'aac',
        '-preset', 'fast',
        '-avoid_negative_ts', '1',
        output_path, '-y'
    ]

    logger.info(f"Raw cut: {start:.1f}s–{end:.1f}s ({duration:.1f}s) → {os.path.basename(output_path)}")
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        raise RuntimeError(f"Raw cut failed: {result.stderr[-500:]}")

    return output_path


# ─── Step 2a: Build Keep-Segments ─────────────────────────────

def build_keep_segments(
    words: list,
    clip_start: float,
    clip_end: float,
    max_pause_ms: int = 300,
    remove_fillers: bool = True,
    pad_ms: int = 50,
) -> list:
    """
    Given the word list from Phase 1 (global timestamps), return a list
    of (start, end) tuples in CLIP-LOCAL time representing the segments
    of audio/video to keep. Everything between segments gets cut.

    Thresholds:
        200ms — Aggressive. Cuts almost all breathing room. Very punchy.
        300ms — Natural. Cuts long pauses and fillers. Tight but human.
        500ms — Gentle. Only cuts very long dead air. Preserves rhythm.

    Args:
        words: Full word list from transcript (global timestamps).
        clip_start: Global start time of this clip.
        clip_end: Global end time of this clip.
        max_pause_ms: Max allowed gap between words (ms). Gaps beyond
                      this threshold get cut.
        remove_fillers: If True, drop words flagged is_filler.
        pad_ms: Milliseconds of audio to preserve before/after each
                kept word so cuts don't feel clinical. 50ms is
                imperceptible to the human ear.

    Returns:
        List of (start, end) tuples in clip-local time.
    """
    pad       = pad_ms / 1000
    max_pause = max_pause_ms / 1000

    # Filter to words inside this clip's window, drop fillers if requested
    clip_words = [
        w for w in words
        if clip_start <= w['start'] <= clip_end
        and not (remove_fillers and w.get('is_filler', False))
    ]

    if not clip_words:
        # No words found — return the whole clip uncut
        logger.warning("No words found in clip window — skipping jump cuts")
        return [(0.0, clip_end - clip_start)]

    # Rebase timestamps to clip-local time (clip_start becomes 0.0)
    local_words = [
        {**w,
         'start': round(w['start'] - clip_start, 3),
         'end':   round(w['end']   - clip_start, 3)}
        for w in clip_words
    ]

    segments  = []
    seg_start = max(0.0, local_words[0]['start'] - pad)
    seg_end   = local_words[0]['end'] + pad

    for i in range(1, len(local_words)):
        prev = local_words[i - 1]
        curr = local_words[i]
        gap  = curr['start'] - prev['end']

        if gap <= max_pause:
            # Small gap — stretch current segment to cover it
            seg_end = curr['end'] + pad
        else:
            # Gap exceeds threshold — close segment, open new one
            segments.append((round(seg_start, 3), round(seg_end, 3)))
            seg_start = max(0.0, curr['start'] - pad)
            seg_end   = curr['end'] + pad

    segments.append((round(seg_start, 3), round(seg_end, 3)))

    logger.info(
        f"Jump cut plan: {len(local_words)} words → {len(segments)} segments "
        f"(max_pause={max_pause_ms}ms, fillers={'removed' if remove_fillers else 'kept'})"
    )
    return segments


# ─── Step 2b: Cut and Stitch Segments ─────────────────────────

def cut_and_stitch(
    raw_clip_path: str,
    segments: list,
    output_path: str,
) -> dict:
    """
    Cut each keep-segment out of the raw clip and stitch them together
    using ffmpeg's concat demuxer. Returns a rebase_map so word
    timestamps can be adjusted to match the new (shorter) timeline.

    Args:
        raw_clip_path: Path to the raw (uncut) clip.
        segments: List of (start, end) tuples in clip-local time.
        output_path: Where to write the stitched result.

    Returns:
        Dict with output_path, rebase_map, new_duration, time_removed.
    """
    segment_files = []
    rebase_map    = []
    accumulated   = 0.0
    tmp_dir       = tempfile.mkdtemp(prefix='clipping_jc_')

    try:
        for i, (seg_start, seg_end) in enumerate(segments):
            seg_duration = seg_end - seg_start
            seg_path     = os.path.join(tmp_dir, f'seg_{i:04d}.mp4')

            cmd = [
                'ffmpeg',
                '-ss', str(seg_start),
                '-i', raw_clip_path,
                '-t', str(seg_duration),
                '-c:v', 'libx264',
                '-c:a', 'aac',
                '-preset', 'ultrafast',     # speed > quality — intermediate only
                '-avoid_negative_ts', '1',
                seg_path, '-y'
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                raise RuntimeError(
                    f"Segment cut failed at ({seg_start:.3f}, {seg_end:.3f}): "
                    f"{result.stderr[-300:]}"
                )

            segment_files.append(seg_path)

            # Record how this segment's original time maps to new timeline
            rebase_map.append({
                'original_start': round(seg_start, 3),
                'original_end':   round(seg_end, 3),
                'new_start':      round(accumulated, 3),
                'offset':         round(accumulated - seg_start, 3),
            })
            accumulated += seg_duration

        # Write ffmpeg concat list
        concat_list_path = os.path.join(tmp_dir, 'concat.txt')
        with open(concat_list_path, 'w') as f:
            for seg_path in segment_files:
                f.write(f"file '{seg_path}'\n")

        # Stitch — concat demuxer copies streams, no re-encode
        cmd = [
            'ffmpeg',
            '-f', 'concat',
            '-safe', '0',
            '-i', concat_list_path,
            '-c', 'copy',
            output_path, '-y'
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"Stitch failed: {result.stderr[-300:]}")

        original_span = segments[-1][1] - segments[0][0]
        time_removed  = original_span - accumulated

        logger.info(
            f"Jump cut done: {len(segments)} segments stitched → "
            f"{accumulated:.1f}s (removed {time_removed:.1f}s)"
        )

        return {
            'output_path':  output_path,
            'rebase_map':   rebase_map,
            'new_duration': round(accumulated, 3),
            'time_removed': round(time_removed, 3),
        }

    finally:
        # Cleanup temp files regardless of success/failure
        for seg_path in segment_files:
            if os.path.exists(seg_path):
                os.remove(seg_path)
        concat_path = os.path.join(tmp_dir, 'concat.txt')
        if os.path.exists(concat_path):
            os.remove(concat_path)
        if os.path.exists(tmp_dir):
            try:
                os.rmdir(tmp_dir)
            except OSError:
                pass  # dir not empty — non-critical


# ─── Step 2c: Rebase Word Timestamps ─────────────────────────

def rebase_word_timestamps(
    words: list,
    clip_start: float,
    clip_end: float,
    rebase_map: list,
    remove_fillers: bool = True,
) -> list:
    """
    Adjust word timestamps from global time into the new jump-cut timeline.
    Words that fall inside a removed gap are dropped.

    After jump cutting, a word at 45.3s in the raw clip might sit at 31.7s
    in the stitched clip because 13.6s of silence was removed before it.
    Phase 4 must use these rebased timestamps for caption sync.

    Args:
        words: Full word list from transcript (global timestamps).
        clip_start: Global start time of this clip.
        clip_end: Global end time of this clip.
        rebase_map: List of segment mappings from cut_and_stitch().
        remove_fillers: If True, drop filler words.

    Returns:
        List of word dicts with adjusted start/end times, ready for Phase 4.
    """
    # Filter to clip window and rebase to clip-local time
    clip_words = [
        {**w,
         'start': round(w['start'] - clip_start, 3),
         'end':   round(w['end']   - clip_start, 3)}
        for w in words
        if clip_start <= w['start'] <= clip_end
        and not (remove_fillers and w.get('is_filler', False))
    ]

    rebased = []
    for word in clip_words:
        for seg in rebase_map:
            if seg['original_start'] <= word['start'] <= seg['original_end']:
                rebased.append({
                    **word,
                    'start': round(word['start'] + seg['offset'], 3),
                    'end':   round(word['end']   + seg['offset'], 3),
                })
                break
        # Word not in any kept segment → it was inside a cut gap → skip

    logger.info(f"Rebased {len(rebased)} words (dropped {len(clip_words) - len(rebased)} in cut gaps)")
    return rebased
