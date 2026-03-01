# PHASE 5 — DASHBOARD UI
### The Control Room That Connects All Phases

---

## What This Phase Does

Phase 5 is the interface where the human operates the entire tool. It is not an afterthought — it is the product. Everything from Phase 1 through Phase 4 runs invisibly in the background. What the user actually sees, touches, and makes decisions in is the dashboard.

The dashboard orchestrates the full pipeline:

1. **Input** — paste a URL or upload a file
2. **Transcription progress** — live feedback while Phase 1 runs
3. **Clip review** — browse AI-selected candidates, approve or reject each one
4. **Caption configuration** — choose style per clip, preview timing, toggle options
5. **Processing queue** — watch Phase 3 and 4 run per approved clip
6. **Export** — download finished clips with proper filenames

The design principle throughout: the user should never have to think about what's running under the hood. Every technical process has a clear, human-readable status. Every decision point is presented as a simple choice, not a configuration form.

---

## Tech Stack

```
Frontend:  React (Vite)
Backend:   FastAPI (Python)
Comms:     REST for actions, WebSockets for live progress updates
Storage:   Local filesystem (no database needed for a local tool)
Styling:   Tailwind CSS
State:     React Context + useReducer (no Redux — overkill for a local tool)
```

Everything runs locally. No cloud. No accounts. No upload limits. The FastAPI backend wraps all the Python processing from Phases 1–4 and exposes it as a local API. The React frontend is the UI layer.

```
User → Browser (localhost:5173)
         ↕ REST + WebSockets
      FastAPI (localhost:8000)
         ↕ subprocess calls
      Phases 1–4 (Python scripts)
         ↕ filesystem
      /projects/{id}/ (output files)
```

---

## Screen Architecture

The dashboard has five screens that the user moves through linearly for each project run. Once a project is complete they can return to any clip from a project history list.

```
[Screen 1: Input]
     ↓
[Screen 2: Transcribing]  ← live progress, no interaction
     ↓
[Screen 3: Clip Review]   ← the most important screen
     ↓
[Screen 4: Processing]    ← live progress per clip
     ↓
[Screen 5: Export]        ← download + file management
```

Plus a persistent sidebar: **Project History** (all past runs accessible by name).

---

## Screen 1 — Input

The entry point. Clean, minimal. One job: get the source material.

### Layout

```
┌────────────────────────────────────────────────────────────┐
│                                                            │
│   CLIPR                              [Project History ›]   │
│                                                            │
│   ─────────────────────────────────────────────────────   │
│                                                            │
│   Drop a video or paste a URL                              │
│                                                            │
│   ┌──────────────────────────────────────────────────┐    │
│   │                                                  │    │
│   │      [↑]  Drop MP4, MOV, MKV here               │    │
│   │           or click to browse                     │    │
│   │                                                  │    │
│   └──────────────────────────────────────────────────┘    │
│                                                            │
│          ─────────── or ───────────                        │
│                                                            │
│   ┌──────────────────────────────────────────────────┐    │
│   │  https://youtube.com/watch?v=...                 │    │
│   └──────────────────────────────────────────────────┘    │
│                                                            │
│   Genre ▾                                                  │
│   ○ Business & Entrepreneurship                            │
│   ○ Self-Improvement & Mindset                             │
│   ○ Finance & Investing                                    │
│   ○ Health & Fitness                                       │
│   ○ Relationships & Dating                                 │
│   ○ True Crime & Storytelling                              │
│                                                            │
│   [ Start Processing ]                                     │
│                                                            │
└────────────────────────────────────────────────────────────┘
```

### Behaviour

- File drop triggers validation (format check, rough size estimate)
- URL field auto-detects platform (YouTube, Spotify, etc.) and shows a small badge
- Genre selection defaults to Business if not changed — it persists between sessions
- `Start Processing` is disabled until either a file or URL is provided AND a genre is selected
- On submit, the backend creates a `project_id` (UUID), initialises the project folder, and transitions to Screen 2

