# Clipping Pipeline — Modal Integration Log

> **Status:** 🟢 Integration Complete — Ready for Testing
> **Last Updated:** 2026-03-01 18:10 UTC
> **Current Phase:** Modal integration complete, awaiting authentication and testing

---

## Project Overview

**What:** Local podcast/video clipping tool that:
- Takes long-form video (URL or file upload)
- Transcribes it with Whisper
- Uses AI (Groq) to find best clip moments
- Cuts them into vertical 9:16 videos with face tracking
- Burns captions on top

**Current Pipeline Status:**
- ✅ **Phase 1:** Ingestion & Transcription (PARTIAL — transcription kills Mac CPU/RAM)
- ✅ **Phase 2:** AI Clip Selection (Groq API) — Working
- ✅ **Phase 3:** Video Processing — Working
- ✅ **Phase 4:** Caption Rendering — Working

**The Problem:** Phase 1 Step 4 (Whisper transcription) destroys the Mac. The `large-v3-turbo` model on CPU with `int8` compute and `beam_size=5` pins all cores at 100%, eats 6-10 GB RAM, and can take 30-60+ minutes for a long video.

**The Solution:** Move **only** the Whisper transcription to Modal cloud GPU. Everything else stays local.

---

## Progress Log

### ✅ Completed

#### 2026-03-01 17:53 — Modal Installation
- **Status:** ✅ Complete
- **Action:** Installed Modal v1.3.4 into virtual environment
- **Notes:** Used system pip to install to venv target due to broken venv pip
- **File:** Modal package installed in `.venv/`

#### 2026-03-01 17:54 — Creating modal_transcribe.py
- **Status:** ✅ Complete
- **Action:** Created Modal app definition with GPU transcription function
- **Configuration:**
  - Image: debian_slim + ffmpeg + faster-whisper 1.0.3
  - GPU: T4 (cheapest, sufficient for large-v3)
  - Model: large-v3-turbo (to match local)
  - Compute type: float16 (GPU)
  - Model cache: persistent Volume named "whisper-model-cache"
  - Timeout: 3600s (1 hour)
- **Output Format:** Matches local transcriber exactly (segments + words with segment_id)
- **File:** `modal_transcribe.py` created at project root
- **CLI Testing:** `modal run modal_transcribe.py --audio-file test.mp3`

#### 2026-03-01 18:00 — Pipeline Integration
- **Status:** ✅ Complete
- **Actions Completed:**
  1. Added `USE_MODAL` flag to `config.py` (reads from env, defaults to true)
  2. Created `pipeline/modal_transcriber.py` wrapper with automatic fallback
  3. Updated `pipeline/processor.py` to use modal transcriber
  4. Added `modal>=1.0.0` to `requirements.txt`
- **Fallback:** If Modal fails, automatically falls back to local transcription
- **Files Modified:**
  - `config.py` — Added USE_MODAL flag
  - `pipeline/processor.py` — Changed import to modal_transcriber
  - `requirements.txt` — Added modal dependency
- **Files Created:**
  - `modal_transcribe.py` — Modal GPU function
  - `pipeline/modal_transcriber.py` — Local wrapper

---

### 🔴 Blockers — User Action Required

#### Modal Authentication
- **Status:** 🔴 Required Before Testing
- **Command:** `source .venv/bin/activate && python -m modal setup`
- **Action:** Opens browser for Modal account authentication
- **One-time setup:** Only needs to be done once per machine
- **Blocks:** All Modal testing

---

### 📋 Next Steps

#### 1. Modal Authentication (REQUIRED)
```bash
source .venv/bin/activate
python -m modal setup
```
- Opens browser for Modal account signup/login
- $30 free credit included (~250 podcasts)
- No credit card required for free tier

#### 2. Test Modal in Isolation
```bash
# Extract a short test clip (30-60 seconds)
ffmpeg -i any_video.mp4 -t 60 -c copy test_clip.mp4

# Test Modal transcription
modal run modal_transcribe.py --audio-file test_clip.mp4
```
- Expected: First run takes 2-3 min (container build + model download)
- Subsequent runs: ~30 seconds for 1-minute clip
- Output: `test_clip_transcript.json` with word timestamps

