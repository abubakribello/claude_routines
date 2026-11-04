"""Channel registry — add new channels here."""

from reach_kit.channels.github import GitHubChannel
from reach_kit.channels.web import WebChannel


def get_all_channels():
    """Return all registered channels in priority order.

    Channels are tried in order for `reach-kit read <url>`:
    the first one whose can_handle() returns True wins.
    WebChannel is last because it handles everything.
    """
    return [
        GitHubChannel(),
        WebChannel(),
    ]
