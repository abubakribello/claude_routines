"""CLI entry point for reach-kit.

Commands:
  reach-kit channels                   list all channels, actions, params
  reach-kit <channel> <action> [args]  run an action
  reach-kit read <url>                 auto-pick channel and read a URL
  reach-kit setup                      install the Claude skill file
  reach-kit version                    print version as JSON

All commands print one JSON object to stdout.
Exit 0 = ok, 1 = error.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import List, Optional

from reach_kit import __version__
from reach_kit.channels import get_all_channels
from reach_kit.channels.base import Action, Channel
from reach_kit.runtime.dispatch import DEFAULT_TIMEOUT, find_action, run_action
from reach_kit.runtime.result import (
    BAD_INPUT,
    NOT_FOUND,
    SCHEMA_VERSION,
    SkillError,
    envelope,
)

SKILL_SRC = Path(__file__).parent / "skill" / "SKILL.md"


def _emit(payload: dict) -> int:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()
    return 0 if payload.get("ok") else 1


def _mgmt(action: str, fn, *args, **kwargs) -> int:
    try:
        result, error = fn(*args, **kwargs), None
    except SkillError as err:
        result = None
        error = {"code": err.code, "message": err.message, "hint": err.hint or ""}
    return _emit({
        "schema_version": SCHEMA_VERSION,
        "ok": error is None,
        "action": action,
        "result": result,
        "error": error,
    })


# ── channel listing ──────────────────────────────────────────────────────────

def _action_dict(ch: Channel, a: Action) -> dict:
    usage_parts = ["reach-kit", ch.name, a.name]
    for p in a.params:
        usage_parts.append(f"<{p.name}>" if p.required else f"[--{p.name} {p.name.upper()}]")
    return {
        "name": a.name,
        "help": a.help,
        "usage": " ".join(usage_parts),
        "params": [
            {"name": p.name, "help": p.help, "required": p.required,
             "type": p.type.__name__, "default": p.default}
            for p in a.params
        ],
        "backends": [label for label, _ in a.backends],
    }


def cmd_channels() -> int:
    channels = [
        {
            "name": ch.name,
            "description": ch.description,
            "level": ch.level,
            "actions": [_action_dict(ch, a) for a in ch.actions],
        }
        for ch in get_all_channels()
    ]
    return _emit({
        "schema_version": SCHEMA_VERSION,
        "ok": True,
        "commands": {
            "read": "reach-kit read <url>  (picks the channel from the URL)",
            "action": "reach-kit <channel> <action> [args] [--timeout SECONDS]",
        },
        "channels": channels,
    })


# ── read <url> ───────────────────────────────────────────────────────────────

def cmd_read(url: str, timeout: float = DEFAULT_TIMEOUT, backend: Optional[str] = None) -> int:
    channels = get_all_channels()
    channel = next((ch for ch in channels if ch.can_handle(url)), None)
    if channel is None:
        # WebChannel always handles, so this shouldn't happen
        err = SkillError(NOT_FOUND, f"no channel handles URL: {url}")
        return _emit(envelope(channel=None, action="read", error=err))

    action = find_action(channel, "read")
    if action is None:
        # Fall back to web channel
        from reach_kit.channels.web import WebChannel
        channel = WebChannel()

    return _emit(run_action(channel, "read", {"target": url}, timeout=timeout, only_backend=backend))


def cmd_download(
    url: str,
    output: Optional[str] = None,
    quality: str = "best",
    timeout: float = 300.0,
    backend: Optional[str] = None,
) -> int:
    """Auto-pick channel from URL and run its download action."""
    channels = get_all_channels()
    channel = next((ch for ch in channels if ch.can_handle(url)), None)
    if channel is None:
        from reach_kit.channels.web import WebChannel
        channel = WebChannel()

    action = find_action(channel, "download")
    if action is None:
        err = SkillError(
            BAD_INPUT,
            f"channel '{channel.name}' does not support download",
            hint="Only social media channels support download (youtube, tiktok, twitter, instagram, reddit, facebook, linkedin).",
        )
        return _emit(envelope(channel=channel.name, action="download", error=err))

    params = {"target": url, "quality": quality}
    if output:
        params["output"] = output

    return _emit(run_action(channel, "download", params, timeout=timeout, only_backend=backend))


# ── setup (install skill) ────────────────────────────────────────────────────

def _do_setup() -> dict:
    """Copy SKILL.md into ~/.agents/skills/reach-kit/SKILL.md."""
    dest_dir = Path.home() / ".agents" / "skills" / "reach-kit"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / "SKILL.md"
    dest.write_text(SKILL_SRC.read_text(encoding="utf-8"), encoding="utf-8")
    return {
        "skill_path": str(dest),
        "message": f"Skill installed at {dest}. Claude will load it on next session start.",
        "channels": [ch.name for ch in get_all_channels()],
    }


# ── version ──────────────────────────────────────────────────────────────────

def cmd_version() -> int:
    return _emit({
        "schema_version": SCHEMA_VERSION,
        "ok": True,
        "action": "version",
        "result": {"version": __version__},
        "error": None,
    })


# ── argument parsing ─────────────────────────────────────────────────────────

HELP = """reach-kit — platform skill kit for AI agents (all output is JSON)

  reach-kit channels                     list channels, actions, params
  reach-kit <channel> <action> [args]    e.g. reach-kit github search playwright
  reach-kit read <url>                   read a URL with the matching channel
  reach-kit download <url>               download video/audio from any supported URL
  reach-kit setup                        install the Claude skill file
  reach-kit version                      print version

