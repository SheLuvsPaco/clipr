"""
Pipeline Processor — Orchestrates the full Phase 1 pipeline end-to-end.
Download/receive → extract audio → preprocess → transcribe → post-process → save.
"""

import os
import json
import shutil
import logging
import traceback
from datetime import datetime, timezone
from typing import Optional

from config import PROJECTS_DIR, SUPPORTED_EXTENSIONS, MAX_FILE_SIZE_BYTES, PHASE_1_STAGES
from pipeline.job_manager import update_progress, complete_job, fail_job, push_log
from pipeline.downloader import download_video
from pipeline.audio import extract_audio, normalize_audio, reduce_noise, is_audio_only
from pipeline.transcriber import transcribe_audio
from pipeline.postprocessor import postprocess_transcript

logger = logging.getLogger(__name__)


def _get_stage_progress(stage_id: str, stage_fraction: float) -> float:
    """Calculate overall progress given the current stage and fraction within it."""
    cumulative = 0.0
    for stage in PHASE_1_STAGES:
        if stage["id"] == stage_id:
            return cumulative + stage["weight"] * stage_fraction
        cumulative += stage["weight"]
    return cumulative


def _get_stage_label(stage_id: str) -> str:
    """Get the display label for a stage."""
    for stage in PHASE_1_STAGES:
        if stage["id"] == stage_id:
            return stage["label"]
    return stage_id


def _fmt_bytes(n: int) -> str:
    """Format bytes into human readable string."""
    if n < 1024:
        return f"{n} B"
    elif n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    elif n < 1024 * 1024 * 1024:
        return f"{n / (1024 * 1024):.1f} MB"
    return f"{n / (1024 * 1024 * 1024):.2f} GB"


