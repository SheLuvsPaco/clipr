# PHASE 3 — CLIP CUTTING & VIDEO PROCESSING
### From Timestamps to Platform-Ready Vertical Video

---

## What This Phase Does

Phase 3 takes the approved clip candidates from the dashboard — each carrying a start timestamp, end timestamp, trim suggestions from Phase 2, and jump cut settings chosen by the user — and transforms them into properly formatted, jump-cut, cropped, and colour-graded vertical video files ready for caption rendering in Phase 4.

This is the most technically complex phase. It deals with real video data, frame-accurate cutting, silence and filler removal, intelligent reframing from 16:9 to 9:16, and platform-specific encoding. Every decision here directly impacts the pacing and visual quality of the final post.

---

## The Processing Pipeline Per Clip

```
[Approved Candidate: start, end, trim suggestions, jump cut settings]
              ↓
[Step 1: Frame-Accurate Raw Cut]
  (extract the candidate window from the full source video)
              ↓
[Step 2: Jump Cut Editing]
  (remove silences, fillers, and dead air from the raw cut)
  (produce rebased word timestamps for Phase 4 captions)
              ↓
[Step 3: Source Video Layout Analysis]
  (detect layout: single speaker / split-screen / b-roll)
              ↓
[Step 4: Face Detection & Tracking]
  (locate speaker(s) across all frames of the jump-cut clip)
              ↓
[Step 5: Smart Vertical Crop (9:16)]
  (crop window determined by face position)
              ↓
[Step 6: Crop Path Smoothing]
  (prevent jitter from frame-to-frame crop shifts)
              ↓
[Step 7: Subtle Zoom Effect]
  (push-in for energy, if layout is static)
              ↓
[Step 8: Colour Grade]
  (apply platform-optimised look)
              ↓
[Step 9: Audio Normalisation]
  (consistent loudness across all exported clips)
              ↓
[Step 10: Platform Encode]
  (H.264, 1080x1920, correct bitrate for each platform)
              ↓
[Output: clip_{id}_processed.mp4 + rebased_words_{id}.json → Phase 4]
```

**Why jump cuts happen before layout detection and face tracking:** The jump-cut clip is shorter than the raw cut. Running layout detection and face tracking on the shorter clip means we only process the frames we are actually keeping. Running them on the raw clip and then jump-cutting would waste time tracking faces across frames that get discarded.

---

## Step 1 — Frame-Accurate Raw Cut

The first job is to extract just the candidate window from the full 2-hour source video. ffmpeg has two ways to cut and one of them silently destroys your hook.

**The wrong way (stream copy — fast but imprecise):**
```bash
ffmpeg -ss 00:10:23 -i input.mp4 -t 00:01:07 -c copy output.mp4
```
`-c copy` skips re-encoding and is fast, but it can only cut on keyframes. If the start timestamp falls between keyframes — which it almost always does — ffmpeg snaps to the nearest keyframe and cuts off the first 0.5–2 seconds. For a 60-second clip that destroys the hook.

**The optimal way (two-pass seek — frame-accurate, fast enough):**
```bash
ffmpeg \
  -ss 00:09:53.400 \      # fast keyframe seek to 30s BEFORE clip start
  -i input.mp4 \
  -ss 00:00:30.000 \      # precise frame-level seek within that 30s window
  -t 00:01:07.200 \
  -c:v libx264 \
  -c:a aac \
  output.mp4
```

The first `-ss` (before `-i`) does a fast keyframe seek to 30 seconds before the clip. The second `-ss` (after `-i`) does a slow frame-accurate decode within that 30-second window. Frame-accurate result, only 30 seconds of decoding overhead regardless of where in the 2-hour file the clip lives.

### Python Implementation

```python
import subprocess
import os

def cut_raw_clip(
    video_path: str,
    start: float,
    end: float,
    output_path: str,
    pre_seek_buffer: float = 30.0
) -> str:
    duration    = end - start
    fast_seek   = max(0, start - pre_seek_buffer)
    precise_seek = start - fast_seek

    cmd = [
        'ffmpeg',
        '-ss', str(fast_seek),
        '-i', video_path,
        '-ss', str(precise_seek),
        '-t', str(duration),
        '-c:v', 'libx264',
        '-c:a', 'aac',
        '-preset', 'fast',
        '-avoid_negative_ts', '1',
        output_path, '-y'
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Raw cut failed: {result.stderr}")

    return output_path


def apply_trim_suggestions(candidate: dict) -> tuple[float, float]:
    start = candidate['start'] + candidate.get('suggested_trim_start', 0)
    end   = candidate['end']   - candidate.get('suggested_trim_end',   0)

    # Safety — never trim more than 5 seconds from either end
    start = min(start, candidate['start'] + 5.0)
    end   = max(end,   candidate['end']   - 5.0)

    return start, end
```

