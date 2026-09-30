#!/usr/bin/env python3
"""Advance the cursor after a batch has been fully processed.

    python scripts/ack.py --through 2026-09-30T18:42:00+01:00 --id exp_ab12cd34
    python scripts/ack.py --from-messages messages.json   # uses the newest message
    python scripts/ack.py --show
"""
from __future__ import annotations

import argparse
import json
import sys

import _bootstrap  # noqa: F401
from wacal import cursor


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--through", help="ISO timestamp of the last processed message")
    g.add_argument("--from-messages", help="path to fetch_messages.py output (or - for stdin)")
    g.add_argument("--show", action="store_true")
    ap.add_argument("--id", help="id of the last processed message (with --through)")
    args = ap.parse_args()

    if args.show:
        print(json.dumps(cursor.load(), indent=2))
        return 0

    if args.from_messages:
        fh = sys.stdin if args.from_messages == "-" else open(args.from_messages)
        with fh:
            doc = json.load(fh)
        msgs = doc["messages"] if isinstance(doc, dict) else doc
        if not msgs:
            print(json.dumps({"action": "noop", "reason": "no messages"}))
            return 0
        newest = max(msgs, key=lambda m: m["timestamp"])
        saved = cursor.save(newest["timestamp"], newest["id"])
    else:
        saved = cursor.save(args.through, args.id)
    print(json.dumps({"action": "advanced", **saved}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
