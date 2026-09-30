"""Message sources.

A source is any callable `fetch(since: datetime | None, limit: int) -> list[Message]`
returning messages newer than `since`, oldest first, in the shape produced by
`wacal.model.normalise_message`. Adding a new provider (e.g. a third-party
WhatsApp bridge) is a matter of writing one such function and registering it
in `SOURCES`.
"""
from __future__ import annotations

from typing import Callable
from datetime import datetime

from . import export, inbox, whatsmeow

Fetcher = Callable[[datetime | None, int], list[dict]]

SOURCES: dict[str, Fetcher] = {
    "export": export.fetch,
    "inbox": inbox.fetch,
    "whatsmeow": whatsmeow.fetch,
}
