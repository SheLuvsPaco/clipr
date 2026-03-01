"""
Post-Processor — Clean and structure raw transcripts for Phase 2.
Handles filler word flagging, thought block segmentation,
confidence filtering, and chapter integration.
"""

import logging
from typing import Optional

from config import (
    FILLER_WORDS,
    THOUGHT_BLOCK_MIN_PAUSE,
    LOW_CONFIDENCE_THRESHOLD,
)

logger = logging.getLogger(__name__)


def flag_fillers(words: list) -> list:
    """
    Flag filler words in the word list.
    We don't delete them — the AI brain in Phase 2 uses filler density
    to score clip quality (lots of fillers = rambling = bad clip).

    Args:
        words: List of word dicts with 'word' key.

    Returns:
        Same list with 'is_filler' boolean added to each word.
    """
    for word in words:
        cleaned = word["word"].lower().strip(",.?!:;\"'")
        word["is_filler"] = cleaned in FILLER_WORDS
    return words


def flag_low_confidence(segments: list, threshold: float = LOW_CONFIDENCE_THRESHOLD) -> list:
    """
    Flag segments with low average word confidence.
    Low-probability words indicate background noise, crosstalk,
    or genuine low-confidence transcription.

    Args:
        segments: List of segment dicts with 'words' key.
        threshold: Confidence threshold (default 0.7).

    Returns:
        Same list with 'confidence' and 'low_confidence' added.
    """
    for seg in segments:
        words = seg.get("words", [])
        if words:
            avg_conf = sum(w.get("probability", 1.0) for w in words) / len(words)
            seg["confidence"] = round(avg_conf, 4)
            seg["low_confidence"] = avg_conf < threshold
        else:
            seg["confidence"] = 1.0
            seg["low_confidence"] = False
    return segments


def segment_thought_blocks(
    segments: list,
    min_pause: float = THOUGHT_BLOCK_MIN_PAUSE,
) -> list:
    """
    Group segments into 'thought blocks' — logical units of meaning
    that could stand alone as a clip.

    Detects boundaries using:
    - Pause duration between segments (>1.5s = likely topic shift)
    - Sentence-ending punctuation followed by a pause

    Args:
        segments: List of segment dicts with start, end, text, words.
        min_pause: Minimum pause duration to trigger a block break (default 1.5s).

    Returns:
        List of thought block dicts.
    """
    if not segments:
        return []

    blocks = []
    current_block = []

    for i, seg in enumerate(segments):
        current_block.append(seg)

        if i < len(segments) - 1:
            pause = segments[i + 1]["start"] - seg["end"]
            text = seg["text"].strip()
            ends_sentence = text[-1] in ".?!" if text else False

            if pause > min_pause and ends_sentence:
                blocks.append(_build_block(current_block, len(blocks)))
                current_block = []

    # Don't forget the final block
    if current_block:
        blocks.append(_build_block(current_block, len(blocks)))

    logger.info(f"Segmented transcript into {len(blocks)} thought blocks")
    return blocks


def _build_block(segments: list, block_id: int) -> dict:
    """Build a thought block dict from a list of segments."""
    # Count total words and filler words across all segments
    total_words = 0
    filler_count = 0
    for seg in segments:
        for w in seg.get("words", []):
            total_words += 1
            if w.get("is_filler", False):
                filler_count += 1

    # Calculate average confidence
    all_confs = [
        w.get("probability", 1.0)
        for seg in segments
        for w in seg.get("words", [])
    ]
    avg_confidence = sum(all_confs) / max(len(all_confs), 1)

    return {
        "id": block_id,
        "start": segments[0]["start"],
        "end": segments[-1]["end"],
        "text": " ".join(seg["text"] for seg in segments),
        "filler_ratio": round(filler_count / max(total_words, 1), 4),
        "confidence": round(avg_confidence, 4),
        "word_count": total_words,
        "chapter": segments[0].get("chapter"),
        "segments": segments,
    }