### API Call

```javascript
async function startProject(input, genre) {
  const formData = new FormData();
  
  if (input.type === 'file') {
    formData.append('file', input.file);
  } else {
    formData.append('url', input.url);
  }
  formData.append('genre', genre);
  
  const response = await fetch('/api/projects', {
    method: 'POST',
    body: formData,
  });
  
  const { project_id } = await response.json();
  navigate(`/project/${project_id}/transcribing`);
}
```

---

## Screen 2 — Transcribing

The user can't do anything here. Phase 1 is running. The screen keeps them informed without being boring.

### Layout

```
┌────────────────────────────────────────────────────────────┐
│                                                            │
│   ← Back          Joe Rogan #2134 — Alex Hormozi          │
│                                                            │
│   ─────────────────────────────────────────────────────   │
│                                                            │
│                   Transcribing...                          │
│                                                            │
│   ████████████████████░░░░░░░░░░░░░░   58%                 │
│                                                            │
│   Downloading audio          ✓  12s                        │
│   Extracting audio           ✓   4s                        │
│   Pre-processing             ✓   2s                        │
│   Transcribing with Whisper  ↻   running                   │
│   AI clip selection          ·   waiting                   │
│                                                            │
│   Estimated time remaining: ~14 minutes                    │
│                                                            │
│   Source: 2h 34m podcast                                   │
│   Engine: faster-whisper large-v3-turbo (CPU)              │
│                                                            │
└────────────────────────────────────────────────────────────┘
```

### Progress via WebSocket

The backend streams progress events over a WebSocket. The frontend subscribes immediately on screen mount:

```javascript
function useProjectProgress(projectId) {
  const [progress, setProgress] = useState({
    stage: 'initialising',
    percent: 0,
    steps: [],
    eta_seconds: null,
  });
  
  useEffect(() => {
    const ws = new WebSocket(`ws://localhost:8000/ws/project/${projectId}`);
    
    ws.onmessage = (event) => {
      const update = JSON.parse(event.data);
      setProgress(update);
    };
    
    ws.onclose = () => {
      // Transcription done — wait for redirect signal
    };
    
    return () => ws.close();
  }, [projectId]);
  
  return progress;
}
```

**Backend WebSocket events:**

```python
# FastAPI endpoint
@app.websocket("/ws/project/{project_id}")
async def project_progress(websocket: WebSocket, project_id: str):
    await websocket.accept()
    
    # Events are pushed by the Phase 1 runner via asyncio.Queue
    queue = get_progress_queue(project_id)
    
    while True:
        event = await queue.get()
        await websocket.send_json(event)
        
        if event.get('stage') == 'complete':
            break
    
    await websocket.close()
```

**Event structure:**

```json
{
  "stage": "transcribing",
  "percent": 58,
  "steps": [
    { "name": "Downloading audio",     "status": "done",    "seconds": 12 },
    { "name": "Extracting audio",      "status": "done",    "seconds": 4  },
    { "name": "Pre-processing",        "status": "done",    "seconds": 2  },
    { "name": "Transcribing",          "status": "running", "seconds": null },
    { "name": "AI clip selection",     "status": "waiting", "seconds": null }
  ],
  "eta_seconds": 840,
  "source_duration": 9240,
  "engine": "faster-whisper large-v3-turbo (CPU)"
}
```

When Phase 1 and Phase 2 both complete, the backend sends a `{ "stage": "complete", "redirect": "/review" }` event and the frontend navigates automatically to Screen 3.

---

## Screen 3 — Clip Review

**This is the most important screen in the entire tool.**

The AI has found 5–15 candidates. The user reviews each one, approves or rejects it, adjusts the caption style, and optionally trims the start/end. Then they send approved clips to processing.

### Overall Layout

```
┌─────────────────────────────────────────────────────────────────┐
│  ← Back   Joe Rogan #2134 — Alex Hormozi         [Send to Processing ›]  │
│  ─────────────────────────────────────────────────────────────  │
│                                                                 │
│  [All 12]  [★ Strong 5]  [✓ Approved 0]  [✗ Rejected 0]        │
│                                                                 │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  Clip 1  ·  Score: 88  ·  STRONG  ·  1:04  ·  Business   │  │
│  │                                                           │  │
│  │  ▶ [Video Preview Thumbnail]                              │  │
│  │                                                           │  │
│  │  Hook: "Nobody talks about the real reason businesses…"   │  │
│  │  Suggested title: "The Real Reason 90% Fail"              │  │
│  │                                                           │  │
│  │  Hook 9/10 · Narrative 8/10 · Standalone 10/10           │  │
│  │                                                           │  │
│  │  Caption Style:                                           │  │
│  │  [Hormozi] [Podcast] [Karaoke] [Reaction] [Cinematic]    │  │
│  │                                                           │  │
│  │  [ ✗ Reject ]                     [ ✓ Approve ]          │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                 │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  Clip 2  ·  Score: 74  ·  DECENT  ·  0:47  ·  Business   │  │
│  │  ...                                                      │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Clip Card — Detailed Breakdown

