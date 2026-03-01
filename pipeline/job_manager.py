"""
Job Manager — In-memory job state tracking for pipeline runs.
Handles job creation, progress updates, and status queries.
"""

import uuid
import time
from datetime import datetime, timezone
from typing import Optional


# In-memory job store (sufficient for local single-user tool)
_jobs: dict = {}


def create_job(source_type: str, source_value: str, settings: Optional[dict] = None) -> dict:
    """Create a new processing job and return its metadata."""
    job_id = str(uuid.uuid4())[:8]  # short IDs for convenience
    job = {
        "id": job_id,
        "source_type": source_type,      # "url" or "upload"
        "source_value": source_value,     # URL string or filename
        "settings": settings or {},
        "status": "pending",
        "stage": None,
        "stage_label": None,
        "progress": 0.0,                 # 0.0 - 1.0 overall
        "stage_progress": 0.0,           # 0.0 - 1.0 within stage
        "created_at": datetime.now(timezone.utc).isoformat(),
        "started_at": None,
        "completed_at": None,
        "error": None,
        "result": None,                  # path to transcript JSON on completion
    }
    _jobs[job_id] = job
    return job


def get_job(job_id: str) -> Optional[dict]:
    """Retrieve a job by ID."""
    return _jobs.get(job_id)


def _push_to_websocket(job_id: str, event: dict):
    """Bridge: push progress event to WebSocket queue for live frontend updates."""
    try:
        from pipeline.dashboard_routes import push_progress
        push_progress(job_id, event)
    except Exception:
        pass  # WebSocket queue not available — fallback polling still works


def push_log(job_id: str, message: str, level: str = "info"):
    """Push a detailed log line to the frontend via WebSocket."""
    ts = datetime.now().strftime("%H:%M:%S.") + f"{datetime.now().microsecond // 1000:03d}"
    _push_to_websocket(job_id, {
        "type": "log",
        "ts": ts,
        "level": level,
        "log": message,
    })


def update_progress(
    job_id: str,
    stage: str,
    stage_label: str,
    overall_progress: float,
    stage_progress: float = 0.0,
):
    """Update the progress of a running job."""
    job = _jobs.get(job_id)
    if not job:
        return

    job["status"] = "processing"
    job["stage"] = stage
    job["stage_label"] = stage_label
    job["progress"] = min(overall_progress, 1.0)
    job["stage_progress"] = min(stage_progress, 1.0)

    if job["started_at"] is None:
        job["started_at"] = datetime.now(timezone.utc).isoformat()

    # Push to WebSocket for live frontend updates
    _push_to_websocket(job_id, {
        "stage": stage,
        "percent": int(min(overall_progress, 1.0) * 100),
        "message": stage_label,
    })


def complete_job(job_id: str, transcript_path: str):
    """Mark a job as successfully completed."""
    job = _jobs.get(job_id)
    if not job:
        return

    job["status"] = "completed"
    job["stage"] = "done"
    job["stage_label"] = "Processing complete"
    job["progress"] = 1.0
    job["stage_progress"] = 1.0
    job["completed_at"] = datetime.now(timezone.utc).isoformat()
    job["result"] = transcript_path

    _push_to_websocket(job_id, {
        "stage": "complete",
        "percent": 100,
        "message": "Processing complete",
    })


def fail_job(job_id: str, error: str):
    """Mark a job as failed with an error message."""
    job = _jobs.get(job_id)
    if not job:
        return

    job["status"] = "failed"
    job["error"] = error
    job["completed_at"] = datetime.now(timezone.utc).isoformat()

    _push_to_websocket(job_id, {
        "stage": "error",
        "message": error,
    })


def list_jobs() -> list:
    """Return all jobs, most recent first."""
    return sorted(_jobs.values(), key=lambda j: j["created_at"], reverse=True)
