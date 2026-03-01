# PHASE 1 — INGESTION & TRANSCRIPTION
### The Foundation Layer of the Clipping Tool

---

## What This Phase Does

Phase 1 takes raw input — either a local video file uploaded through the dashboard or a YouTube/podcast URL — and outputs a single, clean, word-level timestamped transcript that the AI brain in Phase 2 can work with.

Every downstream phase depends on the quality of this output. Bad timestamps = broken captions. Missing words = AI misses good clips. This phase needs to be bulletproof.

---

## Overview of the Pipeline

```
[Input: Video File OR URL]
         ↓
[Step 1: Download / Receive]
         ↓
[Step 2: Extract Audio]
         ↓
[Step 3: Preprocess Audio]
         ↓
[Step 4: Transcribe with Word-Level Timestamps]
         ↓
[Step 5: Post-Process Transcript]
         ↓
[Output: Master Transcript JSON]
```

---

## Step 1 — Input Handling (Two Paths)

### Path A: URL Input (YouTube, podcast, etc.)

**Tool: yt-dlp**

yt-dlp is a free, open-source command-line downloader that supports 1,700+ websites including YouTube, Spotify, SoundCloud, Vimeo, Apple Podcasts, Rumble, and more. It's the industry standard and gets updated constantly to keep up with platform changes.

**Install:**
```bash
pip install yt-dlp
# Also requires ffmpeg installed on system
```

**The correct download command for our use case:**
```bash
# Download original video (keep video for reframing later)
yt-dlp \
  --format "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]" \
  --merge-output-format mp4 \
  --output "%(id)s.%(ext)s" \
  --write-info-json \
  "URL_HERE"
```

Why we download the full video and not audio-only:
- We need the video for the actual clip cutting in Phase 3
- We need the video for face reframing, caption overlay, and vertical cropping
- Audio extraction happens separately as a derived step

**What `--write-info-json` gives us:**
Saves a JSON file alongside the download containing the title, uploader, description, duration, chapter markers (if any), and upload date. We use this to pre-populate metadata in the dashboard and potentially pass chapter titles to the AI as context clues.

**Handling YouTube rate limiting / bot detection:**
YouTube increasingly requires cookies for downloads. The solution is:
```bash
yt-dlp --cookies-from-browser chrome "URL"
```
This pulls cookies from the user's local Chrome browser. Should be documented in the setup guide.

**Python wrapper (how we call it in code):**
```python
import yt_dlp

def download_video(url: str, output_dir: str) -> dict:
    ydl_opts = {
        'format': 'bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]',
        'merge_output_format': 'mp4',
        'outtmpl': f'{output_dir}/%(id)s.%(ext)s',
        'writeinfojson': True,
        'quiet': False,
        'progress_hooks': [progress_hook],  # for dashboard progress bar
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        return {
            'video_path': f"{output_dir}/{info['id']}.mp4",
            'title': info.get('title'),
            'duration': info.get('duration'),
            'chapters': info.get('chapters', []),
        }
```

**Supported platforms confirmed:**
- YouTube ✓
- Spotify (audio) ✓
- SoundCloud ✓
- Apple Podcasts ✓
- Rumble ✓
- Vimeo ✓
- Twitter/X ✓
- Instagram ✓
- TikTok ✓

### Path B: Local File Upload

User uploads a video file directly through the dashboard. No download needed.

**Accepted formats:**
- MP4, MOV, MKV, AVI, WEBM (video)
- MP3, M4A, WAV, FLAC, OGG (audio-only uploads also supported)

**Validation on upload:**
```python
SUPPORTED_VIDEO = ['.mp4', '.mov', '.mkv', '.avi', '.webm']
SUPPORTED_AUDIO = ['.mp3', '.m4a', '.wav', '.flac', '.ogg']

MAX_FILE_SIZE_GB = 10  # practical limit for local processing
```

For audio-only uploads (e.g. someone has just the podcast MP3), the system skips video extraction and goes straight to transcription. Caption rendering in Phase 4 will use a plain background in this case, since there's no video to overlay onto.

---

## Step 2 — Audio Extraction