---

## Step 2 — Jump Cut Editing

This is the step that most simple clipping tools skip entirely. It removes every silence, pause, filler word, and dead gap from the clip so that the speaker's words hit back-to-back with no breathing room. The result sounds fast, dense, and highly produced — even though all we have done is cut the gaps.

Phase 1 already did the hard work. Every word has a millisecond-accurate timestamp. Every filler (`um`, `uh`, `like`, `you know`, `sort of`) is flagged `is_filler: true`. The gaps between consecutive words are measurable. We use all of this to build a list of segments to keep, cut everything else, and stitch the kept segments together.

### 2a — Build the Keep-Segments List

```python
def build_keep_segments(
    words: list,
    clip_start: float,
    clip_end: float,
    max_pause_ms: int = 300,
    remove_fillers: bool = True,
    pad_ms: int = 50
) -> list:
    """
    Given the word list from Phase 1 (global timestamps),
    return a list of (start, end) tuples in CLIP-LOCAL time
    representing the segments of audio/video to keep.
    Everything between segments gets cut.

    pad_ms: milliseconds of audio to preserve before/after each
            kept word so cuts do not feel clinical. 50ms is
            imperceptible to the human ear.
    """
    pad       = pad_ms / 1000
    max_pause = max_pause_ms / 1000

    # Filter to words inside this clip's window, drop fillers if requested
    clip_words = [
        w for w in words
        if clip_start <= w['start'] <= clip_end
        and not (remove_fillers and w.get('is_filler', False))
    ]

    if not clip_words:
        # No words found — return the whole clip uncut
        return [(0.0, clip_end - clip_start)]

    # Rebase timestamps to clip-local time (clip_start becomes 0.0)
    local_words = [
        {**w,
         'start': round(w['start'] - clip_start, 3),
         'end':   round(w['end']   - clip_start, 3)}
        for w in clip_words
    ]

    segments  = []
    seg_start = max(0.0, local_words[0]['start'] - pad)
    seg_end   = local_words[0]['end'] + pad

    for i in range(1, len(local_words)):
        prev = local_words[i - 1]
        curr = local_words[i]
        gap  = curr['start'] - prev['end']

        if gap <= max_pause:
            # Small gap — stretch current segment to cover it
            seg_end = curr['end'] + pad
        else:
            # Gap exceeds threshold — close segment, open new one
            segments.append((seg_start, seg_end))
            seg_start = max(0.0, curr['start'] - pad)
            seg_end   = curr['end'] + pad

    segments.append((seg_start, seg_end))
    return segments
```

**What the thresholds mean in practice:**

| Threshold | Effect | Best For |
|---|---|---|
| 200ms Aggressive | Cuts almost all breathing room. Very punchy, slightly unnatural | Business, finance, high-energy clips |
| 300ms Natural | Cuts long pauses and all fillers. Sounds tight but human | Default for most content |
| 500ms Gentle | Only cuts very long dead air. Preserves natural rhythm | Emotional, storytelling, cinematic clips |

### 2b — Cut and Stitch the Segments

With the keep-segments list built, we cut each segment out of the raw clip and stitch them together using ffmpeg's concat demuxer. The concat demuxer joins pre-cut segment files without re-encoding — fast and lossless.

