#!/usr/bin/env python3
"""Mirror the routine's state files to/from a Google Drive folder.

    python scripts/state_sync.py status
    python scripts/state_sync.py push            # after linking locally: upload the session
    python scripts/state_sync.py pull [--force]  # download (takes the lease)
    python scripts/state_sync.py unlock          # clear a stale lease by hand

With WACAL_STATE_SYNC=drive the whatsmeow source does pull/push around every
bridge run and ack.py pushes the cursor, so you rarely need this directly.
See wacal/statesync.py for the why.
"""
from __future__ import annotations

import argparse
import json
import sys

import _bootstrap  # noqa: F401
from wacal import statesync


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["status", "pull", "push", "unlock"])
    ap.add_argument("--force", action="store_true", help="pull even if another run holds the lease")
    ap.add_argument("--no-lock", action="store_true", help="pull without taking the lease (read-only peek)")
    ap.add_argument("--keep-lock", action="store_true", help="push without releasing the lease")
    args = ap.parse_args()

    try:
        if args.command == "status":
            out = statesync.status()
        elif args.command == "pull":
            out = statesync.pull(force=args.force, lock=not args.no_lock)
        elif args.command == "push":
            out = statesync.push(release=not args.keep_lock)
        else:
            out = statesync.unlock()
    except statesync.Locked as e:
        print(json.dumps({"action": "locked", "error": str(e)}))
        return 3
    except statesync.StateSyncError as e:
        print(json.dumps({"action": "error", "error": str(e)}))
        return 2
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
