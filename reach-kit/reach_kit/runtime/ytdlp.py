"""Shared yt-dlp helpers used by all social channels' download action."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from typing import Optional

from reach_kit.runtime.result import (
    NEED_SETUP,
    NOT_FOUND,
    UPSTREAM_BROKEN,
    SkillError,
    make_item,
)

_CANDIDATES = [
    "yt-dlp",
    "/root/.local/share/uv/tools/agent-reach/bin/yt-dlp",
]

DEFAULT_DOWNLOAD_DIR = "~/reach-kit-downloads"

# Maps quality shorthand to yt-dlp format selectors
_FORMAT = {
    "best":   "bestvideo+bestaudio/best",
    "1080p":  "bestvideo[height<=1080]+bestaudio/best[height<=1080]",
    "720p":   "bestvideo[height<=720]+bestaudio/best[height<=720]",
    "480p":   "bestvideo[height<=480]+bestaudio/best[height<=480]",
    "360p":   "bestvideo[height<=360]+bestaudio/best[height<=360]",
    "audio":  None,  # handled separately via -x
}


def find_ytdlp() -> str:
    exe = next((c for c in _CANDIDATES if shutil.which(c) or os.path.isfile(c)), None)
    if not exe:
        raise SkillError(
            NEED_SETUP,
            "yt-dlp not found",
            hint="Install with: uv tool install yt-dlp  (or: pip install yt-dlp)",
        )
    return exe


def run(*args, timeout: float = 30.0) -> str:
    """Run yt-dlp and return stdout. Raise SkillError on failure."""
    exe = find_ytdlp()
    try:
        proc = subprocess.run(
            [exe, *args],
            capture_output=True, text=True, timeout=timeout,
        )
    except FileNotFoundError:
        raise SkillError(NEED_SETUP, "yt-dlp not found") from None
    except subprocess.TimeoutExpired:
        raise SkillError("TIMEOUT", "yt-dlp timed out") from None
    if proc.returncode != 0:
        err = (proc.stderr or "").strip()
        if any(w in err.lower() for w in ("unavailable", "not available", "private", "removed", "deleted")):
            raise SkillError(NOT_FOUND, f"Content not available: {err[:200]}")
        raise SkillError(UPSTREAM_BROKEN, f"yt-dlp error: {err[:300]}")
    return proc.stdout


def get_info(url: str, timeout: float = 30.0) -> dict:
    out = run("--dump-json", "--no-playlist", "--no-warnings", url, timeout=timeout)
    return json.loads(out.splitlines()[0])


def download(
    url: str,
    *,
    output: Optional[str] = None,
    quality: str = "best",
    timeout: float = 300.0,
) -> dict:
    """Download a video/audio file. Returns a unified item with filepath in raw."""
    if quality not in _FORMAT:
        raise SkillError(
            "BAD_INPUT",
            f"Unknown quality '{quality}'. Valid: {', '.join(_FORMAT)}",
        )

    out_dir = os.path.expanduser(output or DEFAULT_DOWNLOAD_DIR)
    os.makedirs(out_dir, exist_ok=True)
    out_template = os.path.join(out_dir, "%(title).100s.%(ext)s")

    # Get metadata first (fast, cheap)
    info = get_info(url, timeout=min(30.0, timeout / 4))

    # Build yt-dlp args
    if quality == "audio":
        dl_args = [
            url,
            "-x", "--audio-format", "mp3",
            "-o", out_template,
            "--no-warnings",
            "--print", "after_move:filepath",
        ]
    else:
        fmt = _FORMAT[quality]
        dl_args = [
            url,
            "-f", fmt,
            "--merge-output-format", "mp4",
            "-o", out_template,
            "--no-warnings",
            "--print", "after_move:filepath",
        ]

    filepath_out = run(*dl_args, timeout=timeout)
    # yt-dlp prints one line per file; take the last non-empty line
    lines = [l.strip() for l in filepath_out.splitlines() if l.strip()]
    filepath = lines[-1] if lines else None

    filesize = None
    if filepath and os.path.exists(filepath):
        filesize = os.path.getsize(filepath)

    duration = info.get("duration")
    description = (info.get("description") or "")[:500]

    return make_item(
        title=info.get("title"),
        url=info.get("webpage_url") or url,
        author=info.get("uploader") or info.get("channel"),
        published_at=info.get("upload_date"),
        text=description,
        raw={
            "filepath": filepath,
            "filesize_bytes": filesize,
            "duration_seconds": duration,
            "quality": quality,
            "ext": "mp3" if quality == "audio" else "mp4",
            "output_dir": out_dir,
        },
    )
