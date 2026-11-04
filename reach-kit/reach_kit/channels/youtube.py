"""YouTube channel — video info and search via yt-dlp.

Backends:
  read:   yt-dlp (--dump-json on a video URL)
  search: yt-dlp (ytsearch:<query>)

yt-dlp is bundled with reach-kit's optional deps. No API key required
for video metadata and auto-generated subtitles; downloading media
files is out of scope for a read-only skill.
"""

from __future__ import annotations

import json
import subprocess
from typing import Optional
from urllib.parse import urlparse

from reach_kit.channels.base import Action, Channel, Param
from reach_kit.runtime.result import (
    BAD_INPUT,
    NOT_FOUND,
    NEED_SETUP,
    UPSTREAM_BROKEN,
    SkillError,
    make_item,
    unix_to_iso,
)

# yt-dlp may live inside the agent-reach uv tool env; fall back to PATH
_YTDLP_CANDIDATES = [
    "yt-dlp",
    "/root/.local/share/uv/tools/agent-reach/bin/yt-dlp",
]


def _ytdlp(*args, timeout: float = 30.0) -> str:
    """Run yt-dlp and return stdout. Raise SkillError on failure."""
    import shutil
    exe = next((c for c in _YTDLP_CANDIDATES if shutil.which(c) or __import__("os").path.isfile(c)), None)
    if not exe:
        raise SkillError(NEED_SETUP, "yt-dlp not found; install it with `pip install yt-dlp`")
    try:
        proc = subprocess.run(
            [exe, *args],
            capture_output=True, text=True, timeout=timeout,
        )
    except FileNotFoundError:
        raise SkillError(NEED_SETUP, "yt-dlp not found") from None
    if proc.returncode != 0:
        err = (proc.stderr or "").strip()
        if "not available" in err or "unavailable" in err or "private" in err.lower():
            raise SkillError(NOT_FOUND, f"Video not available: {err[:200]}")
        raise SkillError(UPSTREAM_BROKEN, f"yt-dlp error: {err[:300]}")
    return proc.stdout


def _yt_url(url: str) -> str:
    """Validate and normalize a YouTube URL."""
    parsed = urlparse(url)
    if parsed.netloc not in ("youtube.com", "www.youtube.com", "youtu.be", "m.youtube.com"):
        raise SkillError(BAD_INPUT, "not a YouTube URL")
    return url


def _info_to_item(d: dict) -> dict:
    """Convert a yt-dlp --dump-json dict to a unified item."""
    duration = d.get("duration")
    duration_str = f"{int(duration // 60)}:{int(duration % 60):02d}" if duration else None
    description = d.get("description") or ""
    # Truncate huge descriptions
    if len(description) > 3000:
        description = description[:3000] + "…"
    text_parts = [description]
    if duration_str:
        text_parts.append(f"Duration: {duration_str}")
    if d.get("view_count"):
        text_parts.append(f"Views: {d['view_count']:,}")
    return make_item(
        title=d.get("title"),
        url=d.get("webpage_url") or f"https://youtube.com/watch?v={d.get('id', '')}",
        author=d.get("uploader") or d.get("channel"),
        published_at=d.get("upload_date"),  # YYYYMMDD string
        text="\n".join(filter(None, text_parts)),
        raw={
            "id": d.get("id"),
            "channel": d.get("channel"),
            "duration_seconds": duration,
            "view_count": d.get("view_count"),
            "like_count": d.get("like_count"),
            "tags": (d.get("tags") or [])[:10],
        },
    )


