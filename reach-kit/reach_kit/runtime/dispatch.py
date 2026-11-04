"""Run a unified action: validate params, try backends in order, return envelope.

This is the core of the skill kit. For every `reach-kit <channel> <action>` call:
  1. Validate the params against the action's declared Param list.
  2. Try each (backend_label, method_name) in action.backends, in order.
  3. On transient errors (UPSTREAM_BROKEN, TIMEOUT) fall through to the next.
  4. On final errors (BAD_INPUT, NEED_LOGIN, NOT_FOUND, ...) stop immediately.
  5. Return one JSON envelope regardless of outcome.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from reach_kit.channels.base import Action, Channel
from reach_kit.runtime.result import (
    BAD_INPUT,
    FINAL_CODES,
    NEED_SETUP,
    UPSTREAM_BROKEN,
    TIMEOUT,
    SkillError,
    classify,
    envelope,
)

DEFAULT_TIMEOUT = 30.0


def find_action(channel: Channel, name: str) -> Optional[Action]:
    return next((a for a in channel.actions if a.name == name), None)


def _validate(action: Action, params: Dict[str, Any]) -> Dict[str, Any]:
    """Validate and coerce params; raise SkillError(BAD_INPUT) on failure."""
    if not isinstance(params, dict):
        raise SkillError(BAD_INPUT, "params must be a dict")

    clean: Dict[str, Any] = {}
    for p in action.params:
        value = params.get(p.name)
        if isinstance(value, str):
            value = value.strip()
        if value is None or value == "":
            if p.required:
                raise SkillError(BAD_INPUT, f"missing required argument: {p.name}")
            value = p.default
        elif p.type is not str:
            try:
                value = p.type(value)
            except (TypeError, ValueError):
                raise SkillError(BAD_INPUT, f"{p.name} must be {p.type.__name__}") from None
        if p.type is int and p.name in {"limit", "page"} and (not isinstance(value, int) or value < 1):
            raise SkillError(BAD_INPUT, f"{p.name} must be a positive integer")
        clean[p.name] = value

    unknown = set(params) - {p.name for p in action.params}
    if unknown:
        raise SkillError(BAD_INPUT, f"unknown argument(s): {', '.join(sorted(unknown))}")

    return clean


def _pick_error(errors: List[SkillError]) -> SkillError:
    """Return the most informative failure: a real error beats NEED_SETUP."""
    for err in errors:
        if err.code != NEED_SETUP:
            return err
    return errors[0]


def run_action(
    channel: Channel,
    action_name: str,
    params: Dict[str, Any],
    *,
    timeout: float = DEFAULT_TIMEOUT,
    only_backend: Optional[str] = None,
) -> dict:
    """Execute one unified action and return the envelope dict.

    Args:
        channel:      The channel instance to dispatch to.
        action_name:  The action to run (must be in channel.actions).
        params:       Dict of argument values.
        timeout:      Total seconds budget for this call.
        only_backend: If set, skip all other backends.
    """
    started = time.monotonic()
    elapsed = lambda: int((time.monotonic() - started) * 1000)  # noqa: E731

    # Validate action exists
    action = find_action(channel, action_name)
    if action is None:
        valid = ", ".join(a.name for a in channel.actions) or "none"
        err = SkillError(BAD_INPUT, f"unknown action '{action_name}' for '{channel.name}'; valid: {valid}")
        return envelope(channel=channel.name, action=action_name, elapsed_ms=elapsed(), error=err)

    # Validate params
    try:
        clean = _validate(action, params)
    except SkillError as err:
        return envelope(channel=channel.name, action=action_name, elapsed_ms=elapsed(), error=err)

    # Pick applicable backends
    backends = [(label, method) for label, method in action.backends
                if only_backend in (None, label)]
    if not backends:
        err = SkillError(BAD_INPUT, f"no backend named '{only_backend}'")
        return envelope(channel=channel.name, action=action_name, elapsed_ms=elapsed(), error=err)

    attempts: List[dict] = []
    errors:   List[SkillError] = []

    for label, method_name in backends:
        remaining = timeout - (time.monotonic() - started)
        if remaining <= 0:
            attempts.append({"backend": label, "result": TIMEOUT})
            errors.append(SkillError(TIMEOUT, "no time left for this backend"))
            break

        try:
            fn = getattr(channel, method_name)
            items = fn(timeout=remaining, **clean)
        except BaseException as exc:  # noqa: BLE001
            err = classify(exc)
            attempts.append({"backend": label, "result": err.code, "message": err.message})
            errors.append(err)
            if err.code in FINAL_CODES:
                break
            continue  # try next backend

        attempts.append({"backend": label, "result": "ok"})
        return envelope(
            channel=channel.name,
            action=action_name,
            backend=label,
            items=items,
            elapsed_ms=elapsed(),
            attempts=attempts,
        )

    # All backends failed
    err = _pick_error(errors) if errors else SkillError(BAD_INPUT, "no backends available")
    return envelope(channel=channel.name, action=action_name, elapsed_ms=elapsed(),
                    attempts=attempts, error=err)
