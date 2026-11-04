"""Facebook channel.

Facebook's Graph API requires an app token for virtually all content.
Without credentials, almost nothing is publicly readable.

What works without auth:
  - oEmbed for public posts: https://graph.facebook.com/v18.0/oembed_post
    (requires a Facebook App token, but no special user permissions)
  - Public page posts are readable via oEmbed if you have a client_access_token.

Backends:
  read:   fb-oembed (requires FB_APP_TOKEN env var)
  search: web fallback only

Set FB_APP_TOKEN to an app access token from developers.facebook.com.
(No user auth needed — just an app token from your app's dashboard.)
"""

from __future__ import annotations

import json
import os
import re
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
_GRAPH = "https://graph.facebook.com/v18.0"


def _fb_url(url: str) -> str:
    parsed = urlparse(url)
    if "facebook.com" not in parsed.netloc and "fb.com" not in parsed.netloc:
        raise SkillError(BAD_INPUT, "not a Facebook URL")
    return url


def _strip_html(html: str) -> str:
    return re.sub(r"<[^>]+>", "", html).strip()


class FacebookChannel(Channel):
    name = "facebook"
    description = "Facebook public posts via oEmbed (requires FB_APP_TOKEN; most content needs login)"
    level = "experimental"
    domains = ("facebook.com", "fb.com")
    login_url = "https://www.facebook.com/login"

    actions = (
        Action(
            "read",
            "Read a public Facebook post via oEmbed (requires FB_APP_TOKEN)",
            (Param("target", "Facebook post URL"),),
            backends=(("fb-oembed", "_oembed_read"),),
            public_web=("facebook.com/",),
            live_test={"target": "https://www.facebook.com/Meta/posts/123"},
        ),
        Action(
            "search",
            "Search Facebook (public web only; almost all content requires login)",
            (
                Param("query", "what to search for"),
                Param("limit", "max results", required=False, type=int, default=5),
            ),
            backends=(),
            public_web=("facebook.com/",),
            live_test={"query": "Meta AI announcement"},
        ),
        Action(
            "download",
            "Download a public Facebook video to local disk",
            (
                Param("target", "Facebook video URL"),
                Param("output", "output directory (agent picks if omitted)", required=False, default=None),
                Param("quality", "best | 720p | 480p | audio", required=False, default="best"),
            ),
            backends=(("yt-dlp", "_ytdlp_download"),),
            live_test={"target": "https://www.facebook.com/Meta/videos/123"},
        ),
    )

    def can_handle(self, url: str) -> bool:
        try:
            return "facebook.com" in urlparse(url).netloc or "fb.com" in urlparse(url).netloc
        except Exception:
            return False

    def _ytdlp_download(self, *, target: str, output, quality: str, timeout: float) -> list:
        from reach_kit.runtime.ytdlp import download
        return [download(target, output=output, quality=quality, timeout=timeout)]

    def _oembed_read(self, *, target: str, timeout: float) -> list:
        token = os.environ.get("FB_APP_TOKEN")
        if not token:
            raise SkillError(
                NEED_SETUP,
                "Facebook oEmbed requires an app access token",
                hint="Set FB_APP_TOKEN env var. Get one at developers.facebook.com (no user auth needed).",
            )
        url = _fb_url(target)
        oembed_url = f"{_GRAPH}/oembed_post?{urllib.parse.urlencode({'url': url, 'access_token': token})}"
        req = urllib.request.Request(oembed_url, headers={"User-Agent": _UA})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                d = json.loads(resp.read(512 * 1024))
        except urllib.request.HTTPError as exc:
            body = exc.read(4096).decode("utf-8", errors="replace")
            if exc.code == 404:
                raise SkillError(NOT_FOUND, "Facebook post not found or is private")
            if exc.code == 429:
                raise SkillError(RATE_LIMITED, "Facebook API rate-limited")
            if exc.code in (400, 401, 403):
                try:
                    err = json.loads(body).get("error", {})
                    if err.get("code") == 190:
                        raise SkillError(NEED_SETUP, "FB_APP_TOKEN is invalid or expired")
                except (ValueError, AttributeError):
                    pass
            raise SkillError(UPSTREAM_BROKEN, f"Facebook oEmbed HTTP {exc.code}: {body[:200]}")

        html = d.get("html", "")
        text = _strip_html(html)
        return [make_item(
            url=url,
            author=d.get("author_name"),
            text=text,
            raw={
                "author_url": d.get("author_url"),
                "provider": d.get("provider_name"),
                "thumbnail_url": d.get("thumbnail_url"),
            },
        )]
