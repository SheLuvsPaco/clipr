"""
Dashboard Routes — Phase 5 backend endpoints.
Unified project lifecycle, WebSocket progress, clip preview,
export/download, ASS re-render, and project history.
"""

import os
import io
import json
import asyncio
import zipfile
import subprocess
import tempfile
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, WebSocket, HTTPException, Form, UploadFile, File, BackgroundTasks
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from config import PROJECTS_DIR

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

# ─── WebSocket progress queues ────────────────────────────────
_progress_queues: dict = {}  # project_id → asyncio.Queue


def get_progress_queue(project_id: str) -> asyncio.Queue:
    """Get or create a progress queue for a project."""
    if project_id not in _progress_queues:
        _progress_queues[project_id] = asyncio.Queue()
    return _progress_queues[project_id]


def push_progress(project_id: str, event: dict):
    """Push a progress event to the project's queue (non-async)."""
    queue = get_progress_queue(project_id)
    try:
        queue.put_nowait(event)
    except asyncio.QueueFull:
        pass  # Drop event rather than block


# ─── Request Models ───────────────────────────────────────────

class ProjectProcessRequest(BaseModel):
    clips: list  # [{clip_id, style, trim_start, trim_end}, ...]


class RerenderRequest(BaseModel):
    ass_content: str


# ─── Project Lifecycle ────────────────────────────────────────

