"""TikTok channel.

TikTok's API requires business account credentials. Without them:
  1. oEmbed endpoint (www.tiktok.com/oembed) — returns video title,
     author and thumbnail for any public video URL.
  2. yt-dlp — can extract full video metadata from TikTok URLs without
     auth (may require the --cookies-from-browser option for some content).

Backends:
  read:   tiktok-oembed → yt-dlp
  search: web fallback only (no unauthenticated search API)
"""

from __future__ import annotations

import json
import subprocess
import urllib.parse
import urllib.request
from urllib.parse import urlparse

from reach_kit.channels.base import Action, Channel, Param
from reach_kit.runtime.result import (
    BAD_INPUT,
    NEED_SETUP,
    NOT_FOUND,
    RATE_LIMITED,
    UPSTREAM_BROKEN,
    SkillError,
    make_item,
)

_UA = "reach-kit"
_YTDLP_CANDIDATES = [
    "yt-dlp",
    "/root/.local/share/uv/tools/agent-reach/bin/yt-dlp",
]


def _ytdlp(*args, timeout: float = 30.0) -> str:
    import shutil, os
    exe = next((c for c in _YTDLP_CANDIDATES if shutil.which(c) or os.path.isfile(c)), None)
    if not exe:
        raise SkillError(NEED_SETUP, "yt-dlp not found")
    try:
        proc = subprocess.run([exe, *args], capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        raise SkillError(NEED_SETUP, "yt-dlp not found") from None
    if proc.returncode != 0:
        err = (proc.stderr or "").strip()
        if "not available" in err or "unavailable" in err or "private" in err.lower():
            raise SkillError(NOT_FOUND, f"TikTok video not available: {err[:200]}")
        raise SkillError(UPSTREAM_BROKEN, f"yt-dlp error: {err[:300]}")
    return proc.stdout


def _tt_url(url: str) -> str:
    parsed = urlparse(url)
    if "tiktok.com" not in parsed.netloc and "vm.tiktok.com" not in parsed.netloc:
        raise SkillError(BAD_INPUT, "not a TikTok URL")
    return url


class TikTokChannel(Channel):
    name = "tiktok"
    description = "TikTok video metadata via oEmbed and yt-dlp (public videos only)"
    level = "experimental"
    domains = ("tiktok.com", "vm.tiktok.com")

    actions = (
        Action(
            "read",
            "Read TikTok video title, author, and description",
            (Param("target", "TikTok video URL"),),
            backends=(("tiktok-oembed", "_oembed_read"), ("yt-dlp", "_ytdlp_read")),
            live_test={"target": "https://www.tiktok.com/@tiktok/video/6829267836783971589"},
        ),
    )

    def can_handle(self, url: str) -> bool:
        try:
            return "tiktok.com" in urlparse(url).netloc
        except Exception:
            return False

    def _oembed_read(self, *, target: str, timeout: float) -> list:
        url = _tt_url(target)
        oembed_url = f"https://www.tiktok.com/oembed?{urllib.parse.urlencode({'url': url})}"
        req = urllib.request.Request(oembed_url, headers={"User-Agent": _UA})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                d = json.loads(resp.read(512 * 1024))
        except urllib.request.HTTPError as exc:
            if exc.code == 404:
                raise SkillError(NOT_FOUND, "TikTok video not found")
            if exc.code == 429:
                raise SkillError(RATE_LIMITED, "TikTok oEmbed rate-limited")
            raise SkillError(UPSTREAM_BROKEN, f"TikTok oEmbed HTTP {exc.code}")
        return [make_item(
            title=d.get("title"),
            url=url,
            author=d.get("author_name"),
            text=d.get("title") or "",
            raw={
                "author_url": d.get("author_url"),
                "thumbnail_url": d.get("thumbnail_url"),
            },
        )]

    def _ytdlp_read(self, *, target: str, timeout: float) -> list:
        url = _tt_url(target)
        out = _ytdlp("--dump-json", "--no-warnings", url, timeout=timeout)
        d = json.loads(out.splitlines()[0])
        description = (d.get("description") or "")[:2000]
        return [make_item(
            title=d.get("title"),
            url=d.get("webpage_url") or url,
            author=d.get("uploader") or d.get("channel"),
            published_at=d.get("upload_date"),
            text=description,
            raw={
                "id": d.get("id"),
                "view_count": d.get("view_count"),
                "like_count": d.get("like_count"),
                "comment_count": d.get("comment_count"),
                "duration": d.get("duration"),
            },
        )]
