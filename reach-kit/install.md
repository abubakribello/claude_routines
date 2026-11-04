# Install Reach Kit

For the AI doing the work. Run every command yourself.

## Install

```bash
uv tool install https://github.com/abubakribello/claude_routines/archive/refs/heads/main.zip#subdirectory=reach-kit
reach-kit setup
```

Or from a local clone:

```bash
uv tool install /path/to/reach-kit
reach-kit setup
```

`setup` copies the skill file to `~/.agents/skills/reach-kit/SKILL.md` so Claude loads it on session start.

## Verify

```bash
reach-kit version
reach-kit channels
reach-kit github read microsoft/playwright
```

## Usage

```bash
reach-kit github search "async python"           # search GitHub repos
reach-kit github read owner/repo                 # read repo + README
reach-kit github read https://github.com/owner/repo/issues/42
reach-kit web search "playwright browser test"   # web search via Exa
reach-kit web read https://example.com           # read a page via Jina/Exa
reach-kit read https://github.com/owner/repo     # auto-pick channel
```

All commands output one JSON object: `{ok, channel, action, backend, items[], meta, error}`.

## Add a new channel

1. Create `reach_kit/channels/myplatform.py` — subclass `Channel`, implement `can_handle` and backend methods.
2. Register it in `reach_kit/channels/__init__.py`.
3. The dispatcher picks it up automatically.

See `reach_kit/channels/github.py` for a complete example.
