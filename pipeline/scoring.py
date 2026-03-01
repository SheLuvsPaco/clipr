"""
Scoring Engine — Weighted score computation, diversity filtering,
and final ranking for clip candidates.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ─── Score Weights ────────────────────────────────────────────
# Hook is most important — you either stop the scroll or you don't.
# Narrative second — does the clip land.
# Standalone third — must make sense without context.
# Emotional fourth — drives shares/saves.
# Length is a tiebreaker.

SCORE_WEIGHTS = {
    "hook_score":       0.30,
    "narrative_score":  0.25,
    "standalone_score": 0.20,
    "emotional_score":  0.15,
    "length_score":     0.10,
}


def compute_final_score(scores: dict) -> float:
    """
    Compute weighted final score from individual dimension scores.

    Args:
        scores: dict with hook_score, narrative_score, standalone_score,
                emotional_score, length_score (each 0-10).

    Returns:
        Final score 0-100.
    """
    # Check for automatic disqualification
    if scores.get("total_score") == 0 or scores.get("verdict") == "WEAK":
        return 0.0

    weighted = sum(
        scores.get(key, 0) * weight
        for key, weight in SCORE_WEIGHTS.items()
    )
    return round(weighted * 10, 1)  # 0–100


def apply_diversity_filter(
    candidates: list,
    min_gap_seconds: float = 300.0,  # 5 minutes
    max_results: int = 10,
) -> list:
    """
    Filter candidates to ensure diversity across the podcast.
    Prevents 5 clips from the same 10-minute section.

    Args:
        candidates: Sorted list of scored candidates (highest first).
        min_gap_seconds: Minimum time gap between selected clips.
        max_results: Maximum number of clips to return.

    Returns:
        Filtered list of diverse, top-scoring candidates.
    """
    selected = []
    for candidate in sorted(candidates, key=lambda x: x.get("final_score", 0), reverse=True):
        # Check if this candidate is too close to any already selected
        too_close = any(
            abs(candidate["start"] - s["start"]) < min_gap_seconds
            for s in selected
        )
        if not too_close:
            selected.append(candidate)
        if len(selected) >= max_results:
            break

    logger.info(
        f"Diversity filter: {len(candidates)} candidates → {len(selected)} selected "
        f"(min gap: {min_gap_seconds}s)"
    )
    return selected


def rank_candidates(candidates: list, genre: str) -> list:
    """
    Rank candidates by final score and assign rank numbers.

    Args:
        candidates: List of scored, filtered candidates.
        genre: Genre string for metadata.

    Returns:
        List of candidates with rank and genre fields added.
    """
    sorted_candidates = sorted(
        candidates,
        key=lambda x: x.get("final_score", 0),
        reverse=True,
    )

    for i, candidate in enumerate(sorted_candidates):
        candidate["rank"] = i + 1
        candidate["genre"] = genre
        if "start" in candidate and "end" in candidate:
            candidate["duration"] = round(candidate["end"] - candidate["start"], 1)

    return sorted_candidates
