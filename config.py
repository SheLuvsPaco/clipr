"""
Central configuration for the Clipping Tool.
All paths, limits, and defaults in one place.
"""

import os

# ─── Base Paths ───────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECTS_DIR = os.path.join(BASE_DIR, "projects")

# ─── File Validation ─────────────────────────────────────────
SUPPORTED_VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".webm"}
SUPPORTED_AUDIO_EXTENSIONS = {".mp3", ".m4a", ".wav", ".flac", ".ogg"}
SUPPORTED_EXTENSIONS = SUPPORTED_VIDEO_EXTENSIONS | SUPPORTED_AUDIO_EXTENSIONS

MAX_FILE_SIZE_GB = 10
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_GB * 1024 * 1024 * 1024  # 10 GB

# ─── Transcription Defaults ──────────────────────────────────
DEFAULT_MODEL_SIZE = "large-v3-turbo"
FALLBACK_MODEL_SIZE = "medium"  # For CPU-only / low-RAM machines
DEFAULT_LANGUAGE = "en"
DEFAULT_BEAM_SIZE = 5

# Modal Cloud GPU — Set to True to use Modal GPU for transcription
# When False, transcription runs locally (can be very slow on CPU)
USE_MODAL = os.getenv("USE_MODAL", "true").lower() == "true"

# VAD Parameters
VAD_MIN_SILENCE_MS = 500   # 0.5s silence = chunk boundary
VAD_SPEECH_PAD_MS = 400    # pad edges so words aren't cut

# ─── Audio Preprocessing ─────────────────────────────────────
AUDIO_SAMPLE_RATE = 16000  # 16kHz — Whisper's native rate
AUDIO_CHANNELS = 1         # Mono

# Loudnorm (EBU R128)
LOUDNORM_TARGET_I = -16
LOUDNORM_TARGET_TP = -1.5
LOUDNORM_TARGET_LRA = 11

# ─── Post-Processing ─────────────────────────────────────────
FILLER_WORDS = {
    "um", "uh", "like", "you know", "i mean",
    "basically", "literally", "right", "so", "well",
    "actually", "kind of", "sort of",
}

THOUGHT_BLOCK_MIN_PAUSE = 1.5  # seconds
LOW_CONFIDENCE_THRESHOLD = 0.7

# ─── Progress Stages ─────────────────────────────────────────
PHASE_1_STAGES = [
    {"id": "download",    "label": "Downloading video",                    "weight": 0.20},
    {"id": "extract",     "label": "Extracting audio",                     "weight": 0.05},
    {"id": "preprocess",  "label": "Preprocessing audio",                  "weight": 0.05},
    {"id": "transcribe",  "label": "Transcribing (this takes a while)",    "weight": 0.60},
    {"id": "postprocess", "label": "Processing transcript",                "weight": 0.10},
]

# ─── Phase 2 — AI Clip Selection ─────────────────────────────
GROQ_MODEL = "llama-3.3-70b-versatile"
GROQ_TEMPERATURE_DISCOVERY = 0.2   # Low for consistent scanning
GROQ_TEMPERATURE_SCORING = 0.3    # Slightly higher for creative reasoning
GROQ_MAX_TOKENS_DISCOVERY = 4000
GROQ_MAX_TOKENS_SCORING = 1000
CONTEXT_EXPANSION_SECONDS = 30.0   # ±30s context for deep scoring
DIVERSITY_MIN_GAP_SECONDS = 300.0  # 5 minutes between clips
DEFAULT_MAX_CLIPS = 10

PHASE_2_STAGES = [
    {"id": "discovery",  "label": "AI scanning for clip candidates",   "weight": 0.30},
    {"id": "scoring",    "label": "Deep scoring each candidate",       "weight": 0.60},
    {"id": "ranking",    "label": "Ranking and filtering results",     "weight": 0.10},
]

# ─── Phase 3 — Clip Cutting & Video Processing ──────────────
DEFAULT_JUMP_CUT_SETTINGS = {
    "enabled": True,
    "max_pause_ms": 300,       # Natural: tight but human
    "remove_fillers": True,
}

DEFAULT_GRADE_PRESET = "standard"

PHASE_3_STAGES = [
    {"id": "cutting",      "label": "Frame-accurate raw cut",       "weight": 0.05},
    {"id": "jump_cutting", "label": "Jump cut editing",             "weight": 0.10},
    {"id": "analysing",    "label": "Layout analysis",              "weight": 0.05},
    {"id": "tracking",     "label": "Face tracking",                "weight": 0.13},
    {"id": "cropping",     "label": "Dynamic crop + zoom",          "weight": 0.30},
    {"id": "normalising",  "label": "Audio normalisation",          "weight": 0.07},
    {"id": "encoding",     "label": "Final platform encode",        "weight": 0.30},
]

# ─── Phase 4 — Caption Rendering ─────────────────────────────
DEFAULT_CAPTION_STYLE = "hormozi"

PHASE_4_STAGES = [
    {"id": "filtering",  "label": "Filtering words",         "weight": 0.05},
    {"id": "rendering",  "label": "Burning captions",        "weight": 0.85},
    {"id": "saving",     "label": "Saving ASS file",         "weight": 0.10},
]

# ─── Ensure projects directory exists ─────────────────────────
os.makedirs(PROJECTS_DIR, exist_ok=True)
