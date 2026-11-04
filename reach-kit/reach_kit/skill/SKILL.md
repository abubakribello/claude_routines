---
name: reach-kit
description: >
  Read-only access to platform content: GitHub, YouTube, Reddit, Twitter/X, Instagram,
  TikTok, LinkedIn, Facebook, and the open web. Use when the user mentions a link to any
  of these platforms, wants to search them, or read a URL and your built-in tools are
  unavailable or insufficient. Does not post, comment, or write anything.
metadata:
  homepage: https://github.com/abubakribello/claude_routines/tree/main/reach-kit
  version: "0.1.0"
---

# Reach Kit

One command for every platform: `reach-kit`. Read-only. Always outputs one JSON object.

Before acting, say "using reach-kit (channel X)". These rules apply for the whole session.

## Choosing a route

- For public content, use your own search/read tools first. When they are enough, answer directly.
- Use Reach Kit when your tools are unavailable, fail, or the user needs platform-specific data.
- Unsure of available actions? Run `reach-kit channels`.

```bash
reach-kit channels                        # list channels, actions, params
reach-kit <channel> <action> [args]       # e.g. reach-kit github search "playwright"
reach-kit read <url>                      # auto-pick channel from URL
```

## Results

- `ok: true` → content in `items`; each has `title / url / author / published_at / text / raw`
- `ok: false` → branch on `error.code` and follow `error.hint`:

| error.code | What to do |
|---|---|
| `NEED_SETUP` | Missing tool/dependency. Tell the user to run `reach-kit setup`. |
| `NEED_LOGIN` | Channel needs auth. Run `reach-kit login <channel>`; the user logs in. Never ask for passwords. |
| `UPSTREAM_BROKEN` | Platform temporarily unavailable. Tell the user which platform, not which tool. |
| `TIMEOUT` | Backend timed out. Don't retry in a loop. |
| `RATE_LIMITED` | Platform rate-limited. Wait `retry_after_seconds`. Don't switch backends. |
| `NOT_FOUND` | Content doesn't exist. Check the URL or ID. |
| `BAD_INPUT` | Invalid arguments. Run `reach-kit channels` for valid usage. |

## Channels

| Channel | Level | Actions | Needs |
|---|---|---|---|
| github | default | search, read | nothing (gh CLI optional) |
| web | default | search, read | nothing |
| youtube | default | read, search, subtitles | yt-dlp (bundled) |
| reddit | optional | search, read, subreddit | nothing |
| twitter | experimental | read, search | TWITTER_BEARER_TOKEN for search |
| instagram | experimental | read | nothing (oEmbed, public posts only) |
| tiktok | experimental | read | yt-dlp (bundled) |
| linkedin | experimental | read, search | LINKEDIN_ACCESS_TOKEN for read |
| facebook | experimental | read, search | FB_APP_TOKEN for read |

`default` channels work out of the box. `optional` channels need no auth but may have rate limits.
`experimental` channels have partial coverage — expect some content to need login.

## Managing Reach Kit

| User says | You run |
|---|---|
| Install / set up | `reach-kit setup` |
| Check status | `reach-kit channels` |
| Read a URL | `reach-kit read <url>` |
| Search GitHub | `reach-kit github search "<query>"` |
| Read a repo or issue | `reach-kit github read owner/repo` |
| Search the web | `reach-kit web search "<query>"` |
| Read a web page | `reach-kit web read <url>` |
| Get YouTube video info | `reach-kit youtube read <url>` |
| Search YouTube | `reach-kit youtube search "<query>"` |
| Get video subtitles | `reach-kit youtube subtitles <url>` |
| Search Reddit | `reach-kit reddit search "<query>"` |
| Read Reddit post | `reach-kit reddit read <url>` |
| Browse subreddit | `reach-kit reddit subreddit <name>` |
| Read a tweet | `reach-kit twitter read <url>` |
| Read Instagram post | `reach-kit instagram read <url>` |
| Read TikTok video | `reach-kit tiktok read <url>` |

## Red lines

- Read only. Never post, comment, like, or message.
- Never log in for the user. Never ask for or print passwords or cookies.
- Never retry a failed backend in a loop; tell the user what failed and why.
