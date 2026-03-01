"""
Clip Selector — Two-pass AI clip selection using Groq API.
Pass 1: Broad candidate discovery across full transcript.
Pass 2: Deep scoring of each candidate against genre-specific criteria.
"""

import os
import json
import time
import logging
import asyncio
from typing import Optional, Callable

logger = logging.getLogger(__name__)


def _get_groq_client():
    """Initialize the Groq client (lazily, so import errors are caught)."""
    from groq import Groq
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise ValueError(
            "GROQ_API_KEY not set. Set it in your .env file or environment variables.\n"
            "Get a free key at https://console.groq.com"
        )
    return Groq(api_key=api_key)


# ─── Prompt Builders ─────────────────────────────────────────

def build_discovery_prompt(transcript: dict, genre: str) -> str:
    """
    Build the Pass 1 discovery prompt with all thought blocks.

    Args:
        transcript: Master transcript dict with 'thought_blocks'.
        genre: Genre label string (e.g., "Business & Entrepreneurship").

    Returns:
        Complete prompt string for the discovery pass.
    """
    from pipeline.genre_profiles import DISCOVERY_SYSTEM_PROMPT

    blocks_text = ""
    for block in transcript["thought_blocks"]:
        blocks_text += (
            f"[BLOCK {block['id']} | {block['start']:.1f}s–{block['end']:.1f}s "
            f"| {block['end'] - block['start']:.0f}s long"
            f"| filler_ratio: {block.get('filler_ratio', 0):.2f}]\n"
            f"{block['text']}\n\n"
        )

    system_prompt = DISCOVERY_SYSTEM_PROMPT.format(genre=genre)
    return system_prompt + "\n\n--- TRANSCRIPT ---\n\n" + blocks_text


def build_scoring_prompt(expanded_candidate: dict, genre: str, scoring_criteria: str) -> str:
    """
    Build the Pass 2 scoring prompt for a single candidate.

    Args:
        expanded_candidate: Candidate with context_before, core_text, context_after.
        genre: Genre label string.
        scoring_criteria: Full scoring rubric for this genre.

    Returns:
        Complete prompt string for scoring.
    """
    from pipeline.genre_profiles import SCORING_PROMPT_TEMPLATE

    duration = round(expanded_candidate["end"] - expanded_candidate["start"], 1)

    return SCORING_PROMPT_TEMPLATE.format(
        genre=genre,
        context_before=expanded_candidate.get("context_before", "(none)"),
        core_text=expanded_candidate.get("core_text", ""),
        context_after=expanded_candidate.get("context_after", "(none)"),
        duration=duration,
        scoring_criteria=scoring_criteria,
    )


# ─── Context Expansion ──────────────────────────────────────

def expand_candidate_context(
    candidate: dict,
    transcript: dict,
    context_seconds: float = 30.0,
) -> dict:
    """
    Expand a candidate with ±30s of context for deeper scoring.

    Args:
        candidate: Candidate dict with start, end timestamps.
        transcript: Full transcript dict with 'words' list.
        context_seconds: Seconds of context to add on each side.

    Returns:
        Candidate dict enriched with context_before, core_text, context_after.
    """
    duration = transcript.get("source", {}).get("duration", 0)
    if not duration:
        duration = transcript.get("duration", float("inf"))

    expanded_start = max(0, candidate["start"] - context_seconds)
    expanded_end = min(duration, candidate["end"] + context_seconds)

    words = transcript.get("words", [])

    context_before_words = [
        w for w in words
        if expanded_start <= w["start"] < candidate["start"]
    ]
    core_words = [
        w for w in words
        if candidate["start"] <= w["start"] <= candidate["end"]
    ]
    context_after_words = [
        w for w in words
        if candidate["end"] < w["start"] <= expanded_end
    ]

    return {
        **candidate,
        "context_before": " ".join(w["word"] for w in context_before_words),
        "core_text": " ".join(w["word"] for w in core_words),
        "context_after": " ".join(w["word"] for w in context_after_words),
    }


# ─── API Call Helpers ─────────────────────────────────────────