def inject_chapter_markers(
    segments: list,
    chapters: Optional[list] = None,
) -> list:
    """
    Merge chapter markers from video metadata into the transcript.
    Gives the Phase 2 AI structural context — "this section is about X".

    Args:
        segments: List of segment dicts.
        chapters: List of chapter dicts with 'start_time', 'end_time', 'title'.

    Returns:
        Same segments list with 'chapter' field added.
    """
    if not chapters:
        for seg in segments:
            seg["chapter"] = None
        return segments

    for seg in segments:
        seg["chapter"] = None
        for chapter in chapters:
            start = chapter.get("start_time", chapter.get("start", 0))
            end = chapter.get("end_time", chapter.get("end", float("inf")))
            if start <= seg["start"] <= end:
                seg["chapter"] = chapter.get("title", "")
                break

    logger.info(f"Injected chapter markers from {len(chapters)} chapters")
    return segments


def detect_hallucinations(segments: list) -> list:
    """
    Detect potential Whisper hallucinations (repeated phrases).
    Flags segments that contain repetitive text patterns.

    Args:
        segments: List of segment dicts.

    Returns:
        Same list with 'is_hallucination' flag added where detected.
    """
    for seg in segments:
        text = seg["text"].strip()
        words = text.split()
        seg["is_hallucination"] = False

        # Check for repeated phrases (3+ word sequences repeated 3+ times)
        if len(words) >= 9:
            for phrase_len in range(3, min(len(words) // 3 + 1, 8)):
                for start_idx in range(len(words) - phrase_len * 2):
                    phrase = " ".join(words[start_idx:start_idx + phrase_len])
                    count = text.count(phrase)
                    if count >= 3:
                        seg["is_hallucination"] = True
                        logger.warning(f"Potential hallucination detected in segment {seg['id']}: '{phrase}' repeated {count} times")
                        break
                if seg["is_hallucination"]:
                    break

    return segments


def postprocess_transcript(raw_transcript: dict, chapters: Optional[list] = None) -> dict:
    """
    Run all post-processing steps on a raw transcript.
    This is the main entry point for the post-processing pipeline.

    Args:
        raw_transcript: Raw transcript dict from the transcriber.
        chapters: Optional chapter markers from video metadata.

    Returns:
        Fully processed transcript ready for Phase 2.
    """
    logger.info("Starting transcript post-processing...")

    segments = raw_transcript["segments"]
    words = raw_transcript["words"]

    # Step 5a — Flag filler words
    words = flag_fillers(words)

    # Also flag fillers in segment-level words
    for seg in segments:
        seg["words"] = flag_fillers(seg.get("words", []))

    # Step 5b — Confidence filtering
    segments = flag_low_confidence(segments)

    # Detect hallucinations
    segments = detect_hallucinations(segments)

    # Remove hallucinated segments
    clean_segments = [s for s in segments if not s.get("is_hallucination", False)]
    removed = len(segments) - len(clean_segments)
    if removed > 0:
        logger.info(f"Removed {removed} hallucinated segments")

    # Step 5c — Inject chapter markers
    clean_segments = inject_chapter_markers(clean_segments, chapters)

    # Step 5d — Segment into thought blocks
    thought_blocks = segment_thought_blocks(clean_segments)

    # Count low-confidence segments
    low_conf_count = sum(1 for s in clean_segments if s.get("low_confidence", False))
    low_conf_ratio = low_conf_count / max(len(clean_segments), 1)

    # Build processed transcript
    processed = {
        "language": raw_transcript["language"],
        "duration": raw_transcript["duration"],
        "processing_time_seconds": raw_transcript.get("processing_time_seconds", 0),
        "stats": {
            "total_segments": len(clean_segments),
            "total_words": len(words),
            "total_thought_blocks": len(thought_blocks),
            "low_confidence_segments": low_conf_count,
            "low_confidence_ratio": round(low_conf_ratio, 4),
            "hallucinated_segments_removed": removed,
            "filler_words": sum(1 for w in words if w.get("is_filler", False)),
            "filler_ratio": round(
                sum(1 for w in words if w.get("is_filler", False))
                / max(len(words), 1),
                4,
            ),
        },
        "thought_blocks": thought_blocks,
        "words": words,
    }

    logger.info(
        f"Post-processing complete: {processed['stats']['total_thought_blocks']} thought blocks, "
        f"{processed['stats']['total_words']} words, "
        f"filler ratio: {processed['stats']['filler_ratio']:.1%}"
    )

    return processed