Even when we have a video file, we extract audio separately before transcribing. Reasons:
- Audio files are 10-50x smaller than video — faster to process
- Whisper only needs audio — no point feeding it video frames
- We can normalize and clean the audio independently of the video

**Tool: ffmpeg**

```bash
ffmpeg \
  -i input_video.mp4 \
  -vn \                        # no video
  -acodec pcm_s16le \          # uncompressed PCM, what Whisper prefers
  -ar 16000 \                  # 16kHz sample rate (Whisper's native rate)
  -ac 1 \                      # mono (stereo gives no benefit for speech)
  output_audio.wav
```

**Why WAV over MP3:**
Whisper processes raw PCM audio internally. Feeding it WAV (already uncompressed) avoids a lossy decode step. The file is larger but processing is cleaner.

**Why 16kHz:**
Whisper was trained on 16kHz audio. Feeding higher sample rates forces a resample internally. We do it explicitly here to control quality.

**Python implementation:**
```python
import subprocess
import os

def extract_audio(video_path: str, output_dir: str) -> str:
    audio_path = os.path.join(output_dir, 'audio.wav')
    cmd = [
        'ffmpeg', '-i', video_path,
        '-vn',
        '-acodec', 'pcm_s16le',
        '-ar', '16000',
        '-ac', '1',
        audio_path,
        '-y'  # overwrite if exists
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return audio_path
```

---

## Step 3 — Audio Preprocessing

Raw podcast audio has problems that hurt transcription accuracy:
- Volume inconsistency between speakers
- Background music (common in podcast intros/outros)
- Room echo or reverb
- Two speakers at different volume levels (remote guest vs in-studio host)

We apply targeted preprocessing before passing to Whisper.

### 3a — Volume Normalization

Equalizes volume across the entire file so quiet segments get transcribed as accurately as loud ones.

```bash
ffmpeg -i audio.wav -af "loudnorm=I=-16:TP=-1.5:LRA=11" normalized.wav
```

`loudnorm` is ffmpeg's implementation of the EBU R128 loudness normalization standard. It's the industry standard for broadcast audio.

### 3b — Noise Reduction (Optional, CPU-intensive)

For low-quality recordings, we can apply noise reduction using `noisereduce` Python library:

```python
import noisereduce as nr
import soundfile as sf
import numpy as np

def reduce_noise(audio_path: str) -> str:
    data, rate = sf.read(audio_path)
    # Use first 0.5 seconds as noise profile (usually silence/room tone)
    noise_sample = data[:rate // 2]
    reduced = nr.reduce_noise(y=data, sr=rate, y_noise=noise_sample)
    output_path = audio_path.replace('.wav', '_clean.wav')
    sf.write(output_path, reduced, rate)
    return output_path
```

This is optional and toggled in settings. For clean studio podcasts it's not needed. For phone call recordings it makes a big difference.

### 3c — VAD (Voice Activity Detection) Pre-Scan

Before transcription, we run a fast Voice Activity Detection pass to identify segments of actual speech vs silence vs music. This serves two purposes:

1. We can warn the user if >30% of the file is music/silence (common in podcasts with long intros)
2. We can skip non-speech segments to speed up transcription

**Tool: Silero VAD** (bundled with faster-whisper, or standalone)

```python
# faster-whisper has VAD built in — we enable it at transcription time
# vad_filter=True in the transcribe() call
```

---

## Step 4 — Transcription

This is the most critical and most resource-intensive step.

### The Whisper Landscape (What We're Working With)

There are four main options and it matters which one we pick:

| Variant | Speed | Word Timestamps | Speaker Labels | Best For |
|---|---|---|---|---|
| openai/whisper | Slow | Approximate | No | Reference only |
| faster-whisper | 4x faster | Good | No | Our default |
| WhisperX | 2-3x faster | Excellent (wav2vec2 forced alignment) | Yes (optional) | When we need perfect captions |
| whisper-turbo | 8x faster | Approximate | No | Quick previews |

**Our recommendation: faster-whisper as the primary engine, with WhisperX available as an optional high-accuracy mode.**

### Why faster-whisper is the right default