@router.post("/projects")
async def create_project(
    background_tasks: BackgroundTasks,
    url: str = Form(None),
    file: UploadFile = File(None),
    genre: str = Form("business"),
):
    """
    Unified project creation. Accepts either a URL or file upload + genre.
    Starts Phase 1 + 2 as background tasks.
    Returns project_id immediately.
    """
    import uuid
    from pipeline.job_manager import create_job

    if not url and not file:
        raise HTTPException(status_code=400, detail="Provide either a URL or a file")

    source_type = "url" if url else "upload"
    source_value = url if url else file.filename

    # Create job
    job = create_job(source_type, source_value, {"genre": genre})
    project_id = job["id"]
    project_dir = os.path.join(PROJECTS_DIR, project_id)
    os.makedirs(project_dir, exist_ok=True)

    # Save uploaded file if present
    file_path = None
    if file:
        raw_dir = os.path.join(project_dir, "raw")
        os.makedirs(raw_dir, exist_ok=True)
        file_path = os.path.join(raw_dir, file.filename)
        with open(file_path, "wb") as f:
            content = await file.read()
            f.write(content)

    # Save project metadata
    meta = {
        "project_id": project_id,
        "source_type": source_type,
        "source_value": source_value,
        "genre": genre,
        "status": "transcribing",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    with open(os.path.join(project_dir, "meta.json"), "w") as f:
        json.dump(meta, f, indent=2)

    # Add to history
    _add_to_history(project_id, meta)

    # Start Phase 1 pipeline as background task
    from pipeline.processor import run_pipeline

    pipeline_source = url if source_type == "url" else file_path
    background_tasks.add_task(
        run_pipeline,
        project_id,
        source_type,
        pipeline_source,
        {"genre": genre},
    )

    logger.info(f"Project created: {project_id} ({source_type}: {source_value})")

    return {"project_id": project_id, "status": "transcribing"}


@router.get("/projects/{project_id}")
async def get_project(project_id: str):
    """Get project status and metadata."""
    from pipeline.job_manager import get_job

    project_dir = os.path.join(PROJECTS_DIR, project_id)
    meta_path = os.path.join(project_dir, "meta.json")

    # Try meta.json first
    if os.path.exists(meta_path):
        with open(meta_path, "r") as f:
            meta = json.load(f)
    else:
        meta = {}

    # Enrich with job state
    job = get_job(project_id)
    if job:
        meta.update({
            "status": job.get("status", meta.get("status")),
            "stage": job.get("stage"),
            "stage_label": job.get("stage_label"),
            "progress": job.get("progress", 0),
            "error": job.get("error"),
        })
    elif not meta:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")

    return meta


# ─── WebSocket Progress ──────────────────────────────────────

@router.websocket("/ws/project/{project_id}")
async def project_progress_ws(websocket: WebSocket, project_id: str):
    """
    WebSocket endpoint for live progress updates.
    Dashboard connects here immediately on Screen 2 mount.
    """
    await websocket.accept()
    queue = get_progress_queue(project_id)

    try:
        while True:
            try:
                # Wait for event with timeout to allow ping/pong
                event = await asyncio.wait_for(queue.get(), timeout=30.0)
                await websocket.send_json(event)

                if event.get("stage") in ("complete", "error"):
                    break
            except asyncio.TimeoutError:
                # Send keepalive ping
                await websocket.send_json({"type": "ping"})
    except Exception:
        pass
    finally:
        try:
            await websocket.close()
        except RuntimeError:
            pass  # Already closed by client


# ─── Clip Preview ─────────────────────────────────────────────

@router.get("/projects/{project_id}/clips/{clip_id}/preview")
async def get_clip_preview(project_id: str, clip_id: int):
    """
    Fast-seek preview of a clip candidate.
    Uses two-pass ffmpeg seek for speed, caches the result.
    """
    from pipeline.job_manager import get_job

    project_dir = os.path.join(PROJECTS_DIR, project_id)
    cache_dir = os.path.join(project_dir, "preview_cache")
    os.makedirs(cache_dir, exist_ok=True)
    preview_path = os.path.join(cache_dir, f"clip_{clip_id}_preview.mp4")

    # Return cached preview if exists
    if os.path.exists(preview_path):
        return FileResponse(preview_path, media_type="video/mp4")

    # Find clips data
    clips_path = os.path.join(project_dir, "clips.json")
    job = get_job(project_id)
    if job and job.get("clips_result"):
        clips_path = job["clips_result"]

    if not os.path.exists(clips_path):
        raise HTTPException(status_code=404, detail="No clip candidates found")

    with open(clips_path, "r") as f:
        clips = json.load(f)

    clip = next((c for c in clips if c.get("rank") == clip_id), None)
    if not clip:
        raise HTTPException(status_code=404, detail=f"Clip {clip_id} not found")

    # Find source video
    video_path = _find_project_video(project_dir)
    if not video_path:
        raise HTTPException(status_code=404, detail="Source video not found")

    # Generate preview with fast two-pass seek
    start = clip.get("start", 0)
    end = clip.get("end", start + 60)
    cmd = [
        "ffmpeg",
        "-ss", str(max(0, start - 0.5)),
        "-i", video_path,
        "-ss", "0.5",
        "-t", str(end - start),
        "-c:v", "libx264",
        "-crf", "28",
        "-preset", "ultrafast",
        "-vf", "scale=540:-2",
        "-c:a", "aac",
        "-b:a", "96k",
        preview_path,
        "-y",
    ]
    subprocess.run(cmd, capture_output=True)

    if os.path.exists(preview_path):
        return FileResponse(preview_path, media_type="video/mp4")

    raise HTTPException(status_code=500, detail="Preview generation failed")


# ─── Submit Approved Clips for Processing ─────────────────────

@router.post("/projects/{project_id}/process")
async def process_approved_clips(
    project_id: str,
    request: ProjectProcessRequest,
    background_tasks: BackgroundTasks,
):
    """
    Submit approved clips for Phase 3 + 4 processing.
    Each clip includes style choice and optional trim adjustments.
    """
    from pipeline.job_manager import get_job

    project_dir = os.path.join(PROJECTS_DIR, project_id)
    if not os.path.exists(project_dir):
        raise HTTPException(status_code=404, detail=f"Project not found")

    # Save decisions
    decisions_path = os.path.join(project_dir, "decisions.json")
    with open(decisions_path, "w") as f:
        json.dump(request.clips, f, indent=2)

    # Update meta
    meta_path = os.path.join(project_dir, "meta.json")
    if os.path.exists(meta_path):
        with open(meta_path, "r") as f:
            meta = json.load(f)
        meta["status"] = "processing"
        meta["approved_count"] = len(request.clips)
        with open(meta_path, "w") as f:
            json.dump(meta, f, indent=2)

    background_tasks.add_task(
        _run_full_processing, project_id, request.clips
    )

    return {
        "message": f"Processing {len(request.clips)} clips",
        "project_id": project_id,
    }


def _run_full_processing(project_id: str, approved_clips: list):
    """Background task: run Phase 3 then Phase 4 for each approved clip."""
    from pipeline.job_manager import get_job, update_progress, fail_job
    from pipeline.video_processor import process_all_clips
    from pipeline.caption_renderer import run_phase_4_batch

    try:
        project_dir = os.path.join(PROJECTS_DIR, project_id)

        # Load clips data
        clips_path = os.path.join(project_dir, "clips.json")
        job = get_job(project_id)
        if job and job.get("clips_result"):
            clips_path = job["clips_result"]
        with open(clips_path, "r") as f:
            all_clips = json.load(f)

        # Filter to approved
        approved_ids = {c["clip_id"] for c in approved_clips}
        candidates = [c for c in all_clips if c.get("rank") in approved_ids]

        # Build style map from decisions
        style_map = {c["clip_id"]: c.get("style", "hormozi") for c in approved_clips}

        # Load transcript
        transcript_path = None
        if job:
            transcript_path = job.get("result")
        if not transcript_path:
            transcript_path = os.path.join(project_dir, "transcript.json")
        with open(transcript_path, "r") as f:
            transcript = json.load(f)

        # Phase 3: Video processing
        push_progress(project_id, {
            "stage": "phase3", "percent": 10,
            "message": "Starting video processing...",
        })

        jump_cut_settings = {"enabled": True, "max_pause_ms": 300, "remove_fillers": True}
        p3_results = process_all_clips(
            candidates=candidates,
            video_path=_find_project_video(project_dir),
            transcript_words=transcript.get("words", []),
            output_dir=project_dir,
            jump_cut_settings=jump_cut_settings,
        )

        # Save Phase 3 results
        p3_path = os.path.join(project_dir, "processed_clips.json")
        with open(p3_path, "w") as f:
            clean = [{k: v for k, v in r.items() if k != "face_positions"} for r in p3_results]
            json.dump(clean, f, indent=2)

        # Phase 4: Caption rendering (use per-clip style from decisions)
        push_progress(project_id, {
            "stage": "phase4", "percent": 70,
            "message": "Rendering captions...",
        })

        # Default style for batch (individual styles handled by run_phase_4_batch)
        p4_results = run_phase_4_batch(
            clips=p3_results,
            caption_style="hormozi",  # fallback
            output_dir=project_dir,
        )

        # Save Phase 4 results
        p4_path = os.path.join(project_dir, "captioned_clips.json")
        with open(p4_path, "w") as f:
            clean = [{k: v for k, v in r.items() if k != "face_positions"} for r in p4_results]
            json.dump(clean, f, indent=2)

        # Update meta
        meta_path = os.path.join(project_dir, "meta.json")
        if os.path.exists(meta_path):
            with open(meta_path, "r") as f:
                meta = json.load(f)
            meta["status"] = "export_ready"
            meta["completed_at"] = datetime.now(timezone.utc).isoformat()
            with open(meta_path, "w") as f:
                json.dump(meta, f, indent=2)
            _update_history(project_id, meta)

        push_progress(project_id, {
            "stage": "complete", "percent": 100,
            "redirect": "/export",
        })

        logger.info(f"Project {project_id}: all processing complete")

    except Exception as e:
        logger.error(f"Project {project_id} processing failed: {e}")
        push_progress(project_id, {
            "stage": "error", "message": str(e),
        })


@router.websocket("/ws/project/{project_id}/processing")
async def processing_progress_ws(websocket: WebSocket, project_id: str):
    """WebSocket for per-clip processing progress (Screen 4)."""
    await websocket.accept()
    queue = get_progress_queue(project_id)

    try:
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=30.0)
                await websocket.send_json(event)
                if event.get("stage") in ("complete", "error"):
                    break
            except asyncio.TimeoutError:
                await websocket.send_json({"type": "ping"})
    except Exception:
        pass
    finally:
        try:
            await websocket.close()
        except RuntimeError:
            pass  # Already closed by client


