"""Instagram channel.

Instagram locks down almost everything behind auth. What works publicly:
  - oEmbed API: returns caption + author for any public post URL.
    Endpoint: https://graph.facebook.com/v18.0/instagram_oembed
    (requires a Facebook App token with no special permissions)
  - Basic oEmbed (no token): https://api.instagram.com/oembed?url=...
    Returns minimal data: title (caption) and author_name.

Backends:
  read:  ig-oembed  (api.instagram.com/oembed — no key needed)
  search/profile: web fallback only without login

For full access (private profiles, search, comments): add a browser
session via `reach-kit login instagram`, then OpenCLI takes over.
"""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from urllib.parse import urlparse

from reach_kit.channels.base import Action, Channel, Param
from reach_kit.runtime.result import (
    BAD_INPUT,
    NOT_FOUND,
    RATE_LIMITED,
    UPSTREAM_BROKEN,
    SkillError,
    make_item,
)

_UA = "reach-kit"


def _ig_url(url: str) -> str:
    parsed = urlparse(url)
    if "instagram.com" not in parsed.netloc and "instagr.am" not in parsed.netloc:
        raise SkillError(BAD_INPUT, "not an Instagram URL")
    return url


def _strip_html(html: str) -> str:
    return re.sub(r"<[^>]+>", "", html).strip()


class InstagramChannel(Channel):
    name = "instagram"
    description = "Instagram posts via oEmbed (public posts only; login needed for search/profiles)"
    level = "experimental"
    domains = ("instagram.com", "instagr.am")
    login_url = "https://www.instagram.com/accounts/login/"

    actions = (
        Action(
            "read",
            "Read a public Instagram post caption and author via oEmbed",
            (Param("target", "Instagram post URL (instagram.com/p/...)"),),
            backends=(("ig-oembed", "_oembed_read"),),
            public_web=("instagram.com/p/",),
            live_test={"target": "https://www.instagram.com/p/CqP6Z8RLJi9/"},
        ),
        Action(
            "search",
            "Search Instagram (public web only; login needed for full results)",
            (
                Param("query", "what to search for"),
                Param("limit", "max results", required=False, type=int, default=5),
            ),
            backends=(),
            public_web=("instagram.com/",),
            live_test={"query": "nasa space"},
        ),
        Action(
            "download",
            "Download an Instagram reel or video to local disk",
            (
                Param("target", "Instagram reel or post URL"),
                Param("output", "output directory (agent picks if omitted)", required=False, default=None),
                Param("quality", "best | 720p | 480p | audio", required=False, default="best"),
            ),
            backends=(("yt-dlp", "_ytdlp_download"),),
            live_test={"target": "https://www.instagram.com/p/CqP6Z8RLJi9/"},
        ),
    )

    def can_handle(self, url: str) -> bool:
        try:
            return "instagram.com" in urlparse(url).netloc or "instagr.am" in urlparse(url).netloc
        except Exception:
            return False

    def _ytdlp_download(self, *, target: str, output, quality: str, timeout: float) -> list:
        from reach_kit.runtime.ytdlp import download
        return [download(target, output=output, quality=quality, timeout=timeout)]

    def _oembed_read(self, *, target: str, timeout: float) -> list:
        url = _ig_url(target)
        # Instagram's basic oEmbed — no token needed, returns caption + author
        oembed_url = f"https://api.instagram.com/oembed?{urllib.parse.urlencode({'url': url})}"
        req = urllib.request.Request(oembed_url, headers={"User-Agent": _UA})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                d = json.loads(resp.read(512 * 1024))
        except urllib.request.HTTPError as exc:
            if exc.code == 404:
                raise SkillError(NOT_FOUND, "Post not found or account is private")
            if exc.code == 429:
                raise SkillError(RATE_LIMITED, "Instagram oEmbed rate-limited")
            raise SkillError(UPSTREAM_BROKEN, f"Instagram oEmbed HTTP {exc.code}")

        title = d.get("title") or ""
        # Clean up HTML entities in caption
        caption = _strip_html(title)
        return [make_item(
            url=url,
            author=d.get("author_name"),
            text=caption,
            raw={
                "author_url": d.get("author_url"),
                "thumbnail_url": d.get("thumbnail_url"),
                "media_id": d.get("media_id"),
            },
        )]