def run_pipeline(
    job_id: str,
    source_type: str,
    source_value: str,
    settings: Optional[dict] = None,
):
    """
    Run the full Phase 1 pipeline for a job.

    Args:
        job_id: The job ID for progress tracking.
        source_type: "url" or "upload"
        source_value: URL string or path to uploaded file.
        settings: Optional dict with keys like 'model_size', 'language',
                  'noise_reduction', 'device'.
    """
    settings = settings or {}
    project_dir = os.path.join(PROJECTS_DIR, job_id)
    raw_dir = os.path.join(project_dir, "raw")
    transcripts_dir = os.path.join(project_dir, "transcripts")
    os.makedirs(raw_dir, exist_ok=True)
    os.makedirs(transcripts_dir, exist_ok=True)

    push_log(job_id, f"Pipeline started — job {job_id}")
    push_log(job_id, f"Source: {source_type} → {source_value}")
    push_log(job_id, f"Settings: {settings}")

    try:
        # ════════════════════════════════════════════
        # STEP 1 — Download or receive input
        # ════════════════════════════════════════════
        video_info = {}
        chapters = []

        if source_type == "url":
            push_log(job_id, "─── STEP 1/5 — Downloading video ───")
            push_log(job_id, f"URL: {source_value}")
            push_log(job_id, "Resolving video metadata via yt-dlp...")

            update_progress(
                job_id, "download", _get_stage_label("download"),
                _get_stage_progress("download", 0.0)
            )

            _last_log_pct = [-1]  # mutable ref for closure

            def download_progress(p):
                pct = int(p * 100)
                update_progress(
                    job_id, "download", _get_stage_label("download"),
                    _get_stage_progress("download", p), p
                )
                # Log every 5% to avoid flooding
                if pct >= _last_log_pct[0] + 5:
                    _last_log_pct[0] = pct
                    push_log(job_id, f"Downloading... {pct}%")

            video_info = download_video(source_value, raw_dir, download_progress)
            video_path = video_info["video_path"]
            chapters = video_info.get("chapters", [])

            file_size = os.path.getsize(video_path) if os.path.exists(video_path) else 0
            push_log(job_id, f"Download complete: \"{video_info.get('title', '?')}\"")
            push_log(job_id, f"Duration: {video_info.get('duration', 0):.0f}s | Size: {_fmt_bytes(file_size)}")
            push_log(job_id, f"Uploader: {video_info.get('uploader', '?')}")
            if chapters:
                push_log(job_id, f"Chapters found: {len(chapters)}")

        elif source_type == "upload":
            push_log(job_id, "─── STEP 1/5 — File received ───")

            update_progress(
                job_id, "download", "File received",
                _get_stage_progress("download", 1.0), 1.0
            )

            video_path = source_value
            file_size = os.path.getsize(video_path) if os.path.exists(video_path) else 0
            push_log(job_id, f"File: {os.path.basename(source_value)} ({_fmt_bytes(file_size)})")
            video_info = {
                "title": os.path.basename(source_value),
                "duration": 0,
                "url": None,
            }

        else:
            raise ValueError(f"Unknown source type: {source_type}")

        # Check if the input is audio-only
        audio_only = is_audio_only(video_path)
        if audio_only:
            push_log(job_id, "Detected audio-only input (no video stream)")

        # ════════════════════════════════════════════
        # STEP 2 — Extract audio
        # ════════════════════════════════════════════
        push_log(job_id, "─── STEP 2/5 — Extracting audio ───")

        update_progress(
            job_id, "extract", _get_stage_label("extract"),
            _get_stage_progress("extract", 0.0)
        )

        if audio_only:
            audio_path = os.path.join(raw_dir, "audio.wav")
            if video_path != audio_path:
                push_log(job_id, "Converting to WAV 16kHz mono...")
                from pipeline.audio import extract_audio as _extract
                audio_path = _extract(video_path, raw_dir)
            push_log(job_id, "Audio-only — skipped video demux")
        else:
            push_log(job_id, "Running ffmpeg: demux → WAV 16kHz mono PCM")
            audio_path = extract_audio(video_path, raw_dir)

        audio_size = os.path.getsize(audio_path) if os.path.exists(audio_path) else 0
        push_log(job_id, f"Audio extracted: {_fmt_bytes(audio_size)}")

        update_progress(
            job_id, "extract", _get_stage_label("extract"),
            _get_stage_progress("extract", 1.0), 1.0
        )

        # ════════════════════════════════════════════
        # STEP 3 — Preprocess audio
        # ════════════════════════════════════════════
        push_log(job_id, "─── STEP 3/5 — Preprocessing audio ───")

        update_progress(
            job_id, "preprocess", _get_stage_label("preprocess"),
            _get_stage_progress("preprocess", 0.0)
        )

        # Always normalize
        push_log(job_id, "Applying EBU R128 loudness normalization (I=-16, TP=-1.5)")
        normalized_path = normalize_audio(audio_path, raw_dir)
        push_log(job_id, "Loudness normalization complete")

        # Optional noise reduction
        final_audio_path = normalized_path
        if settings.get("noise_reduction", False):
            push_log(job_id, "Applying noise reduction (profiling first 0.5s as baseline)...")
            final_audio_path = reduce_noise(normalized_path)
            push_log(job_id, "Noise reduction complete")
        else:
            push_log(job_id, "Noise reduction: skipped (not enabled)")

        update_progress(
            job_id, "preprocess", _get_stage_label("preprocess"),
            _get_stage_progress("preprocess", 1.0), 1.0
        )

        # ════════════════════════════════════════════
        # STEP 4 — Transcribe
        # ════════════════════════════════════════════
        model_size = settings.get("model_size", "large-v3-turbo")
        device = settings.get("device", "auto")
        language = settings.get("language", "en")

        push_log(job_id, "─── STEP 4/5 — Transcribing with Whisper ───")
        push_log(job_id, f"Model: {model_size} | Device: {device} | Language: {language}")
        push_log(job_id, "Loading model into memory...")

        update_progress(
            job_id, "transcribe", _get_stage_label("transcribe"),
            _get_stage_progress("transcribe", 0.0)
        )

        _last_t_pct = [-1]
        _seg_count = [0]

        def transcribe_progress(p):
            pct = int(p * 100)
            update_progress(
                job_id, "transcribe", _get_stage_label("transcribe"),
                _get_stage_progress("transcribe", p), p
            )
            if pct >= _last_t_pct[0] + 2:
                _last_t_pct[0] = pct
                push_log(job_id, f"Transcribing... {pct}%")

        raw_transcript = transcribe_audio(
            final_audio_path,
            model_size=model_size,
            device=device,
            language=language,
            progress_callback=transcribe_progress,
        )

        seg_count = len(raw_transcript.get("segments", []))
        word_count = len(raw_transcript.get("words", []))
        proc_time = raw_transcript.get("processing_time_seconds", 0)
        push_log(job_id, f"Transcription complete in {proc_time:.1f}s")
        push_log(job_id, f"Segments: {seg_count} | Words: {word_count}")
        push_log(job_id, f"Detected language: {raw_transcript.get('language', '?')} "
                         f"(confidence: {raw_transcript.get('language_probability', 0):.1%})")

        # Save raw transcript
        raw_transcript_path = os.path.join(transcripts_dir, "transcript_raw.json")
        with open(raw_transcript_path, "w") as f:
            json.dump(raw_transcript, f, indent=2, ensure_ascii=False)
        push_log(job_id, f"Raw transcript saved → {os.path.basename(raw_transcript_path)}")
        logger.info(f"Raw transcript saved: {raw_transcript_path}")

        # ════════════════════════════════════════════
        # STEP 5 — Post-process transcript
        # ════════════════════════════════════════════
        push_log(job_id, "─── STEP 5/5 — Post-processing transcript ───")
        push_log(job_id, "Flagging filler words, segmenting thought blocks...")

        update_progress(
            job_id, "postprocess", _get_stage_label("postprocess"),
            _get_stage_progress("postprocess", 0.0)
        )

        processed_transcript = postprocess_transcript(raw_transcript, chapters)

        stats = processed_transcript.get("stats", {})
        block_count = len(processed_transcript.get("thought_blocks", []))
        push_log(job_id, f"Thought blocks: {block_count}")
        push_log(job_id, f"Total words: {stats.get('total_words', '?')} | "
                         f"Duration: {stats.get('total_duration', 0):.0f}s | "
                         f"WPM: {stats.get('avg_words_per_minute', 0):.0f}")

        # ════════════════════════════════════════════
        # FINAL — Assemble master transcript JSON
        # ════════════════════════════════════════════
        push_log(job_id, "Assembling master transcript...")

        master_transcript = {
            "source": {
                "type": source_type,
                "url": video_info.get("url"),
                "title": video_info.get("title", "Unknown"),
                "uploader": video_info.get("uploader", "Unknown"),
                "duration": video_info.get("duration", raw_transcript.get("duration", 0)),
                "downloaded_at": datetime.now(timezone.utc).isoformat(),
                "audio_only": audio_only,
            },
            "transcription": {
                "model": model_size,
                "language": processed_transcript["language"],
                "processing_time_seconds": processed_transcript["processing_time_seconds"],
            },
            "stats": processed_transcript["stats"],
            "thought_blocks": processed_transcript["thought_blocks"],
            "words": processed_transcript["words"],
        }

        # Save master transcript
        transcript_path = os.path.join(transcripts_dir, "transcript.json")
        with open(transcript_path, "w") as f:
            json.dump(master_transcript, f, indent=2, ensure_ascii=False)

        push_log(job_id, f"Master transcript saved → {os.path.basename(transcript_path)}")
        logger.info(f"Master transcript saved: {transcript_path}")

        update_progress(
            job_id, "postprocess", _get_stage_label("postprocess"),
            _get_stage_progress("postprocess", 1.0), 1.0
        )

        # Mark job as complete
        push_log(job_id, "═══ Pipeline complete ═══", "success")
        complete_job(job_id, transcript_path)

        logger.info(f"Pipeline complete for job {job_id}")
        return master_transcript

    except Exception as e:
        error_msg = f"{type(e).__name__}: {str(e)}"
        push_log(job_id, f"PIPELINE FAILED: {error_msg}", "error")
        logger.error(f"Pipeline failed for job {job_id}: {error_msg}")
        logger.error(traceback.format_exc())
        fail_job(job_id, error_msg)
        raise