Each clip card has several interactive zones:

**1. The Preview Player**

A scrubbing preview that lets the user watch the exact clip that will be cut. Clicking the thumbnail opens an inline player:

```javascript
function ClipPreview({ projectId, clipId, start, end }) {
  const [playing, setPlaying] = useState(false);
  const videoRef = useRef(null);
  
  // The backend serves a pre-cut preview segment on demand
  // This is a fast seek operation, NOT a full re-encode
  const previewUrl = `/api/projects/${projectId}/clips/${clipId}/preview`;
  
  return (
    <div className="clip-preview">
      <video
        ref={videoRef}
        src={previewUrl}
        onClick={() => setPlaying(!playing)}
      />
      <div className="preview-overlay">
        <span className="duration">{formatDuration(end - start)}</span>
        {playing ? <PauseIcon /> : <PlayIcon />}
      </div>
    </div>
  );
}
```

The preview endpoint uses the two-pass seek from Phase 3 to deliver a fast-cut preview segment without fully processing the clip. This takes 3–5 seconds to generate on first request and is then cached.

**2. The Score Display**

```javascript
function ScoreBar({ label, score, weight }) {
  return (
    <div className="score-row">
      <span className="score-label">{label}</span>
      <div className="score-bar">
        <div
          className="score-fill"
          style={{ width: `${score * 10}%` }}
        />
      </div>
      <span className="score-value">{score}/10</span>
    </div>
  );
}
```

**3. Caption Style Selector**

Five buttons, one per style. The selected style is highlighted. Clicking one shows a brief animated text preview of what the captions will look like for that clip:

```javascript
const STYLE_PREVIEWS = {
  hormozi:          'NOBODY TALKS ABOUT THIS',
  podcast_subtitle: 'Nobody actually talks about the real reason...',
  karaoke:          'Nobody actually talks about the real reason...',  // with word highlight
  reaction:         'Nobody talks about this 👀',
  cinematic:        'nobody actually talks about this',
};

function CaptionStylePicker({ selected, onChange }) {
  return (
    <div className="style-picker">
      {Object.entries(STYLE_PREVIEWS).map(([style, preview]) => (
        <button
          key={style}
          className={`style-btn ${selected === style ? 'active' : ''}`}
          onClick={() => onChange(style)}
        >
          <span className="style-name">{STYLE_LABELS[style]}</span>
          <span className="style-preview">{preview}</span>
        </button>
      ))}
    </div>
  );
}
```

**4. Approve / Reject Controls**

```javascript
function ClipActions({ clipId, onApprove, onReject, approved }) {
  return (
    <div className="clip-actions">
      <button
        className={`action-btn reject ${approved === false ? 'active' : ''}`}
        onClick={() => onReject(clipId)}
      >
        ✗ Reject
      </button>
      <button
        className={`action-btn approve ${approved === true ? 'active' : ''}`}
        onClick={() => onApprove(clipId)}
      >
        ✓ Approve
      </button>
    </div>
  );
}
```

