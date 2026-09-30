"""Minimal Google Calendar client (stdlib only).

Auth model: a standard "Desktop app" OAuth client. `scripts/google_auth.py`
runs the consent flow once and writes `state/google_token.json` containing a
refresh token. Every later call refreshes the access token on demand.

Idempotency: every event we create carries a private extended property
`wacal_key=<source_key>`. Before inserting we search for that key; if an event
exists we PATCH it instead. Deleting an event in the calendar UI is respected:
a cancelled event with the same key is *not* resurrected unless --force.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any

from .config import cfg, state_path

TOKEN_FILE = "google_token.json"
SCOPES = ["https://www.googleapis.com/auth/calendar.events"]
AUTH_URI = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URI = "https://oauth2.googleapis.com/token"
API = "https://www.googleapis.com/calendar/v3"
KEY_PROP = "wacal_key"


class GCalError(RuntimeError):
    pass


# --------------------------------------------------------------------------
# OAuth
# --------------------------------------------------------------------------

def load_token() -> dict[str, Any]:
    p = state_path(TOKEN_FILE)
    if not p.exists():
        raise GCalError(
            f"No Google token at {p}. Run `python scripts/google_auth.py` once "
            "(or set GOOGLE_REFRESH_TOKEN / GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET)."
        )
    return json.loads(p.read_text())


def save_token(tok: dict[str, Any]) -> None:
    p = state_path(TOKEN_FILE)
    p.write_text(json.dumps(tok, indent=2) + "\n")
    p.chmod(0o600)


def _client_creds() -> tuple[str, str]:
    return (cfg("GOOGLE_CLIENT_ID", required=True), cfg("GOOGLE_CLIENT_SECRET", required=True))


def _post_form(url: str, data: dict[str, str]) -> dict[str, Any]:
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        raise GCalError(f"OAuth token endpoint {e.code}: {e.read().decode(errors='replace')}") from None


def build_consent_url(redirect_uri: str, state: str) -> str:
    client_id, _ = _client_creds()
    q = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    return f"{AUTH_URI}?{urllib.parse.urlencode(q)}"


def exchange_code(code: str, redirect_uri: str) -> dict[str, Any]:
    client_id, client_secret = _client_creds()
    tok = _post_form(TOKEN_URI, {
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    })
    if "refresh_token" not in tok:
        raise GCalError("Google did not return a refresh_token; revoke the app at "
                        "https://myaccount.google.com/permissions and retry.")
    tok["expires_at"] = time.time() + int(tok.get("expires_in", 3600))
    return tok


def access_token() -> str:
    """Return a valid access token, refreshing if needed.

    Precedence: env GOOGLE_REFRESH_TOKEN (handy for CI / routine secrets),
    otherwise the token file written by google_auth.py.
    """
    env_refresh = cfg("GOOGLE_REFRESH_TOKEN")
    tok = {"refresh_token": env_refresh} if env_refresh else load_token()

    if tok.get("access_token") and tok.get("expires_at", 0) - 60 > time.time():
        return tok["access_token"]

    client_id, client_secret = _client_creds()
    fresh = _post_form(TOKEN_URI, {
        "refresh_token": tok["refresh_token"],
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "refresh_token",
    })
    tok["access_token"] = fresh["access_token"]
    tok["expires_at"] = time.time() + int(fresh.get("expires_in", 3600))
    if not env_refresh:
        save_token(tok)
    return tok["access_token"]


# --------------------------------------------------------------------------
# REST helpers
# --------------------------------------------------------------------------

def _request(method: str, path: str, *, params: dict | None = None, body: dict | None = None) -> dict[str, Any]:
    url = f"{API}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params, doseq=True)
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Authorization": f"Bearer {access_token()}", "Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503) and attempt < 2:
                time.sleep(2 ** attempt)
                continue
            raise GCalError(f"{method} {path} -> {e.code}: {e.read().decode(errors='replace')}") from None
    raise GCalError("unreachable")


def _cal_id() -> str:
    return cfg("GOOGLE_CALENDAR_ID", "primary")


def _cal_path(suffix: str = "") -> str:
    return f"/calendars/{urllib.parse.quote(_cal_id(), safe='')}/events{suffix}"


# --------------------------------------------------------------------------
# Public operations
# --------------------------------------------------------------------------

def find_by_key(source_key: str) -> dict[str, Any] | None:
    res = _request("GET", _cal_path(), params={
        "privateExtendedProperty": f"{KEY_PROP}={source_key}",
        "showDeleted": "true",
        "maxResults": 5,
        "singleEvents": "true",
    })
    items = res.get("items", [])
    # Prefer a live event; fall back to a cancelled one so callers can decide.
    live = [i for i in items if i.get("status") != "cancelled"]
    return (live or items or [None])[0]


def list_window(time_min: datetime, time_max: datetime, *, query: str | None = None) -> list[dict[str, Any]]:
    params = {
        "timeMin": time_min.astimezone(timezone.utc).isoformat(),
        "timeMax": time_max.astimezone(timezone.utc).isoformat(),
        "singleEvents": "true",
        "orderBy": "startTime",
        "maxResults": 250,
    }
    if query:
        params["q"] = query
    items: list[dict[str, Any]] = []
    page_token = None
    while True:
        if page_token:
            params["pageToken"] = page_token
        res = _request("GET", _cal_path(), params=params)
        items.extend(res.get("items", []))
        page_token = res.get("nextPageToken")
        if not page_token:
            break
    return items


def event_body(ev: dict[str, Any], tz: str) -> dict[str, Any]:
    """Translate a validated wacal event into a Calendar API resource."""
    if ev["all_day"]:
        start = {"date": ev["start"]}
        end_date = ev["end"] or ev["start"]
        # Google's all-day `end.date` is exclusive; add one day.
        from datetime import date, timedelta
        end = {"date": (date.fromisoformat(end_date) + timedelta(days=1)).isoformat()}
    else:
        start_dt = datetime.fromisoformat(ev["start"])
        end_dt = datetime.fromisoformat(ev["end"]) if ev["end"] else None
        if end_dt is None:
            from datetime import timedelta
            end_dt = start_dt + timedelta(hours=1)
        start = {"dateTime": start_dt.isoformat(), "timeZone": tz}
        end = {"dateTime": end_dt.isoformat(), "timeZone": tz}

    footer = "\n\n— Added from WhatsApp by wacal. Source messages: " + ", ".join(ev["source_message_ids"])
    body: dict[str, Any] = {
        "summary": ev["title"],
        "description": (ev["description"] or "") + footer,
        "start": start,
        "end": end,
        "extendedProperties": {"private": {
            KEY_PROP: ev["source_key"],
            "wacal_chat": ev["chat_id"][:200],
            "wacal_confidence": f"{ev['confidence']:.2f}",
        }},
        "source": {"title": "WhatsApp", "url": "https://web.whatsapp.com/"},
    }
    if ev["location"]:
        body["location"] = ev["location"]
    return body


def upsert(ev: dict[str, Any], *, tz: str, dry_run: bool = False, force: bool = False) -> dict[str, Any]:
    """Create or update the calendar event for `ev`. Returns a result record."""
    existing = find_by_key(ev["source_key"])
    body = event_body(ev, tz)

    if existing and existing.get("status") == "cancelled" and not force:
        return {"action": "skipped_deleted", "key": ev["source_key"], "title": ev["title"],
                "event_id": existing["id"], "reason": "event was deleted in Google Calendar; pass --force to recreate"}

    if dry_run:
        return {"action": "would_update" if existing else "would_create", "key": ev["source_key"],
                "title": ev["title"], "event_id": existing["id"] if existing else None, "body": body}

    if existing and existing.get("status") != "cancelled":
        res = _request("PATCH", _cal_path(f"/{existing['id']}"), body=body)
        return {"action": "updated", "key": ev["source_key"], "title": ev["title"],
                "event_id": res["id"], "html_link": res.get("htmlLink")}

    res = _request("POST", _cal_path(), body=body)
    return {"action": "created", "key": ev["source_key"], "title": ev["title"],
            "event_id": res["id"], "html_link": res.get("htmlLink")}


def delete_by_key(source_key: str, *, dry_run: bool = False) -> dict[str, Any]:
    existing = find_by_key(source_key)
    if not existing or existing.get("status") == "cancelled":
        return {"action": "not_found", "key": source_key}
    if dry_run:
        return {"action": "would_delete", "key": source_key, "event_id": existing["id"]}
    _request("DELETE", _cal_path(f"/{existing['id']}"))
    return {"action": "deleted", "key": source_key, "event_id": existing["id"]}