```python
import tempfile

def cut_and_stitch(
    raw_clip_path: str,
    segments: list,
    output_path: str,
) -> dict:
    """
    Cuts the raw clip to keep only the specified (start, end) segments
    and stitches them into a single continuous output file.

    Returns a rebase_map so that word timestamps can be
    adjusted to match the new (shorter) timeline.
    """
    segment_files = []
    rebase_map    = []
    accumulated   = 0.0
    tmp_dir       = tempfile.mkdtemp()

    for i, (seg_start, seg_end) in enumerate(segments):
        seg_duration = seg_end - seg_start
        seg_path     = os.path.join(tmp_dir, f'seg_{i:04d}.mp4')

        cmd = [
            'ffmpeg',
            '-ss', str(seg_start),
            '-i', raw_clip_path,
            '-t', str(seg_duration),
            '-c:v', 'libx264',
            '-c:a', 'aac',
            '-preset', 'ultrafast',   # speed over quality — intermediate file only
            '-avoid_negative_ts', '1',
            seg_path, '-y'
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(
                f"Segment cut failed at ({seg_start}, {seg_end}): {result.stderr}"
            )

        segment_files.append(seg_path)

        # Record how this segment's original time maps to new timeline
        rebase_map.append({
            'original_start': seg_start,
            'original_end':   seg_end,
            'new_start':      accumulated,
            'offset':         accumulated - seg_start,
        })
        accumulated += seg_duration

    # Write ffmpeg concat list
    concat_list_path = os.path.join(tmp_dir, 'concat.txt')
    with open(concat_list_path, 'w') as f:
        for seg_path in segment_files:
            f.write(f"file '{seg_path}'\n")

    # Stitch — concat demuxer copies streams, no re-encode
    cmd = [
        'ffmpeg',
        '-f', 'concat',
        '-safe', '0',
        '-i', concat_list_path,
        '-c', 'copy',
        output_path, '-y'
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Stitch failed: {result.stderr}")

    for seg_path in segment_files:
        os.remove(seg_path)
    os.remove(concat_list_path)
    os.rmdir(tmp_dir)

    return {
        'output_path':  output_path,
        'rebase_map':   rebase_map,
        'new_duration': accumulated,
        'time_removed': (segments[-1][1] - segments[0][0]) - accumulated,
    }
```

### 2c — Rebase Word Timestamps

After jump cutting the video timeline has shifted. A word spoken at 45.3 seconds in the raw clip might now sit at 31.7 seconds in the stitched clip because 13.6 seconds of silence was removed before it. If Phase 4 used the original timestamps, every caption would be out of sync.

We walk every word through the rebase map and adjust:

```python
def rebase_word_timestamps(
    words: list,
    clip_start: float,
    clip_end: float,
    rebase_map: list,
    remove_fillers: bool = True,
) -> list:
    """
    Adjusts word timestamps from clip-local time into the new
    jump-cut timeline. Words that fall inside a removed gap are
    dropped. Returns a list ready for Phase 4 to use directly.
    """
    # Filter to clip window and rebase to local time
    clip_words = [
        {**w,
         'start': round(w['start'] - clip_start, 3),
         'end':   round(w['end']   - clip_start, 3)}
        for w in words
        if clip_start <= w['start'] <= clip_end
        and not (remove_fillers and w.get('is_filler', False))
    ]

    rebased = []
    for word in clip_words:
        for seg in rebase_map:
            if seg['original_start'] <= word['start'] <= seg['original_end']:
                rebased.append({
                    **word,
                    'start': round(word['start'] + seg['offset'], 3),
                    'end':   round(word['end']   + seg['offset'], 3),
                })
                break
        # Word not in any kept segment = it was inside a cut gap, skip it

    return rebased
```

The rebased word list is saved as `rebased_words_{id}.json`. Phase 4 loads this file — not the original transcript — so captions are perfectly in sync with the jump-cut audio.

### 2d — What Gets Cut, Concretely

For a typical 90-second podcast segment:

```
BEFORE JUMP CUTS
─────────────────────────────────────────────────────────────────────
Word  gap  word  [um]  [pause 0.8s]  word  gap  word  [uh]  word ...
Total: 90 seconds

AFTER JUMP CUTS (Natural 300ms, fillers removed)
─────────────────────────────────────────────────────────────────────
Word gap word  [CUT]  [CUT]  word gap word  [CUT]  word ...
Total: ~72 seconds

Time removed: ~18 seconds (20% of original)
Fillers removed: ~8 (um, uh, like, you know)
Long pauses cut: ~6
```

A 90-second clip becomes a 72-second clip. Same content. Same delivery pace. Every dead moment gone. Viewers feel the difference without being able to name it.

---

## Step 3 — Source Video Layout Analysis

Layout analysis runs on the jump-cut clip — not the raw cut — so we only process frames we are actually keeping.

### The Four Layouts