#### 3. Test Full Pipeline
- Start the FastAPI backend
- Upload a short video through the web UI
- Verify transcription runs on Modal (check logs)
- Expected: No CPU spike, quick transcription

#### 4. Monitor Cost
- Check usage at: https://modal.com/apps
- Expected: ~$0.005 per 30-second test clip

---

## Pipeline Flow (After Modal Integration)

```
┌─────────────────────────────────────────────────────────────────┐
│ Phase 1: Ingestion & Transcription                              │
├─────────────────────────────────────────────────────────────────┤
│ 1. Download/Receive    → Local (yt-dlp)                         │
│ 2. Extract Audio       → Local (ffmpeg)                         │
│ 3. Preprocess          → Local (loudnorm, noisereduce)          │
│ 4. TRANSCRIBE          → MODAL GPU (faster-whisper large-v3)    │
│ 5. Post-process        → Local (fillers, thought blocks)        │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│ Phase 2: AI Clip Selection (Groq API) — Local                  │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│ Phase 3: Video Processing — Local                              │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│ Phase 4: Caption Rendering — Local                             │
└─────────────────────────────────────────────────────────────────┘
```

---

## Key Files

| File | Status | Purpose |
|------|--------|---------|
| `modal_transcribe.py` | ✅ Done | Modal GPU function definition |
| `pipeline/modal_transcriber.py` | ✅ Done | Local wrapper for Modal function |
| `pipeline/processor.py` | ✅ Done | Orchestrator — now uses Modal transcriber |
| `pipeline/transcriber.py` | ✅ Done | Local fallback (kept for backup) |
| `config.py` | ✅ Done | USE_MODAL toggle flag added |
| `requirements.txt` | ✅ Done | Modal dependency added |
| `LOG.md` | ✅ Active | This file — progress tracking |

---

## Configuration

**Current Settings:**
- Project Dir: `projects/`
- Virtual Env: `.venv/` (Python 3.12)
- Modal Version: 1.3.4
- Whisper Model: large-v3-turbo
- Groq API: Configured (`.env`)

**To Add:**
- `USE_MODAL=True` in `config.py` or `.env`
- Modal credentials via `modal setup`

---

## Current Configuration

**Environment Variables:**
```bash
# In .env or shell
USE_MODAL=true    # Enable Modal (default: true)
# To disable and use local CPU:
# USE_MODAL=false
```

**Modal Settings:**
- App Name: `podcast-clipper-transcriber`
- GPU: T4 (cheapest, ~$0.000164/sec)
- Model Cache Volume: `whisper-model-cache`
- Container Idle Timeout: 120 seconds
- Max Timeout: 3600 seconds (1 hour)

---

## Expected Timeline

| Task | Estimate | Status |
|------|----------|--------|
| Modal install | Done | ✅ |
| Create modal_transcribe.py | Done | ✅ |
| Add USE_MODAL to config | Done | ✅ |
| Create modal wrapper | Done | ✅ |
| Modify processor.py | Done | ✅ |
| Update requirements.txt | Done | ✅ |
| User: modal setup | 2 min | 🔴 Required |
| Test with short clip | 15 min | 📋 |
| Full pipeline test | 30 min | 📋 |

**Integration Status:** ✅ Code Complete — Awaiting User Authentication

---

## What Happens When We Run the Pipeline

### Initial Run (Cold Start)

When you run the pipeline with Modal for the first time:

