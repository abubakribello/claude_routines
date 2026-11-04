"""LinkedIn channel.

LinkedIn's API (now "LinkedIn APIs") requires OAuth 2.0 for almost
everything, including reading posts. Without credentials:
  - Company pages and job listings are publicly accessible via web.
  - Individual posts and profiles require auth.

Backends:
  search: web fallback (Jina/Exa via public_web)
  read:   web fallback for public company/job pages

For authenticated access, set LINKEDIN_ACCESS_TOKEN from an OAuth flow
at https://www.linkedin.com/developers/apps and add the r_liteprofile,
r_emailaddress, and w_member_social scopes.
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
_API = "https://api.linkedin.com/v2"


def _li_url(url: str) -> str:
    parsed = urlparse(url)
    if "linkedin.com" not in parsed.netloc:
        raise SkillError(BAD_INPUT, "not a LinkedIn URL")
    return url


def _api_get(path: str, token: str, timeout: float) -> dict:
    req = urllib.request.Request(
        f"{_API}{path}",
        headers={
            "User-Agent": _UA,
            "Authorization": f"Bearer {token}",
            "X-Restli-Protocol-Version": "2.0.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read(1024 * 1024))
    except urllib.request.HTTPError as exc:
        if exc.code == 401 or exc.code == 403:
            raise SkillError(NEED_SETUP, "LinkedIn token expired or missing required scopes")
        if exc.code == 404:
            raise SkillError(NOT_FOUND, "LinkedIn resource not found")
        if exc.code == 429:
            raise SkillError(RATE_LIMITED, "LinkedIn API rate-limited")
        raise SkillError(UPSTREAM_BROKEN, f"LinkedIn API HTTP {exc.code}")


class LinkedInChannel(Channel):
    name = "linkedin"
    description = "LinkedIn jobs and company pages (web fallback; set LINKEDIN_ACCESS_TOKEN for profile/post access)"
    level = "experimental"
    domains = ("linkedin.com",)
    login_url = "https://www.linkedin.com/login"

    actions = (
        Action(
            "search",
            "Search LinkedIn (uses web fallback for public content)",
            (
                Param("query", "what to search for"),
                Param("limit", "max results", required=False, type=int, default=5),
            ),
            backends=(),
            public_web=("linkedin.com/",),
            live_test={"query": "senior software engineer remote"},
        ),
        Action(
            "read",
            "Read a LinkedIn profile or company page (public data via web; auth for posts)",
            (Param("target", "LinkedIn URL"),),
            backends=(("linkedin-api", "_api_read"),),
            public_web=("linkedin.com/company/", "linkedin.com/jobs/"),
            live_test={"target": "https://www.linkedin.com/company/anthropic"},
        ),
    )

    def can_handle(self, url: str) -> bool:
        try:
            return "linkedin.com" in urlparse(url).netloc
        except Exception:
            return False

    def _api_read(self, *, target: str, timeout: float) -> list:
        token = os.environ.get("LINKEDIN_ACCESS_TOKEN")
        if not token:
            raise SkillError(
                NEED_SETUP,
                "LinkedIn read requires an access token",
                hint="Set LINKEDIN_ACCESS_TOKEN env var. Create an app at linkedin.com/developers.",
            )
        url = _li_url(target)

        # Try to extract company vanity name from URL
        m = re.search(r"/company/([^/?#]+)", url)
        if m:
            company = m.group(1)
            # Look up company by vanity name
            d = _api_get(
                f"/organizations?q=vanityName&vanityName={urllib.parse.quote(company)}",
                token, timeout,
            )
            elements = d.get("elements", [])
            if not elements:
                raise SkillError(NOT_FOUND, f"Company '{company}' not found on LinkedIn")
            org = elements[0]
            name = org.get("localizedName") or org.get("name", {}).get("localized", {})
            if isinstance(name, dict):
                name = next(iter(name.values()), company)
            desc = org.get("localizedDescription") or ""
            return [make_item(
                title=str(name),
                url=url,
                text=str(desc),
                raw={"id": org.get("id"), "website": org.get("websiteUrl")},
            )]

        raise SkillError(
            BAD_INPUT,
            "Only company page URLs are supported with the API backend. "
            "For job listings and posts, use the web fallback.",
        )