Approved clips get a green left border. Rejected clips are visually dimmed. Both remain visible and re-clickable — the user can change their mind at any time before hitting "Send to Processing."

**5. Optional: Trim Controls**

Phase 2 provided `suggested_trim_start` and `suggested_trim_end`. By default these are applied automatically. An advanced toggle exposes manual trim handles:

```javascript
function TrimControls({ start, end, trimStart, trimEnd, onChange }) {
  return (
    <div className="trim-controls">
      <label>Trim start: <input
        type="range"
        min={0} max={5} step={0.1}
        value={trimStart}
        onChange={e => onChange('start', parseFloat(e.target.value))}
      /> {trimStart.toFixed(1)}s</label>
      
      <label>Trim end: <input
        type="range"
        min={0} max={5} step={0.1}
        value={trimEnd}
        onChange={e => onChange('end', parseFloat(e.target.value))}
      /> {trimEnd.toFixed(1)}s</label>
    </div>
  );
}
```

### State Management

```javascript
const initialState = {
  clips: [],           // array of clip candidates from Phase 2
  decisions: {},       // { clipId: 'approved' | 'rejected' | null }
  styles: {},          // { clipId: 'hormozi' | 'podcast_subtitle' | ... }
  trims: {},           // { clipId: { start: 0, end: 0 } }
  filter: 'all',       // 'all' | 'strong' | 'approved' | 'rejected'
};

function clipReviewReducer(state, action) {
  switch (action.type) {
    case 'LOAD_CLIPS':
      return {
        ...state,
        clips: action.clips,
        styles: Object.fromEntries(
          action.clips.map(c => [c.rank, 'hormozi'])  // default style
        ),
        decisions: Object.fromEntries(
          action.clips.map(c => [c.rank, null])
        ),
      };
    
    case 'APPROVE_CLIP':
      return {
        ...state,
        decisions: { ...state.decisions, [action.clipId]: 'approved' }
      };
    
    case 'REJECT_CLIP':
      return {
        ...state,
        decisions: { ...state.decisions, [action.clipId]: 'rejected' }
      };
    
    case 'SET_STYLE':
      return {
        ...state,
        styles: { ...state.styles, [action.clipId]: action.style }
      };
    
    case 'SET_FILTER':
      return { ...state, filter: action.filter };
    
    default:
      return state;
  }
}
```

### Send to Processing

The "Send to Processing" button in the header is only enabled when at least one clip is approved. Clicking it submits the decisions and navigates to Screen 4:

```javascript
async function sendToProcessing(projectId, decisions, styles, trims) {
  const approved = Object.entries(decisions)
    .filter(([_, status]) => status === 'approved')
    .map(([clipId]) => ({
      clip_id: parseInt(clipId),
      style: styles[clipId],
      trim_start: trims[clipId]?.start ?? 0,
      trim_end: trims[clipId]?.end ?? 0,
    }));
  
  await fetch(`/api/projects/${projectId}/process`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ clips: approved }),
  });
  
  navigate(`/project/${projectId}/processing`);
}
```

---

## Screen 4 — Processing

Phase 3 (clip cutting + reframing) and Phase 4 (caption rendering) run here per approved clip. Progress is shown per clip, not as a single total bar.

### Layout

```
┌────────────────────────────────────────────────────────────┐
│  ← Back    Processing 3 clips                              │
│  ──────────────────────────────────────────────────────    │
│                                                            │
│  Clip 1  ·  1:04  ·  "The Real Reason 90% Fail"           │
│  ─────────────────────────────────────────────────────     │
│  [████████████████████████░░░░░░░░░░]  Cropping...  71%   │
│                                                            │
│  ✓ Cutting                  2s                             │
│  ✓ Layout detection         1s                             │
│  ✓ Face tracking            9s                             │
│  ↻ Cropping & reframing     ...                            │
│  · Audio normalisation      waiting                        │
│  · Encoding                 waiting                        │
│  · Caption rendering        waiting                        │
│                                                            │
│  Clip 2  ·  0:47  ·  "You're building the wrong thing"    │
│  ─────────────────────────────────────────────────────     │
│  [·····················]  Queued                           │
│                                                            │
│  Clip 3  ·  1:18  ·  "The $100M offer framework"          │
│  ─────────────────────────────────────────────────────     │
│  [·····················]  Queued                           │
│                                                            │
│  Processing 1 of 3 · Est. ~4 minutes remaining             │
│                                                            │
└────────────────────────────────────────────────────────────┘
```

