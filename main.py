"""
Clipping Tool — Phase 1, 2, 3 & 4 API
FastAPI backend for Ingestion, Transcription, AI Clip Selection,
Video Processing, and Caption Rendering.
"""

# Load .env before anything else
from dotenv import load_dotenv
load_dotenv()

import os
import json
import shutil
import logging
from typing import Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from config import PROJECTS_DIR, SUPPORTED_EXTENSIONS, MAX_FILE_SIZE_BYTES
from pipeline.job_manager import create_job, get_job, list_jobs
from pipeline.processor import run_pipeline
from pipeline.clip_selector import run_phase_2
from pipeline.genre_profiles import get_available_genres, GENRE_PROFILES
from pipeline.video_processor import process_all_clips
from pipeline.caption_renderer import (
    run_phase_4_batch, get_available_caption_styles, STYLE_MAP,
)
from pipeline.dashboard_routes import router as dashboard_router

# ─── Logging ──────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(name)-25s │ %(levelname)-7s │ %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


# ─── App Setup ────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    logger.info("═" * 60)
    logger.info("  Clipping Tool — Phase 1 & 2")
    logger.info("  Phase 1: Ingestion & Transcription")
    logger.info("  Phase 2: AI Clip Selection")
    logger.info(f"  Projects directory: {PROJECTS_DIR}")
    groq_key = os.environ.get("GROQ_API_KEY", "")
    logger.info(f"  Groq API Key: {'✓ configured' if groq_key else '✗ NOT SET'}")
    logger.info("═" * 60)
    yield
    logger.info("Shutting down Clipping Tool...")


app = FastAPI(
    title="Clipping Tool",
    description="AI-Powered Short-Form Content Clipping — Full Pipeline",
    version="0.5.0",
    lifespan=lifespan,
)

# CORS — allow React frontend (any origin)
# Note: allow_credentials=True is incompatible with allow_origins=["*"] in Starlette,
# which causes 403 on WebSocket connections. Use allow_credentials=False with wildcard.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Dashboard routes (project lifecycle, WebSocket, export, etc.)
app.include_router(dashboard_router)


# ─── Request / Response Models ────────────────────────────────
class ProcessURLRequest(BaseModel):
    url: str
    model_size: Optional[str] = "large-v3-turbo"
    language: Optional[str] = "en"
    device: Optional[str] = "auto"
    noise_reduction: Optional[bool] = False


class ClipSelectionRequest(BaseModel):
    job_id: str
    genre: str
    max_clips: Optional[int] = 10


class ClipProcessingRequest(BaseModel):
    job_id: str
    jump_cut_enabled: Optional[bool] = True
    max_pause_ms: Optional[int] = 300
    remove_fillers: Optional[bool] = True
    grade_preset: Optional[str] = "standard"


class CaptionRequest(BaseModel):
    job_id: str
    caption_style: Optional[str] = "hormozi"
    remove_fillers: Optional[bool] = False


class JobResponse(BaseModel):
    id: str
    status: str
    stage: Optional[str] = None
    stage_label: Optional[str] = None
    progress: float = 0.0
    stage_progress: float = 0.0
    created_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    error: Optional[str] = None
    result: Optional[str] = None


# ─── API Routes ───────────────────────────────────────────────

@app.post("/api/process/url", response_model=JobResponse)
async def process_url(request: ProcessURLRequest, background_tasks: BackgroundTasks):
    """
    Start processing a video from a URL.
    Downloads the video, extracts audio, transcribes, and post-processes.
    Returns immediately with a job ID for progress polling.
    """
    logger.info(f"Processing URL: {request.url}")

    settings = {
        "model_size": request.model_size,
        "language": request.language,
        "device": request.device,
        "noise_reduction": request.noise_reduction,
    }

    job = create_job("url", request.url, settings)

    # Run pipeline in background
    background_tasks.add_task(
        run_pipeline,
        job["id"],
        "url",
        request.url,
        settings,
    )

    return JobResponse(**job)


