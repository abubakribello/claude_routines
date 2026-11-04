"""GitHub channel — search repos and read repo/issue/PR content.

Backends (tried in order):
  search: gh-cli (GitHub CLI `gh search repos`) → github-api (REST API)
  read:   gh-cli (`gh repo view`, `gh issue view`, `gh pr view`) → github-api

The gh CLI is the preferred backend because it handles auth automatically
when the user is logged in. The github-api backend works unauthenticated
for public content (60 req/hr) or uses a GITHUB_TOKEN env var.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import urllib.request
from typing import Optional
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

_API = "https://api.github.com"
_UA = "reach-kit"


def _gh(*args, timeout: float = 30.0) -> str:
    """Run a gh CLI command and return stdout. Raise SkillError on failure."""
    try:
        proc = subprocess.run(
            ["gh", *args],
            capture_output=True, text=True,
            timeout=timeout,
            env={**os.environ, "GH_NO_UPDATE_NOTIFIER": "1"},
        )
    except FileNotFoundError:
        raise SkillError("NEED_SETUP", "gh CLI not found; install it from https://cli.github.com") from None
    if proc.returncode != 0:
        msg = (proc.stderr or proc.stdout or "").strip()
        if "not found" in msg.lower() or "404" in msg:
            raise SkillError(NOT_FOUND, msg[:300])
        if "rate limit" in msg.lower() or "429" in msg:
            raise SkillError(RATE_LIMITED, msg[:300])
        raise SkillError(UPSTREAM_BROKEN, msg[:300])
    return proc.stdout


def _api_get(path: str, timeout: float = 30.0) -> dict:
    """GET from GitHub REST API. Uses GITHUB_TOKEN if set."""
    headers = {"User-Agent": _UA, "Accept": "application/vnd.github+json",
               "X-GitHub-Api-Version": "2022-11-28"}
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(f"{_API}{path}", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read(4 * 1024 * 1024))
    except urllib.request.HTTPError as exc:
        if exc.code == 404:
            raise SkillError(NOT_FOUND, f"not found: {path}")
        if exc.code == 429 or exc.code == 403:
            raise SkillError(RATE_LIMITED, f"GitHub API rate limited (HTTP {exc.code})")
        raise SkillError(UPSTREAM_BROKEN, f"GitHub API HTTP {exc.code}")


def _parse_repo_ref(target: str) -> Optional[str]:
    """Extract owner/repo from a string like 'owner/repo' or a GitHub URL."""
    target = target.strip()
    # GitHub URL pattern
    m = re.match(r"https?://github\.com/([^/]+/[^/]+?)(?:\.git|/.*)?$", target)
    if m:
        return m.group(1)
    # owner/repo pattern
    if re.match(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", target):
        return target
    return None


def _parse_issue_ref(target: str) -> Optional[tuple]:
    """Extract (owner/repo, number, kind) from a GitHub issue/PR URL."""
    m = re.match(
        r"https?://github\.com/([^/]+/[^/]+?)/(issues|pull)/(\d+)", target
    )
    if m:
        return m.group(1), int(m.group(3)), m.group(2)
    return None


class GitHubChannel(Channel):
    name = "github"
    description = "GitHub repos, issues and pull requests"
    level = "default"
    domains = ("github.com",)

    actions = (
        Action(
            "search",
            "Search GitHub repositories",
            (
                Param("query", "what to search for"),
                Param("limit", "max results", required=False, type=int, default=5),
            ),
            backends=(("gh-cli", "_gh_search"), ("github-api", "_api_search")),
            live_test={"query": "playwright browser automation", "limit": 3},
        ),
        Action(
            "read",
            "Read a repo (with README) or an issue/PR (with comments)",
            (Param("target", "owner/repo, or a GitHub issue/PR URL"),),
            backends=(("gh-cli", "_gh_read"), ("github-api", "_api_read")),
            live_test={"target": "microsoft/playwright"},
        ),
    )

    def can_handle(self, url: str) -> bool:
        try:
            return urlparse(url).netloc in ("github.com", "www.github.com")
        except Exception:
            return False

    # ── search backends ──

    def _gh_search(self, *, query: str, limit: int, timeout: float) -> list:
        out = _gh("search", "repos", query, "--limit", str(limit),
                  "--json", "fullName,description,stargazersCount,url,updatedAt",
                  timeout=timeout)
        rows = json.loads(out or "[]")
        return [make_item(
            title=r.get("fullName"),
            url=r.get("url"),
            text=r.get("description"),
            published_at=r.get("updatedAt"),
            raw=r,
        ) for r in rows[:limit]]

    def _api_search(self, *, query: str, limit: int, timeout: float) -> list:
        data = _api_get(f"/search/repositories?q={urllib.parse.quote(query)}&per_page={limit}", timeout)
        return [make_item(
            title=r.get("full_name"),
            url=r.get("html_url"),
            text=r.get("description"),
            published_at=r.get("updated_at"),
            raw={"stars": r.get("stargazers_count"), "language": r.get("language")},
        ) for r in data.get("items", [])[:limit]]

    # ── read backends ──

    def _gh_read(self, *, target: str, timeout: float) -> list:
        issue_ref = _parse_issue_ref(target)
        if issue_ref:
            repo, num, kind = issue_ref
            path = "pulls" if kind == "pull" else "issues"
            out = _gh("api", f"repos/{repo}/{path}/{num}", timeout=timeout)
            d = json.loads(out)
            comments_out = _gh("api", f"repos/{repo}/{path}/{num}/comments", timeout=timeout)
            comments = json.loads(comments_out) if comments_out else []
            comment_text = "\n\n---\n\n".join(
                f"**{c.get('user', {}).get('login', '?')}**: {c.get('body', '')}"
                for c in (comments if isinstance(comments, list) else [])
            )
            body = d.get("body", "") or ""
            full_text = body + ("\n\n" + comment_text if comment_text else "")
            return [make_item(
                title=d.get("title"),
                url=d.get("html_url"),
                author=d.get("user", {}).get("login"),
                published_at=d.get("created_at"),
                text=full_text.strip(),
                raw={"comments_count": d.get("comments")},
            )]

        repo = _parse_repo_ref(target)
        if not repo:
            raise SkillError(BAD_INPUT, "target must be owner/repo or a GitHub issue/PR URL")
        out = _gh("api", f"repos/{repo}", timeout=timeout)
        d = json.loads(out)
        readme = ""
        try:
            import base64
            readme_out = _gh("api", f"repos/{repo}/readme", timeout=timeout / 2)
            readme = base64.b64decode(json.loads(readme_out).get("content", "")).decode("utf-8", errors="replace")
        except Exception:
            pass
        return [make_item(
            title=d.get("full_name"),
            url=d.get("html_url"),
            text=(d.get("description") or "") + ("\n\n" + readme if readme else ""),
            raw={"stars": d.get("stargazers_count"), "language": d.get("language")},
        )]

    def _api_read(self, *, target: str, timeout: float) -> list:
        issue_ref = _parse_issue_ref(target)
        if issue_ref:
            repo, num, kind = issue_ref
            path = "pulls" if kind == "pull" else "issues"
            d = _api_get(f"/repos/{repo}/{path}/{num}", timeout)
            comments_data = _api_get(f"/repos/{repo}/{path}/{num}/comments", timeout)
            comments = comments_data if isinstance(comments_data, list) else []
            comment_text = "\n\n---\n\n".join(
                f"**{c.get('user', {}).get('login', '?')}**: {c.get('body', '')}"
                for c in comments
            )
            body = d.get("body", "") or ""
            full_text = body + ("\n\n" + comment_text if comment_text else "")
            return [make_item(
                title=d.get("title"),
                url=d.get("html_url"),
                author=d.get("user", {}).get("login"),
                published_at=d.get("created_at"),
                text=full_text.strip(),
                raw={"comments_count": d.get("comments")},
            )]

        repo = _parse_repo_ref(target)
        if not repo:
            raise SkillError(BAD_INPUT, "target must be owner/repo or a GitHub issue/PR URL")
        d = _api_get(f"/repos/{repo}", timeout)
        # Try to fetch README
        readme_text = ""
        try:
            readme = _api_get(f"/repos/{repo}/readme", timeout / 2)
            import base64
            readme_text = base64.b64decode(readme.get("content", "")).decode("utf-8", errors="replace")
        except (SkillError, Exception):
            pass
        return [make_item(
            title=d.get("full_name"),
            url=d.get("html_url"),
            text=(d.get("description") or "") + ("\n\n" + readme_text if readme_text else ""),
            raw={"stars": d.get("stargazers_count"), "language": d.get("language")},
        )]


# Fix missing import
import urllib.parse  # noqa: E402
