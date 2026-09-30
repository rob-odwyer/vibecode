#!/usr/bin/env python3
"""List existing calendar events in a window, so the agent can spot events
that were already added by hand (a different key) before creating a twin.

    python scripts/calendar_search.py --from 2026-10-01 --to 2026-10-31
    python scripts/calendar_search.py --days 60 --query dentist
    python scripts/calendar_search.py --key wa_1234abcd          # exact wacal key
    python scripts/calendar_search.py --delete-key wa_1234abcd   # remove one we created
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import _bootstrap  # noqa: F401
from wacal import gcal
from wacal.config import cfg


def _slim(item: dict) -> dict:
    priv = (item.get("extendedProperties") or {}).get("private") or {}
    return {
        "id": item.get("id"),
        "title": item.get("summary"),
        "start": (item.get("start") or {}).get("dateTime") or (item.get("start") or {}).get("date"),
        "end": (item.get("end") or {}).get("dateTime") or (item.get("end") or {}).get("date"),
        "location": item.get("location"),
        "status": item.get("status"),
        "wacal_key": priv.get(gcal.KEY_PROP),
        "html_link": item.get("htmlLink"),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--from", dest="from_", help="YYYY-MM-DD (default today)")
    ap.add_argument("--to", help="YYYY-MM-DD (default from + --days)")
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--query", help="free-text filter (Google 'q' param)")
    ap.add_argument("--key", help="look up one event by wacal source_key")
    ap.add_argument("--delete-key", help="delete the event with this wacal source_key")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if args.delete_key:
        print(json.dumps(gcal.delete_by_key(args.delete_key, dry_run=args.dry_run)))
        return 0
    if args.key:
        item = gcal.find_by_key(args.key)
        print(json.dumps(_slim(item) if item else None))
        return 0

    tz = ZoneInfo(cfg("TIMEZONE", "UTC"))
    start = datetime.fromisoformat(args.from_).replace(tzinfo=tz) if args.from_ else datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)
    end = datetime.fromisoformat(args.to).replace(tzinfo=tz) + timedelta(days=1) if args.to else start + timedelta(days=args.days)
    items = gcal.list_window(start, end, query=args.query)
    json.dump({"from": start.isoformat(), "to": end.isoformat(), "count": len(items),
               "events": [_slim(i) for i in items]}, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
