# FIXPIPELINE.md — YouTube Pipeline Failure Diagnosis

## Summary

When you paste a YouTube link and click "Start Processing", the project is created but **the processing pipeline never starts**. The frontend sits on the "Transcribing..." page forever, polling endlessly with no progress. There are **3 distinct bugs** causing this, all of which must be fixed together.

---

## Bug #1: Pipeline Never Starts (THE ROOT CAUSE)

### What happens
The frontend calls `POST /api/projects` (InputPage.jsx:55). This hits the `create_project` endpoint in `dashboard_routes.py:60-113`. That function:

1. Creates a job via `create_job()`
2. Saves project metadata to `meta.json`
3. Returns `{"project_id": "...", "status": "transcribing"}`
4. **Never calls `run_pipeline()`**

The pipeline function (`processor.py:run_pipeline`) is never invoked. No download, no transcription, no anything.

### Where exactly
**File:** `pipeline/dashboard_routes.py`, lines 60-113 (`create_project` function)

The function is missing a `background_tasks.add_task(run_pipeline, ...)` call. Compare this to the *other* project creation endpoint in `main.py:141-168` (`process_url`), which correctly calls:

```python
background_tasks.add_task(
    run_pipeline,
    job["id"],
    "url",
    request.url,
    settings,
)
```

The `dashboard_routes.py` version just... doesn't do this.

### Evidence from backend.log
```
21:12:01 │ pipeline.dashboard_routes │ INFO │ Project created: 5da4a587 (url: https://www.youtube.com/watch?v=...)
INFO:     127.0.0.1:54335 - "POST /api/projects HTTP/1.1" 200 OK
```
Notice: **No download log, no pipeline log, nothing after project creation.** Just endless polling:
```
INFO:     127.0.0.1:54359 - "GET /api/projects/5da4a587 HTTP/1.1" 200 OK
INFO:     127.0.0.1:54359 - "GET /api/projects/5da4a587 HTTP/1.1" 200 OK
(repeats forever...)
```

### How to fix
In `dashboard_routes.py`, inside `create_project`, add the pipeline invocation after saving metadata:

```python
# After the meta.json save and _add_to_history call, add:
from pipeline.processor import run_pipeline

source_val = url if url else file_path  # file_path is the saved upload path
background_tasks.add_task(
    run_pipeline,
    project_id,
    source_type,
    source_val,
    {"genre": genre},
)
```

For file uploads, `source_val` must be the path where the file was saved (`file_path`), not `file.filename`.

---

## Bug #2: WebSocket Connection Rejected (403 Forbidden)

### What happens
Even if the pipeline were running, the frontend would never receive live progress updates because the WebSocket connection is rejected immediately.

### Where exactly
**Backend log line 20:**
```
INFO:     ('127.0.0.1', 54340) - "WebSocket /ws/project/5da4a587" 403
INFO:     connection rejected (403 Forbidden)
```

**Two sub-issues cause this:**

**Sub-issue A: Route path mismatch (the real 403 cause)**

The WebSocket routes are defined in `dashboard_routes.py` which uses `APIRouter(prefix="/api")`. So the actual registered routes are:
- `/api/ws/project/{project_id}` (for Phase 1 progress)
- `/api/ws/project/{project_id}/processing` (for Phase 3+4 progress)

But the frontend connects to paths WITHOUT the `/api` prefix:
- `TranscribingPage.jsx:25`: `ws://127.0.0.1:8000/ws/project/${projectId}`
- `ProcessingPage.jsx:29`: `ws://127.0.0.1:8000/ws/project/${projectId}/processing`

Starlette returns 403 when a WebSocket upgrade is attempted on a route that doesn't exist.

**Sub-issue B: CORS misconfiguration**

`main.py` had `allow_credentials=True` with `allow_origins=["*"]`. This combination is invalid per the CORS spec and causes Starlette to use stricter origin validation. Also, the `WebSocketCORSMiddleware` was an unnecessary workaround.

### How it was fixed
1. Fixed frontend WebSocket URLs to include `/api` prefix
2. Removed `WebSocketCORSMiddleware` (unnecessary — Starlette CORSMiddleware already skips WebSocket requests)
3. Changed `allow_credentials=True` to `allow_credentials=False` (correct for wildcard origins)

---

## Bug #3: Progress Systems Are Disconnected

### What happens
There are **two completely separate progress reporting systems** that don't talk to each other:

1. **`job_manager.update_progress()`** — Updates an in-memory dict. Used by `processor.py` (Phase 1 pipeline). The frontend can only see this via `GET /api/projects/{id}` polling.

2. **`dashboard_routes.push_progress()`** — Pushes events to an `asyncio.Queue`. The WebSocket reads from this queue. Used by `_run_full_processing()` (Phase 3+4) but **NOT by Phase 1**.