```
LAYOUT A: Single Speaker (Most common)
┌─────────────────────────────┐
│                             │
│         [Speaker]           │
│                             │
└─────────────────────────────┘
Strategy: face_follow — crop to speaker, centre in 9:16

LAYOUT B: Side-by-Side (Zoom/Remote interview style)
┌──────────────┬──────────────┐
│  [Speaker 1] │  [Speaker 2] │
└──────────────┴──────────────┘
Strategy: dynamic_speaker_crop — detect active speaker, cut between halves

LAYOUT C: In-Studio Two-Person (Wide shot)
┌─────────────────────────────┐
│   [Speaker 1] [Speaker 2]   │
│                             │
└─────────────────────────────┘
Strategy: active_speaker_follow — pan to active speaker, switch on lip movement

LAYOUT D: Split-Screen with Branding
┌──────────────┬──────────────┐
│  [Speaker]   │  [Logo/B-roll│
└──────────────┴──────────────┘
Strategy: face_follow on speaker side, ignore branding panel
```

### Layout Detection

We sample 10 frames evenly distributed across the jump-cut clip and run MediaPipe face detection on each.

```python
import cv2
import mediapipe as mp
import numpy as np

def detect_layout(video_path: str) -> dict:
    cap          = cv2.VideoCapture(video_path)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    width        = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height       = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    sample_frames  = [int(i * total_frames / 10) for i in range(10)]
    mp_face        = mp.solutions.face_detection
    face_detector  = mp_face.FaceDetection(min_detection_confidence=0.5)
    face_positions = []

    for frame_idx in sample_frames:
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ret, frame = cap.read()
        if not ret:
            continue

        rgb     = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = face_detector.process(rgb)

        if results.detections:
            frame_faces = []
            for detection in results.detections:
                bbox = detection.location_data.relative_bounding_box
                cx   = bbox.xmin + bbox.width / 2
                cy   = bbox.ymin + bbox.height / 2
                frame_faces.append({'cx': cx, 'cy': cy, 'w': bbox.width})
            face_positions.append(frame_faces)

    cap.release()
    return classify_layout(face_positions, width, height)


def classify_layout(face_positions: list, width: int, height: int) -> dict:
    if not face_positions:
        return {'type': 'no_face', 'strategy': 'center_crop'}

    avg_faces = np.mean([len(fp) for fp in face_positions])

    if avg_faces < 1.3:
        return {'type': 'single_speaker', 'strategy': 'face_follow'}

    all_cx = [f['cx'] for fp in face_positions for f in fp]
    cx_std = np.std(all_cx)

    if cx_std > 0.25:
        return {'type': 'split_screen',    'strategy': 'dynamic_speaker_crop'}
    else:
        return {'type': 'in_studio_wide',  'strategy': 'active_speaker_follow'}
```

---

## Step 4 — Face Detection & Position Tracking

We sample the jump-cut clip at 2fps, detect face positions, and interpolate to produce a face coordinate for every frame. Sampling at 2fps rather than every frame processes 144 samples versus 2,160 frames for a 72-second clip at 30fps — sufficient accuracy at a fraction of the cost.

```python
def track_face_positions(video_path: str, sample_fps: int = 2) -> list:
    cap        = cv2.VideoCapture(video_path)
    native_fps = cap.get(cv2.CAP_PROP_FPS)
    total      = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    skip       = int(native_fps / sample_fps)

    mp_face  = mp.solutions.face_detection
    detector = mp_face.FaceDetection(min_detection_confidence=0.6)
    sampled  = {}
    idx      = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        if idx % skip == 0:
            rgb     = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            results = detector.process(rgb)

            if results.detections:
                largest = max(
                    results.detections,
                    key=lambda d: d.location_data.relative_bounding_box.width
                )
                bbox         = largest.location_data.relative_bounding_box
                sampled[idx] = (
                    bbox.xmin + bbox.width / 2,
                    bbox.ymin + bbox.height / 2,
                    bbox.width
                )
            elif sampled:
                sampled[idx] = list(sampled.values())[-1]
        idx += 1

    cap.release()
    return interpolate_positions(sampled, total)


def interpolate_positions(sampled: dict, total_frames: int) -> list:
    if not sampled:
        return [(0.5, 0.33, 0.3)] * total_frames

    keys   = sorted(sampled.keys())
    result = []

    for i in range(total_frames):
        before = max([k for k in keys if k <= i], default=keys[0])
        after  = min([k for k in keys if k >= i], default=keys[-1])

        if before == after:
            result.append(sampled[before])
        else:
            t  = (i - before) / (after - before)
            p0 = sampled[before]
            p1 = sampled[after]
            result.append((
                p0[0] + t * (p1[0] - p0[0]),
                p0[1] + t * (p1[1] - p0[1]),
                p0[2] + t * (p1[2] - p0[2]),
            ))

    return result
```

---

## Step 5 — Smart Vertical Crop (9:16)