```
┌─────────────────────────────────────────────────────────────────┐
│ USER ACTION: Upload video or provide URL                        │
└─────────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────────┐
│ LOCAL: Phase 1 Step 1-3 (download, extract, preprocess)        │
│ • yt-dlp downloads video from URL                              │
│ • ffmpeg extracts audio to 16kHz mono WAV                      │
│ • EBU R128 loudness normalization                              │
│ Timeline: ~2-5 minutes depending on file size                  │
│ Resources: Low — network I/O and light CPU                      │
└─────────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────────┐
│ MODAL: Phase 1 Step 4 (Transcription) — GPU CLOUD              │
│                                                                 │
│ 1. MODAL CONTAINER SPIN UP (~30-60 seconds)                    │
│    • Modal allocates T4 GPU                                    │
│    • Starts Debian container with pre-built image              │
│    • Mounts persistent volume for model cache                  │
│                                                                 │
│ 2. MODEL LOADING (~10 seconds on warm cache)                   │
│    • First run: Downloads ~3GB Whisper model (1-2 minutes)     │
│    • Subsequent runs: Loads from cache in ~10 seconds          │
│                                                                 │
│ 3. AUDIO UPLOAD (~5-30 seconds depending on file size)         │
│    • Preprocessed WAV sent to Modal GPU                        │
│    • For 2-hour podcast: ~100MB upload                         │
│                                                                 │
│ 4. GPU TRANSCRIPTION (~10-12 minutes for 2-hour podcast)       │
│    • faster-whisper large-v3-turbo on T4 GPU                   │
│    • float16 precision for speed                               │
│    • VAD filtering skips silence                               │
│    • Word-level timestamps extracted                           │
│                                                                 │
│ 5. RESULT DOWNLOAD (~1 second)                                 │
│    • Transcript JSON returned to Mac (few KB)                  │
│    • Container stays warm for 2 minutes                        │
│                                                                 │
│ Timeline: ~15-20 minutes total for 2-hour podcast (first run)  │
│           ~12-15 minutes total (subsequent runs)               │
│ Resources: ZERO local CPU/RAM — all compute in cloud           │
│ Cost: ~$0.12 for 2-hour podcast                                │
└─────────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────────┐
│ LOCAL: Phase 1 Step 5 (post-process)                            │
│ • Flags filler words (um, uh, like, etc.)                      │
│ • Segments thought blocks                                      │
│ • Injects chapter markers                                      │
│ Timeline: ~30 seconds                                           │
│ Resources: Low — pure Python                                    │
└─────────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────────┐
│ LOCAL: Phase 2-4 (Clip selection, video processing, captions)  │
│ • All run locally as before                                    │
│ • No changes to these phases                                   │
└─────────────────────────────────────────────────────────────────┘
```

### Subsequent Runs (Warm Container)

If you process multiple videos within 2 minutes:

```
MODAL TRANSCRIPTION (Steps 4-5 only):
• No container spin-up (already warm)
• No model loading (already in memory)
• Audio upload → GPU transcribe → Result download
Timeline: ~10-12 minutes for 2-hour podcast
```

### Progress Indicators

When Modal is transcribing, you'll see logs like:

```
[INFO] Using Modal GPU for transcription (model: large-v3-turbo)
[INFO] Sending 98.5 MB to Modal GPU...
[INFO] (Modal) Loading Whisper large-v3-turbo...
[INFO] (Modal) Model loaded in 9.2s
[INFO] (Modal) Transcribing audio.wav (98.5 MB)...
[INFO] (Modal) Done. Language: en, Words: 18432, Duration: 7243.5s, Time: 682.3s
[INFO] Modal transcription complete in 682.3s: 18432 words, 7243s duration
```

### Error Handling

If Modal fails for any reason:
```
[ERROR] Modal transcription failed: [error details]
[INFO] Falling back to local transcription...
```
The pipeline will automatically fall back to local CPU transcription
(though this will be slow and resource-intensive).

---

## Notes

- **Cost:** ~$0.12 per 2-hour podcast on T4 GPU
- **Free Tier:** $30 credit ≈ 250 podcasts
- **Cold Start:** ~30-60 seconds first run, ~5 seconds cached
- **Speed:** 10-12 min for 2-hour podcast (vs 30-60 min local CPU)
- **Local Resources:** Near-zero CPU/RAM during Modal transcription
- **Network:** Upload ~100MB for 2-hour podcast, download <1MB transcript

---

*This log is updated after each significant action or milestone.*