def _call_groq_json(client, prompt: str, temperature: float = 0.3, max_tokens: int = 4000) -> dict:
    """
    Make a Groq API call with JSON mode and retry logic.

    Args:
        client: Groq client instance.
        prompt: The prompt to send.
        temperature: Sampling temperature.
        max_tokens: Max tokens for response.

    Returns:
        Parsed JSON dict from the response.
    """
    max_retries = 3
    last_error = None

    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=temperature,
                max_tokens=max_tokens,
            )

            content = response.choices[0].message.content
            return json.loads(content)

        except json.JSONDecodeError as e:
            logger.warning(f"JSON parse error on attempt {attempt + 1}: {e}")
            last_error = e
            # Retry with stricter instruction
            prompt += "\n\nIMPORTANT: Return ONLY valid JSON. No text before or after."

        except Exception as e:
            error_str = str(e)
            logger.warning(f"Groq API error on attempt {attempt + 1}: {error_str}")
            last_error = e

            # Rate limit — exponential backoff
            if "rate_limit" in error_str.lower() or "429" in error_str:
                wait_time = 5 * (2 ** attempt)
                logger.info(f"Rate limited. Waiting {wait_time}s before retry...")
                time.sleep(wait_time)
            else:
                time.sleep(1)

    raise RuntimeError(f"Groq API failed after {max_retries} retries: {last_error}")


# ─── Pass 1 — Candidate Discovery ────────────────────────────

def run_discovery_pass(
    transcript: dict,
    genre: str,
    genre_label: str,
    progress_callback: Optional[Callable[[float], None]] = None,
) -> list:
    """
    Pass 1: Scan full transcript and find all promising clip candidates.

    Args:
        transcript: Master transcript dict.
        genre: Genre slug (e.g., "business").
        genre_label: Genre display label (e.g., "Business & Entrepreneurship").
        progress_callback: Optional progress callback.

    Returns:
        List of candidate dicts with block_id, start, end, hook_preview, why_flagged.
    """
    client = _get_groq_client()

    logger.info(f"Pass 1: Discovering candidates for genre '{genre_label}'...")
    if progress_callback:
        progress_callback(0.1)

    prompt = build_discovery_prompt(transcript, genre_label)

    result = _call_groq_json(client, prompt, temperature=0.2, max_tokens=4000)
    candidates = result.get("candidates", [])

    logger.info(f"Pass 1 complete: {len(candidates)} candidates found")
    if progress_callback:
        progress_callback(1.0)

    return candidates


# ─── Pass 2 — Deep Scoring ───────────────────────────────────

def score_single_candidate(
    client,
    candidate: dict,
    transcript: dict,
    genre_label: str,
    scoring_criteria: str,
) -> dict:
    """
    Score a single candidate using the genre-specific rubric.

    Args:
        client: Groq client instance.
        candidate: Candidate dict from Pass 1.
        transcript: Full transcript dict.
        genre_label: Genre display label.
        scoring_criteria: Full scoring rubric text.

    Returns:
        Candidate dict enriched with all scores and analysis.
    """
    expanded = expand_candidate_context(candidate, transcript)
    prompt = build_scoring_prompt(expanded, genre_label, scoring_criteria)

    try:
        scores = _call_groq_json(client, prompt, temperature=0.3, max_tokens=1000)
        return {**candidate, **scores}
    except Exception as e:
        logger.error(f"Scoring failed for block {candidate.get('block_id')}: {e}")
        return {
            **candidate,
            "hook_score": 0, "narrative_score": 0, "standalone_score": 0,
            "emotional_score": 0, "length_score": 0,
            "total_score": 0, "verdict": "WEAK",
            "error": str(e),
        }