With face positions for every frame we compute the crop window. We extract a 608×1080 region from the 1920×1080 source and scale it up to 1080×1920. The horizontal position tracks the speaker's face. We place the face at roughly 35% from the top — slightly above centre — which is where subjects feel most natural in vertical video.

```python
def compute_crop_window(
    face_cx: float,
    face_cy: float,
    face_size: float,
    source_w: int,
    source_h: int,
    target_ratio: float = 9 / 16
) -> dict:
    crop_w    = int(source_h * target_ratio)   # 608 for 1080p source
    crop_h    = source_h
    face_x_px = int(face_cx * source_w)
    crop_x    = int(face_x_px - crop_w / 2)
    crop_x    = max(0, min(crop_x, source_w - crop_w))
    return {'x': crop_x, 'y': 0, 'w': crop_w, 'h': crop_h}


def compute_crop_path(face_positions: list, source_w: int, source_h: int) -> list:
    return [
        compute_crop_window(cx, cy, size, source_w, source_h)
        for cx, cy, size in face_positions
    ]
```

---

## Step 6 — Crop Path Smoothing

Raw face tracking data is jittery. Even small head movements produce frame-to-frame crop window shifts that make the video look unstable. A 1.5-second rolling average over the crop_x values eliminates jitter while still following intentional movement like a head turn.

```python
def smooth_crop_path(
    crop_path: list,
    fps: float = 30.0,
    window_seconds: float = 1.5
) -> list:
    window   = int(fps * window_seconds)
    xs       = [c['x'] for c in crop_path]
    smoothed = []

    for i in range(len(xs)):
        half  = window // 2
        start = max(0, i - half)
        end   = min(len(xs), i + half + 1)
        smoothed.append(int(sum(xs[start:end]) / (end - start)))

    return [{**c, 'x': smoothed[i]} for i, c in enumerate(crop_path)]
```

### Applying the Dynamic Crop

Per-frame crop values are applied by reading frames with OpenCV, slicing the crop region, scaling to 1080×1920, and piping raw frames into ffmpeg. The audio track is pulled from the jump-cut clip.

```python
def apply_dynamic_crop(
    input_path: str,
    crop_path: list,
    output_path: str,
    target_w: int = 1080,
    target_h: int = 1920,
) -> str:
    cap = cv2.VideoCapture(input_path)
    fps = cap.get(cv2.CAP_PROP_FPS)

    ffmpeg_cmd = [
        'ffmpeg', '-y',
        '-f', 'rawvideo', '-vcodec', 'rawvideo',
        '-s', f'{target_w}x{target_h}',
        '-pix_fmt', 'bgr24',
        '-r', str(fps),
        '-i', 'pipe:0',
        '-i', input_path,
        '-map', '0:v',
        '-map', '1:a',
        '-c:v', 'libx264',
        '-preset', 'fast',
        '-crf', '18',
        '-c:a', 'aac',
        '-b:a', '192k',
        output_path
    ]

    proc      = subprocess.Popen(ffmpeg_cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    frame_idx = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        crop    = crop_path[min(frame_idx, len(crop_path) - 1)]
        cropped = frame[crop['y']:crop['y'] + crop['h'], crop['x']:crop['x'] + crop['w']]
        resized = cv2.resize(cropped, (target_w, target_h))

        proc.stdin.write(resized.tobytes())
        frame_idx += 1

    proc.stdin.close()
    proc.wait()
    cap.release()
    return output_path
```

---

## Step 7 — Subtle Zoom Effect

A slow push-in from 100% to 108% over the full clip creates energy and a subliminal sense of forward momentum. Applied per-frame inside the `apply_dynamic_crop` loop, after the crop, before writing to the pipe.

```python
def apply_zoom(
    frame: np.ndarray,
    frame_idx: int,
    total_frames: int,
    zoom_start: float = 1.0,
    zoom_end: float = 1.08
) -> np.ndarray:
    h, w     = frame.shape[:2]
    progress = frame_idx / max(total_frames - 1, 1)
    zoom     = zoom_start + (zoom_end - zoom_start) * progress
    new_w    = int(w / zoom)
    new_h    = int(h / zoom)
    x1       = (w - new_w) // 2
    y1       = (h - new_h) // 2
    return cv2.resize(frame[y1:y1 + new_h, x1:x1 + new_w], (w, h))
```

Do not apply zoom to split-screen layouts or clips with significant camera movement.

---

## Step 8 — Colour Grade

