# MODAL WHISPER SETUP
### Offload faster-whisper transcription from local Mac to GPU in the cloud

---

## What This Document Is

This is a complete setup guide for integrating Modal into the podcast clipping pipeline to handle Phase 1 transcription remotely. The goal is to stop running faster-whisper locally on the Mac (which kills RAM and CPU) and instead send audio to a Modal GPU container, receive the transcript, and save it locally as if the transcription happened locally.

The Mac continues to run the FastAPI backend and dashboard UI. Only the Whisper computation moves to Modal.

---

## How Modal Works

Modal is a serverless GPU compute platform. You write Python locally, decorate functions with `@app.function(gpu=...)`, and when those functions are called with `.remote()`, Modal spins up a container in the cloud with the requested GPU, runs the function, streams logs back to your terminal, and shuts the container down when idle.

**The debug experience is local.** You run `modal run script.py` from your terminal and see live logs exactly as if the code ran locally. No SSH. No deployment steps. No server to manage. Container cold start is roughly 5 seconds for a warm image, 30–60 seconds on first run when Modal builds the image.

**Cost model:** You pay only when the function is actually executing. A T4 GPU costs approximately $0.000164 per second. A 2-hour podcast transcribed with `large-v3` on a T4 takes around 10–12 minutes of GPU time, which works out to roughly $0.12 per podcast. Modal gives $30 free credit on signup — enough for around 250 podcasts before any charges.

---

## Prerequisites

- Python 3.10 or higher installed on the Mac
- pip available
- The project already has a working FastAPI backend
- An existing `requirements.txt` or virtual environment for the project

---

## Step 1 — Install Modal Locally

Modal is installed as a Python package on the Mac. It does not need to be installed inside any remote container — Modal handles that automatically.

```bash
pip install modal
```

If the project uses a virtual environment, activate it first:

```bash
source venv/bin/activate    # or whatever the venv path is
pip install modal
```

Verify the install:

```bash
modal --version
```

---

## Step 2 — Create a Modal Account and Authenticate

Go to https://modal.com and create a free account. No credit card required for the free tier.

After creating the account, run:

```bash
modal setup
```

This opens a browser window, authenticates with the Modal account, and writes a token to `~/.modal.toml`. This only needs to be done once per machine.

Verify authentication:

```bash
modal token show
```

---

## Step 3 — Project File Structure

The Modal transcription integration consists of two files that sit inside the existing project:

```
your_project/
  modal_transcribe.py        ← the Modal function definition
  phase1_runner.py           ← wrapper that calls Modal from FastAPI
  (existing FastAPI files)
```

Both files are created in the steps below.

---

## Step 4 — Create `modal_transcribe.py`

This file defines the remote environment and the transcription function. Create it at the root of the project.