- Uses CTranslate2 (C++ inference engine) instead of PyTorch — 4x faster with same accuracy
- Supports INT8 quantization — runs on CPU without GPU and still performs well
- Has built-in Silero VAD integration (automatically skips silence)
- Supports word-level timestamps natively
- Actively maintained, works on any machine
- No GPU required (critical if users are running on a regular laptop)

### Model Selection

Whisper comes in multiple sizes. For our use case:

| Model | VRAM | Speed | Accuracy | Recommendation |
|---|---|---|---|---|
| tiny | 1GB | Very fast | Low | Not suitable |
| base | 1GB | Fast | Decent | Not suitable |
| small | 2GB | Fast | Good | Testing/preview |
| medium | 5GB | Medium | Very good | Production (CPU) |
| large-v3 | 10GB | Slow | Best | Production (GPU) |
| large-v3-turbo | 6GB | Fast | Near-large | Best all-around |

**Default: `large-v3-turbo`** — nearly the accuracy of large-v3 at 8x the speed. This is OpenAI's October 2024 release and the sweet spot for our use case.

**Fallback for CPU-only machines: `medium`** — still excellent for English podcast content.

### The Chunking Problem (Why 2-Hour Files Are Tricky)

Whisper's core model window is 30 seconds. Everything longer is handled by the inference wrapper, not the model itself.

**The issue:** When processing long files naively, Whisper can:
- Hallucinate phrases that weren't said (especially in silence or music)
- Drift on timestamps over time
- Run out of memory on machines with <16GB RAM

**Our solution: faster-whisper's built-in chunked pipeline with VAD**

faster-whisper handles long files correctly by:
1. Running VAD to find speech segments
2. Chunking on silence boundaries (not arbitrary 30-second cuts)
3. Processing each chunk with a 30-second overlap between neighbors
4. Stitching transcripts at boundaries without mid-word cuts

The key is using `vad_filter=True` which ensures chunks are cut at natural silence points, not mid-sentence.

**For files over 2 hours (memory management):**

Large video files can require 500MB+ of RAM for the PCM audio array alone. We handle this by:

```python
# Process audio in 30-minute segments, then merge transcripts
SEGMENT_DURATION = 30 * 60  # 30 minutes in seconds
```

This keeps memory usage under 200MB per segment.

### Full Transcription Implementation

```python
from faster_whisper import WhisperModel
import json

def transcribe_audio(
    audio_path: str,
    model_size: str = "large-v3-turbo",
    device: str = "auto",  # auto-detects CPU vs GPU
    language: str = "en"
) -> dict:
    
    # Load model (cached after first load)
    compute_type = "int8" if device == "cpu" else "float16"
    model = WhisperModel(model_size, device=device, compute_type=compute_type)
    
    # Transcribe with all critical options
    segments, info = model.transcribe(
        audio_path,
        language=language,
        word_timestamps=True,       # CRITICAL for caption sync
        vad_filter=True,            # Skip silence, prevent hallucinations
        vad_parameters={
            "min_silence_duration_ms": 500,   # 0.5s silence = chunk boundary
            "speech_pad_ms": 400,              # pad edges so words aren't cut
        },
        beam_size=5,                # default, balances speed vs accuracy
        condition_on_previous_text=True,  # uses context for better accuracy
    )
    
    # Build structured output
    transcript = {
        "language": info.language,
        "duration": info.duration,
        "segments": [],
        "words": []  # flat word list for easy lookup
    }
    
    for segment in segments:
        seg_data = {
            "id": segment.id,
            "start": segment.start,
            "end": segment.end,
            "text": segment.text.strip(),
            "words": []
        }
        
        for word in segment.words:
            word_data = {
                "word": word.word.strip(),
                "start": word.start,
                "end": word.end,
                "probability": word.probability  # confidence score
            }
            seg_data["words"].append(word_data)
            transcript["words"].append({**word_data, "segment_id": segment.id})
        
        transcript["segments"].append(seg_data)
    
    return transcript
```

### WhisperX Mode (High-Accuracy, Optional)

For users who want frame-perfect caption timing (karaoke style), we offer WhisperX as an alternative. It uses wav2vec2 forced alignment after transcription to achieve millisecond-accurate word timestamps.