@app.post("/api/process/upload", response_model=JobResponse)
async def process_upload(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    model_size: str = Form(default="large-v3-turbo"),
    language: str = Form(default="en"),
    device: str = Form(default="auto"),
    noise_reduction: bool = Form(default=False),
):
    """
    Start processing an uploaded video/audio file.
    Accepts MP4, MOV, MKV, AVI, WEBM, MP3, M4A, WAV, FLAC, OGG.
    Returns immediately with a job ID for progress polling.
    """
    # Validate file extension
    _, ext = os.path.splitext(file.filename or "")
    ext = ext.lower()

    if ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file format: {ext}. Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}",
        )

    settings = {
        "model_size": model_size,
        "language": language,
        "device": device,
        "noise_reduction": noise_reduction,
    }

    job = create_job("upload", file.filename, settings)

    # Save uploaded file to project directory
    project_dir = os.path.join(PROJECTS_DIR, job["id"])
    raw_dir = os.path.join(project_dir, "raw")
    os.makedirs(raw_dir, exist_ok=True)

    file_path = os.path.join(raw_dir, f"uploaded{ext}")

    # Stream the file to disk to handle large files
    with open(file_path, "wb") as f:
        while True:
            chunk = await file.read(1024 * 1024)  # 1MB chunks
            if not chunk:
                break
            f.write(chunk)

    file_size = os.path.getsize(file_path)
    if file_size > MAX_FILE_SIZE_BYTES:
        os.remove(file_path)
        raise HTTPException(
            status_code=413,
            detail=f"File too large ({file_size / (1024**3):.1f} GB). Maximum: 10 GB.",
        )

    logger.info(f"File uploaded: {file.filename} ({file_size / (1024**2):.1f} MB)")

    # Run pipeline in background
    background_tasks.add_task(
        run_pipeline,
        job["id"],
        "upload",
        file_path,
        settings,
    )

    return JobResponse(**job)


@app.get("/api/status/{job_id}", response_model=JobResponse)
async def get_status(job_id: str):
    """
    Get the current status and progress of a processing job.
    Poll this endpoint to track pipeline progress.
    """
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
    return JobResponse(**job)


@app.get("/api/transcript/{job_id}")
async def get_transcript(job_id: str):
    """
    Get the completed master transcript for a job.
    Only available after the job status is 'completed'.
    """
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    if job["status"] != "completed":
        raise HTTPException(
            status_code=400,
            detail=f"Job is not completed yet. Current status: {job['status']}",
        )

    transcript_path = job.get("result")
    if not transcript_path or not os.path.exists(transcript_path):
        raise HTTPException(status_code=404, detail="Transcript file not found")

    with open(transcript_path, "r") as f:
        transcript = json.load(f)

    return JSONResponse(content=transcript)


@app.get("/api/jobs")
async def get_all_jobs():
    """List all jobs, most recent first."""
    jobs = list_jobs()
    return [JobResponse(**j) for j in jobs]