Clips are processed one at a time to avoid saturating the CPU. The current clip shows its detailed step progress. Queued clips show a minimal waiting state.

When each clip completes, its row transforms into a success state with a green checkmark and a clickable thumbnail preview of the finished output (with captions visible).

When all clips are done, a "Go to Export" button appears.

---

## Screen 5 — Export

The finished line. All processed clips are presented as a grid. The user downloads them.

### Layout

```
┌────────────────────────────────────────────────────────────┐
│  Done! 3 clips ready                    [↓ Download All]   │
│  ──────────────────────────────────────────────────────    │
│                                                            │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐        │
│  │  [Thumbnail]│  │  [Thumbnail]│  │  [Thumbnail]│        │
│  │             │  │             │  │             │        │
│  │  1:04       │  │  0:47       │  │  1:18       │        │
│  │  Score: 88  │  │  Score: 74  │  │  Score: 81  │        │
│  │  Hormozi    │  │  Karaoke    │  │  Hormozi    │        │
│  │             │  │             │  │             │        │
│  │  [▶ Preview]│  │  [▶ Preview]│  │  [▶ Preview]│        │
│  │  [↓ Download│  │  [↓ Download│  │  [↓ Download│        │
│  └─────────────┘  └─────────────┘  └─────────────┘        │
│                                                            │
│  ─────────────────────────────────────────────────         │
│  Run summary                                               │
│  Source: Joe Rogan #2134 — Alex Hormozi (2h 34m)           │
│  Clips processed: 3 of 12 candidates                       │
│  Total output: 3m 9s of content                            │
│  Processing time: 18 minutes                               │
│                                                            │
│  [ Start a new project ]                                   │
│                                                            │
└────────────────────────────────────────────────────────────┘
```

### Download Naming

Files are renamed sensibly on download so they arrive ready to post:

```javascript
function getDownloadFilename(clip, project) {
  const title = clip.suggested_title
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-|-$/g, '');
  
  const date = new Date().toISOString().slice(0, 10);
  return `${date}_${title}_${clip.caption_style}.mp4`;
}

// Example output:
// 2025-11-14_the-real-reason-90-percent-fail_hormozi.mp4
// 2025-11-14_youre-building-the-wrong-thing_karaoke.mp4
```

"Download All" creates a zip file containing all clips named as above. The zip is assembled server-side and streamed to the browser.

### The .ass Edit Option

Each clip card has a small "Edit Captions" link. This opens the `.ass` file in a minimal inline editor — a plain `<textarea>` pre-populated with the ASS content. The user can fix typos, adjust timing, or change colours. Saving re-runs only the ffmpeg burn step (not the full pipeline) and delivers an updated clip within 15–20 seconds.

```javascript
async function reRenderCaptions(projectId, clipId, assContent) {
  const response = await fetch(
    `/api/projects/${projectId}/clips/${clipId}/rerender`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ass_content: assContent }),
    }
  );
  const { updated_path } = await response.json();
  // Update the clip thumbnail and download link
}
```

---

## Project History (Persistent Sidebar)

A collapsible panel available from any screen. Shows all past projects sorted by date. Each entry links back to its Export screen so the user can re-download clips from any previous run.

