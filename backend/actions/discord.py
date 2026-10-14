"""Discord webhook: the one external action. Only ever called from a human click ("Approve & post")."""
import os
import re

import httpx

HOOK_RE = re.compile(r"^https://(?:discord(?:app)?\.com)/api/webhooks/\d+/[\w-]+$")
MAX_LEN = 1900


def post_incident(message: str, webhook_url: str | None = None, transport=None) -> dict:
    url = (webhook_url or os.environ.get("DISCORD_WEBHOOK_URL", "")).strip()
    if not url:
        return dict(posted=False, reason="no webhook configured")
    if not HOOK_RE.match(url):
        return dict(posted=False, reason="webhook URL is not a Discord webhook")
    body = message if len(message) <= MAX_LEN else message[: MAX_LEN - 3] + "..."
    # allowed_mentions empty: nothing we post can ping @everyone
    with httpx.Client(transport=transport, timeout=10) as c:
        r = c.post(url, json={"content": body, "allowed_mentions": {"parse": []}})
    if r.status_code >= 300:
        return dict(posted=False, reason=f"discord returned {r.status_code}")
    return dict(posted=True, channel="#incidents")
