# Reach Kit

A reverse-engineered implementation of the [Agent Reach](https://github.com/Panniantong/Agent-Reach) skill architecture — documented, minimal, and ready to extend.

Gives AI agents read-only access to 9 platforms: GitHub, YouTube, Reddit, Twitter/X, Instagram, TikTok, LinkedIn, Facebook, and the open web.

---

## Quick install

```bash
# Install the CLI
uv tool install /path/to/reach-kit
# or: pip install /path/to/reach-kit

# Copy SKILL.md so Claude picks it up at session start
reach-kit setup

# Verify everything
reach-kit channels
```

---

## Dependencies

### Python packages

None. reach-kit uses only the Python standard library (`urllib.request`, `json`, `subprocess`, `re`). It installs clean with no transitive deps.

### External tools

#### yt-dlp (YouTube and TikTok)

Required for the `youtube` and `tiktok` channels. Everything else works without it.

```bash
# Option A — uv (recommended)
uv tool install yt-dlp

# Option B — pip
pip install yt-dlp

# Option C — already have agent-reach?
# yt-dlp ships with it at:
# ~/.local/share/uv/tools/agent-reach/bin/yt-dlp
# reach-kit finds it automatically.
```

Verify: `yt-dlp --version`

#### gh CLI (GitHub, optional)

The `github` channel works without it (falls back to the REST API), but the gh CLI is faster and handles auth automatically.

```bash
# macOS
brew install gh && gh auth login

# Linux
# See https://cli.github.com/manual/installation
gh auth login
```

---

## API tokens (optional per channel)

Most channels work without any credentials. The table below shows what unlocks each channel's full capability.

| Channel | Without token | With token | Token env var |
|---|---|---|---|
| **github** | Public repos only (60 req/hr) | Private repos, higher rate limit | `GITHUB_TOKEN` |
| **youtube** | Full — yt-dlp needs no key | — | — |
| **reddit** | Full — public JSON API | — | — |
| **twitter** | Read public tweets (oEmbed + Nitter) | Search tweets | `TWITTER_BEARER_TOKEN` |
| **instagram** | Read public post captions (oEmbed) | — | — |
| **tiktok** | Read public video metadata | — | — |
| **linkedin** | Web fallback only | Read company pages via API | `LINKEDIN_ACCESS_TOKEN` |
| **facebook** | Web fallback only | Read public post text (oEmbed) | `FB_APP_TOKEN` |
| **web** | Full — Jina + Exa | — | `EXA_API_KEY` for Exa |

### How to get each token

#### `GITHUB_TOKEN`
Create a fine-grained personal access token at github.com → Settings → Developer settings → Personal access tokens. No special scopes needed for public repos; add `repo` scope for private ones.

#### `TWITTER_BEARER_TOKEN`
1. Apply for a developer account at developer.twitter.com
2. Create an app → Keys and tokens → Bearer Token

#### `LINKEDIN_ACCESS_TOKEN`
1. Create an app at linkedin.com/developers
2. Add the `r_organization_social` product
3. OAuth 2.0 auth code flow → exchange for access token

#### `FB_APP_TOKEN`
1. Create an app at developers.facebook.com
2. App Dashboard → Settings → Advanced → App Access Token
3. No special permissions needed for public oEmbed

#### `EXA_API_KEY`
Sign up at exa.ai. The web channel works without it (Jina handles reads); Exa adds semantic search.

### Setting tokens

```bash
# Session only
export TWITTER_BEARER_TOKEN=your_token_here

# Persistent (add to ~/.bashrc or ~/.zshrc)
echo 'export TWITTER_BEARER_TOKEN=your_token_here' >> ~/.zshrc

# Or use a .env file and source it before running Claude
```

---

## Usage

```bash
reach-kit channels                                      # list all channels and actions

# GitHub
reach-kit github search "playwright browser automation"
reach-kit github read microsoft/playwright
reach-kit github read https://github.com/owner/repo/issues/42

# YouTube
reach-kit youtube read https://www.youtube.com/watch?v=dQw4w9WgXcQ
reach-kit youtube search "how to use playwright"
reach-kit youtube subtitles https://www.youtube.com/watch?v=VIDEO_ID

# Reddit
reach-kit reddit search "playwright automation" --limit 5
reach-kit reddit read https://www.reddit.com/r/Python/comments/abc123
reach-kit reddit subreddit Python --limit 10

# Twitter / X
reach-kit twitter read https://twitter.com/user/status/123456789

# Instagram
reach-kit instagram read https://www.instagram.com/p/POST_ID/

# TikTok
reach-kit tiktok read https://www.tiktok.com/@user/video/123456789

# Web (fallback for any URL)
reach-kit web search "agent reach claude skill"
reach-kit web read https://example.com

# Auto-pick channel from URL
reach-kit read https://github.com/owner/repo
reach-kit read https://www.youtube.com/watch?v=abc123
reach-kit read https://reddit.com/r/Python/comments/abc123
```

## Downloading videos

Any public video URL can be downloaded with a single command. The channel is picked automatically.

```bash
# Download — auto-picks channel from URL
reach-kit download https://www.youtube.com/watch?v=dQw4w9WgXcQ
reach-kit download https://www.tiktok.com/@user/video/123456789
reach-kit download https://twitter.com/user/status/123456789
reach-kit download https://www.instagram.com/reel/ABC123/
reach-kit download https://www.reddit.com/r/videos/comments/abc123
reach-kit download https://www.facebook.com/page/videos/123
reach-kit download https://www.linkedin.com/posts/example_video_123

# Quality options: best (default) | 1080p | 720p | 480p | 360p | audio
reach-kit download https://youtube.com/watch?v=abc123 --quality 720p
reach-kit download https://youtube.com/watch?v=abc123 --quality audio   # extracts MP3

# Custom output directory
reach-kit download https://youtube.com/watch?v=abc123 --output ~/Desktop
reach-kit download https://youtube.com/watch?v=abc123 --output /tmp/videos

# Or per-channel (same flags)
reach-kit youtube download https://youtube.com/watch?v=abc123 --quality 1080p
reach-kit tiktok  download https://tiktok.com/@user/video/123
```

Output is always a JSON envelope. The local filepath and filesize are in `raw`:

```json
{
  "ok": true,
  "channel": "youtube",
  "action": "download",
  "backend": "yt-dlp",
  "items": [{
    "title": "Never Gonna Give You Up",
    "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    "author": "Rick Astley",
    "text": "Official music video...",
    "raw": {
      "filepath": "/root/reach-kit-downloads/Never Gonna Give You Up.mp4",
      "filesize_bytes": 24581234,
      "duration_seconds": 213,
      "quality": "best",
      "ext": "mp4",
      "output_dir": "/root/reach-kit-downloads"
    }
  }]
}
```

**Default output directory:** `~/reach-kit-downloads/` — created automatically if it doesn't exist.

**What works without auth:** any public video on YouTube, TikTok, Twitter, Reddit. Instagram reels sometimes work. Facebook and LinkedIn public videos vary.

**What doesn't work:** private videos, login-walled content, age-restricted videos without cookies. These return `NOT_FOUND` or `UPSTREAM_BROKEN`.

---

## For agents installing reach-kit

If you are an AI agent reading this to set up reach-kit, follow these steps in order:

**Step 1 — Install the CLI**
```bash
uv tool install /path/to/reach-kit
```
Or if cloning from GitHub:
```bash
git clone https://github.com/abubakribello/claude_routines
uv tool install claude_routines/reach-kit/
```

**Step 2 — Install the skill file**
```bash
reach-kit setup
```
This copies `SKILL.md` to `~/.agents/skills/reach-kit/SKILL.md`. Claude will load it at the next session start.

**Step 3 — Install yt-dlp** (needed for YouTube and TikTok)
```bash
uv tool install yt-dlp
```

**Step 4 — Verify**
```bash
reach-kit channels
reach-kit reddit subreddit Python --limit 3
```
If the second command returns `ok: true` with items, the core setup is working.

**Step 5 — Set tokens for gated channels** (only if the user needs them)

Check whether the user needs Twitter search, LinkedIn, or Facebook access. If so, ask them for the token and set it:
```bash
export TWITTER_BEARER_TOKEN=<token_from_user>
export LINKEDIN_ACCESS_TOKEN=<token_from_user>
export FB_APP_TOKEN=<token_from_user>
```

**What to expect without tokens:**
- YouTube, Reddit, Instagram, TikTok: fully functional
- Twitter: can read individual public tweets, cannot search
- LinkedIn, Facebook: fall back to web channel (Jina/Exa) automatically

---

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

### Key design decisions

**Everything outputs one JSON object.** Agents never parse prose. The shape never changes without bumping `schema_version`.

**Backends are ordered lists, not singletons.** Each action declares `backends = [("label", "method"), ...]`. On a transient error (`UPSTREAM_BROKEN`, `TIMEOUT`) the dispatcher falls through to the next. On a final error (`BAD_INPUT`, `NEED_LOGIN`, `NOT_FOUND`) it stops immediately.

**Error codes are the API.** Agents branch on `error.code`, never on message text. The `hint` field tells the agent exactly what to do next.

**Items are normalized.** Every successful result returns `items[]` with `{title, url, author, published_at, text, raw}`. The `raw` field keeps the upstream data untouched.

**The skill file is the agent interface.** `SKILL.md` has YAML frontmatter that tells Claude when to invoke the skill, and a Markdown body that tells it how to behave.

---

## File structure

```
reach-kit/
├── pyproject.toml
├── README.md
├── reach_kit/
│   ├── __init__.py               ← version
│   ├── cli.py                    ← entry point (reach-kit command)
│   ├── channels/
│   │   ├── __init__.py           ← channel registry (add yours here)
│   │   ├── base.py               ← Channel, Action, Param base classes
│   │   ├── web.py                ← web search/read (Jina + Exa)
│   │   ├── github.py             ← GitHub (gh CLI + REST API)
│   │   ├── youtube.py            ← YouTube (yt-dlp)
│   │   ├── reddit.py             ← Reddit (public JSON API)
│   │   ├── twitter.py            ← Twitter/X (oEmbed + Nitter + v2 API)
│   │   ├── instagram.py          ← Instagram (oEmbed)
│   │   ├── tiktok.py             ← TikTok (oEmbed + yt-dlp)
│   │   ├── linkedin.py           ← LinkedIn (Graph API)
│   │   └── facebook.py           ← Facebook (Graph oEmbed)
│   ├── runtime/
│   │   ├── result.py             ← error codes, envelope, make_item
│   │   └── dispatch.py           ← run_action() — the core dispatcher
│   └── skill/
│       └── SKILL.md              ← Claude skill instructions
```

---

## Error codes

| Code | Meaning | Agent should |
|---|---|---|
| `NEED_SETUP` | Missing tool/dependency | Tell user to install it; check `error.hint` |
| `NEED_LOGIN` | Auth required | Run login command; never ask for password |
| `UPSTREAM_BROKEN` | Platform/network error | Report which platform, not which tool |
| `TIMEOUT` | Backend didn't respond | Don't retry in a loop |
| `RATE_LIMITED` | Platform rate-limited | Wait `retry_after_seconds` |
| `PLATFORM_BLOCKED` | Captcha / risk verification | Let user resolve on official site |
| `NOT_FOUND` | Content doesn't exist | Check the URL |
| `BAD_INPUT` | Invalid arguments | Run `reach-kit channels` |

---

## Adding a channel

```python
# reach_kit/channels/myplatform.py
from reach_kit.channels.base import Action, Channel, Param
from reach_kit.runtime.result import make_item, SkillError, NOT_FOUND

class MyPlatformChannel(Channel):
    name = "myplatform"
    description = "One-line description"
    level = "optional"          # default | optional | experimental
    domains = ("myplatform.com",)

    actions = (
        Action(
            "read",
            "Read a page",
            (Param("target", "URL to read"),),
            backends=(("api", "_api_read"),),
        ),
    )

    def can_handle(self, url: str) -> bool:
        return "myplatform.com" in url

    def _api_read(self, *, target: str, timeout: float) -> list:
        # ... fetch and return items
        return [make_item(title="...", url=target, text="...")]
```

Then register in `reach_kit/channels/__init__.py` and reinstall with `uv tool install --force .`

---

## License

MIT