# ─── Export / Download ────────────────────────────────────────

@router.get("/projects/{project_id}/exports")
async def list_exports(project_id: str):
    """List all finished clips available for download."""
    project_dir = os.path.join(PROJECTS_DIR, project_id)
    clips_dir = os.path.join(project_dir, "clips")

    if not os.path.exists(clips_dir):
        raise HTTPException(status_code=404, detail="No exports found")

    exports = []
    for f in sorted(os.listdir(clips_dir)):
        if f.endswith("_final.mp4"):
            clip_path = os.path.join(clips_dir, f)
            size_mb = os.path.getsize(clip_path) / (1024 * 1024)
            exports.append({
                "filename": f,
                "path": clip_path,
                "size_mb": round(size_mb, 1),
            })

    # Load captioned data for metadata
    captioned_path = os.path.join(project_dir, "captioned_clips.json")
    clip_meta = []
    if os.path.exists(captioned_path):
        with open(captioned_path, "r") as f:
            clip_meta = json.load(f)

    return {
        "project_id": project_id,
        "exports": exports,
        "clip_metadata": clip_meta,
    }


@router.get("/projects/{project_id}/exports/{clip_id}")
async def download_clip(project_id: str, clip_id: int):
    """Download a single finished clip."""
    project_dir = os.path.join(PROJECTS_DIR, project_id)
    clip_path = os.path.join(project_dir, "clips", f"clip_{clip_id}_final.mp4")

    if not os.path.exists(clip_path):
        raise HTTPException(status_code=404, detail=f"Clip {clip_id} not found")

    # Generate friendly filename
    filename = _get_download_filename(project_id, clip_id)
    return FileResponse(clip_path, media_type="video/mp4", filename=filename)