```python
import whisperx

def transcribe_whisperx(audio_path: str, device: str = "cpu") -> dict:
    model = whisperx.load_model("large-v3-turbo", device=device)
    result = model.transcribe(audio_path, batch_size=8)
    
    # Forced alignment for word-level timestamps
    model_a, metadata = whisperx.load_align_model(
        language_code=result["language"], device=device
    )
    result = whisperx.align(
        result["segments"], model_a, metadata, audio_path, device
    )
    
    return result
```

WhisperX is heavier to install (requires pyannote-audio for optional diarization) so we make it optional, not default.

---

## Step 5 — Transcript Post-Processing

Raw Whisper output has several problems we need to clean before passing to Phase 2.

### 5a — Filler Word Handling

Whisper transcribes "um", "uh", "like", "you know" etc. We don't delete them — we flag them. The AI brain in Phase 2 uses filler density to score clip quality (lots of fillers = rambling = bad clip).

```python
FILLERS = {"um", "uh", "like", "you know", "i mean", "basically", "literally", "right"}

def flag_fillers(words: list) -> list:
    for word in words:
        word['is_filler'] = word['word'].lower().strip(',.?!') in FILLERS
    return words
```

### 5b — Thought Block Segmentation

Raw Whisper gives us sentence-level segments. For Phase 2 we need to group these into "thought blocks" — logical units of meaning that could stand alone as a clip.

We detect thought boundaries using:
- Pause duration between segments (>1.5 seconds = likely topic shift)
- Sentence-ending punctuation followed by a pause
- Speaker transitions (if we have diarization)

```python
def segment_thought_blocks(segments: list, min_pause: float = 1.5) -> list:
    blocks = []
    current_block = []
    
    for i, seg in enumerate(segments):
        current_block.append(seg)
        
        if i < len(segments) - 1:
            pause = segments[i+1]['start'] - seg['end']
            ends_sentence = seg['text'].strip()[-1] in '.?!'
            
            if pause > min_pause and ends_sentence:
                blocks.append({
                    'start': current_block[0]['start'],
                    'end': current_block[-1]['end'],
                    'text': ' '.join(s['text'] for s in current_block),
                    'segments': current_block,
                    'filler_ratio': sum(
                        1 for s in current_block 
                        for w in s.get('words', []) 
                        if w.get('is_filler')
                    ) / max(sum(len(s.get('words', [])) for s in current_block), 1)
                })
                current_block = []
    
    if current_block:
        blocks.append({
            'start': current_block[0]['start'],
            'end': current_block[-1]['end'],
            'text': ' '.join(s['text'] for s in current_block),
            'segments': current_block,
        })
    
    return blocks
```

### 5c — Confidence Filtering

Whisper assigns a probability score to each word. Low-probability words indicate either background noise, crosstalk, or actual low-confidence transcription. We flag segments with average word confidence below 0.7 for review.

```python
def flag_low_confidence(segments: list, threshold: float = 0.7) -> list:
    for seg in segments:
        words = seg.get('words', [])
        if words:
            avg_conf = sum(w.get('probability', 1.0) for w in words) / len(words)
            seg['confidence'] = avg_conf
            seg['low_confidence'] = avg_conf < threshold
    return segments
```

### 5d — Chapter Integration

If the video had chapters (from YouTube or podcast metadata), we merge those into the transcript. This gives the Phase 2 AI structural context — "this section is about X" — which dramatically improves clip selection.

```python
def inject_chapter_markers(transcript: dict, chapters: list) -> dict:
    for seg in transcript['segments']:
        seg['chapter'] = None
        for chapter in chapters:
            if chapter['start_time'] <= seg['start'] <= chapter['end_time']:
                seg['chapter'] = chapter['title']
                break
    return transcript
```

---

## Final Output — Master Transcript JSON

The output of Phase 1 is a single JSON file that gets saved alongside the video. Everything Phase 2 needs is in here.

