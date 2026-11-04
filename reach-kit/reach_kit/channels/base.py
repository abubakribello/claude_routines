"""Channel base class and data structures.

A Channel represents one platform (GitHub, YouTube, Reddit, ...).
It declares:
  - name, description, level
  - actions: what the channel can do, each with an ordered list of backends
  - can_handle(url): does this URL belong here?

The dispatcher tries each backend method in order and falls back on
transient errors. Agents see one JSON envelope regardless of which
backend succeeded.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple


@dataclass(frozen=True)
class Param:
    """One argument of a channel action."""
    name:     str
    help:     str
    required: bool = True
    type:     type = str
    default:  object = None


@dataclass(frozen=True)
class Action:
    """One action a channel exposes (e.g. `reach-kit github search`).

    `backends` is an ordered list of (backend_label, channel_method_name).
    The dispatcher calls them in order; on a transient error it tries the next.

    `public_web` lists URL scopes that can be queried through the web channel
    before the platform-specific tools are tried (for channels not yet set up).
    """
    name:       str
    help:       str
    params:     Tuple[Param, ...]
    backends:   Tuple[Tuple[str, str], ...]
    live_test:  Optional[Dict[str, object]] = None
    timeout:    Optional[float] = None
    public_web: Tuple[str, ...] = field(default_factory=tuple)


class Channel(ABC):
    """Base class for all channels."""

    name:        str = ""
    description: str = ""
    level:       str = ""    # "default" | "optional" | "experimental"
    actions:     Tuple[Action, ...] = ()

    # Login / session
    login_url:  str = ""
    domains:    Tuple[str, ...] = ()

    # Tools installed by `reach-kit add <channel>`
    tools:   Tuple[str, ...] = ()
    prereqs: Tuple[str, ...] = ()

    @abstractmethod
    def can_handle(self, url: str) -> bool:
        """Return True if this channel handles the given URL."""
        ...

    def setup_problems(self) -> list:
        """Return a list of strings describing what blocks this channel."""
        return []
