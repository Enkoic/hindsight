"""POST a summary to a Slack/Discord-style incoming webhook.

Both platforms have different limits — handle them by chunking. Any URL whose
host contains 'discord' is treated as Discord (2000 char hard limit per
message); everything else is treated as Slack-compatible (~4000 chars works
fine, but Slack supports `text` blocks beyond that via mrkdwn).
"""

from __future__ import annotations

from urllib.parse import urlparse

import httpx

DISCORD_LIMIT = 1900   # leave headroom under the 2000 hard limit
SLACK_LIMIT = 3500     # plenty under Slack's per-block soft limit


def _is_discord(url: str) -> bool:
    return "discord" in (urlparse(url).hostname or "").lower()


def _chunks(text: str, size: int) -> list[str]:
    if len(text) <= size:
        return [text]
    out: list[str] = []
    while text:
        if len(text) <= size:
            out.append(text)
            break
        # Break at the last newline before `size` to avoid mid-line cuts.
        cut = text.rfind("\n", 0, size)
        if cut < size // 2:
            cut = size
        out.append(text[:cut])
        text = text[cut:].lstrip("\n")
    return out


def push_to_webhook(url: str, label: str, content: str) -> str:
    """POST one or more messages and return the URL we posted to."""
    discord = _is_discord(url)
    limit = DISCORD_LIMIT if discord else SLACK_LIMIT
    header = f"*Hindsight — {label}*\n\n" if not discord else f"**Hindsight — {label}**\n\n"
    body = _chunks(header + content, limit)

    with httpx.Client(timeout=30.0) as client:
        for i, msg in enumerate(body):
            if discord:
                payload = {"content": msg, "username": "hindsight"}
            else:
                payload = {"text": msg}
            r = client.post(url, json=payload)
            r.raise_for_status()
            if i + 1 < len(body):
                # Slack/Discord both rate-limit; a tiny pause is enough for normal use.
                pass
    return url
