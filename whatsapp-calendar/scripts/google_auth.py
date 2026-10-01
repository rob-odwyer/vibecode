#!/usr/bin/env python3
"""One-time Google OAuth consent. Writes state/google_token.json.

Prerequisites (Google Cloud Console):
  1. Enable the Google Calendar API.
  2. Create an OAuth client of type "Desktop app"; put its id/secret in .env
     as GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET.
  3. While the app is in "Testing", add your Google account as a test user.

Re-run it if the scopes in wacal/gcal.py change (e.g. after enabling Drive
state sync); Google only grants a refresh token for the scopes consented to.

This works on a headless machine: it prints a URL, you open it anywhere,
approve, and paste back the URL your browser lands on (it will be a
http://localhost/... address that fails to load - that's expected; the code
is in its query string).

    python scripts/google_auth.py
    python scripts/google_auth.py --print-refresh-token   # to store it as a secret instead
"""
from __future__ import annotations

import argparse
import secrets
import sys
import urllib.parse

import _bootstrap  # noqa: F401
from wacal import gcal

REDIRECT_URI = "http://localhost:8765/"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--print-refresh-token", action="store_true",
                    help="also print the refresh token so you can store it as GOOGLE_REFRESH_TOKEN")
    args = ap.parse_args()

    state = secrets.token_urlsafe(16)
    print("\n1. Open this URL and approve access:\n")
    print("   " + gcal.build_consent_url(REDIRECT_URI, state) + "\n")
    print("2. Your browser will be redirected to a localhost URL that does not load.")
    pasted = input("   Paste that full URL (or just the code) here: ").strip()

    if pasted.startswith("http"):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(pasted).query)
        if q.get("state", [None])[0] != state:
            print("state mismatch - start over", file=sys.stderr)
            return 1
        code = q.get("code", [None])[0]
    else:
        code = pasted
    if not code:
        print("no code found", file=sys.stderr)
        return 1

    tok = gcal.exchange_code(code, REDIRECT_URI)
    gcal.save_token(tok)
    print(f"\nSaved token to {gcal.state_path(gcal.TOKEN_FILE)}")
    if args.print_refresh_token:
        print("\nGOOGLE_REFRESH_TOKEN=" + tok["refresh_token"])
    print("\nVerifying... ", end="", flush=True)
    gcal.access_token()
    print("ok. Try: python scripts/calendar_search.py --days 7")
    return 0


if __name__ == "__main__":
    sys.exit(main())
