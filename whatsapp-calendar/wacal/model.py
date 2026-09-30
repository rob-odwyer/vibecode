"""Shared data shapes.

Two JSON documents flow between the scripts and the agent:

* Message  – one normalised WhatsApp message (output of fetch_messages).
* Event    – one calendar event the agent extracted (input to calendar_upsert).

Both are plain dicts so they serialise trivially; the helpers below validate
and fill defaults.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, date
from typing import Any

MESSAGE_FIELDS = ("id", "chat_id", "sender", "timestamp", "text")


def normalise_message(
    *,
    id: str,
    chat_id: str,
    sender: str,
    timestamp: datetime,
    text: str,
    reply_to: str | None = None,
    media_type: str | None = None,
) -> dict[str, Any]:
    if timestamp.tzinfo is None:
        raise ValueError("message timestamps must be timezone-aware")
    return {
        "id": id,
        "chat_id": chat_id,
        "sender": sender,
        "timestamp": timestamp.isoformat(),
        "text": text,
        "reply_to": reply_to,
        "media_type": media_type,
    }


class EventValidationError(ValueError):
    pass


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _is_datetime(value: str) -> bool:
    try:
        datetime.fromisoformat(value)
        return "T" in value
    except ValueError:
        return False


def validate_event(ev: dict[str, Any]) -> dict[str, Any]:
    """Check an agent-produced event and return a cleaned copy.

    Required: title, start, source_message_ids (non-empty list).
    start/end are either YYYY-MM-DD (all-day) or ISO-8601 datetimes with an
    offset. If end is missing for a timed event we default to +1h; for an
    all-day event the end defaults to the same day.
    """
    if not isinstance(ev, dict):
        raise EventValidationError("event must be an object")
    title = (ev.get("title") or "").strip()
    if not title:
        raise EventValidationError("event.title is required")
    start = ev.get("start")
    if not isinstance(start, str) or not start:
        raise EventValidationError(f"{title!r}: event.start is required")
    ids = ev.get("source_message_ids")
    if not isinstance(ids, list) or not ids or not all(isinstance(i, str) for i in ids):
        raise EventValidationError(f"{title!r}: source_message_ids must be a non-empty list of strings")

    all_day = bool(_DATE_RE.match(start))
    if not all_day and not _is_datetime(start):
        raise EventValidationError(f"{title!r}: start must be YYYY-MM-DD or an ISO datetime, got {start!r}")
    if not all_day and datetime.fromisoformat(start).tzinfo is None:
        raise EventValidationError(f"{title!r}: timed start must include a UTC offset, got {start!r}")

    end = ev.get("end")
    if end is not None:
        if all_day and not _DATE_RE.match(end):
            raise EventValidationError(f"{title!r}: all-day event end must be YYYY-MM-DD")
        if not all_day and (not _is_datetime(end) or datetime.fromisoformat(end).tzinfo is None):
            raise EventValidationError(f"{title!r}: timed end must be an ISO datetime with offset")

    confidence = ev.get("confidence", 1.0)
    try:
        confidence = float(confidence)
    except (TypeError, ValueError):
        raise EventValidationError(f"{title!r}: confidence must be a number") from None

    cleaned = {
        "title": title,
        "start": start,
        "end": end,
        "all_day": all_day,
        "location": (ev.get("location") or None),
        "description": (ev.get("description") or ""),
        "source_message_ids": sorted(set(ids)),
        "chat_id": ev.get("chat_id") or "",
        "confidence": confidence,
        # Optional stable key supplied by the agent (e.g. when it *updates*
        # an event it created earlier from different messages).
        "source_key": ev.get("source_key") or None,
    }
    if cleaned["source_key"] is None:
        cleaned["source_key"] = event_source_key(cleaned)
    return cleaned


def event_source_key(ev: dict[str, Any]) -> str:
    """Stable idempotency key for an extracted event.

    Based on the chat and the *earliest* source message plus a normalised
    title. Re-running the routine over the same messages therefore updates the
    existing calendar entry instead of creating a duplicate, while a genuinely
    different event mentioned in the same message still gets its own key.
    """
    first_msg = sorted(ev["source_message_ids"])[0]
    norm_title = re.sub(r"[^a-z0-9]+", " ", ev["title"].lower()).strip()
    raw = f"{ev.get('chat_id','')}|{first_msg}|{norm_title}"
    return "wa_" + hashlib.sha1(raw.encode()).hexdigest()[:20]


def today() -> date:
    return date.today()