```python
# modal_transcribe.py
# Defines the Modal app and transcription function.
# This function runs on a GPU in the cloud, not on the local Mac.

import modal

# ── Remote environment definition ────────────────────────────────────────────
# Modal builds this as a Docker container. Every .pip_install() and
# .apt_install() runs inside the container, not on the Mac.
# The image is cached after the first build — subsequent runs reuse it.

image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("ffmpeg")
    .pip_install(
        "faster-whisper==1.0.3",
        "ctranslate2>=4.0.0",
    )
)

app = modal.App("podcast-clipper-transcriber", image=image)

# ── Model cache volume ────────────────────────────────────────────────────────
# Persists the downloaded Whisper model weights between runs so Modal
# does not re-download 3GB on every cold start. Created automatically
# on first run.

model_volume = modal.Volume.from_name(
    "whisper-model-cache",
    create_if_missing=True,
)

MODEL_CACHE_DIR = "/model_cache"

# ── Transcription function ────────────────────────────────────────────────────

@app.function(
    gpu="T4",                          # cheapest NVIDIA GPU, sufficient for large-v3
    timeout=3600,                      # max 1 hour — covers very long podcasts
    container_idle_timeout=120,        # keep container alive 2 min between calls
                                       # avoids cold start when processing multiple clips
    volumes={MODEL_CACHE_DIR: model_volume},
)
def transcribe_audio(audio_bytes: bytes, filename: str) -> dict:
    """
    Receives raw audio bytes, transcribes with faster-whisper large-v3,
    returns a structured dict with word-level timestamps and filler flags.

    Parameters:
        audio_bytes: raw bytes of the audio/video file
        filename:    original filename including extension (used to write
                     a temp file with the correct extension so ffmpeg
                     inside faster-whisper can parse the format)

    Returns:
        {
            "language":  str,
            "duration":  float,       # seconds
            "words": [
                {
                    "word":      str,
                    "start":     float,   # seconds
                    "end":       float,   # seconds
                    "is_filler": bool,
                }
            ]
        }
    """
    import os
    import tempfile
    from faster_whisper import WhisperModel

    # Words to flag as fillers for the jump cut system in Phase 3
    FILLERS = {
        "um", "uh", "like", "you know", "sort of", "i mean",
        "basically", "literally", "actually", "right", "okay",
        "hmm", "hm", "ah", "er",
    }

    # Load model — uses the mounted volume as cache dir
    # On first run this downloads ~3GB. On subsequent runs it loads in ~10s.
    print(f"Loading Whisper large-v3...")
    model = WhisperModel(
        "large-v3",
        device="cuda",
        compute_type="float16",
        download_root=MODEL_CACHE_DIR,
    )

    # Write audio bytes to a temp file so faster-whisper can open it
    ext = os.path.splitext(filename)[-1] or ".mp3"
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as f:
        f.write(audio_bytes)
        tmp_path = f.name

    print(f"Transcribing {filename} ({len(audio_bytes) / 1024 / 1024:.1f} MB)...")

    segments, info = model.transcribe(
        tmp_path,
        beam_size=5,
        word_timestamps=True,         # required — Phase 3 jump cuts rely on this
        vad_filter=True,              # voice activity detection — skips silent sections
        vad_parameters={
            "min_silence_duration_ms": 500,
        },
    )

    # Consume the generator and build word list
    words = []
    for segment in segments:
        if segment.words is None:
            continue
        for word in segment.words:
            clean = word.word.strip().lower()
            words.append({
                "word":      word.word.strip(),
                "start":     round(word.start, 3),
                "end":       round(word.end, 3),
                "is_filler": clean in FILLERS,
            })

    os.remove(tmp_path)

    print(f"Done. Language: {info.language}, Words: {len(words)}, Duration: {info.duration:.1f}s")

    return {
        "language": info.language,
        "duration": info.duration,
        "words":    words,
    }


# ── Local entrypoint for CLI testing ─────────────────────────────────────────
# Used for testing only — not called by FastAPI.
# Run with: modal run modal_transcribe.py --audio-file /path/to/audio.mp3

@app.local_entrypoint()
def main(audio_file: str):
    import json
    import os

    if not os.path.exists(audio_file):
        print(f"Error: file not found: {audio_file}")
        return

    with open(audio_file, "rb") as f:
        audio_bytes = f.read()

    print(f"Sending {len(audio_bytes) / 1024 / 1024:.1f} MB to Modal GPU...")

    result = transcribe_audio.remote(audio_bytes, os.path.basename(audio_file))

    output_path = audio_file.rsplit(".", 1)[0] + "_transcript.json"
    with open(output_path, "w") as f:
        json.dump(result, f, indent=2)

    print(f"Transcript saved to: {output_path}")
    print(f"Words: {len(result['words'])}")
    print(f"Duration: {result['duration']:.1f}s")
    print(f"Language: {result['language']}")
```

---

## Step 5 — Create `phase1_runner.py`

This file is the bridge between the existing FastAPI backend and the Modal function. It handles reading the project audio, calling Modal, and saving the result to the project directory.

