"""Web channel — search and read any public page.

Backends (tried in order):
  read:   jina (r.jina.ai reader API) → exa (Exa MCP fetch)
  search: exa  (Exa MCP web search)

This channel is a fallback: agents with working built-in search/fetch
should use those first. `can_handle` returns True for any URL so it
catches everything the more specific channels don't claim.
"""

from __future__ import annotations

import json
import re
import time
import urllib.request
from typing import Optional
from urllib.parse import urlparse

from reach_kit.channels.base import Action, Channel, Param
from reach_kit.runtime.result import (
    BAD_INPUT,
    RATE_LIMITED,
    UPSTREAM_BROKEN,
    SkillError,
    make_item,
)

_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
_EXA_MCP = "https://mcp.exa.ai/mcp"
_JINA_BASE = "https://r.jina.ai/"
_MAX_BYTES = 5 * 1024 * 1024

_EXA_HEADER_RE = re.compile(r"^(Title|URL|Published|Author):\s*(.*)$")
_EXA_RATE_RE = re.compile(
    r"\b429\b|rate[ _-]?limit|too many requests|\bquota\b|"
    r"(?:credit|credits|balance).{0,40}(?:exhaust|deplet|insufficient|exceed)",
    re.IGNORECASE,
)


def _normalize_url(raw: str) -> str:
    """Ensure the URL has a scheme and is http(s)."""
    raw = raw.strip()
    if not raw.startswith(("http://", "https://")):
        raw = "https://" + raw
    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https"):
        raise SkillError(BAD_INPUT, "target must be a public http(s) URL")
    if not parsed.netloc:
        raise SkillError(BAD_INPUT, "target URL has no host")
    return raw


def _http_post(url: str, body: bytes, headers: dict, timeout: float) -> bytes:
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read(_MAX_BYTES)


def _exa_call(tool: str, arguments: dict, timeout: float) -> str:
    """Call one tool on Exa's free hosted MCP and return the text content."""
    body = json.dumps({
        "jsonrpc": "2.0", "id": 1,
        "method": "tools/call",
        "params": {"name": tool, "arguments": arguments},
    }).encode()

    raw = _http_post(_EXA_MCP, body, {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }, timeout).decode("utf-8", errors="replace")

    # Exa responds with Server-Sent Events lines or plain JSON
    payloads = [ln[5:].strip() for ln in raw.splitlines() if ln.startswith("data:")] or [raw]
    msg = json.loads(payloads[-1])

    if "error" in msg:
        text = str(msg["error"].get("message", msg["error"]))
        code = msg["error"].get("code")
        if code in (-32602, "-32602"):
            raise SkillError(BAD_INPUT, f"Exa rejected arguments: {text[:300]}")
        if code in (429, "429") or _EXA_RATE_RE.search(text):
            raise SkillError(RATE_LIMITED, f"Exa rate limited: {text[:300]}")
        raise SkillError(UPSTREAM_BROKEN, f"Exa error: {text[:300]}")

    result = msg.get("result") or {}
    if result.get("isError"):
        text = "\n".join(c.get("text", "") for c in result.get("content", []) if c.get("type") == "text")
        raise SkillError(UPSTREAM_BROKEN, f"Exa tool error: {text[:300]}")

    return "\n".join(c.get("text", "") for c in result.get("content", []) if c.get("type") == "text")


def _parse_exa(text: str) -> list:
    """Parse Exa's Title:/URL:/Published:/Author: block format into items."""
    items = []
    for block in re.split(r"\n(?=Title: )", "\n" + text.strip()):
        block = block.strip()
        if not block.startswith("Title:"):
            continue
        fields, body_lines = {}, []
        lines = block.splitlines()
        i = 0
        while i < len(lines):
            m = _EXA_HEADER_RE.match(lines[i])
            if not m:
                break
            fields[m.group(1).lower()] = m.group(2).strip()
            i += 1
        for line in lines[i:]:
            if line.strip() in ("Highlights:", "Text:"):
                continue
            body_lines.append(line)
        na = lambda v: None if v in (None, "", "N/A") else v  # noqa: E731
        items.append(make_item(
            title=na(fields.get("title")),
            url=na(fields.get("url")),
            author=na(fields.get("author")),
            published_at=na(fields.get("published")),
            text="\n".join(body_lines).strip(),
            raw=fields,
        ))
    return items


def _parse_jina(url: str, body: str) -> dict:
    """Extract title, published_at and markdown content from a Jina Reader response."""
    title = re.search(r"^Title:\s*(.*)$", body, re.M)
    published = re.search(r"^Published Time:\s*(.*)$", body, re.M)
    content = body.split("Markdown Content:", 1)[1] if "Markdown Content:" in body else body
    return make_item(
        title=title.group(1).strip() if title else None,
        url=url,
        published_at=published.group(1).strip() if published else None,
        text=content.strip(),
    )


class WebChannel(Channel):
    name = "web"
    description = "Web search and page reading (fallback for any URL)"
    level = "default"

    actions = (
        Action(
            "search",
            "Search the web via Exa semantic search",
            (
                Param("query", "what to search for"),
                Param("limit", "max results", required=False, type=int, default=5),
            ),
            backends=(("exa", "_exa_search"),),
            live_test={"query": "playwright browser automation", "limit": 3},
        ),
        Action(
            "read",
            "Read a web page as clean markdown text",
            (Param("target", "page URL"),),
            backends=(("jina", "_jina_read"), ("exa", "_exa_read")),
            live_test={"target": "https://example.com"},
        ),
    )

    def can_handle(self, url: str) -> bool:
        return True  # fallback: handles any URL not claimed by another channel

    # ── backends ──

    def _exa_search(self, *, query: str, limit: int, timeout: float) -> list:
        text = _exa_call("web_search_exa", {"query": query, "objective": query, "numResults": limit}, timeout)
        items = _parse_exa(text)
        if not items:
            raise SkillError(UPSTREAM_BROKEN, "Exa returned no recognizable search results")
        return items[:limit]

    def _jina_read(self, *, target: str, timeout: float) -> list:
        url = _normalize_url(target)
        req = urllib.request.Request(
            _JINA_BASE + url,
            headers={"User-Agent": _UA, "Accept": "text/plain"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read(_MAX_BYTES).decode("utf-8", errors="replace")
        # Detect anti-bot challenge pages
        sample = body[:4096].casefold()
        if ("just a moment" in sample or "captcha" in sample) and "cloudflare" in sample:
            raise SkillError(UPSTREAM_BROKEN, "Jina Reader returned a Cloudflare challenge page")
        return [_parse_jina(url, body)]

    def _exa_read(self, *, target: str, timeout: float) -> list:
        url = _normalize_url(target)
        text = _exa_call("web_fetch_exa", {"urls": [url], "maxCharacters": 20000}, timeout)
        items = _parse_exa(text)
        if items:
            items[0]["url"] = items[0]["url"] or url
            return items[:1]
        if not text.strip():
            raise SkillError(UPSTREAM_BROKEN, "Exa returned no content for this URL")
        return [make_item(url=url, text=text.strip())]