@app.delete("/api/jobs/{job_id}")
async def delete_job(job_id: str):
    """Delete a job and its associated files."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    # Remove project directory
    project_dir = os.path.join(PROJECTS_DIR, job_id)
    if os.path.exists(project_dir):
        shutil.rmtree(project_dir)

    return {"message": f"Job {job_id} deleted"}


# ─── Phase 2: AI Clip Selection ───────────────────────────────

@app.get("/api/genres")
async def list_genres():
    """List all available genre profiles for clip selection."""
    return get_available_genres()


@app.post("/api/clips/select")
async def select_clips(request: ClipSelectionRequest, background_tasks: BackgroundTasks):
    """
    Run Phase 2 AI clip selection on a completed transcript.
    Requires a completed Phase 1 job_id and a genre selection.
    Returns immediately — poll /api/clips/{job_id} for results.
    """
    job = get_job(request.job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job not found: {request.job_id}")

    if job["status"] != "completed":
        raise HTTPException(
            status_code=400,
            detail=f"Job is not completed yet. Current status: {job['status']}. Phase 1 must finish first.",
        )

    if request.genre not in GENRE_PROFILES:
        available = ", ".join(GENRE_PROFILES.keys())
        raise HTTPException(
            status_code=400,
            detail=f"Unknown genre: '{request.genre}'. Available: {available}",
        )

    # Load the transcript
    transcript_path = job.get("result")
    if not transcript_path or not os.path.exists(transcript_path):
        raise HTTPException(status_code=404, detail="Transcript file not found")

    with open(transcript_path, "r") as f:
        transcript = json.load(f)

    # Run Phase 2 in background
    background_tasks.add_task(
        _run_clip_selection,
        request.job_id,
        transcript,
        request.genre,
        request.max_clips,
    )

    return {
        "message": f"Phase 2 started for job {request.job_id} with genre '{request.genre}'",
        "job_id": request.job_id,
        "genre": request.genre,
    }


def _run_clip_selection(job_id: str, transcript: dict, genre: str, max_clips: int):
    """Background task to run Phase 2 clip selection."""
    try:
        from pipeline.job_manager import update_progress

        update_progress(job_id, "clip_selection", "AI analyzing transcript...", 0.0)

        clips = run_phase_2(transcript, genre, max_clips)

        # Save clip candidates
        clips_path = os.path.join(PROJECTS_DIR, job_id, "clips.json")
        with open(clips_path, "w") as f:
            json.dump(clips, f, indent=2, ensure_ascii=False)

        # Update job with clips result
        job = get_job(job_id)
        if job:
            job["clips_result"] = clips_path
            job["clips_genre"] = genre
            job["clips_count"] = len(clips)
            job["status"] = "completed"
            job["stage"] = "done"
            job["stage_label"] = f"Phase 2 complete: {len(clips)} clips found"

        logger.info(f"Phase 2 complete for job {job_id}: {len(clips)} clips")

    except Exception as e:
        logger.error(f"Phase 2 failed for job {job_id}: {e}")
        from pipeline.job_manager import fail_job
        fail_job(job_id, f"Phase 2 error: {str(e)}")


@app.get("/api/clips/{job_id}")
async def get_clips(job_id: str):
    """
    Get clip candidates for a job after Phase 2 completes.
    """
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    clips_path = job.get("clips_result")
    if not clips_path:
        # Check if file exists on disk even if not in job state
        clips_path = os.path.join(PROJECTS_DIR, job_id, "clips.json")

    if not os.path.exists(clips_path):
        raise HTTPException(
            status_code=404,
            detail="No clip candidates found. Run Phase 2 clip selection first.",
        )

    with open(clips_path, "r") as f:
        clips = json.load(f)

    return {
        "job_id": job_id,
        "genre": job.get("clips_genre", "unknown"),
        "clips_count": len(clips),
        "clips": clips,
    }


# ─── Phase 3: Video Processing ───────────────────────────────────

@app.post("/api/clips/process")
async def process_clips(request: ClipProcessingRequest, background_tasks: BackgroundTasks):
    """
    Run Phase 3 video processing on approved clip candidates.
    Requires a completed Phase 2 job (clips.json must exist).
    Returns immediately — poll /api/clips/{job_id}/processed for results.
    """
    job = get_job(request.job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job not found: {request.job_id}")

    # Load clip candidates
    clips_path = job.get("clips_result")
    if not clips_path:
        clips_path = os.path.join(PROJECTS_DIR, request.job_id, "clips.json")
    if not os.path.exists(clips_path):
        raise HTTPException(status_code=400, detail="No clip candidates found. Run Phase 2 first.")

    # Load transcript for word timestamps
    transcript_path = job.get("result")
    if not transcript_path or not os.path.exists(transcript_path):
        raise HTTPException(status_code=404, detail="Transcript file not found")

    with open(clips_path, "r") as f:
        candidates = json.load(f)
    with open(transcript_path, "r") as f:
        transcript = json.load(f)

    jump_cut_settings = {
        "enabled": request.jump_cut_enabled,
        "max_pause_ms": request.max_pause_ms,
        "remove_fillers": request.remove_fillers,
    }

    background_tasks.add_task(
        _run_video_processing,
        request.job_id,
        candidates,
        transcript,
        jump_cut_settings,
        request.grade_preset,
    )

    return {
        "message": f"Phase 3 started for job {request.job_id} ({len(candidates)} clips)",
        "job_id": request.job_id,
        "clips_count": len(candidates),
    }


def _run_video_processing(
    job_id: str,
    candidates: list,
    transcript: dict,
    jump_cut_settings: dict,
    grade_preset: str,
):
    """Background task to run Phase 3 video processing."""
    try:
        from pipeline.job_manager import update_progress

        update_progress(job_id, "video_processing", "Processing clips...", 0.0)

        # Find the source video
        project_dir = os.path.join(PROJECTS_DIR, job_id)
        video_path = _find_source_video(project_dir)
        if not video_path:
            raise FileNotFoundError("Source video not found in project directory")

        # Get word list from transcript
        words = transcript.get("words", [])

        results = process_all_clips(
            candidates=candidates,
            video_path=video_path,
            transcript_words=words,
            output_dir=project_dir,
            jump_cut_settings=jump_cut_settings,
            grade_preset=grade_preset,
        )

        # Save processed results
        results_path = os.path.join(project_dir, "processed_clips.json")
        # Remove face_positions (too large for JSON)
        clean_results = []
        for r in results:
            entry = {k: v for k, v in r.items() if k != 'face_positions'}
            clean_results.append(entry)
        with open(results_path, "w") as f:
            json.dump(clean_results, f, indent=2, ensure_ascii=False)

        job = get_job(job_id)
        if job:
            job["processed_result"] = results_path
            job["status"] = "completed"
            job["stage"] = "done"
            successful = sum(1 for r in results if r.get('processed_path'))
            job["stage_label"] = f"Phase 3 complete: {successful}/{len(results)} clips processed"

        logger.info(f"Phase 3 complete for job {job_id}")

    except Exception as e:
        logger.error(f"Phase 3 failed for job {job_id}: {e}")
        from pipeline.job_manager import fail_job
        fail_job(job_id, f"Phase 3 error: {str(e)}")


def _find_source_video(project_dir: str) -> str:
    """Find the source video file in a project directory."""
    raw_dir = os.path.join(project_dir, "raw")
    if os.path.exists(raw_dir):
        for f in os.listdir(raw_dir):
            if any(f.endswith(ext) for ext in ('.mp4', '.mov', '.mkv', '.avi', '.webm')):
                return os.path.join(raw_dir, f)
    # Fallback: check project root
    for f in os.listdir(project_dir):
        if any(f.endswith(ext) for ext in ('.mp4', '.mov', '.mkv', '.avi', '.webm')):
            return os.path.join(project_dir, f)
    return ""


@app.get("/api/clips/{job_id}/processed")
async def get_processed_clips(job_id: str):
    """
    Get processed clip results after Phase 3 completes.
    """
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    results_path = job.get("processed_result")
    if not results_path:
        results_path = os.path.join(PROJECTS_DIR, job_id, "processed_clips.json")

    if not os.path.exists(results_path):
        raise HTTPException(
            status_code=404,
            detail="No processed clips found. Run Phase 3 video processing first.",
        )

    with open(results_path, "r") as f:
        results = json.load(f)

    return {
        "job_id": job_id,
        "processed_count": len(results),
        "clips": results,
    }


# ─── Phase 4: Caption Rendering ──────────────────────────────────

@app.get("/api/caption-styles")
async def list_caption_styles():
    """List all available caption styles."""
    return {
        "styles": get_available_caption_styles(),
        "default": "hormozi",
    }


@app.post("/api/captions/render")
async def render_clip_captions(request: CaptionRequest, background_tasks: BackgroundTasks):
    """
    Run Phase 4 caption rendering on processed clips.
    Requires completed Phase 3 (processed_clips.json must exist).
    Returns immediately — poll /api/captions/{job_id} for results.
    """
    job = get_job(request.job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job not found: {request.job_id}")

    if request.caption_style not in STYLE_MAP:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown caption style: {request.caption_style}. "
                   f"Available: {list(STYLE_MAP.keys())}",
        )

    # Load processed clips from Phase 3
    processed_path = job.get("processed_result")
    if not processed_path:
        processed_path = os.path.join(PROJECTS_DIR, request.job_id, "processed_clips.json")
    if not os.path.exists(processed_path):
        raise HTTPException(
            status_code=400,
            detail="No processed clips found. Run Phase 3 first.",
        )

    with open(processed_path, "r") as f:
        clips = json.load(f)

    background_tasks.add_task(
        _run_caption_rendering,
        request.job_id,
        clips,
        request.caption_style,
        request.remove_fillers,
    )

    return {
        "message": f"Phase 4 started for job {request.job_id} ({len(clips)} clips, style={request.caption_style})",
        "job_id": request.job_id,
        "clips_count": len(clips),
        "caption_style": request.caption_style,
    }


def _run_caption_rendering(
    job_id: str,
    clips: list,
    caption_style: str,
    remove_fillers: bool,
):
    """Background task to run Phase 4 caption rendering."""
    try:
        from pipeline.job_manager import update_progress

        update_progress(job_id, "caption_rendering", "Rendering captions...", 0.0)

        project_dir = os.path.join(PROJECTS_DIR, job_id)

        results = run_phase_4_batch(
            clips=clips,
            caption_style=caption_style,
            output_dir=project_dir,
            remove_fillers=remove_fillers,
        )

        # Save captioned results
        results_path = os.path.join(project_dir, "captioned_clips.json")
        clean_results = [
            {k: v for k, v in r.items() if k != 'face_positions'}
            for r in results
        ]
        with open(results_path, "w") as f:
            json.dump(clean_results, f, indent=2, ensure_ascii=False)

        job = get_job(job_id)
        if job:
            job["captioned_result"] = results_path
            job["status"] = "completed"
            job["stage"] = "done"
            successful = sum(1 for r in results if r.get('final_path'))
            job["stage_label"] = f"Phase 4 complete: {successful}/{len(results)} clips captioned"

        logger.info(f"Phase 4 complete for job {job_id}")

    except Exception as e:
        logger.error(f"Phase 4 failed for job {job_id}: {e}")
        from pipeline.job_manager import fail_job
        fail_job(job_id, f"Phase 4 error: {str(e)}")


@app.get("/api/captions/{job_id}")
async def get_captioned_clips(job_id: str):
    """
    Get captioned clip results after Phase 4 completes.
    """
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    results_path = job.get("captioned_result")
    if not results_path:
        results_path = os.path.join(PROJECTS_DIR, job_id, "captioned_clips.json")

    if not os.path.exists(results_path):
        raise HTTPException(
            status_code=404,
            detail="No captioned clips found. Run Phase 4 caption rendering first.",
        )

    with open(results_path, "r") as f:
        results = json.load(f)

    return {
        "job_id": job_id,
        "captioned_count": len(results),
        "clips": results,
    }


# ─── Health Check ─────────────────────────────────────────────
@app.get("/api/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "ok",
        "phases": [
            "Phase 1 — Ingestion & Transcription",
            "Phase 2 — AI Clip Selection",
            "Phase 3 — Clip Cutting & Video Processing",
            "Phase 4 — Caption Rendering",
        ],
        "version": "0.4.0",
        "groq_configured": bool(os.environ.get("GROQ_API_KEY")),
        "caption_styles": list(STYLE_MAP.keys()),
    }