def run_scoring_pass(
    candidates: list,
    transcript: dict,
    genre: str,
    genre_label: str,
    scoring_criteria: str,
    progress_callback: Optional[Callable[[float], None]] = None,
) -> list:
    """
    Pass 2: Deep-score each candidate against genre criteria.

    Args:
        candidates: List of candidates from Pass 1.
        transcript: Full transcript dict.
        genre: Genre slug.
        genre_label: Genre display label.
        scoring_criteria: Full scoring rubric text.
        progress_callback: Optional progress callback.

    Returns:
        List of scored candidate dicts.
    """
    client = _get_groq_client()

    logger.info(f"Pass 2: Scoring {len(candidates)} candidates...")
    scored = []

    for i, candidate in enumerate(candidates):
        logger.info(f"  Scoring candidate {i + 1}/{len(candidates)} (block {candidate.get('block_id')})...")

        result = score_single_candidate(
            client, candidate, transcript, genre_label, scoring_criteria
        )
        scored.append(result)

        if progress_callback:
            progress_callback((i + 1) / len(candidates))

        # Small delay between calls to respect rate limits
        if i < len(candidates) - 1:
            time.sleep(0.5)

    logger.info(f"Pass 2 complete: {len(scored)} candidates scored")
    return scored


# ─── Full Phase 2 Pipeline ───────────────────────────────────

def run_phase_2(
    transcript: dict,
    genre: str,
    max_clips: int = 10,
    progress_callback: Optional[Callable[[str, float], None]] = None,
) -> list:
    """
    Run the full Phase 2 clip selection pipeline.

    Args:
        transcript: Master transcript dict from Phase 1.
        genre: Genre slug (e.g., "business", "health", "finance").
        max_clips: Maximum clips to return (default 10).
        progress_callback: Optional callback(stage, progress) for updates.

    Returns:
        Ranked list of clip candidates ready for the review dashboard.
    """
    from pipeline.genre_profiles import GENRE_PROFILES
    from pipeline.scoring import compute_final_score, apply_diversity_filter, rank_candidates

    # Validate genre
    if genre not in GENRE_PROFILES:
        available = ", ".join(GENRE_PROFILES.keys())
        raise ValueError(f"Unknown genre: '{genre}'. Available: {available}")

    profile = GENRE_PROFILES[genre]
    genre_label = profile["label"]
    scoring_criteria = profile["scoring_criteria"]

    logger.info(f"═══ Phase 2: AI Clip Selection ({genre_label}) ═══")

    # ── Pass 1: Candidate Discovery ──
    if progress_callback:
        progress_callback("discovery", 0.0)

    def discovery_progress(p):
        if progress_callback:
            progress_callback("discovery", p)

    candidates = run_discovery_pass(transcript, genre, genre_label, discovery_progress)

    if not candidates:
        logger.warning("Pass 1 returned zero candidates. Transcript may be low quality.")
        return []

    # ── Pass 2: Deep Scoring ──
    if progress_callback:
        progress_callback("scoring", 0.0)

    def scoring_progress(p):
        if progress_callback:
            progress_callback("scoring", p)

    scored = run_scoring_pass(
        candidates, transcript, genre, genre_label, scoring_criteria, scoring_progress
    )

    # ── Filter weak candidates ──
    valid = [c for c in scored if c.get("verdict") != "WEAK"]
    logger.info(f"Filtered: {len(scored)} scored → {len(valid)} non-WEAK")

    if not valid:
        logger.warning("All candidates scored as WEAK. Returning best available.")
        valid = sorted(scored, key=lambda x: x.get("total_score", 0), reverse=True)[:max_clips]

    # ── Compute weighted final scores ──
    for candidate in valid:
        candidate["final_score"] = compute_final_score(candidate)

    # ── Apply diversity filter ──
    diverse = apply_diversity_filter(valid, min_gap_seconds=300.0, max_results=max_clips)

    # ── Rank and format output ──
    final = rank_candidates(diverse, genre)

    logger.info(
        f"═══ Phase 2 complete: {len(final)} clips selected ═══\n"
        + "\n".join(
            f"  #{c['rank']}: score={c['final_score']} | "
            f"{c['start']:.1f}s–{c['end']:.1f}s | "
            f"{c.get('suggested_title', 'Untitled')}"
            for c in final
        )
    )

    if progress_callback:
        progress_callback("complete", 1.0)

    return final
