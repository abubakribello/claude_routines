"""Channel registry — add new channels here."""

from reach_kit.channels.facebook import FacebookChannel
from reach_kit.channels.github import GitHubChannel
from reach_kit.channels.instagram import InstagramChannel
from reach_kit.channels.linkedin import LinkedInChannel
from reach_kit.channels.reddit import RedditChannel
from reach_kit.channels.tiktok import TikTokChannel
from reach_kit.channels.twitter import TwitterChannel
from reach_kit.channels.web import WebChannel
from reach_kit.channels.youtube import YouTubeChannel


def get_all_channels():
    """Return all registered channels in priority order.

    Channels are tried in order for `reach-kit read <url>`:
    the first one whose can_handle() returns True wins.
    WebChannel is last because it handles everything.
    """
    return [
        GitHubChannel(),
        YouTubeChannel(),
        RedditChannel(),
        TwitterChannel(),
        InstagramChannel(),
        TikTokChannel(),
        LinkedInChannel(),
        FacebookChannel(),
        WebChannel(),
    ]