```json
{
  "source": {
    "type": "youtube",
    "url": "https://youtube.com/...",
    "title": "Jack Neel on Elliott Bewick Podcast",
    "duration": 7234.5,
    "downloaded_at": "2026-02-21T18:33:00Z"
  },
  "transcription": {
    "model": "large-v3-turbo",
    "language": "en",
    "processing_time_seconds": 210
  },
  "thought_blocks": [
    {
      "id": 0,
      "start": 0.0,
      "end": 45.2,
      "text": "The biggest mistake I see entrepreneurs make...",
      "filler_ratio": 0.03,
      "confidence": 0.94,
      "chapter": "Entrepreneurship Mistakes",
      "segments": [...]
    }
  ],
  "words": [
    {
      "word": "The",
      "start": 0.0,
      "end": 0.12,
      "probability": 0.99,
      "segment_id": 0,
      "is_filler": false
    }
  ]
}
```

---

## Requirements & Dependencies

### Python Packages

```
faster-whisper>=1.0.0
whisperx>=3.1.0          # optional, high-accuracy mode
yt-dlp>=2024.12.0
noisereduce>=3.0.0
soundfile>=0.12.0
numpy>=1.24.0
```

### System Dependencies

```bash
# Ubuntu/Debian
sudo apt install ffmpeg

# macOS
brew install ffmpeg

# Windows
# Download from gyan.dev, add to PATH
```

### Hardware Requirements

| Mode | CPU | RAM | GPU | Processing Time (2hr podcast) |
|---|---|---|---|---|
| Minimum | Any modern CPU | 8GB | None | ~45 mins |
| Recommended | 8+ core CPU | 16GB | None | ~20 mins |
| Fast | Any | 16GB | NVIDIA 8GB VRAM | ~5 mins |
| Ultra | Any | 32GB | NVIDIA 16GB+ | ~2 mins |

For most users running this locally, the CPU path with `large-v3-turbo` on 16GB RAM is the right choice. Runtime of ~20 minutes for a 2-hour podcast is perfectly acceptable since transcription runs in the background while the dashboard shows a progress bar.

---

## File & Folder Structure for Phase 1

```
/projects/
  /{project_id}/
    /raw/
      video.mp4              ← original download or upload
      audio.wav              ← extracted audio (16kHz mono)
      audio_normalized.wav   ← preprocessed audio
      info.json              ← yt-dlp metadata
    /transcripts/
      transcript_raw.json    ← raw whisper output
      transcript.json        ← processed master transcript (Phase 1 output)
```

---

## Error Handling & Edge Cases

| Scenario | Handling |
|---|---|
| URL is private/age-gated | Return clear error, prompt user to upload cookies or use file upload |
| File is audio-only (MP3) | Skip video extraction, use audio directly, flag for Phase 3 (no video to clip) |
| File >10GB | Warn user, offer to process anyway with extended time estimate |
| Transcription confidence <60% on >30% of file | Flag entire transcript as low quality, recommend better source |
| Language detected as non-English | Alert user, offer to continue or switch language model |
| Whisper hallucinates (repetitive phrases) | Detect loops via duplicate text detection, remove and flag |
| No speech detected | Return error immediately, don't waste time transcribing music |

---

## Progress Reporting (For Dashboard)

Phase 1 is the longest-running step. The dashboard must show meaningful progress, not just a spinner.

```python
PHASE_1_STAGES = [
    {"id": "download",    "label": "Downloading video",        "weight": 0.20},
    {"id": "extract",     "label": "Extracting audio",         "weight": 0.05},
    {"id": "preprocess",  "label": "Preprocessing audio",      "weight": 0.05},
    {"id": "transcribe",  "label": "Transcribing (this takes a while)", "weight": 0.60},
    {"id": "postprocess", "label": "Processing transcript",    "weight": 0.10},
]
```

Transcription progress is estimated using `info.duration` from yt-dlp vs elapsed processing time, updated every 30 seconds.

---

## What Phase 2 Receives

A clean, structured `transcript.json` containing:

- Every spoken word with millisecond timestamps
- Thought blocks with filler ratios and confidence scores
- Chapter markers from source metadata
- Full text for AI context window
- All source metadata (title, duration, creator)

Phase 2 reads this file and begins the AI clip selection process.