So even when all other bugs are fixed:
- Phase 1 (`run_pipeline`) updates `job_manager` but **never pushes to the WebSocket queue**
- The WebSocket listener in `TranscribingPage.jsx` waits for events that never come
- The fallback polling (every 5 seconds) would eventually catch the "completed" status, but only after Phase 1 finishes — there would be **no live progress** during download/transcription

### Where exactly
- `processor.py` calls `update_progress()` from `job_manager.py` (lines 73-81, 110-113, etc.)
- `dashboard_routes.py` WebSocket reads from `_progress_queues` via `push_progress()` (line 39-45)
- These are completely different data stores

### How to fix
Bridge the two systems. After each `update_progress()` call in `processor.py`, also push to the WebSocket queue:

```python
# In processor.py, add at the top:
from pipeline.dashboard_routes import push_progress

# Then after each update_progress() call, add:
push_progress(job_id, {
    "stage": stage_id,
    "percent": int(overall_progress * 100),
    "message": stage_label,
    "steps": [...]  # build step list for frontend
})
```

Or, modify `job_manager.update_progress()` to also call `push_progress()` automatically:

```python
# In job_manager.py
def update_progress(job_id, stage, stage_label, overall_progress, stage_progress=0.0):
    # ... existing code ...

    # Also push to WebSocket queue
    try:
        from pipeline.dashboard_routes import push_progress
        push_progress(job_id, {
            "stage": stage,
            "percent": int(overall_progress * 100),
            "message": stage_label,
        })
    except ImportError:
        pass
```

And push a "complete" event when the job finishes:

```python
# In job_manager.py complete_job():
def complete_job(job_id, transcript_path):
    # ... existing code ...
    try:
        from pipeline.dashboard_routes import push_progress
        push_progress(job_id, {"stage": "complete", "percent": 100})
    except ImportError:
        pass
```

---

## Root Cause Architecture Diagram

```
WHAT THE FRONTEND DOES:
  InputPage.jsx ──POST /api/projects──> dashboard_routes.py::create_project
                                         ├── Creates job         ✓
                                         ├── Saves meta.json     ✓
                                         ├── Returns project_id  ✓
                                         └── Starts pipeline     ✗ MISSING

  TranscribingPage.jsx ──WebSocket──> dashboard_routes.py::project_progress_ws
                                       └── Reads from _progress_queues
                                           └── EMPTY (nothing pushes here during Phase 1)

  TranscribingPage.jsx ──GET /api/projects/{id}──> dashboard_routes.py::get_project
                                                    └── Returns meta.json (status: "transcribing" forever)


WHAT SHOULD HAPPEN:
  create_project ──background_task──> processor.py::run_pipeline
                                       ├── download_video()      → push_progress(download)
                                       ├── extract_audio()       → push_progress(extract)
                                       ├── transcribe_audio()    → push_progress(transcribe)
                                       ├── postprocess()         → push_progress(postprocess)
                                       └── complete_job()        → push_progress(complete)
                                                                    ↓
                                                            WebSocket → Frontend
```

---

## The Duplicate API Problem

There are **two sets of endpoints** that do similar things but work differently:

| Action | `main.py` endpoint | `dashboard_routes.py` endpoint | Frontend uses |
|--------|-------------------|-------------------------------|--------------|
| Create project from URL | `POST /api/process/url` (starts pipeline) | `POST /api/projects` (does NOT start pipeline) | `/api/projects` |
| Create project from file | `POST /api/process/upload` (starts pipeline) | `POST /api/projects` (does NOT start pipeline) | `/api/projects` |
| Get status | `GET /api/status/{job_id}` | `GET /api/projects/{project_id}` | `/api/projects/{id}` |

The frontend was built to use the `dashboard_routes.py` endpoints, but the pipeline-starting logic only exists in the `main.py` endpoints. This is the fundamental disconnect.

---

## Fix Priority

| Priority | Bug | Impact | Effort |
|----------|-----|--------|--------|
| P0 | #1 — Pipeline never starts | Nothing works at all | Add ~10 lines to `dashboard_routes.py` |
| P1 | #2 — WebSocket 403 | No live progress (fallback polling works but no real-time) | Fix middleware or origin handling |
| P2 | #3 — Progress systems disconnected | WebSocket never receives Phase 1 events | Bridge `update_progress` → `push_progress` |

---

## Quick Verification After Fix

1. Start the backend: `python -m uvicorn main:app --reload`
2. Paste any YouTube URL and click "Start Processing"
3. Check backend.log — you should see:
   - `"Starting download: https://youtube.com/..."`
   - `"Download complete: ..."`
   - `"Raw transcript saved: ..."`
   - `"Pipeline complete for job ..."`
4. The WebSocket should push progress events (check browser DevTools → Network → WS)
5. The TranscribingPage should show real-time progress and auto-navigate to `/review` on completion