class YouTubeChannel(Channel):
    name = "youtube"
    description = "YouTube video info and search"
    level = "default"
    domains = ("youtube.com", "youtu.be")

    actions = (
        Action(
            "read",
            "Get video title, description, stats and metadata",
            (Param("target", "YouTube video URL"),),
            backends=(("yt-dlp", "_ytdlp_read"),),
            live_test={"target": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
        ),
        Action(
            "search",
            "Search YouTube videos",
            (
                Param("query", "what to search for"),
                Param("limit", "max results", required=False, type=int, default=5),
            ),
            backends=(("yt-dlp", "_ytdlp_search"),),
            live_test={"query": "playwright browser automation tutorial", "limit": 3},
        ),
        Action(
            "subtitles",
            "Get auto-generated or manual subtitles for a video",
            (
                Param("target", "YouTube video URL"),
                Param("lang", "subtitle language code", required=False, default="en"),
            ),
            backends=(("yt-dlp", "_ytdlp_subtitles"),),
            live_test={"target": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
        ),
    )

    def can_handle(self, url: str) -> bool:
        try:
            return urlparse(url).netloc.lstrip("www.").lstrip("m.") in ("youtube.com", "youtu.be")
        except Exception:
            return False

    def _ytdlp_read(self, *, target: str, timeout: float) -> list:
        _yt_url(target)
        out = _ytdlp("--dump-json", "--no-playlist", "--no-warnings", target, timeout=timeout)
        d = json.loads(out.splitlines()[0])
        return [_info_to_item(d)]

    def _ytdlp_search(self, *, query: str, limit: int, timeout: float) -> list:
        out = _ytdlp(
            f"ytsearch{limit}:{query}",
            "--dump-json", "--flat-playlist", "--no-warnings",
            timeout=timeout,
        )
        items = []
        for line in out.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except ValueError:
                continue
            items.append(make_item(
                title=d.get("title"),
                url=d.get("url") or f"https://youtube.com/watch?v={d.get('id', '')}",
                author=d.get("uploader") or d.get("channel"),
                published_at=d.get("upload_date"),
                text=d.get("description") or "",
                raw={"id": d.get("id"), "duration": d.get("duration"), "view_count": d.get("view_count")},
            ))
        if not items:
            raise SkillError(UPSTREAM_BROKEN, "yt-dlp returned no search results")
        return items[:limit]

    def _ytdlp_subtitles(self, *, target: str, lang: str, timeout: float) -> list:
        _yt_url(target)
        # List available subtitles first
        info_out = _ytdlp("--dump-json", "--no-playlist", "--no-warnings", target, timeout=timeout / 2)
        d = json.loads(info_out.splitlines()[0])
        subs = d.get("subtitles", {})
        auto_subs = d.get("automatic_captions", {})
        available = {**auto_subs, **subs}
        if not available:
            raise SkillError(NOT_FOUND, "No subtitles available for this video")
        # Pick requested lang or first available
        chosen_lang = lang if lang in available else next(iter(available))
        tracks = available[chosen_lang]
        # Prefer vtt format
        vtt = next((t for t in tracks if t.get("ext") == "vtt"), tracks[0] if tracks else None)
        if not vtt:
            raise SkillError(NOT_FOUND, f"No subtitle track found for language '{chosen_lang}'")
        # Fetch the subtitle content
        import urllib.request
        req = urllib.request.Request(vtt["url"], headers={"User-Agent": "reach-kit"})
        with urllib.request.urlopen(req, timeout=timeout / 2) as resp:
            raw_subs = resp.read(2 * 1024 * 1024).decode("utf-8", errors="replace")
        # Strip VTT timestamps to get plain text
        import re
        lines = raw_subs.splitlines()
        text_lines = [l for l in lines if l.strip()
                      and not l.startswith("WEBVTT")
                      and not re.match(r"^\d{2}:\d{2}", l)
                      and not re.match(r"^NOTE\b", l)
                      and not re.match(r"^\d+$", l)]
        text = "\n".join(text_lines).strip()
        return [make_item(
            title=d.get("title"),
            url=target,
            author=d.get("uploader") or d.get("channel"),
            text=text,
            raw={"lang": chosen_lang, "available_langs": list(available.keys())[:20]},
        )]
