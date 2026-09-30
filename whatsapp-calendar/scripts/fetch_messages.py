#!/usr/bin/env python3
"""Fetch new WhatsApp messages as JSON.

    python scripts/fetch_messages.py                 # since the saved cursor
    python scripts/fetch_messages.py --since 2026-09-01T00:00:00+00:00
    python scripts/fetch_messages.py --source export --limit 500

Output (stdout): {"source": ..., "since": ..., "count": N, "messages": [...]}
Each message: {id, chat_id, sender, timestamp, text, reply_to, media_type}.
Messages are oldest-first. Nothing is written; run ack.py to move the cursor.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone

import _bootstrap  # noqa: F401
from wacal import cursor
from wacal.config import cfg
from wacal.sources import SOURCES


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", default=cfg("WACAL_SOURCE", "export"), choices=sorted(SOURCES))
    ap.add_argument("--since", help="ISO timestamp; overrides the saved cursor")
    ap.add_argument("--lookback-days", type=float, default=float(cfg("WACAL_DEFAULT_LOOKBACK_DAYS", "7")),
                    help="used when there is no cursor yet (default 7)")
    ap.add_argument("--limit", type=int, default=int(cfg("WACAL_FETCH_LIMIT", "300")))
    ap.add_argument("--pretty", action="store_true")
    args = ap.parse_args()

    if args.since:
        since = datetime.fromisoformat(args.since)
        if since.tzinfo is None:
            since = since.replace(tzinfo=timezone.utc)
    else:
        cur = cursor.load()
        if cur["last_seen_ts"]:
            since = datetime.fromisoformat(cur["last_seen_ts"])
        else:
            since = datetime.now(timezone.utc) - timedelta(days=args.lookback_days)

    messages = SOURCES[args.source](since, args.limit)
    out = {
        "source": args.source,
        "since": since.isoformat(),
        "count": len(messages),
        "truncated": len(messages) >= args.limit,
        "messages": messages,
    }
    json.dump(out, sys.stdout, indent=2 if args.pretty else None, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
