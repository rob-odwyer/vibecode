"""Source: our own inbox service fed by WhatsApp Business Cloud API webhooks.

Meta's Cloud API never lets you *pull* history; it *pushes* each incoming
message to a webhook. `scripts/inbox_server.py` is that webhook. It stores
messages in SQLite and exposes them over a tiny authenticated GET endpoint,
which this adapter calls.

Settings:
    WACAL_INBOX_URL     e.g. https://inbox.example.com
    WACAL_INBOX_TOKEN   bearer token shared with the inbox server
    WACAL_INBOX_CHAT_ID optional: only return messages for this chat
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from datetime import datetime

from ..config import cfg


def fetch(since: datetime | None, limit: int) -> list[dict]:
    base = cfg("WACAL_INBOX_URL", required=True).rstrip("/")
    token = cfg("WACAL_INBOX_TOKEN", required=True)
    params = {"limit": str(limit)}
    if since is not None:
        params["since"] = since.isoformat()
    chat_id = cfg("WACAL_INBOX_CHAT_ID")
    if chat_id:
        params["chat_id"] = chat_id
    url = f"{base}/messages?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.load(resp)
    return payload["messages"]