```python
# phase1_runner.py
# Called by the FastAPI backend to kick off transcription.
# Sends the audio to Modal and saves the result to the project directory.

import json
import os
from pathlib import Path

# Import the Modal function — Modal handles the remote call transparently
from modal_transcribe import transcribe_audio

PROJECT_BASE_DIR = os.path.expanduser("~/.clipr/projects")


def run_phase1(
    project_id: str,
    progress_callback=None,
) -> dict:
    """
    Reads the project video, sends audio to Modal for transcription,
    saves the result, and returns the transcript dict.

    progress_callback(stage: str, percent: float) is called at key points
    so the WebSocket progress system can update the dashboard.
    """

    project_dir   = Path(PROJECT_BASE_DIR) / project_id
    video_path    = project_dir / "video.mp4"
    transcript_path = project_dir / "transcript.json"

    if not video_path.exists():
        raise FileNotFoundError(f"No video found at {video_path}")

    # Read the video file as bytes
    # Modal accepts bytes — no temp file manipulation needed on the Mac side
    if progress_callback:
        progress_callback("reading_file", 0.02)

    with open(video_path, "rb") as f:
        audio_bytes = f.read()

    size_mb = len(audio_bytes) / 1024 / 1024
    print(f"[Phase 1] Sending {size_mb:.1f} MB to Modal...")

    if progress_callback:
        progress_callback("uploading", 0.05)

    # Call Modal — this blocks until the remote function completes
    # For async FastAPI, use: await transcribe_audio.remote.aio(...)
    result = transcribe_audio.remote(audio_bytes, "video.mp4")

    if progress_callback:
        progress_callback("saving", 0.95)

    # Save transcript to project directory
    with open(transcript_path, "w") as f:
        json.dump(result, f, indent=2)

    print(f"[Phase 1] Transcript saved. {len(result['words'])} words.")

    if progress_callback:
        progress_callback("done", 1.0)

    return result


# ── Async version for FastAPI ─────────────────────────────────────────────────

async def run_phase1_async(
    project_id: str,
    progress_callback=None,
) -> dict:
    """
    Async version for use with FastAPI async endpoints.
    Uses Modal's .remote.aio() to avoid blocking the event loop.
    """
    import asyncio

    project_dir     = Path(PROJECT_BASE_DIR) / project_id
    video_path      = project_dir / "video.mp4"
    transcript_path = project_dir / "transcript.json"

    if not video_path.exists():
        raise FileNotFoundError(f"No video found at {video_path}")

    if progress_callback:
        await progress_callback("reading_file", 0.02)

    with open(video_path, "rb") as f:
        audio_bytes = f.read()

    if progress_callback:
        await progress_callback("uploading", 0.05)

    # Non-blocking Modal call
    result = await transcribe_audio.remote.aio(audio_bytes, "video.mp4")

    if progress_callback:
        await progress_callback("saving", 0.95)

    with open(transcript_path, "w") as f:
        json.dump(result, f, indent=2)

    if progress_callback:
        await progress_callback("done", 1.0)

    return result
```

---

## Step 6 — Update the FastAPI Endpoint

In the existing FastAPI backend, replace whatever currently calls faster-whisper locally with a call to `run_phase1_async`. The rest of the endpoint stays the same.

```python
# In your existing FastAPI file (e.g. main.py or routes/transcribe.py)

from phase1_runner import run_phase1_async

@app.post("/api/projects/{project_id}/transcribe")
async def start_transcription(project_id: str):
    """
    Kicks off Phase 1 transcription via Modal.
    Returns immediately — progress is sent via WebSocket.
    """
    import asyncio

    # Build a progress callback that pushes updates over the WebSocket
    async def send_progress(stage: str, percent: float):
        await websocket_manager.broadcast(project_id, {
            "stage":   stage,
            "percent": percent,
        })

    # Run transcription in background so the HTTP response returns immediately
    asyncio.create_task(
        run_phase1_async(project_id, progress_callback=send_progress)
    )

    return {"status": "started", "project_id": project_id}
```

---

## Step 7 — Add Modal to Requirements

Add Modal to the project's `requirements.txt`:

```
modal>=0.64.0
faster-whisper==1.0.3
```

Note: `faster-whisper` stays in `requirements.txt` even though it runs remotely, because the local dev environment may import from it. Modal installs it separately inside the remote container via `image.pip_install()`.

---

## Running and Testing

### Test the transcription function in isolation (CLI)

This is the fastest way to verify everything works. It does not involve FastAPI at all.

```bash
modal run modal_transcribe.py --audio-file /path/to/test_audio.mp3
```

What happens:

1. Modal authenticates using the token in `~/.modal.toml`
2. Modal builds the container image (first time only, ~2 minutes; cached after)
3. A T4 GPU container spins up (~5–30 seconds)
4. The audio file bytes are uploaded to Modal
5. faster-whisper runs inside the container with GPU acceleration
6. Logs stream back to the terminal in real time
7. The container stays warm for 2 minutes, then shuts down
8. A `test_audio_transcript.json` file is saved locally