```
┌────────────────────┐
│  Project History   │
│  ──────────────    │
│  Today             │
│  · Rogan #2134     │
│    3 clips · 18m   │
│                    │
│  Yesterday         │
│  · Huberman #201   │
│    5 clips · 22m   │
│                    │
│  Last week         │
│  · Diary CEO #412  │
│    4 clips · 31m   │
│                    │
└────────────────────┘
```

Project history is stored as a simple JSON file at `~/.clipr/history.json`. No database needed.

---

## FastAPI Backend — Endpoint Map

```
POST   /api/projects                              ← create project, start Phase 1
GET    /api/projects/{id}                         ← project status + metadata
WS     /ws/project/{id}                           ← live progress stream

GET    /api/projects/{id}/clips                   ← Phase 2 results (candidates)
GET    /api/projects/{id}/clips/{clip_id}/preview ← fast-seek preview segment

POST   /api/projects/{id}/process                 ← submit approved clips → Phase 3+4
WS     /ws/project/{id}/processing                ← per-clip processing progress

GET    /api/projects/{id}/exports                 ← list finished clips
GET    /api/projects/{id}/exports/{clip_id}       ← download finished clip
GET    /api/projects/{id}/exports/all.zip         ← download all as zip

GET    /api/projects/{id}/clips/{clip_id}/ass     ← get .ass file content
POST   /api/projects/{id}/clips/{clip_id}/rerender ← re-burn captions from edited .ass

GET    /api/history                               ← project history list
```

### Project Runner — Background Task Management

Phase 1 is a long-running process. We can't run it synchronously in a FastAPI request — it would time out and block the server. We use `asyncio` + subprocess management:

```python
import asyncio
from fastapi import BackgroundTasks

@app.post("/api/projects")
async def create_project(
    background_tasks: BackgroundTasks,
    url: str = Form(None),
    file: UploadFile = File(None),
    genre: str = Form(...),
):
    project_id = str(uuid.uuid4())
    project_dir = create_project_dir(project_id)
    
    # Save upload or store URL
    source = await prepare_source(project_id, url, file)
    
    # Save project metadata
    save_project_meta(project_id, {
        'source': source,
        'genre': genre,
        'status': 'transcribing',
        'created_at': datetime.utcnow().isoformat(),
    })
    
    # Run Phase 1 as a background task
    background_tasks.add_task(run_phase_1_pipeline, project_id, source, genre)
    
    return { 'project_id': project_id }


async def run_phase_1_pipeline(project_id: str, source: str, genre: str):
    queue = get_progress_queue(project_id)
    
    try:
        # Step 1: Download/copy source
        await queue.put({ 'stage': 'downloading', 'percent': 5, ... })
        video_path = await download_source(source, project_id)
        
        # Step 2: Extract audio
        await queue.put({ 'stage': 'extracting', 'percent': 15, ... })
        audio_path = extract_audio(video_path)
        
        # Step 3: Transcribe
        await queue.put({ 'stage': 'transcribing', 'percent': 20, ... })
        transcript = await transcribe_with_progress(audio_path, queue, project_id)
        
        # Step 4: AI clip selection
        await queue.put({ 'stage': 'selecting', 'percent': 85, ... })
        candidates = await run_phase_2(transcript, genre)
        
        # Save results
        save_transcript(project_id, transcript)
        save_candidates(project_id, candidates)
        update_project_status(project_id, 'review_ready')
        
        await queue.put({ 'stage': 'complete', 'redirect': '/review' })
        
    except Exception as e:
        await queue.put({ 'stage': 'error', 'message': str(e) })
        update_project_status(project_id, 'error')
```

---

## File-Based State (No Database)

The project's entire state lives on the filesystem. This makes the tool simple, portable, and debuggable without any database setup.

```
~/.clipr/
  history.json                   ← list of all projects
  projects/
    {project_id}/
      meta.json                  ← source, genre, status, timestamps
      video.mp4                  ← downloaded/uploaded source video
      audio.wav                  ← extracted audio
      transcript.json            ← Phase 1 output
      candidates.json            ← Phase 2 output
      clips/
        clip_1_processed.mp4     ← Phase 3 output
        clip_1_final.mp4         ← Phase 4 output (with captions)
        clip_1.ass               ← editable subtitle source
        clip_2_processed.mp4
        clip_2_final.mp4
        clip_2.ass
      preview_cache/
        clip_1_preview.mp4       ← fast-generated preview segments
        clip_2_preview.mp4
```

