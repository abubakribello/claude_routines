"""Twitter / X channel.

Twitter's API requires OAuth for nearly everything. Without credentials,
the best available approaches are:
  1. Twitter's oEmbed endpoint — works for any public tweet URL, returns
     the rendered HTML embed with the tweet text.
  2. Nitter public instances — open-source Twitter front-ends that scrape
     the site. Instance availability varies; we try a short list.
  3. Web fallback via Jina/Exa (declared as public_web on actions).

Backends:
  read:   oembed → nitter-scrape
  search: web fallback only (no unauthenticated search API exists)

Add a TWITTER_BEARER_TOKEN env var to unlock the v2 API for search.
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
_OEMBED = "https://publish.twitter.com/oembed"
_NITTER_INSTANCES = [
    "https://nitter.net",
    "https://nitter.poast.org",
    "https://nitter.privacydev.net",
]


def _get_json(url: str, headers: dict, timeout: float) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": _UA, **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read(1024 * 1024))
    except urllib.request.HTTPError as exc:
        if exc.code == 404:
            raise SkillError(NOT_FOUND, "Tweet not found or account is private")
        if exc.code == 429:
            raise SkillError(RATE_LIMITED, "Twitter rate-limited; try again later")
        raise SkillError(UPSTREAM_BROKEN, f"HTTP {exc.code}")


def _tweet_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.netloc not in ("twitter.com", "www.twitter.com", "x.com", "www.x.com", "t.co"):
        raise SkillError(BAD_INPUT, "not a Twitter/X URL")
    # Normalize x.com → twitter.com for oembed compatibility
    return url.replace("x.com/", "twitter.com/").replace("www.x.com/", "twitter.com/")


def _strip_html(html: str) -> str:
    """Very simple HTML tag stripper for oembed content."""
    return re.sub(r"<[^>]+>", "", html).strip()


class TwitterChannel(Channel):
    name = "twitter"
    description = "Twitter / X posts (public tweets via oEmbed; search needs TWITTER_BEARER_TOKEN)"
    level = "experimental"
    domains = ("twitter.com", "x.com", "t.co")

    actions = (
        Action(
            "read",
            "Read a public tweet",
            (Param("target", "Tweet URL (twitter.com or x.com)"),),
            backends=(("oembed", "_oembed_read"), ("nitter", "_nitter_read")),
            live_test={"target": "https://twitter.com/Twitter/status/1"},
        ),
        Action(
            "search",
            "Search tweets (requires TWITTER_BEARER_TOKEN env var)",
            (
                Param("query", "search query"),
                Param("limit", "max results", required=False, type=int, default=10),
            ),
            backends=(("twitter-v2", "_v2_search"),),
            public_web=("x.com/", "twitter.com/"),
            live_test={"query": "playwright browser automation", "limit": 3},
        ),
        Action(
            "download",
            "Download video from a tweet to local disk",
            (
                Param("target", "Tweet URL containing a video"),
                Param("output", "output directory (agent picks if omitted)", required=False, default=None),
                Param("quality", "best | 720p | 480p | audio", required=False, default="best"),
            ),
            backends=(("yt-dlp", "_ytdlp_download"),),
            live_test={"target": "https://twitter.com/Twitter/status/1"},
        ),
    )

    def can_handle(self, url: str) -> bool:
        try:
            return urlparse(url).netloc.lstrip("www.") in ("twitter.com", "x.com", "t.co")
        except Exception:
            return False

    def _ytdlp_download(self, *, target: str, output, quality: str, timeout: float) -> list:
        from reach_kit.runtime.ytdlp import download
        return [download(target, output=output, quality=quality, timeout=timeout)]

    def _oembed_read(self, *, target: str, timeout: float) -> list:
        url = _tweet_url(target)
        oembed_url = f"{_OEMBED}?{urllib.parse.urlencode({'url': url, 'omit_script': 'true'})}"
        d = _get_json(oembed_url, {}, timeout)
        html = d.get("html", "")
        # Extract tweet text: everything before the footer paragraph
        text = _strip_html(html)
        # Remove standard footer noise like "— Name (@handle) Date"
        text = re.sub(r"—\s+.+?\(@\w+\)\s+\w+ \d+, \d{4}$", "", text, flags=re.S).strip()
        return [make_item(
            title=None,
            url=url,
            author=d.get("author_name"),
            text=text,
            raw={"author_url": d.get("author_url"), "provider": d.get("provider_name")},
        )]

    def _nitter_read(self, *, target: str, timeout: float) -> list:
        """Scrape a Nitter instance for the tweet text."""
        url = _tweet_url(target)
        # Extract the path after the domain (twitter.com/user/status/ID)
        parsed = urlparse(url)
        path = parsed.path

        last_err = SkillError(UPSTREAM_BROKEN, "All Nitter instances failed")
        for base in _NITTER_INSTANCES:
            try:
                req = urllib.request.Request(
                    base + path,
                    headers={"User-Agent": "Mozilla/5.0", "Accept": "text/html"},
                )
                with urllib.request.urlopen(req, timeout=timeout / len(_NITTER_INSTANCES)) as resp:
                    html = resp.read(512 * 1024).decode("utf-8", errors="replace")
                # Extract tweet text from Nitter's HTML
                m = re.search(r'class="tweet-content[^"]*"[^>]*>(.*?)</div>', html, re.S)
                if m:
                    text = _strip_html(m.group(1)).strip()
                    author_m = re.search(r'class="fullname"[^>]*>([^<]+)', html)
                    author = author_m.group(1).strip() if author_m else None
                    return [make_item(url=url, author=author, text=text,
                                      raw={"source": base})]
            except Exception as exc:
                last_err = SkillError(UPSTREAM_BROKEN, f"Nitter {base}: {exc}")
        raise last_err

    def _v2_search(self, *, query: str, limit: int, timeout: float) -> list:
        token = os.environ.get("TWITTER_BEARER_TOKEN")
        if not token:
            raise SkillError(
                NEED_SETUP,
                "Twitter v2 search requires a bearer token",
                hint="Set TWITTER_BEARER_TOKEN env var. Get one at developer.twitter.com.",
            )
        params = urllib.parse.urlencode({
            "query": query + " -is:retweet lang:en",
            "max_results": min(limit, 100),
            "tweet.fields": "author_id,created_at,text,public_metrics",
            "expansions": "author_id",
            "user.fields": "username,name",
        })
        d = _get_json(
            f"https://api.twitter.com/2/tweets/search/recent?{params}",
            {"Authorization": f"Bearer {token}"},
            timeout,
        )
        users = {u["id"]: u for u in d.get("includes", {}).get("users", [])}
        tweets = d.get("data") or []
        if not tweets:
            raise SkillError(NOT_FOUND, "No tweets found for this query")
        return [make_item(
            url=f"https://twitter.com/i/web/status/{t['id']}",
            author=users.get(t.get("author_id"), {}).get("username"),
            published_at=t.get("created_at"),
            text=t.get("text", ""),
            raw=t.get("public_metrics"),
        ) for t in tweets[:limit]]
