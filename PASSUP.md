# PASSUP — Pipeline Context & Modal Migration Plan

> Context document for any AI agent picking up this project.
> Read this top-to-bottom before writing any code.

---

## What This Project Is

A local podcast/video clipping tool. You give it a long-form video (URL or file upload), it transcribes it, uses AI to find the best short-form clip moments, cuts them into vertical 9:16 videos with face tracking, and burns captions on top. The output is ready-to-post short-form content.

The backend is **FastAPI** (Python 3.12). The frontend is **React** (in `frontend/`). Everything runs locally on a Mac — there is no deployment server. Projects live in `projects/{job_id}/`.

---

## How the Pipeline Works (4 Phases)

### Phase 1 — Ingestion & Transcription (`pipeline/processor.py` orchestrates)

| Step | File | What it does | Resource cost |
|------|------|-------------|---------------|
| 1. Download | `pipeline/downloader.py` | yt-dlp grabs the video from URL (or accepts upload) | Low — network I/O |
| 2. Extract audio | `pipeline/audio.py` → `extract_audio()` | ffmpeg demuxes to 16kHz mono WAV | Low — single ffmpeg pass |
| 3. Preprocess | `pipeline/audio.py` → `normalize_audio()`, `reduce_noise()` | EBU R128 loudnorm, optional noisereduce | Low-Medium |
| 4. **Transcribe** | `pipeline/transcriber.py` → `transcribe_audio()` | faster-whisper `large-v3-turbo`, beam_size=5, word timestamps, VAD | **EXTREME on CPU — this is what kills the Mac** |
| 5. Post-process | `pipeline/postprocessor.py` → `postprocess_transcript()` | Flag fillers, detect hallucinations, segment thought blocks, inject chapters | Low — pure Python |

**Output:** `projects/{job_id}/transcripts/transcript.json` — contains `words[]` (flat word list with timestamps + filler flags) and `thought_blocks[]`.

### Phase 2 — AI Clip Selection (`pipeline/clip_selector.py`)

Two-pass system using **Groq API** (LLaMA 3.3 70B):
- **Pass 1 — Discovery:** Scans all thought blocks, identifies candidate clip moments.
- **Pass 2 — Scoring:** Deep scores each candidate on hook, narrative, standalone, emotional, length dimensions.
- **Ranking:** `pipeline/scoring.py` applies weighted scoring (hook 30%, narrative 25%, standalone 20%, emotional 15%, length 10%) + diversity filtering (5-min minimum gap between clips).

**Resource cost:** Near-zero locally — it's API calls to Groq. Needs `GROQ_API_KEY` in `.env`.

**Output:** `projects/{job_id}/clips.json`

### Phase 3 — Video Processing (`pipeline/video_processor.py` orchestrates)

10-step pipeline per clip:

| Steps | Files | What it does |
|-------|-------|-------------|
| 1. Raw cut | `video_cutter.py` | Frame-accurate ffmpeg seek + cut |
| 2. Jump cuts | `video_cutter.py` | Remove silences/fillers, rebase word timestamps |
| 3. Layout analysis | `video_analysis.py` | Detect single speaker / split-screen / studio / no-face |
| 4. Face tracking | `video_analysis.py` | Sample faces at 2fps with OpenCV, interpolate between |
| 5-6. Crop + smooth | `video_crop.py` | Compute 9:16 crop window centered on face, smooth path with 1.5s rolling average |
| 7. Dynamic crop | `video_crop.py` | Apply per-frame crop + subtle zoom via OpenCV→ffmpeg pipe |
| 8. Color grade | `video_encoder.py` | Preset-based eq/colorbalance (standard, vibrant, cinematic) |
| 9. Audio normalize | `video_encoder.py` | EBU R128 measurement |
| 10. Final encode | `video_encoder.py` | H.264, 1080x1920, CRF 18, faststart |

**Resource cost:** Heavy — CPU-bound face tracking and video encoding, but spread over time and not as spiky as Whisper.

**Output:** `projects/{job_id}/clips/clip_{n}_processed.mp4` + `rebased_words_{n}.json`

### Phase 4 — Caption Rendering (`pipeline/caption_renderer.py`)