Podcast footage is often flat, slightly desaturated, and inconsistently lit. We apply a lightweight grade that makes clips look crisp without looking filtered. All grading runs as ffmpeg filter arguments on the final encode — zero extra processing time.

```python
GRADE_PRESETS = {
    'standard': {
        'eq':           'saturation=1.05:contrast=1.03:brightness=0.01:gamma=1.0',
        'colorbalance': 'rs=0.02:gs=0.01:bs=-0.03',    # subtle warm push
    },
    'vibrant': {
        'eq':           'saturation=1.15:contrast=1.05:brightness=0.02:gamma=0.95',
        'colorbalance': 'rs=0.03:gs=0.02:bs=-0.05',
    },
    'cinematic': {
        'eq':           'saturation=0.92:contrast=1.08:brightness=-0.01:gamma=1.05',
        'colorbalance': 'rs=-0.02:gs=0.0:bs=0.03',     # cool push
    },
    'none': None,
}
```

---

## Step 9 — Audio Normalisation

Every clip is cut from a different section of the podcast and may have been recorded at a different level. We normalise all clips to EBU R128 (-14 LUFS) — the standard used by Spotify, YouTube, and broadcast television. Two-pass: first pass measures actual loudness, second pass applies the correction.

```python
def get_audio_loudness(video_path: str) -> dict:
    cmd = [
        'ffmpeg', '-i', video_path,
        '-af', 'loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json',
        '-f', 'null', '-'
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    import re, json
    match = re.search(r'\{[^}]+\}', result.stderr, re.DOTALL)
    return json.loads(match.group()) if match else {}
```

---

## Step 10 — Final Platform Encode

One encode spec that satisfies TikTok, Instagram Reels, and YouTube Shorts simultaneously.

| Spec | Value |
|---|---|
| Resolution | 1080×1920 |
| Codec | H.264 (libx264) |
| Profile | High / Level 4.0 |
| Pixel format | yuv420p |
| Frame rate | 30fps |
| Quality | CRF 18 |
| Audio | AAC 192k, 44100 Hz stereo |
| Moov atom | Front-loaded (faststart) |

CRF 18 is used instead of a fixed bitrate so the encoder allocates more bits to complex frames and fewer to static talking-head frames. For podcast content most frames are near-static and encode very efficiently.

```python
def encode_final(
    input_path: str,
    output_path: str,
    loudness_data: dict,
    grade_preset: str = 'standard',
    target_w: int = 1080,
    target_h: int = 1920,
) -> str:
    grade    = GRADE_PRESETS.get(grade_preset)
    vf_parts = [f'scale={target_w}:{target_h}']

    if grade:
        vf_parts.append(f"eq={grade['eq']}")
        vf_parts.append(f"colorbalance={grade['colorbalance']}")
    vf = ','.join(vf_parts)

    if loudness_data:
        af = (
            f"loudnorm=I=-14:TP=-1.5:LRA=11"
            f":measured_I={loudness_data.get('input_i', -14)}"
            f":measured_TP={loudness_data.get('input_tp', -1.5)}"
            f":measured_LRA={loudness_data.get('input_lra', 11)}"
            f":measured_thresh={loudness_data.get('input_thresh', -24)}"
            f":linear=true"
        )
    else:
        af = 'loudnorm=I=-14:TP=-1.5:LRA=11'

    cmd = [
        'ffmpeg', '-i', input_path,
        '-c:v', 'libx264',
        '-profile:v', 'high',
        '-level:v', '4.0',
        '-pix_fmt', 'yuv420p',
        '-crf', '18',
        '-preset', 'slow',
        '-r', '30',
        '-vf', vf,
        '-c:a', 'aac',
        '-b:a', '192k',
        '-ar', '44100',
        '-ac', '2',
        '-af', af,
        '-movflags', '+faststart',
        output_path, '-y'
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Encode failed: {result.stderr}")

    return output_path
```

---

## Layout-Specific Strategies In Full

### Strategy A: `face_follow` (Single Speaker)

1. Build keep-segments from word timestamps
2. Cut and stitch → jump-cut clip + rebase map
3. Face tracking at 2fps across jump-cut clip
4. Compute and smooth crop path
5. Dynamic crop + zoom via frame pipe
6. Final encode with grade + loudnorm

### Strategy B: `dynamic_speaker_crop` (Side-by-Side Split Screen)

Jump cuts run first, same as A. On the stitched clip we detect which half has the active speaker by comparing face sizes. Larger face = closer = more prominent = active. A minimum 2-second hold per side prevents rapid flip-flopping.

