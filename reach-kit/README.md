# Reach Kit

A reverse-engineered implementation of the [Agent Reach](https://github.com/Panniantong/Agent-Reach) skill architecture — documented, minimal, and ready to extend.

## What this is

Agent Reach is a Claude skill that lets AI agents read login-walled and Chinese platforms via a shared browser session. This repo reverse-engineers its core architecture and packages the patterns as a clean, documented Python package you can build on.

## Architecture

```
SKILL.md (injected into Claude at session start)
    ↓
Claude recognizes trigger → runs: reach-kit <channel> <action> [args]
    ↓
cli.py → parses args, finds channel
    ↓
dispatch.py → run_action()
    │
    ├─ tries backends in order:
    │    backend 1 → success → return items
    │    backend 1 → transient error → try backend 2
    │    backend 2 → final error → stop
    │
    └─ returns one JSON envelope:
         {schema_version, ok, channel, action, backend, items[], meta, error}
```

### Key design decisions (from the original)

**Everything outputs one JSON object.** Agents never parse prose. The shape never changes without bumping `schema_version`.

**Backends are ordered lists, not singletons.** Each action declares `backends = [("label", "method"), ...]`. On a transient error (UPSTREAM_BROKEN, TIMEOUT) the dispatcher falls through to the next. On a final error (BAD_INPUT, NEED_LOGIN, NOT_FOUND) it stops immediately.

**Error codes are the API.** Agents branch on `error.code`, never on message text. The `hint` field tells the agent exactly what to do next.

**Items are normalized.** Every successful result returns `items[]` with `{title, url, author, published_at, text, raw}`. The `raw` field keeps the upstream data untouched.

**The skill file is the agent interface.** `SKILL.md` has YAML frontmatter that tells Claude when to invoke the skill, and Markdown body that tells it how to behave. Claude reads it at session start and follows its rules for the whole session.

## File structure

```
reach-kit/
├── pyproject.toml
├── install.md                    ← agent-readable install guide
├── reach_kit/
│   ├── __init__.py               ← version
│   ├── cli.py                    ← entry point (reach-kit command)
│   ├── channels/
│   │   ├── __init__.py           ← channel registry (add yours here)
│   │   ├── base.py               ← Channel, Action, Param base classes
│   │   ├── web.py                ← web search/read (Jina + Exa)
│   │   └── github.py             ← GitHub search/read (gh CLI + API)
│   ├── runtime/
│   │   ├── result.py             ← error codes, envelope, make_item
│   │   └── dispatch.py           ← run_action() — the core dispatcher
│   └── skill/
│       └── SKILL.md              ← Claude skill instructions
```

## Install

```bash
uv tool install /path/to/reach-kit
reach-kit setup    # copies SKILL.md to ~/.agents/skills/reach-kit/
```

## Usage

```bash
reach-kit channels
reach-kit github search "playwright browser automation"
reach-kit github read microsoft/playwright
reach-kit github read https://github.com/microsoft/playwright/issues/1234
reach-kit web search "agent reach claude skill"
reach-kit web read https://example.com
reach-kit read https://github.com/owner/repo    # auto-picks github channel
```

## Adding a channel

```python
# reach_kit/channels/reddit.py
from reach_kit.channels.base import Action, Channel, Param
from reach_kit.runtime.result import make_item, SkillError, NOT_FOUND

class RedditChannel(Channel):
    name = "reddit"
    description = "Reddit posts and comments"
    level = "optional"
    domains = ("reddit.com",)

    actions = (
        Action(
            "read",
            "Read a Reddit post with comments",
            (Param("target", "post URL"),),
            backends=(("json-api", "_json_read"),),
        ),
    )

    def can_handle(self, url: str) -> bool:
        return "reddit.com" in url

    def _json_read(self, *, target: str, timeout: float) -> list:
        # Reddit serves JSON at <post_url>.json
        import urllib.request, json
        url = target.rstrip("/") + ".json"
        req = urllib.request.Request(url, headers={"User-Agent": "reach-kit"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read())
        post = data[0]["data"]["children"][0]["data"]
        return [make_item(
            title=post.get("title"),
            url=f"https://reddit.com{post.get('permalink')}",
            author=post.get("author"),
            text=post.get("selftext") or post.get("url"),
            raw={"score": post.get("score"), "num_comments": post.get("num_comments")},
        )]
```

Then register it in `reach_kit/channels/__init__.py`:
```python
from reach_kit.channels.reddit import RedditChannel

def get_all_channels():
    return [GitHubChannel(), RedditChannel(), WebChannel()]
```

## Error codes

| Code | Meaning | Agent should |
|---|---|---|
| `NEED_SETUP` | Missing tool/dependency | Tell user to install it |
| `NEED_LOGIN` | Auth required | Run login command; never ask for password |
| `UPSTREAM_BROKEN` | Platform/network error | Report which platform, not which tool |
| `TIMEOUT` | Backend didn't respond | Don't retry in a loop |
| `RATE_LIMITED` | Platform rate-limited | Wait `retry_after_seconds` |
| `PLATFORM_BLOCKED` | Captcha / risk verification | Let user resolve on official site |
| `NOT_FOUND` | Content doesn't exist | Check the URL |
| `BAD_INPUT` | Invalid arguments | Run `reach-kit channels` |

## License

MIT