---

## Error States

Every screen has an error state. Errors never crash silently.

```javascript
function ErrorBanner({ error, projectId }) {
  return (
    <div className="error-banner">
      <span className="error-icon">⚠</span>
      <div className="error-content">
        <strong>{error.type}</strong>
        <p>{error.message}</p>
        {error.suggestions.map(s => <p key={s}>• {s}</p>)}
      </div>
      <div className="error-actions">
        <button onClick={() => retryFromStage(projectId, error.stage)}>
          Retry this step
        </button>
        <button onClick={() => startOver(projectId)}>
          Start over
        </button>
      </div>
    </div>
  );
}
```

**Common errors and their user-facing messages:**

| Error | Message | Suggestion |
|---|---|---|
| yt-dlp fails on URL | "Couldn't download from this URL" | Check if video is private or age-restricted |
| faster-whisper OOM | "Ran out of memory during transcription" | Try closing other apps, or use a smaller model |
| Groq API rate limit | "AI service is busy" | Wait 60 seconds and retry |
| No clips found | "Couldn't find strong clips in this episode" | Try a different genre setting or a different episode |
| ffmpeg not found | "Video processing tools not installed" | Run: `brew install ffmpeg` or `sudo apt install ffmpeg` |
| Disk space low | "Not enough disk space" | Need ~5GB free — clear some space |

---

## First-Run Setup Screen

On the very first launch, before the Input screen, the tool checks for required dependencies and guides the user through any missing pieces:

```
┌────────────────────────────────────────────────────────────┐
│  Setting up CLIPR                                          │
│  ──────────────────────────────────────────────────────    │
│                                                            │
│  ✓ ffmpeg found (v6.1.1)                                   │
│  ✓ Python 3.11 found                                       │
│  ✓ faster-whisper installed                                │
│  ✓ mediapipe installed                                     │
│  ↻ Downloading Whisper model (large-v3-turbo)...  2.1 GB   │
│    [████████████████░░░░░░░░░░░░]  54%                     │
│  · Groq API key                                            │
│                                                            │
│  Groq API key (free at console.groq.com):                  │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ gsk_...                                              │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                            │
│  [ Continue ]   (available once all checks pass)           │
│                                                            │
└────────────────────────────────────────────────────────────┘
```

The API key is saved to `~/.clipr/config.json` and never leaves the machine.

---

## Processing Time Summary (Full Run)

For a 2-hour podcast producing 5 clips of ~60 seconds each:

| Phase | What happens | Time |
|---|---|---|
| Download | yt-dlp pulls video | 1–3 min |
| Transcription | faster-whisper on CPU | ~20 min |
| AI selection | Groq API (2 passes) | ~1 min |
| **User review** | Human approves clips | variable |
| Phase 3 × 5 clips | Cut, crop, encode | ~7 min |
| Phase 4 × 5 clips | Caption burn | ~2 min |
| **Total automated** | End to end | ~34 min |
| **Total delivered** | After human review | ~34 min + review time |

---

## What Phase 6 Would Look Like

Phase 5 is the final phase documented in this planning series. If a Phase 6 were added it would cover:

- **Scheduling & posting** — direct upload to TikTok, Instagram, YouTube via their respective APIs
- **Analytics integration** — track view counts per clip, feed successful clip patterns back into Phase 2 scoring weights
- **Multi-project workspace** — manage clips across multiple podcasters or clients
- **Caption template editor** — visual ASS editor inside the dashboard instead of raw text
- **Collaboration** — share project links with a team member for review

None of these are in scope for v1. The tool as documented delivers its stated goal: URL in, platform-ready clips out, free, local, no subscriptions.