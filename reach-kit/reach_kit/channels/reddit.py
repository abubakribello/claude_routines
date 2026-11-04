"""Reddit channel — posts and comments via Reddit's public JSON API.

No API key required for public subreddits and posts. Reddit serves
JSON at <url>.json for any public page — the cleanest public API
in this list.

Backends:
  search: reddit-json  (www.reddit.com/search.json)
  read:   reddit-json  (www.reddit.com/r/.../comments/ID.json)
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
    unix_to_iso,
)

_UA = "reach-kit:v0.1 (read-only research tool)"
_MAX_BYTES = 2 * 1024 * 1024


def _get(url: str, timeout: float) -> dict | list:
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read(_MAX_BYTES))
    except urllib.request.HTTPError as exc:
        if exc.code == 404:
            raise SkillError(NOT_FOUND, f"Reddit page not found: {url}")
        if exc.code == 429:
            raise SkillError(RATE_LIMITED, "Reddit rate-limited; try again later")
        if exc.code == 403:
            raise SkillError(NOT_FOUND, "Reddit page is private or removed")
        raise SkillError(UPSTREAM_BROKEN, f"Reddit HTTP {exc.code}")


def _post_url(url: str) -> str:
    """Validate and normalize a Reddit post URL."""
    parsed = urlparse(url)
    if "reddit.com" not in parsed.netloc:
        raise SkillError(BAD_INPUT, "not a reddit.com URL")
    # Ensure we use www.reddit.com
    return url.replace("old.reddit.com", "www.reddit.com").replace("np.reddit.com", "www.reddit.com")


class RedditChannel(Channel):
    name = "reddit"
    description = "Reddit posts and comments (public subreddits)"
    level = "optional"
    domains = ("reddit.com",)

    actions = (
        Action(
            "search",
            "Search Reddit posts",
            (
                Param("query", "what to search for"),
                Param("limit", "max results", required=False, type=int, default=5),
                Param("subreddit", "limit to subreddit (without r/)", required=False, default=None),
            ),
            backends=(("reddit-json", "_json_search"),),
            live_test={"query": "playwright browser automation", "limit": 3},
        ),
        Action(
            "read",
            "Read a Reddit post with its top comments",
            (Param("target", "Reddit post URL"),),
            backends=(("reddit-json", "_json_read"),),
            live_test={"target": "https://www.reddit.com/r/Python/comments/1234567"},
        ),
        Action(
            "subreddit",
            "Get hot posts from a subreddit",
            (
                Param("name", "subreddit name (without r/)"),
                Param("limit", "max results", required=False, type=int, default=10),
            ),
            backends=(("reddit-json", "_json_subreddit"),),
            live_test={"name": "programming", "limit": 5},
        ),
        Action(
            "download",
            "Download a Reddit video post to local disk",
            (
                Param("target", "Reddit post URL containing a video"),
                Param("output", "output directory (agent picks if omitted)", required=False, default=None),
                Param("quality", "best | 720p | 480p | audio", required=False, default="best"),
            ),
            backends=(("yt-dlp", "_ytdlp_download"),),
            live_test={"target": "https://www.reddit.com/r/videos/comments/abc123"},
        ),
    )

    def can_handle(self, url: str) -> bool:
        try:
            return "reddit.com" in urlparse(url).netloc
        except Exception:
            return False

    def _ytdlp_download(self, *, target: str, output, quality: str, timeout: float) -> list:
        from reach_kit.runtime.ytdlp import download
        return [download(target, output=output, quality=quality, timeout=timeout)]

    def _json_search(self, *, query: str, limit: int, timeout: float,
                     subreddit: str = None) -> list:
        base = f"https://www.reddit.com/r/{subreddit}/search.json" if subreddit \
               else "https://www.reddit.com/search.json"
        url = f"{base}?{urllib.parse.urlencode({'q': query, 'limit': limit, 'sort': 'relevance', 'type': 'link'})}"
        data = _get(url, timeout)
        posts = data.get("data", {}).get("children", [])
        if not posts:
            raise SkillError(NOT_FOUND, "No Reddit results found")
        return [make_item(
            title=p["data"].get("title"),
            url=f"https://www.reddit.com{p['data'].get('permalink', '')}",
            author=p["data"].get("author"),
            published_at=unix_to_iso(p["data"].get("created_utc")),
            text=p["data"].get("selftext") or p["data"].get("url") or "",
            raw={
                "score": p["data"].get("score"),
                "num_comments": p["data"].get("num_comments"),
                "subreddit": p["data"].get("subreddit"),
            },
        ) for p in posts[:limit] if p.get("data")]

    def _json_read(self, *, target: str, timeout: float) -> list:
        url = _post_url(target)
        json_url = url.rstrip("/") + ".json?limit=25"
        data = _get(json_url, timeout)
        if not isinstance(data, list) or len(data) < 2:
            raise SkillError(UPSTREAM_BROKEN, "Unexpected Reddit JSON structure")

        post_data = data[0]["data"]["children"][0]["data"]
        comments_children = data[1]["data"]["children"]

        def _extract_comments(children, depth=0, max_depth=3) -> list:
            result = []
            for c in children:
                if c.get("kind") != "t1":
                    continue
                cd = c.get("data", {})
                body = cd.get("body", "").strip()
                if not body or body == "[deleted]" or body == "[removed]":
                    continue
                indent = "  " * depth
                result.append(f"{indent}**{cd.get('author', '?')}** ({cd.get('score', 0)} pts): {body[:500]}")
                if depth < max_depth:
                    replies = cd.get("replies") or {}
                    if isinstance(replies, dict):
                        sub = replies.get("data", {}).get("children", [])
                        result.extend(_extract_comments(sub, depth + 1, max_depth))
            return result

        body = post_data.get("selftext", "") or post_data.get("url", "")
        comments = _extract_comments(comments_children)
        full_text = body + ("\n\n---\n\n" + "\n\n".join(comments[:30]) if comments else "")

        return [make_item(
            title=post_data.get("title"),
            url=f"https://www.reddit.com{post_data.get('permalink', '')}",
            author=post_data.get("author"),
            published_at=unix_to_iso(post_data.get("created_utc")),
            text=full_text.strip(),
            raw={
                "score": post_data.get("score"),
                "num_comments": post_data.get("num_comments"),
                "subreddit": post_data.get("subreddit"),
                "flair": post_data.get("link_flair_text"),
            },
        )]

    def _json_subreddit(self, *, name: str, limit: int, timeout: float) -> list:
        url = f"https://www.reddit.com/r/{name}/hot.json?limit={limit}"
        data = _get(url, timeout)
        posts = data.get("data", {}).get("children", [])
        if not posts:
            raise SkillError(NOT_FOUND, f"No posts found in r/{name}")
        return [make_item(
            title=p["data"].get("title"),
            url=f"https://www.reddit.com{p['data'].get('permalink', '')}",
            author=p["data"].get("author"),
            published_at=unix_to_iso(p["data"].get("created_utc")),
            text=p["data"].get("selftext", "") or p["data"].get("url", ""),
            raw={"score": p["data"].get("score"), "num_comments": p["data"].get("num_comments")},
        ) for p in posts[:limit] if p.get("data")]
