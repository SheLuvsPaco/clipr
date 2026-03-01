"""
Video Crop & Effects — Steps 5–7 of Phase 3.
Smart vertical crop (9:16), crop path smoothing, dynamic per-frame
crop application via OpenCV→ffmpeg pipe, and subtle zoom effect.
"""

import os
import subprocess
import logging

logger = logging.getLogger(__name__)


# ─── Step 5: Compute Crop Window ─────────────────────────────

def compute_crop_window(
    face_cx: float,
    face_cy: float,
    face_size: float,
    source_w: int,
    source_h: int,
    target_ratio: float = 9 / 16,
) -> dict:
    """
    Compute a 9:16 crop region centred on the speaker's face.

    For a 1920×1080 source: crop_w = 1080 × 9/16 = 608px.
    We use the full source height and slide the crop horizontally
    to track the face.

    The face is placed at ~35% from top in vertical video — slightly
    above centre — which is where subjects feel most natural.

    Args:
        face_cx: Normalised face centre x (0.0–1.0).
        face_cy: Normalised face centre y (0.0–1.0).
        face_size: Normalised face width.
        source_w: Source video width in pixels.
        source_h: Source video height in pixels.
        target_ratio: Target aspect ratio (default 9/16).

    Returns:
        Dict with x, y, w, h of the crop region in pixels.
    """
    crop_w    = int(source_h * target_ratio)   # 608 for 1080p source
    crop_h    = source_h                       # Full height of source
    face_x_px = int(face_cx * source_w)

    # Centre the crop on the face, clamped to frame edges
    crop_x = int(face_x_px - crop_w / 2)
    crop_x = max(0, min(crop_x, source_w - crop_w))

    return {'x': crop_x, 'y': 0, 'w': crop_w, 'h': crop_h}


def compute_crop_path(
    face_positions: list,
    source_w: int,
    source_h: int,
) -> list:
    """
    Compute crop windows for every frame of the video from face positions.

    Args:
        face_positions: List of (cx, cy, size) tuples, one per frame.
        source_w: Source video width.
        source_h: Source video height.

    Returns:
        List of crop dicts, one per frame.
    """
    return [
        compute_crop_window(cx, cy, size, source_w, source_h)
        for cx, cy, size in face_positions
    ]


# ─── Step 6: Crop Path Smoothing ─────────────────────────────

def smooth_crop_path(
    crop_path: list,
    fps: float = 30.0,
    window_seconds: float = 1.5,
) -> list:
    """
    Smooth the crop path with a rolling average to eliminate jitter
    from frame-to-frame face detection noise.

    A 1.5-second window at 30fps = 45 frames. This eliminates small
    head-movement jitter while still tracking intentional movement
    like a head turn.

    Args:
        crop_path: List of crop dicts from compute_crop_path.
        fps: Video frame rate.
        window_seconds: Smoothing window duration.

    Returns:
        Smoothed crop path (same format, same length).
    """
    if not crop_path:
        return crop_path

    window   = max(1, int(fps * window_seconds))
    xs       = [c['x'] for c in crop_path]
    smoothed = []

    for i in range(len(xs)):
        half  = window // 2
        start = max(0, i - half)
        end   = min(len(xs), i + half + 1)
        smoothed.append(int(sum(xs[start:end]) / (end - start)))

    return [{**c, 'x': smoothed[i]} for i, c in enumerate(crop_path)]


# ─── Step 7: Subtle Zoom Effect ──────────────────────────────

