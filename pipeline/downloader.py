"""
Downloader — yt-dlp wrapper for downloading videos from URLs.
Supports YouTube, Spotify, SoundCloud, Vimeo, and 1700+ other sites.
"""

import os
import logging
from typing import Callable, Optional

import yt_dlp

logger = logging.getLogger(__name__)


def download_video(
    url: str,
    output_dir: str,
    progress_callback: Optional[Callable[[float], None]] = None,
) -> dict:
    """
    Download a video from a URL using yt-dlp.

    Args:
        url: The video/podcast URL to download.
        output_dir: Directory to save the downloaded files.
        progress_callback: Optional callback(progress: 0.0-1.0) for progress updates.

    Returns:
        dict with keys: video_path, title, duration, chapters, info_json_path
    """
    os.makedirs(output_dir, exist_ok=True)

    def _progress_hook(d):
        """Internal yt-dlp progress hook."""
        if d["status"] == "downloading" and progress_callback:
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            downloaded = d.get("downloaded_bytes", 0)
            if total > 0:
                progress_callback(downloaded / total)
        elif d["status"] == "finished" and progress_callback:
            progress_callback(1.0)

    ydl_opts = {
        "format": "bv*[ext=mp4]+ba[ext=m4a]/bv*+ba/b[ext=mp4]/best",
        "merge_output_format": "mp4",
        "outtmpl": os.path.join(output_dir, "%(id)s.%(ext)s"),
        "writeinfojson": True,
        "quiet": True,
        "no_warnings": True,
        "progress_hooks": [_progress_hook],
        "remote_components": {"ejs": "github"},
    }

    logger.info(f"Starting download: {url}")

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)

    # Determine the output video path
    video_id = info.get("id", "video")
    video_path = os.path.join(output_dir, f"{video_id}.mp4")

    # If the file doesn't exist with the expected name, search for it
    if not os.path.exists(video_path):
        for f in os.listdir(output_dir):
            if f.endswith(".mp4"):
                video_path = os.path.join(output_dir, f)
                break

    # Find the info JSON
    info_json_path = None
    for f in os.listdir(output_dir):
        if f.endswith(".info.json"):
            info_json_path = os.path.join(output_dir, f)
            break

    result = {
        "video_path": video_path,
        "title": info.get("title", "Unknown"),
        "duration": info.get("duration", 0),
        "chapters": info.get("chapters", []),
        "uploader": info.get("uploader", "Unknown"),
        "upload_date": info.get("upload_date"),
        "description": info.get("description", ""),
        "info_json_path": info_json_path,
        "url": url,
    }

    logger.info(f"Download complete: {result['title']} ({result['duration']}s)")
    return result
