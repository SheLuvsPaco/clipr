"""
Video Analysis — Steps 3–4 of Phase 3.
Layout detection (single speaker / split-screen / studio / no-face)
and face position tracking with interpolation.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


# ─── Utility ──────────────────────────────────────────────────

def get_video_dimensions(video_path: str) -> tuple:
    """
    Get width and height of a video file.

    Returns:
        (width, height) tuple.
    """
    import cv2
    cap = cv2.VideoCapture(video_path)
    w   = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h   = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()
    return w, h


def get_video_info(video_path: str) -> dict:
    """
    Get comprehensive video info.

    Returns:
        Dict with width, height, fps, total_frames, duration, is_vertical.
    """
    import cv2
    cap = cv2.VideoCapture(video_path)
    info = {
        'width':        int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
        'height':       int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
        'fps':          cap.get(cv2.CAP_PROP_FPS),
        'total_frames': int(cap.get(cv2.CAP_PROP_FRAME_COUNT)),
    }
    info['duration']    = info['total_frames'] / max(info['fps'], 1)
    info['is_vertical'] = info['height'] > info['width']
    cap.release()
    return info


# ─── Step 3: Layout Detection ────────────────────────────────

def _init_face_detector(min_confidence: float = 0.5):
    """Lazily import and initialise MediaPipe face detection."""
    import mediapipe as mp
    return mp.solutions.face_detection.FaceDetection(
        min_detection_confidence=min_confidence
    )


def detect_layout(video_path: str) -> dict:
    """
    Detect the video layout by sampling 10 evenly-spaced frames and
    running MediaPipe face detection on each.

    Layouts:
        single_speaker  — 1 face consistently → face_follow
        split_screen    — 2 faces, spread apart → dynamic_speaker_crop
        in_studio_wide  — 2 faces, close together → active_speaker_follow
        no_face         — no detections → center_crop

    Args:
        video_path: Path to the (jump-cut) video to analyse.

    Returns:
        Dict with 'type' and 'strategy' keys.
    """
    import cv2
    cap          = cv2.VideoCapture(video_path)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    width        = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height       = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    if total_frames == 0:
        cap.release()
        logger.warning("Video has 0 frames — falling back to center_crop")
        return {'type': 'no_face', 'strategy': 'center_crop'}

    # Sample 10 evenly spaced frames
    sample_indices = [int(i * total_frames / 10) for i in range(10)]

    detector       = _init_face_detector(0.5)
    face_positions = []

    for frame_idx in sample_indices:
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ret, frame = cap.read()
        if not ret:
            continue

        rgb     = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = detector.process(rgb)

        if results.detections:
            frame_faces = []
            for detection in results.detections:
                bbox = detection.location_data.relative_bounding_box
                cx   = bbox.xmin + bbox.width / 2
                cy   = bbox.ymin + bbox.height / 2
                frame_faces.append({'cx': cx, 'cy': cy, 'w': bbox.width})
            face_positions.append(frame_faces)

    cap.release()
    detector.close()

    layout = classify_layout(face_positions, width, height)
    logger.info(f"Layout detected: {layout['type']} → strategy: {layout['strategy']}")
    return layout


def classify_layout(face_positions: list, width: int, height: int) -> dict:
    """
    Classify layout from face detection patterns across sampled frames.

    Decision logic:
        - No faces at all → center_crop
        - Avg < 1.3 faces/frame → single_speaker (face_follow)
        - 2+ faces → check horizontal spread:
            - cx std > 0.25 → split_screen (faces in different halves)
            - cx std ≤ 0.25 → in_studio_wide (faces clustered together)

    Args:
        face_positions: List of per-frame face position lists.
        width: Video width in pixels.
        height: Video height in pixels.

    Returns:
        Dict with 'type' and 'strategy'.
    """
    import numpy as np

    if not face_positions:
        return {'type': 'no_face', 'strategy': 'center_crop'}

    avg_faces = np.mean([len(fp) for fp in face_positions])

    if avg_faces < 1.3:
        return {'type': 'single_speaker', 'strategy': 'face_follow'}

    # Multiple faces — check horizontal distribution
    all_cx = [f['cx'] for fp in face_positions for f in fp]
    cx_std = np.std(all_cx)

    if cx_std > 0.25:
        return {'type': 'split_screen',   'strategy': 'dynamic_speaker_crop'}
    else:
        return {'type': 'in_studio_wide', 'strategy': 'active_speaker_follow'}


# ─── Step 4: Face Position Tracking ──────────────────────────

def track_face_positions(
    video_path: str,
    sample_fps: int = 2,
) -> list:
    """
    Track the primary speaker's face position across the video by
    sampling at 2fps and interpolating between samples.

    2fps on a 72-second clip = 144 samples vs 2,160 frames at 30fps.
    Sufficient accuracy at a fraction of the cost.

    Args:
        video_path: Path to the video to track.
        sample_fps: Sampling rate (default 2fps).

    Returns:
        List of (cx, cy, size) tuples — one per frame of the video.
        Values are normalised 0.0–1.0.
    """
    import cv2
    cap        = cv2.VideoCapture(video_path)
    native_fps = cap.get(cv2.CAP_PROP_FPS)
    total      = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    if total == 0 or native_fps == 0:
        cap.release()
        logger.warning("Empty video — returning default face positions")
        return [(0.5, 0.33, 0.3)]

    skip = max(1, int(native_fps / sample_fps))

    detector = _init_face_detector(0.6)
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
                # Use the largest face (closest to camera = main speaker)
                largest = max(
                    results.detections,
                    key=lambda d: d.location_data.relative_bounding_box.width
                )
                bbox         = largest.location_data.relative_bounding_box
                sampled[idx] = (
                    bbox.xmin + bbox.width / 2,
                    bbox.ymin + bbox.height / 2,
                    bbox.width,
                )
            elif sampled:
                # No face — hold last known position
                sampled[idx] = list(sampled.values())[-1]

        idx += 1

    cap.release()
    detector.close()

    positions = interpolate_positions(sampled, total)
    logger.info(
        f"Face tracking: {len(sampled)} samples → {len(positions)} interpolated positions"
    )
    return positions


def interpolate_positions(sampled: dict, total_frames: int) -> list:
    """
    Linearly interpolate sampled face positions to produce a value
    for every frame of the video.

    Args:
        sampled: Dict mapping frame_index → (cx, cy, size).
        total_frames: Total number of frames in the video.

    Returns:
        List of (cx, cy, size) tuples, length == total_frames.
    """
    if not sampled:
        # No face detected anywhere — return centre for all frames
        return [(0.5, 0.33, 0.3)] * total_frames

    keys   = sorted(sampled.keys())
    result = []

    for i in range(total_frames):
        # Find surrounding sample frames
        before = max([k for k in keys if k <= i], default=keys[0])
        after  = min([k for k in keys if k >= i], default=keys[-1])

        if before == after:
            result.append(sampled[before])
        else:
            # Linear interpolation between samples
            t  = (i - before) / (after - before)
            p0 = sampled[before]
            p1 = sampled[after]
            result.append((
                p0[0] + t * (p1[0] - p0[0]),
                p0[1] + t * (p1[1] - p0[1]),
                p0[2] + t * (p1[2] - p0[2]),
            ))

    return result


# ─── Strategy Helpers ─────────────────────────────────────────

def detect_active_speaker_side(face_positions_per_frame: list) -> list:
    """
    For split-screen layouts: determine which half (left/right) has the
    active speaker in each frame by comparing face sizes.
    Larger face = closer = more prominent = active.

    Args:
        face_positions_per_frame: List of per-frame face position lists
                                  (each face is a dict with cx, cy, w).

    Returns:
        List of 'left' or 'right' strings, one per frame.
    """
    sides = []
    for faces in face_positions_per_frame:
        if not faces:
            sides.append(sides[-1] if sides else 'left')
            continue

        sorted_faces = sorted(faces, key=lambda f: f['cx'])

        if len(sorted_faces) == 1:
            side = 'left' if sorted_faces[0]['cx'] < 0.5 else 'right'
        else:
            # Two faces — larger face is more prominent (active)
            side = 'left' if sorted_faces[0]['w'] > sorted_faces[-1]['w'] else 'right'

        sides.append(side)
    return sides


def detect_lip_movement(face_landmarks) -> float:
    """
    Measure lip aperture from MediaPipe Face Mesh landmarks.
    Used for active_speaker_follow strategy.
    Landmark 13 = upper lip, Landmark 14 = lower lip.

    Args:
        face_landmarks: MediaPipe face landmarks object.

    Returns:
        Vertical distance between top and bottom lip (0.0–1.0 normalised).
    """
    top_lip    = face_landmarks.landmark[13]
    bottom_lip = face_landmarks.landmark[14]
    return abs(top_lip.y - bottom_lip.y)