def apply_zoom(
    frame,
    frame_idx: int,
    total_frames: int,
    zoom_start: float = 1.0,
    zoom_end: float = 1.08,
):
    """
    Apply a subtle push-in zoom (100%→108%) to a single frame.
    Creates energy and a subliminal sense of forward momentum.

    Applied per-frame inside the dynamic crop loop, after crop,
    before writing to the ffmpeg pipe.

    Do NOT apply to split-screen layouts or clips with significant
    camera movement — it compounds in an ugly way.

    Args:
        frame: NumPy array (BGR image).
        frame_idx: Current frame index.
        total_frames: Total frames in the clip.
        zoom_start: Zoom factor at frame 0 (default 1.0 = no zoom).
        zoom_end: Zoom factor at final frame (default 1.08 = 8% push-in).

    Returns:
        Zoomed frame (same shape as input).
    """
    import cv2

    h, w     = frame.shape[:2]
    progress = frame_idx / max(total_frames - 1, 1)
    zoom     = zoom_start + (zoom_end - zoom_start) * progress

    new_w = int(w / zoom)
    new_h = int(h / zoom)

    x1 = (w - new_w) // 2
    y1 = (h - new_h) // 2

    return cv2.resize(frame[y1:y1 + new_h, x1:x1 + new_w], (w, h))


# ─── Apply Dynamic Crop (OpenCV → ffmpeg pipe) ───────────────

def apply_dynamic_crop(
    input_path: str,
    crop_path: list,
    output_path: str,
    target_w: int = 1080,
    target_h: int = 1920,
    apply_zoom_effect: bool = True,
) -> str:
    """
    Apply per-frame dynamic crop by reading frames with OpenCV,
    slicing the crop region, scaling to target resolution, and
    piping raw frames into ffmpeg. Audio is pulled from the source.

    This is slower than a pure ffmpeg approach but gives full control
    over per-frame crop values. For a 60-second clip at 1080p30,
    approximately 30–60 seconds on a modern CPU.

    Args:
        input_path: Path to the jump-cut clip.
        crop_path: Smoothed crop path (list of crop dicts).
        output_path: Where to write the cropped video.
        target_w: Output width (default 1080).
        target_h: Output height (default 1920).
        apply_zoom_effect: If True, apply 100%→108% push-in.

    Returns:
        output_path on success.
    """
    import cv2

    cap          = cv2.VideoCapture(input_path)
    fps          = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    if total_frames == 0:
        cap.release()
        raise RuntimeError(f"Empty video: {input_path}")

    logger.info(
        f"Dynamic crop: {total_frames} frames, {target_w}x{target_h}, "
        f"zoom={'on' if apply_zoom_effect else 'off'}"
    )

    ffmpeg_cmd = [
        'ffmpeg', '-y',
        '-f', 'rawvideo',
        '-vcodec', 'rawvideo',
        '-s', f'{target_w}x{target_h}',
        '-pix_fmt', 'bgr24',
        '-r', str(fps),
        '-i', 'pipe:0',             # video from stdin
        '-i', input_path,           # second input for audio
        '-map', '0:v',              # video from pipe
        '-map', '1:a',              # audio from original
        '-c:v', 'libx264',
        '-preset', 'fast',
        '-crf', '18',
        '-c:a', 'aac',
        '-b:a', '192k',
        output_path,
    ]

    proc = subprocess.Popen(
        ffmpeg_cmd,
        stdin=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    frame_idx = 0
    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break

            # Get crop for this frame (clamp to last if we overrun)
            crop = crop_path[min(frame_idx, len(crop_path) - 1)]

            # Crop the region
            cropped = frame[
                crop['y']:crop['y'] + crop['h'],
                crop['x']:crop['x'] + crop['w'],
            ]

            # Scale to target resolution
            resized = cv2.resize(cropped, (target_w, target_h))

            # Apply zoom effect if enabled
            if apply_zoom_effect:
                resized = apply_zoom(resized, frame_idx, total_frames)

            # Write raw frame bytes to ffmpeg pipe
            proc.stdin.write(resized.tobytes())
            frame_idx += 1

    except BrokenPipeError:
        logger.warning("ffmpeg pipe broken — checking for errors")
    finally:
        if proc.stdin and not proc.stdin.closed:
            proc.stdin.close()
        proc.wait()
        cap.release()

    if proc.returncode != 0:
        stderr = proc.stderr.read().decode() if proc.stderr else ""
        raise RuntimeError(f"Dynamic crop failed: {stderr[-500:]}")

    logger.info(f"Dynamic crop complete: {frame_idx} frames → {output_path}")
    return output_path
