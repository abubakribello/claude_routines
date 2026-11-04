"""Unified result envelope and error codes.

Every command prints exactly one JSON object:
    {schema_version, ok, channel, action, backend, items, meta, error}

Agents branch on `ok` and `error.code`; they never parse prose.
"""

from __future__ import annotations

import datetime as _dt
import socket
import subprocess
import urllib.error
from typing import Any, Optional

SCHEMA_VERSION = 1

# Error codes
NEED_SETUP      = "NEED_SETUP"       # missing tool/dependency
NEED_LOGIN      = "NEED_LOGIN"       # auth required, user must log in
UPSTREAM_BROKEN = "UPSTREAM_BROKEN"  # platform/network error
TIMEOUT         = "TIMEOUT"          # backend didn't answer in time
RATE_LIMITED    = "RATE_LIMITED"     # platform enforced a rate limit
PLATFORM_BLOCKED = "PLATFORM_BLOCKED" # captcha / risk verification
NOT_FOUND       = "NOT_FOUND"        # content doesn't exist
BAD_INPUT       = "BAD_INPUT"        # invalid arguments

# Codes where trying another backend cannot help
FINAL_CODES = frozenset({NOT_FOUND, BAD_INPUT, PLATFORM_BLOCKED, RATE_LIMITED, NEED_LOGIN})

DEFAULT_HINTS = {
    NEED_SETUP:       "Run `reach-kit setup` or install the required tool.",
    NEED_LOGIN:       "The channel needs authentication. Never ask for a password; open a login window for the user.",
    UPSTREAM_BROKEN:  "Platform is temporarily unavailable. Tell the user which platform, not which tool.",
    TIMEOUT:          "Backend timed out. Don't retry in a loop.",
    RATE_LIMITED:     "Platform rate-limited. Wait retry_after_seconds; don't switch backends.",
    PLATFORM_BLOCKED: "Platform wants verification. Stop; let the user resolve it on the official site.",
    NOT_FOUND:        "Content doesn't exist. Check the URL or ID.",
    BAD_INPUT:        "Invalid arguments. Run `reach-kit channels` to see valid usage.",
}


class SkillError(Exception):
    """A failure with a unified error code that the agent can branch on."""

    def __init__(self, code: str, message: str, hint: Optional[str] = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint


def classify(exc: BaseException) -> SkillError:
    """Map any backend exception to a SkillError."""
    if isinstance(exc, SkillError):
        return exc
    if isinstance(exc, urllib.error.HTTPError):
        if exc.code == 404:
            return SkillError(NOT_FOUND, f"HTTP 404: {exc.reason}")
        if exc.code == 429:
            return SkillError(RATE_LIMITED, "HTTP 429: too many requests")
        return SkillError(UPSTREAM_BROKEN, f"HTTP {exc.code}: {exc.reason}")
    if isinstance(exc, (subprocess.TimeoutExpired, socket.timeout, TimeoutError)):
        return SkillError(TIMEOUT, "upstream did not answer in time")
    if isinstance(exc, urllib.error.URLError):
        return SkillError(UPSTREAM_BROKEN, f"network error: {exc.reason}")
    if isinstance(exc, FileNotFoundError):
        return SkillError(NEED_SETUP, f"missing executable: {exc.filename or exc}")
    return SkillError(UPSTREAM_BROKEN, f"{type(exc).__name__}: {exc}")


def make_item(
    *,
    title: Optional[str] = None,
    url: Optional[str] = None,
    author: Optional[str] = None,
    published_at: Optional[str] = None,
    text: Optional[str] = None,
    raw: Any = None,
) -> dict:
    """One normalized content item. Missing fields are null; `raw` keeps upstream data."""
    return {
        "title":        title or None,
        "url":          url or None,
        "author":       author or None,
        "published_at": published_at or None,
        "text":         text or None,
        "raw":          raw,
    }


def unix_to_iso(value: Any) -> Optional[str]:
    """Convert a unix timestamp (int/float) to ISO 8601 UTC string, or None."""
    try:
        s = int(value)
    except (TypeError, ValueError):
        return None
    if s <= 0:
        return None
    return _dt.datetime.fromtimestamp(s, _dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def envelope(
    *,
    channel: Optional[str],
    action: Optional[str],
    backend: Optional[str] = None,
    items: Optional[list] = None,
    elapsed_ms: int = 0,
    attempts: Optional[list] = None,
    error: Optional[SkillError] = None,
) -> dict:
    """Build the unified output envelope dict."""
    ok = error is None
    return {
        "schema_version": SCHEMA_VERSION,
        "ok":      ok,
        "channel": channel,
        "action":  action,
        "backend": backend if ok else None,
        "items":   list(items or []) if ok else [],
        "meta":    {"elapsed_ms": elapsed_ms, "attempts": list(attempts or [])},
        "error":   None if ok else {
            "code":    error.code,
            "message": error.message,
            "hint":    error.hint or DEFAULT_HINTS.get(error.code, ""),
        },
    }