Flags:
  --timeout SECONDS    per-call timeout (default 30 for read, 300 for download)
  --backend NAME       force a specific backend
  --quality QUALITY    download quality: best | 1080p | 720p | 480p | 360p | audio
  --output DIR         download output directory (agent picks default if omitted)
"""


def main(argv: Optional[List[str]] = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    if not argv or argv[0] in ("-h", "--help", "help"):
        print(HELP)
        return 0

    # Global flags
    timeout: Optional[float] = None
    backend: Optional[str] = None
    quality: str = "best"
    output: Optional[str] = None
    clean: List[str] = []
    i = 0
    while i < len(argv):
        if argv[i] == "--timeout" and i + 1 < len(argv):
            try:
                timeout = float(argv[i + 1])
            except ValueError:
                pass
            i += 2
        elif argv[i] == "--backend" and i + 1 < len(argv):
            backend = argv[i + 1]
            i += 2
        elif argv[i] == "--quality" and i + 1 < len(argv):
            quality = argv[i + 1]
            i += 2
        elif argv[i] == "--output" and i + 1 < len(argv):
            output = argv[i + 1]
            i += 2
        else:
            clean.append(argv[i])
            i += 1
    argv = clean

    cmd = argv[0]

    if cmd == "version":
        return cmd_version()

    if cmd == "channels":
        return cmd_channels()

    if cmd == "setup":
        return _mgmt("setup", _do_setup)

    if cmd == "read":
        if len(argv) < 2:
            err = SkillError(BAD_INPUT, "usage: reach-kit read <url>")
            return _emit(envelope(channel=None, action="read", error=err))
        return cmd_read(argv[1], timeout=timeout or DEFAULT_TIMEOUT, backend=backend)

    if cmd == "download":
        if len(argv) < 2:
            err = SkillError(BAD_INPUT, "usage: reach-kit download <url> [--quality QUALITY] [--output DIR]")
            return _emit(envelope(channel=None, action="download", error=err))
        return cmd_download(argv[1], output=output, quality=quality, timeout=timeout or 300.0, backend=backend)

    # reach-kit <channel> <action> [--param value ...]
    channels_map = {ch.name: ch for ch in get_all_channels()}
    channel = channels_map.get(cmd)
    if channel is None:
        err = SkillError(BAD_INPUT, f"unknown channel '{cmd}'; run `reach-kit channels` for valid options")
        return _emit(envelope(channel=cmd, action=None, error=err))

    if len(argv) < 2:
        err = SkillError(BAD_INPUT, f"usage: reach-kit {cmd} <action> [args]")
        return _emit(envelope(channel=cmd, action=None, error=err))

    action_name = argv[1]

    # Parse remaining args: positional values fill required params in order;
    # --key value fills by name.
    action = find_action(channel, action_name)
    if action is None:
        valid = ", ".join(a.name for a in channel.actions)
        err = SkillError(BAD_INPUT, f"unknown action '{action_name}' for '{cmd}'; valid: {valid}")
        return _emit(envelope(channel=cmd, action=action_name, error=err))

    rest = argv[2:]
    params: dict = {}
    required_positional = [p for p in action.params if p.required]
    pos_idx = 0
    j = 0
    while j < len(rest):
        if rest[j].startswith("--") and j + 1 < len(rest):
            key = rest[j][2:]
            params[key] = rest[j + 1]
            j += 2
        else:
            if pos_idx < len(required_positional):
                params[required_positional[pos_idx].name] = rest[j]
                pos_idx += 1
            j += 1

    return _emit(run_action(channel, action_name, params, timeout=timeout or DEFAULT_TIMEOUT, only_backend=backend))


def entry_point():
    sys.exit(main())
