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
def transcribe_audio(
    audio_bytes: bytes,
    filename: str,
    model_size: str = "large-v3-turbo",
    language: str = "en",
) -> dict:
    """
    Receives raw audio bytes, transcribes with faster-whisper large-v3,
    returns a structured dict with word-level timestamps and filler flags.

    This output matches the format expected by the local pipeline's
    postprocess_transcript() function.

    Parameters:
        audio_bytes: raw bytes of the audio/video file
        filename:    original filename including extension (used to write
                     a temp file with the correct extension so ffmpeg
                     inside faster-whisper can parse the format)
        model_size:  Whisper model size (default: large-v3-turbo to match local)
        language:    Language code (default: "en")

    Returns:
        {
            "language": str,
            "language_probability": float,
            "duration": float,           # seconds
            "segments": [                # for compatibility with local pipeline
                {
                    "id": int,
                    "start": float,
                    "end": float,
                    "text": str,
                    "words": [...]
                }
            ],
            "words": [                   # flat word list
                {
                    "word": str,
                    "start": float,
                    "end": float,
                    "probability": float,
                    "segment_id": int,
                }
            ],
            "processing_time_seconds": float,
        }
    """
    import os
    import tempfile
    import time
    from faster_whisper import WhisperModel

    # Words to flag as fillers for the jump cut system in Phase 3
    FILLERS = {
        "um", "uh", "like", "you know", "sort of", "i mean",
        "basically", "literally", "actually", "right", "okay",
        "hmm", "hm", "ah", "er",
    }

    # Load model — uses the mounted volume as cache dir
    # On first run this downloads ~3GB. On subsequent runs it loads in ~10s.
    print(f"Loading Whisper {model_size}...")
    load_start = time.time()

    model = WhisperModel(
        model_size,
        device="cuda",
        compute_type="float16",           # GPU uses float16 (not int8 like CPU)
        download_root=MODEL_CACHE_DIR,
    )

    print(f"Model loaded in {time.time() - load_start:.1f}s")

    # Write audio bytes to a temp file so faster-whisper can open it
    ext = os.path.splitext(filename)[-1] or ".mp3"
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as f:
        f.write(audio_bytes)
        tmp_path = f.name

    size_mb = len(audio_bytes) / 1024 / 1024
    print(f"Transcribing {filename} ({size_mb:.1f} MB)...")

    transcribe_start = time.time()

    # Transcribe with same settings as local pipeline for consistency
    segments_gen, info = model.transcribe(
        tmp_path,
        language=language,
        word_timestamps=True,             # CRITICAL for caption sync
        vad_filter=True,                  # Skip silence, prevent hallucinations
        vad_parameters={
            "min_silence_duration_ms": 500,   # 0.5s silence = chunk boundary
            "speech_pad_ms": 400,             # pad edges so words aren't cut
        },
        beam_size=5,                      # balances speed vs accuracy
        condition_on_previous_text=True,  # uses context for better accuracy
    )

    # Build structured output that matches local transcriber format
    transcript = {
        "language": info.language,
        "language_probability": info.language_probability,
        "duration": info.duration,
        "segments": [],
        "words": [],  # flat word list for easy lookup
    }

    for segment in segments_gen:
        seg_data = {
            "id": segment.id,
            "start": round(segment.start, 3),
            "end": round(segment.end, 3),
            "text": segment.text.strip(),
            "words": [],
        }

        if segment.words:
            for word in segment.words:
                word_data = {
                    "word": word.word.strip(),
                    "start": round(word.start, 3),
                    "end": round(word.end, 3),
                    "probability": round(word.probability, 4),
                }
                seg_data["words"].append(word_data)

                # Add to flat word list with segment_id for downstream compatibility
                transcript["words"].append({
                    **word_data,
                    "segment_id": segment.id,
                })

        transcript["segments"].append(seg_data)

    processing_time = time.time() - transcribe_start
    transcript["processing_time_seconds"] = round(processing_time, 1)

    # Clean up temp file
    os.remove(tmp_path)

    print(f"Done. Language: {info.language}, Words: {len(transcript['words'])}, "
          f"Duration: {info.duration:.1f}s, Time: {processing_time:.1f}s")

    return transcript


# ── Local entrypoint for CLI testing ─────────────────────────────────────────
# Used for testing only — not called by FastAPI.
# Run with: modal run modal_transcribe.py --audio-file /path/to/audio.mp3

@app.local_entrypoint()
def main(audio_file: str, model_size: str = "large-v3-turbo"):
    import json
    import os

    if not os.path.exists(audio_file):
        print(f"Error: file not found: {audio_file}")
        return

    with open(audio_file, "rb") as f:
        audio_bytes = f.read()

    print(f"Sending {len(audio_bytes) / 1024 / 1024:.1f} MB to Modal GPU...")
    print(f"Model: {model_size}")

    result = transcribe_audio.remote(audio_bytes, os.path.basename(audio_file), model_size)

    output_path = audio_file.rsplit(".", 1)[0] + "_transcript.json"
    with open(output_path, "w") as f:
        json.dump(result, f, indent=2)

    print(f"\n✅ Transcript saved to: {output_path}")
    print(f"   Words: {len(result['words'])}")
    print(f"   Duration: {result['duration']:.1f}s")
    print(f"   Language: {result['language']} (confidence: {result['language_probability']:.1%})")
    print(f"   Processing time: {result['processing_time_seconds']:.1f}s")