For a short 5-minute test clip, the full round trip including cold start should be under 3 minutes. For a 2-hour podcast, expect 15–25 minutes total (including cold start).

### Test with a very short file first

Before sending a full 2-hour podcast, test with a short clip (30–60 seconds) to confirm the pipeline works end-to-end:

```bash
# Extract a 60-second clip from any video for testing
ffmpeg -i podcast.mp4 -t 60 -c copy test_clip.mp4

modal run modal_transcribe.py --audio-file test_clip.mp4
```

### View logs in the Modal dashboard

Every run is logged at https://modal.com/apps — you can see execution time, GPU utilisation, and any errors for every call ever made.

### Watch the container logs live

When running from the terminal, Modal streams all `print()` output from the remote function back in real time. There is nothing extra to configure.

---

## Debugging

### If the Modal function throws an error

The full traceback prints to the terminal, exactly as if the code ran locally. Fix the code and re-run — no redeploy needed.

### If you need an interactive shell inside the container

```bash
modal shell modal_transcribe.py
```

This opens a bash shell inside a container with the same image, GPU, and volume mounts. You can run Python, inspect the model cache, check if ffmpeg is installed, etc.

```bash
# Inside the modal shell
python -c "from faster_whisper import WhisperModel; print('ok')"
nvidia-smi    # check GPU is available
ls /model_cache    # check if model weights are cached
```

### If the model download is slow on first run

The first run downloads ~3GB of model weights. The volume cache means this only happens once. If a run times out during download, just re-run — it will continue from where it left off because the volume persists.

### If you get an authentication error

```bash
modal token show    # check if token exists
modal setup         # re-authenticate if needed
```

### If the container runs out of GPU memory

Switch from `float16` to `int8_float16` in `modal_transcribe.py`:

```python
model = WhisperModel(
    "large-v3",
    device="cuda",
    compute_type="int8_float16",    # uses less VRAM, marginal accuracy difference
    download_root=MODEL_CACHE_DIR,
)
```

Or switch to an A10G GPU which has more VRAM:

```python
@app.function(
    gpu="A10G",    # 24GB VRAM vs T4's 16GB — costs ~3x more but still cheap
    ...
)
```

---

## Cost Reference

| Action | GPU | Time | Cost |
|---|---|---|---|
| 30-second test clip | T4 | ~30s compute | ~$0.005 |
| 60-minute podcast | T4 | ~6 min compute | ~$0.06 |
| 2-hour podcast | T4 | ~12 min compute | ~$0.12 |
| 2-hour podcast | A10G | ~5 min compute | ~$0.15 |

The $30 free credit covers roughly 250 two-hour podcasts on a T4.

---

## What Does Not Change

- The FastAPI backend still runs locally on the Mac
- The dashboard UI still runs locally on the Mac
- All project files (`~/.clipr/projects/`) still live on the Mac
- Phase 2 (Groq AI scoring), Phase 3 (video processing), and Phase 4 (caption rendering) still run locally
- The WebSocket progress system still runs locally
- Only the Whisper transcription computation moves to Modal

---

## Transcript Output Format

The file saved to `~/.clipr/projects/{project_id}/transcript.json` has this structure, which is identical to what Phase 2 and Phase 3 expect:

```json
{
  "language": "en",
  "duration": 7243.5,
  "words": [
    {
      "word": "Nobody",
      "start": 142.320,
      "end": 142.640,
      "is_filler": false
    },
    {
      "word": "um",
      "start": 143.100,
      "end": 143.280,
      "is_filler": true
    }
  ]
}
```

No changes are needed in Phase 2 or Phase 3 — they read `transcript.json` the same way regardless of whether it was produced locally or by Modal.

---

## Summary of Files Created

| File | Purpose |
|---|---|
| `modal_transcribe.py` | Modal app definition. The remote function that runs on GPU. |
| `phase1_runner.py` | Local bridge. Reads the project audio, calls Modal, saves the result. |

That is the complete integration. Two files, one `pip install`, one `modal setup`, and the Mac never touches Whisper again.