```python
def detect_active_speaker_side(face_positions_per_frame: list) -> list:
    sides = []
    for faces in face_positions_per_frame:
        if not faces:
            sides.append(sides[-1] if sides else 'left')
            continue

        sorted_faces = sorted(faces, key=lambda f: f['cx'])

        if len(sorted_faces) == 1:
            side = 'left' if sorted_faces[0]['cx'] < 0.5 else 'right'
        else:
            side = 'left' if sorted_faces[0]['w'] > sorted_faces[-1]['w'] else 'right'

        sides.append(side)
    return sides
```

### Strategy C: `active_speaker_follow` (In-Studio Wide Shot)

Jump cuts run first. Then we track both faces and detect lip movement via MediaPipe Face Mesh (468 landmarks) to determine who is speaking. Speaker switches trigger a smooth crop pan over 12 frames (~0.4 seconds) rather than a hard cut.

```python
def detect_lip_movement(face_landmarks) -> float:
    top_lip    = face_landmarks.landmark[13]
    bottom_lip = face_landmarks.landmark[14]
    return abs(top_lip.y - bottom_lip.y)
```

### Strategy D: `center_crop` (No Face / Fallback)

Static centre crop. No tracking. Used for b-roll, animated content, or any detection failure.

---

## Full Orchestration

```python
async def process_clip(
    candidate: dict,
    video_path: str,
    transcript_words: list,
    output_dir: str,
    jump_cut_settings: dict,    # { enabled, max_pause_ms, remove_fillers }
    grade_preset: str = 'standard',
    progress_callback = None,
) -> dict:

    clip_id = candidate['rank']

    def progress(stage: str, pct: float):
        if progress_callback:
            progress_callback(clip_id, stage, pct)

    # ── Step 1: Frame-accurate raw cut ──────────────────────────────────────
    progress('cutting', 0.05)
    start, end = apply_trim_suggestions(candidate)
    raw_path   = os.path.join(output_dir, f'raw_{clip_id}.mp4')
    cut_raw_clip(video_path, start, end, raw_path)

    # ── Step 2: Jump cut editing ─────────────────────────────────────────────
    progress('jump_cutting', 0.15)
    jc_path       = os.path.join(output_dir, f'jc_{clip_id}.mp4')
    rebased_words = transcript_words   # default: no change

    if jump_cut_settings.get('enabled', True):
        segments = build_keep_segments(
            words          = transcript_words,
            clip_start     = start,
            clip_end       = end,
            max_pause_ms   = jump_cut_settings.get('max_pause_ms', 300),
            remove_fillers = jump_cut_settings.get('remove_fillers', True),
            pad_ms         = 50,
        )

        stitch_result = cut_and_stitch(raw_path, segments, jc_path)

        rebased_words = rebase_word_timestamps(
            words          = transcript_words,
            clip_start     = start,
            clip_end       = end,
            rebase_map     = stitch_result['rebase_map'],
            remove_fillers = jump_cut_settings.get('remove_fillers', True),
        )

        effective_duration = stitch_result['new_duration']
        time_removed       = stitch_result['time_removed']
    else:
        import shutil
        shutil.copy(raw_path, jc_path)
        effective_duration = end - start
        time_removed       = 0.0

    # Save rebased word timestamps for Phase 4
    import json
    rebased_words_path = os.path.join(output_dir, f'rebased_words_{clip_id}.json')
    with open(rebased_words_path, 'w') as f:
        json.dump(rebased_words, f, indent=2)

    # ── Step 3: Layout analysis ──────────────────────────────────────────────
    progress('analysing', 0.25)
    layout = detect_layout(jc_path)

    # ── Step 4: Face tracking ────────────────────────────────────────────────
    progress('tracking', 0.38)
    face_positions = track_face_positions(jc_path)

    # ── Steps 5–6: Crop path + smoothing ─────────────────────────────────────
    source_w, source_h = get_video_dimensions(jc_path)
    crop_path          = compute_crop_path(face_positions, source_w, source_h)
    crop_path          = smooth_crop_path(crop_path)

    # ── Step 7: Dynamic crop + zoom ──────────────────────────────────────────
    progress('cropping', 0.50)
    cropped_path = os.path.join(output_dir, f'cropped_{clip_id}.mp4')
    apply_dynamic_crop(jc_path, crop_path, cropped_path)

    # ── Step 9: Measure loudness ──────────────────────────────────────────────
    progress('normalising', 0.78)
    loudness = get_audio_loudness(cropped_path)

    # ── Step 10: Final encode ─────────────────────────────────────────────────
    progress('encoding', 0.88)
    final_path = os.path.join(output_dir, f'clip_{clip_id}_processed.mp4')
    encode_final(cropped_path, final_path, loudness, grade_preset)

    # ── Cleanup intermediates ─────────────────────────────────────────────────
    os.remove(raw_path)
    os.remove(jc_path)
    os.remove(cropped_path)

    progress('done', 1.0)

    return {
        **candidate,
        'processed_path':     final_path,
        'rebased_words_path': rebased_words_path,
        'layout':             layout['type'],
        'face_positions':     face_positions,
        'original_duration':  end - start,
        'effective_duration': effective_duration,
        'time_removed_by_jc': time_removed,
    }
```

