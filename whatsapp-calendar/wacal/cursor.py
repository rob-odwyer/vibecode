"""Cursor: remembers how far into the chat the routine has processed.

The cursor is advanced explicitly (scripts/ack.py) *after* the agent has
extracted events and they were written to the calendar, so a crash mid-run
simply re-reads the same messages next time; the upsert is idempotent so
that is safe.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from .config import state_path

CURSOR_FILE = "cursor.json"


def load() -> dict[str, Any]:
    p = state_path(CURSOR_FILE)
    if not p.exists():
        return {"last_seen_ts": None, "last_seen_id": None, "updated_at": None}
    return json.loads(p.read_text())


def save(last_seen_ts: str, last_seen_id: str | None) -> dict[str, Any]:
    # Validate the timestamp so a typo can't silently break future fetches.
    datetime.fromisoformat(last_seen_ts)
    doc = {
        "last_seen_ts": last_seen_ts,
        "last_seen_id": last_seen_id,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    state_path(CURSOR_FILE).write_text(json.dumps(doc, indent=2) + "\n")
    return doc