- Filters word timestamps for the clip's time range
- Generates ASS subtitle file from a style template
- Burns captions into video using ffmpeg libass

**5 caption styles available:** hormozi (bold word-by-word), podcast_subtitle (sentence-based box), karaoke (educational), reaction, cinematic. Defined in `pipeline/caption_styles.py`.

**Resource cost:** Moderate — one ffmpeg encode pass per clip.

**Output:** `projects/{job_id}/clips/clip_{n}_captioned.mp4`

---

## API Endpoints (main.py)

| Method | Endpoint | Phase | What it does |
|--------|----------|-------|-------------|
| POST | `/api/process/url` | 1 | Start pipeline from URL |
| POST | `/api/process/upload` | 1 | Start pipeline from file upload |
| GET | `/api/status/{job_id}` | 1 | Poll job progress |
| GET | `/api/transcript/{job_id}` | 1 | Get completed transcript |
| GET | `/api/jobs` | — | List all jobs |
| DELETE | `/api/jobs/{job_id}` | — | Delete job + files |
| GET | `/api/genres` | 2 | List genre profiles |
| POST | `/api/clips/select` | 2 | Run AI clip selection |
| GET | `/api/clips/{job_id}` | 2 | Get clip candidates |
| POST | `/api/clips/process` | 3 | Run video processing |
| GET | `/api/clips/{job_id}/processed` | 3 | Get processed clips |
| GET | `/api/caption-styles` | 4 | List caption styles |
| POST | `/api/captions/render` | 4 | Burn captions |
| GET | `/api/captions/{job_id}` | 4 | Get captioned clips |

All long-running endpoints return immediately with a job ID. Work runs in `BackgroundTasks`. Progress is pushed over WebSocket via `pipeline/dashboard_routes.py` and `pipeline/job_manager.py`.

---

## Key File Map

```
Clipping/
├── main.py                          # FastAPI app, all API routes
├── config.py                        # All constants, defaults, stage weights
├── MODAL.md                         # Full Modal integration guide (reference)
├── pipeline/
│   ├── processor.py                 # Phase 1 orchestrator (download→transcribe→post-process)
│   ├── downloader.py                # yt-dlp wrapper
│   ├── audio.py                     # ffmpeg extract, loudnorm, noisereduce
│   ├── transcriber.py               # faster-whisper integration (THE BOTTLENECK)
│   ├── postprocessor.py             # Filler flagging, thought blocks, hallucination detection
│   ├── clip_selector.py             # Phase 2 — Groq AI two-pass clip selection
│   ├── genre_profiles.py            # Genre-specific prompts and scoring criteria
│   ├── scoring.py                   # Weighted scoring + diversity filter
│   ├── video_processor.py           # Phase 3 orchestrator (10-step clip processing)
│   ├── video_cutter.py              # Raw cut + jump cut + timestamp rebase
│   ├── video_analysis.py            # Layout detection + face tracking (OpenCV)
│   ├── video_crop.py                # 9:16 crop, smoothing, dynamic crop+zoom
│   ├── video_encoder.py             # Color grade, audio norm, final H.264 encode
│   ├── caption_renderer.py          # Phase 4 orchestrator (ASS gen + burn)
│   ├── caption_styles.py            # 5 caption style classes
│   ├── caption_utils.py             # Caption helper functions
│   ├── job_manager.py               # In-memory job state, WebSocket bridge
│   └── dashboard_routes.py          # WebSocket progress + dashboard API
├── frontend/                        # React frontend
├── projects/                        # Runtime data — one dir per job
└── .venv/                           # Python 3.12 virtualenv
```

---

## The Problem

Phase 1 Step 4 (Whisper transcription) destroys the Mac. The `large-v3-turbo` model on CPU with `int8` compute and `beam_size=5` pins all cores at 100%, eats 6-10 GB RAM, and can take 30-60+ minutes for a long video. macOS starts swapping and the whole system locks up.

---

## The Solution — Modal Cloud GPU

Move **only** the Whisper transcription to Modal. Everything else stays local.

### What Modal is

