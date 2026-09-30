"""Source: WhatsApp "Export chat" text files.

Zero-API path. In WhatsApp: chat > ⋮ > More > Export chat > Without media.
Drop the resulting .txt into the directory named by WACAL_EXPORT_DIR (default
./inbox-exports). Every file in that directory is parsed and merged; messages
are deduplicated by (timestamp, sender, text), so re-exporting the same chat
with more history is fine.

WhatsApp export formats vary by platform and locale. The parser handles the
common shapes:

    12/03/2026, 14:05 - Alice: message text
    [12/03/2026, 14:05:33] Alice: message text
    3/12/26, 2:05 PM - Alice: message text

Continuation lines (no leading timestamp) are appended to the previous
message. Set WACAL_EXPORT_DATE_ORDER=MDY for US-style exports (default DMY).
Set WACAL_EXPORT_CHAT_ID to label the chat (defaults to the file stem).
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from ..config import cfg, PROJECT_ROOT
from ..model import normalise_message

_LINE_RE = re.compile(
    r"""^‎?\[?                       # optional LRM + optional opening bracket
        (?P<date>\d{1,4}[./-]\d{1,2}[./-]\d{1,4})
        ,?\s+
        (?P<time>\d{1,2}:\d{2}(?::\d{2})?\s*(?:[AaPp]\.?[Mm]\.?)?)
        \]?\s*(?:-\s*)?
        (?P<sender>[^:]+?):\s
        (?P<text>.*)$""",
    re.VERBOSE,
)


def _parse_date(date_s: str, order: str) -> tuple[int, int, int]:
    raw_parts = re.split(r"[./-]", date_s)
    parts = [int(p) for p in raw_parts]
    if len(raw_parts[0]) == 4:  # ISO-ish YYYY-MM-DD
        y, m, d = parts
    elif order == "MDY":
        m, d, y = parts
    else:
        d, m, y = parts
    if y < 100:
        y += 2000
    return y, m, d


def _parse_time(time_s: str) -> tuple[int, int, int]:
    t = time_s.strip().upper().replace(".", "")
    ampm = None
    if t.endswith("AM") or t.endswith("PM"):
        ampm = t[-2:]
        t = t[:-2].strip()
    bits = [int(x) for x in t.split(":")]
    h, mi = bits[0], bits[1]
    s = bits[2] if len(bits) > 2 else 0
    if ampm == "PM" and h != 12:
        h += 12
    if ampm == "AM" and h == 12:
        h = 0
    return h, mi, s


def parse_export(text: str, *, chat_id: str, tz: ZoneInfo, date_order: str = "DMY") -> list[dict]:
    messages: list[dict] = []
    current: dict | None = None
    for raw in text.splitlines():
        line = raw.rstrip("\n")
        m = _LINE_RE.match(line)
        if m:
            y, mo, d = _parse_date(m.group("date"), date_order)
            h, mi, s = _parse_time(m.group("time"))
            ts = datetime(y, mo, d, h, mi, s, tzinfo=tz)
            sender = m.group("sender").strip().lstrip("‎")
            body = m.group("text")
            current = {"ts": ts, "sender": sender, "text": body}
            messages.append(current)
        elif current is not None and line.strip():
            current["text"] += "\n" + line
        # else: header/system lines before the first message; ignore.

    out = []
    for msg in messages:
        digest = hashlib.sha1(
            f"{msg['ts'].isoformat()}|{msg['sender']}|{msg['text']}".encode()
        ).hexdigest()[:16]
        out.append(
            normalise_message(
                id=f"exp_{digest}",
                chat_id=chat_id,
                sender=msg["sender"],
                timestamp=msg["ts"],
                text=msg["text"],
            )
        )
    return out


def fetch(since: datetime | None, limit: int) -> list[dict]:
    export_dir = Path(cfg("WACAL_EXPORT_DIR", str(PROJECT_ROOT / "inbox-exports")))
    tz = ZoneInfo(cfg("TIMEZONE", "UTC"))
    date_order = (cfg("WACAL_EXPORT_DATE_ORDER", "DMY") or "DMY").upper()
    forced_chat_id = cfg("WACAL_EXPORT_CHAT_ID")

    seen: set[str] = set()
    merged: list[dict] = []
    if not export_dir.exists():
        return []
    for path in sorted(export_dir.glob("*.txt")):
        chat_id = forced_chat_id or path.stem
        for msg in parse_export(path.read_text(encoding="utf-8", errors="replace"),
                                chat_id=chat_id, tz=tz, date_order=date_order):
            if msg["id"] in seen:
                continue
            seen.add(msg["id"])
            merged.append(msg)

    merged.sort(key=lambda m: (m["timestamp"], m["id"]))
    if since is not None:
        merged = [m for m in merged if datetime.fromisoformat(m["timestamp"]) > since]
    return merged[:limit]