@router.get("/projects/{project_id}/exports/all.zip")
async def download_all_clips(project_id: str):
    """Download all finished clips as a zip file."""
    project_dir = os.path.join(PROJECTS_DIR, project_id)
    clips_dir = os.path.join(project_dir, "clips")

    if not os.path.exists(clips_dir):
        raise HTTPException(status_code=404, detail="No exports found")

    # Create zip in memory
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(os.listdir(clips_dir)):
            if f.endswith("_final.mp4"):
                clip_path = os.path.join(clips_dir, f)
                # Use friendly name in zip
                clip_id = int(f.split("_")[1])
                friendly = _get_download_filename(project_id, clip_id)
                zf.write(clip_path, friendly)

    buffer.seek(0)
    return StreamingResponse(
        buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename=clips_{project_id}.zip"},
    )


# ─── ASS Re-render ────────────────────────────────────────────

@router.get("/projects/{project_id}/clips/{clip_id}/ass")
async def get_ass_content(project_id: str, clip_id: int):
    """Get the .ass subtitle file content for editing."""
    project_dir = os.path.join(PROJECTS_DIR, project_id)
    ass_path = os.path.join(project_dir, "clips", f"clip_{clip_id}.ass")

    if not os.path.exists(ass_path):
        raise HTTPException(status_code=404, detail=f"ASS file not found for clip {clip_id}")

    with open(ass_path, "r", encoding="utf-8") as f:
        return {"clip_id": clip_id, "ass_content": f.read()}


