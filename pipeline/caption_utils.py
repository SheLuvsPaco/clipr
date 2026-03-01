"""
Caption Utilities — Phase 4 shared helpers.
ASS colour/time conversion, word grouping, clip word extraction,
filler filtering, and face-aware caption positioning.
"""

import logging

logger = logging.getLogger(__name__)


# ─── ASS Format Helpers ──────────────────────────────────────

def rgb_to_ass_colour(r: int, g: int, b: int, alpha: int = 0) -> str:
    """
    Convert RGB colour to ASS BGR hex format.

    ASS uses &HAABBGGRR where AA=00 is fully opaque and AA=FF
    is fully transparent. This is the OPPOSITE of standard RGBA —
    a common source of bugs.

    Args:
        r: Red channel (0–255).
        g: Green channel (0–255).
        b: Blue channel (0–255).
        alpha: Transparency (0=opaque, 255=transparent).

    Returns:
        ASS colour string like '&H00FFFFFF' (opaque white).
    """
    return f"&H{alpha:02X}{b:02X}{g:02X}{r:02X}"


def seconds_to_ass_time(seconds: float) -> str:
    """
    Convert seconds to ASS time format: H:MM:SS.cc
    (where cc = centiseconds, ie hundredths of a second).

    Args:
        seconds: Time in seconds (can be fractional).

    Returns:
        ASS time string like '0:01:23.45'.
    """
    if seconds < 0:
        seconds = 0.0
    h  = int(seconds // 3600)
    m  = int((seconds % 3600) // 60)
    s  = int(seconds % 60)
    cs = round((seconds % 1) * 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


# ─── Word Grouping ────────────────────────────────────────────

def group_words_into_lines(
    words: list,
    max_chars: int = 30,
    max_gap_seconds: float = 0.6,
    max_words: int = None,
) -> list:
    """
    Group words into display lines for caption rendering.
    Shared by Podcast, Reaction, and other sentence-based styles.

    Line breaks triggered by:
        - Exceeding max_chars
        - Gap between words > max_gap_seconds
        - Exceeding max_words (if set)

    Args:
        words: List of word dicts with 'word', 'start', 'end'.
        max_chars: Max characters per line before breaking.
        max_gap_seconds: Max pause gap before forcing a new line.
        max_words: Max words per line (None = unlimited).

    Returns:
        List of word-groups, each group is a list of word dicts.
    """
    if not words:
        return []

    groups       = []
    current      = []
    current_chars = 0

    for i, word in enumerate(words):
        word_len = len(word['word']) + 1  # +1 for space

        # Measure gap from previous word
        gap = 0
        if current and i > 0:
            gap = word['start'] - words[i - 1]['end']

        # Break condition
        should_break = (
            (current_chars + word_len > max_chars and current) or
            (gap > max_gap_seconds and current) or
            (max_words and len(current) >= max_words and current)
        )

        if should_break:
            groups.append(current)
            current = []
            current_chars = 0

        current.append(word)
        current_chars += word_len

    if current:
        groups.append(current)

    return groups


# ─── Word Extraction & Filtering ─────────────────────────────

def extract_clip_words(
    transcript: dict,
    clip_start: float,
    clip_end: float,
) -> list:
    """
    Extract words that fall within a clip's time window and rebase
    timestamps to clip-local time (clip_start becomes 0.0).

    Args:
        transcript: Master transcript dict from Phase 1 (with 'words' list).
        clip_start: Global start time of the clip.
        clip_end: Global end time of the clip.

    Returns:
        List of word dicts with clip-local timestamps.
    """
    words = []
    for word in transcript.get('words', []):
        if clip_start <= word['start'] <= clip_end:
            words.append({
                'word':        word['word'].strip(),
                'start':       round(word['start'] - clip_start, 3),
                'end':         round(word['end'] - clip_start, 3),
                'probability': word.get('probability', 1.0),
                'is_filler':   word.get('is_filler', False),
            })
    return words


def filter_words_for_captions(
    words: list,
    remove_fillers: bool = False,
    min_confidence: float = 0.6,
) -> list:
    """
    Filter words for caption display.

    By default fillers are KEPT because they're part of natural speech
    rhythm. Removing them makes captions feel out of sync with audio.
    When fillers are removed, timing of surrounding words is preserved —
    we just skip the word visually.

    Args:
        words: List of word dicts.
        remove_fillers: If True, skip filler words.
        min_confidence: Skip words below this confidence threshold.

    Returns:
        Filtered word list.
    """
    filtered = []
    for word in words:
        # Skip very low confidence words (likely misheard)
        if word.get('probability', 1.0) < min_confidence:
            continue

        # Optionally skip fillers
        if remove_fillers and word.get('is_filler', False):
            continue

        filtered.append(word)

    return filtered


# ─── Face-Aware Positioning ───────────────────────────────────

def compute_caption_position(
    face_positions: list,
    bottom_zone_threshold: float = 0.60,
) -> str:
    """
    Determine whether captions should go at top or bottom of frame,
    based on where the speaker's face is.

    Rule:
        - Face in bottom 40% of frame (cy > 0.60) → captions at top
        - Otherwise → captions at bottom (default)

    Args:
        face_positions: List of (cx, cy, size) tuples from Phase 3.
        bottom_zone_threshold: cy threshold above which face is in lower zone.

    Returns:
        'top' or 'bottom'.
    """
    if not face_positions:
        return 'bottom'

    # Sample 10 evenly distributed positions
    step   = max(1, len(face_positions) // 10)
    sample = face_positions[::step]
    avg_cy = sum(pos[1] for pos in sample) / len(sample)

    if avg_cy > bottom_zone_threshold:
        return 'top'
    return 'bottom'


def get_position_y(placement: str, style_name: str, video_h: int = 1920) -> int:
    """
    Get the Y pixel coordinate for caption placement, per style.

    Each style has its own top/bottom positions because font size and
    visual weight differ.

    Args:
        placement: 'top' or 'bottom'.
        style_name: Caption style name.
        video_h: Video height in pixels.

    Returns:
        Y coordinate in pixels.
    """
    POSITIONS = {
        ('hormozi',          'bottom'): 1550,
        ('hormozi',          'top'):    370,
        ('podcast_subtitle', 'bottom'): 1780,
        ('podcast_subtitle', 'top'):    140,
        ('karaoke',          'bottom'): 1720,
        ('karaoke',          'top'):    200,
        ('reaction',         'bottom'): 1200,
        ('reaction',         'top'):    720,
        ('cinematic',        'bottom'): 1800,
        ('cinematic',        'top'):    120,
    }
    return POSITIONS.get((style_name, placement), 1700)