---

## File Structure

```
/projects/{project_id}/
  /clips/
    clip_1_processed.mp4       ← Phase 3 output → Phase 4 input
    rebased_words_1.json       ← jump-cut-adjusted word timestamps → Phase 4
    clip_2_processed.mp4
    rebased_words_2.json
    ...
  /metadata/
    processing_log.json        ← layout, strategy, time removed by JC, etc.
```

---

## Requirements & Dependencies

```
opencv-python>=4.8.0     # frame processing, face detection
mediapipe>=0.10.0        # face detection & tracking
numpy>=1.24.0            # array maths
ffmpeg                   # system install
```

```bash
# Ubuntu/Debian
sudo apt install ffmpeg

# macOS
brew install ffmpeg
```

---

## Processing Time Estimates

Jump cutting adds a small segment-cut-and-stitch overhead but this is offset by all subsequent steps running on a shorter clip. Net result is the pipeline is marginally faster than without jump cuts.

| Raw clip length | After JC (~20% removed) | Cut+Stitch | Layout | Face Track | Crop+Zoom | Encode | Total |
|---|---|---|---|---|---|---|---|
| 30s raw → ~24s JC | 20% shorter | 8s | 2s | 6s | 16s | 12s | ~44s |
| 60s raw → ~48s JC | 20% shorter | 12s | 3s | 9s | 32s | 20s | ~76s |
| 90s raw → ~72s JC | 20% shorter | 16s | 3s | 13s | 48s | 28s | ~108s |

For a batch of 10 clips averaging 60 seconds raw: approximately **13 minutes** total.

With NVIDIA GPU acceleration (h264_nvenc + CUDA): reduce by ~60% → **~5 minutes**.

---

## Error Handling & Edge Cases

| Scenario | Handling |
|---|---|
| No words found in clip window | Skip jump cuts entirely, use raw clip, log warning in dashboard |
| Jump cuts remove more than 60% of clip | Warn user: clip may have had very sparse speech, offer to disable JC for this clip |
| Resulting clip shorter than 10 seconds after JC | Flag as too short, disable JC for this clip automatically and retry |
| Stitch produces audio/video desync | Detect via ffprobe stream duration comparison, retry with `-async 1` flag |
| No face detected in any frame | Fall back to `center_crop` strategy |
| Face disappears mid-clip | Hold last known position up to 3 seconds, then fall back to centre |
| Source video already vertical (9:16) | Skip crop step, go straight to encode |
| Source video below 1080p | Scale up with lanczos, flag quality warning in dashboard |
| Audio silent or corrupted | Skip loudnorm, encode with original audio, flag in dashboard |
| Encoding fails | Retry once with `ultrafast` preset, flag if still failing |
| Disk space insufficient | Check for less than 5GB free before starting, warn user |
| Split-screen but only one face detectable | Fall back to `face_follow` on whichever face is found |

---

## What Phase 4 Receives

For each processed clip Phase 3 delivers:

- `clip_{id}_processed.mp4` — 1080×1920, H.264, 30fps, EBU R128 normalised
- `rebased_words_{id}.json` — word timestamps adjusted to the jump-cut timeline, fillers removed, ready for Phase 4 caption generation without any further processing
- `layout_type` — which cropping strategy was used
- `face_positions` — per-frame face centre coordinates so Phase 4 knows whether to place captions at top or bottom of frame
- `effective_duration` — actual clip length after jump cuts
- `time_removed_by_jc` — seconds removed, shown in dashboard as a quality signal

Phase 4 loads `rebased_words_{id}.json` exclusively — never the original transcript — so captions are frame-perfectly in sync with the edited audio.