@router.post("/projects/{project_id}/clips/{clip_id}/rerender")
async def rerender_captions(project_id: str, clip_id: int, request: RerenderRequest):
    """
    Re-burn captions from edited ASS content.
    Only re-runs the ffmpeg burn step — fast (~15–20s).
    """
    project_dir = os.path.join(PROJECTS_DIR, project_id)
    clips_dir = os.path.join(project_dir, "clips")

    processed_path = os.path.join(clips_dir, f"clip_{clip_id}_processed.mp4")
    final_path = os.path.join(clips_dir, f"clip_{clip_id}_final.mp4")

    if not os.path.exists(processed_path):
        raise HTTPException(
            status_code=404,
            detail="Processed clip not found — may have been cleaned up",
        )

    # Write new ASS content
    ass_path = os.path.join(clips_dir, f"clip_{clip_id}.ass")
    with open(ass_path, "w", encoding="utf-8") as f:
        f.write(request.ass_content)

    # Re-burn captions
    escaped_ass = ass_path.replace("\\", "/").replace(":", "\\:")
    cmd = [
        "ffmpeg",
        "-i", processed_path,
        "-vf", f"ass='{escaped_ass}'",
        "-c:v", "libx264",
        "-crf", "18",
        "-preset", "fast",
        "-c:a", "copy",
        "-movflags", "+faststart",
        final_path,
        "-y",
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise HTTPException(status_code=500, detail=f"Re-render failed: {result.stderr[-300:]}")

    return {
        "message": f"Clip {clip_id} re-rendered successfully",
        "updated_path": final_path,
    }


# ─── Project History ──────────────────────────────────────────

HISTORY_PATH = os.path.join(PROJECTS_DIR, "history.json")


@router.get("/history")
async def get_history():
    """Get project history sorted by date."""
    if not os.path.exists(HISTORY_PATH):
        return {"projects": []}

    with open(HISTORY_PATH, "r") as f:
        history = json.load(f)

    return {"projects": history}


def _add_to_history(project_id: str, meta: dict):
    """Add a project to history."""
    history = []
    if os.path.exists(HISTORY_PATH):
        with open(HISTORY_PATH, "r") as f:
            history = json.load(f)

    history.insert(0, {
        "project_id": project_id,
        "source": meta.get("source_value", ""),
        "genre": meta.get("genre", ""),
        "status": meta.get("status", ""),
        "created_at": meta.get("created_at", ""),
    })

    with open(HISTORY_PATH, "w") as f:
        json.dump(history, f, indent=2)


def _update_history(project_id: str, meta: dict):
    """Update a project in history."""
    if not os.path.exists(HISTORY_PATH):
        return

    with open(HISTORY_PATH, "r") as f:
        history = json.load(f)

    for entry in history:
        if entry["project_id"] == project_id:
            entry["status"] = meta.get("status", entry["status"])
            break

    with open(HISTORY_PATH, "w") as f:
        json.dump(history, f, indent=2)


# ─── Helpers ──────────────────────────────────────────────────

def _find_project_video(project_dir: str) -> str:
    """Find the source video in a project directory."""
    raw_dir = os.path.join(project_dir, "raw")
    if os.path.exists(raw_dir):
        for f in os.listdir(raw_dir):
            if any(f.endswith(ext) for ext in (".mp4", ".mov", ".mkv", ".avi", ".webm")):
                return os.path.join(raw_dir, f)
    for f in os.listdir(project_dir):
        if any(f.endswith(ext) for ext in (".mp4", ".mov", ".mkv", ".avi", ".webm")):
            return os.path.join(project_dir, f)
    return ""


def _get_download_filename(project_id: str, clip_id: int) -> str:
    """Generate a friendly download filename."""
    project_dir = os.path.join(PROJECTS_DIR, project_id)
    date = datetime.now().strftime("%Y-%m-%d")

    # Try to get title from captioned clips
    captioned_path = os.path.join(project_dir, "captioned_clips.json")
    if os.path.exists(captioned_path):
        with open(captioned_path, "r") as f:
            clips = json.load(f)
        clip = next((c for c in clips if c.get("rank") == clip_id), None)
        if clip and clip.get("suggested_title"):
            import re
            title = clip["suggested_title"].lower()
            title = re.sub(r"[^a-z0-9]+", "-", title).strip("-")
            style = clip.get("caption_style", "default")
            return f"{date}_{title}_{style}.mp4"

    return f"{date}_clip_{clip_id}.mp4"