Serverless GPU compute. You define a Python function with `@app.function(gpu="T4")`, call it with `.remote()`, and Modal spins up a GPU container in the cloud, runs the function, streams logs back, and shuts down when idle. Pay-per-second. $30 free credit on signup (~250 two-hour podcasts on T4).

### What changes

- `pipeline/transcriber.py` gets replaced/bypassed — instead of running faster-whisper locally, the audio bytes are sent to a Modal function that runs faster-whisper on a cloud T4 GPU with `float16` compute.
- The Modal function returns the same transcript dict structure (language, duration, words with timestamps).
- `pipeline/processor.py` needs to be updated to call the Modal function instead of the local `transcribe_audio()`.
- The transcript output format stays identical — Phase 2, 3, and 4 see no difference.

### What does NOT change

- FastAPI backend stays local
- React frontend stays local
- All project files stay on the Mac
- Phase 2 (Groq API), Phase 3 (video processing), Phase 4 (captions) stay local
- WebSocket progress system stays local
- Job manager stays local

---

## Next Steps — Modal Installation & Integration

### Step 1: Install & Authenticate Modal

```bash
source .venv/bin/activate
pip install modal
modal setup          # opens browser, writes token to ~/.modal.toml
modal token show     # verify
```

### Step 2: Create `modal_transcribe.py` (project root)

The Modal function definition. See `MODAL.md` Step 4 for the full code. Key decisions:
- Image: `debian_slim` + ffmpeg + faster-whisper 1.0.3
- GPU: T4 (cheapest, sufficient for large-v3)
- Model cache: persistent `modal.Volume` so weights aren't re-downloaded
- Compute type: `float16` (GPU) instead of `int8` (CPU)
- Container idle timeout: 120s (avoids cold start between clips)
- Max timeout: 3600s (1 hour for very long podcasts)

### Step 3: Modify `pipeline/processor.py` to use Modal

The transcription step (Step 4 in `run_pipeline()`) currently calls:
```python
raw_transcript = transcribe_audio(final_audio_path, model_size=..., device=..., ...)
```

This needs to:
1. Read the preprocessed audio file as bytes
2. Call the Modal function with `.remote(audio_bytes, filename)`
3. Map the Modal response back into the same transcript dict format that `postprocess_transcript()` expects (needs `segments` and `words` with `probability` and `segment_id` fields — the MODAL.md version returns a flatter structure that will need adapting)

**Critical compatibility note:** The existing local `transcribe_audio()` returns segments with word-level probabilities and segment IDs. The MODAL.md example returns a flat word list without these. The integration must either:
- (a) Expand the Modal function to return the full segment+word structure, OR
- (b) Add a local adapter that reconstructs segments from the flat word list

Option (a) is cleaner — modify the Modal function to match the existing return format.

### Step 4: Add a local/cloud toggle

Add a `USE_MODAL` flag to `config.py` (or read from settings/env) so the pipeline can fall back to local transcription when Modal is unavailable or for quick testing with small models.

### Step 5: Test with a short clip first

```bash
# Extract a 60s test clip
ffmpeg -i some_video.mp4 -t 60 -c copy test_clip.mp4

# Test Modal function in isolation
modal run modal_transcribe.py --audio-file test_clip.mp4

# Then test through the full pipeline via the API
```

### Step 6: Update requirements

Add `modal>=0.64.0` to requirements/deps.

---

## How We Build From Here

1. **Modal handles transcription only.** The Mac is a thin client for Phase 1 Step 4. All other compute stays local.
2. **Progress reporting** needs updating — the current `transcribe_progress` callback won't work across the Modal boundary. Either poll the Modal function's status or use a simpler "uploading → transcribing → done" three-stage progress for the transcription step.
3. **The transcript format is the contract.** Whatever Modal returns must match what `postprocess_transcript()` in `pipeline/postprocessor.py` expects: `segments[]` with `id, start, end, text, words[]` and `words[]` with `word, start, end, probability, segment_id`. Do not change the downstream contract.
4. **Error handling** — if Modal is down or the call fails, the pipeline should fail gracefully with a clear error, not silently fall back to local (which would freeze the Mac again).
5. **Cost is negligible.** ~$0.12 per 2-hour podcast. The $30 free tier covers months of use.
