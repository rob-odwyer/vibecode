#!/usr/bin/env python3
"""Create or update Google Calendar events from agent-extracted JSON.

    python scripts/calendar_upsert.py events.json
    cat events.json | python scripts/calendar_upsert.py -
    python scripts/calendar_upsert.py events.json --dry-run

Input: a JSON array of events, or {"events": [...]}. See events.schema.json.
Each event is validated, given a stable source_key, and upserted; re-running
with the same input is a no-op apart from PATCHing unchanged fields.

Events below --min-confidence (default 0.6) are reported but not written, so
the agent can mention them to the user instead.

Output: one JSON result per line, then a summary line to stderr.
Exit code 0 on success, 2 if any event failed validation or the API errored.
"""
from __future__ import annotations

import argparse
import json
import sys

import _bootstrap  # noqa: F401
from wacal import gcal
from wacal.config import cfg
from wacal.model import EventValidationError, validate_event


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path", help="events JSON file, or - for stdin")
    ap.add_argument("--dry-run", action="store_true", help="show what would change; touch nothing")
    ap.add_argument("--force", action="store_true", help="recreate events the user deleted in Calendar")
    ap.add_argument("--min-confidence", type=float, default=float(cfg("WACAL_MIN_CONFIDENCE", "0.6")))
    ap.add_argument("--timezone", default=cfg("TIMEZONE", "UTC"))
    args = ap.parse_args()

    fh = sys.stdin if args.path == "-" else open(args.path)
    with fh:
        doc = json.load(fh)
    raw_events = doc["events"] if isinstance(doc, dict) else doc

    failures = 0
    summary = {"created": 0, "updated": 0, "skipped": 0, "invalid": 0, "errors": 0}
    for raw in raw_events:
        try:
            ev = validate_event(raw)
        except EventValidationError as e:
            failures += 1
            summary["invalid"] += 1
            print(json.dumps({"action": "invalid", "error": str(e), "input": raw}))
            continue
        if ev["confidence"] < args.min_confidence:
            summary["skipped"] += 1
            print(json.dumps({"action": "skipped_low_confidence", "title": ev["title"],
                              "confidence": ev["confidence"], "key": ev["source_key"]}))
            continue
        try:
            res = gcal.upsert(ev, tz=args.timezone, dry_run=args.dry_run, force=args.force)
        except gcal.GCalError as e:
            failures += 1
            summary["errors"] += 1
            print(json.dumps({"action": "error", "title": ev["title"], "key": ev["source_key"], "error": str(e)}))
            continue
        if res["action"] in ("created", "would_create"):
            summary["created"] += 1
        elif res["action"] in ("updated", "would_update"):
            summary["updated"] += 1
        else:
            summary["skipped"] += 1
        print(json.dumps(res))

    print(json.dumps({"summary": summary, "dry_run": args.dry_run}), file=sys.stderr)
    return 2 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
