#!/usr/bin/env python3
"""Inbox: receives WhatsApp Business Cloud API webhooks, serves them back.

Meta pushes; it never lets you pull history. So this small always-on service
sits between WhatsApp and the routine:

    WhatsApp Cloud API --POST /webhook-->  inbox_server (SQLite)
    fetch_messages.py  --GET  /messages--> inbox_server

Endpoints
  GET  /webhook?hub.mode=subscribe&hub.verify_token=...&hub.challenge=...
       Meta's one-time verification; echoes the challenge if the token matches.
  POST /webhook
       Signed (X-Hub-Signature-256 over the raw body with WACAL_META_APP_SECRET).
       Stores every text message in the payload. Always 200s so Meta doesn't retry.
  GET  /messages?since=<iso>&chat_id=<id>&limit=<n>
       Bearer WACAL_INBOX_TOKEN. Returns {"messages": [...]} oldest-first.
  GET  /healthz

Settings: WACAL_META_VERIFY_TOKEN, WACAL_META_APP_SECRET, WACAL_INBOX_TOKEN,
          WACAL_INBOX_DB (default state/inbox.sqlite3), PORT (default 8080).

Run it anywhere with a public HTTPS URL (Cloud Run, Fly.io, a VPS behind
Caddy). It is single-process and stdlib-only; put a real TLS terminator in
front of it.

Note: Cloud API delivers messages *sent to your business number* and, for
group chats, only if the group feature is enabled for your WABA. It does
not mirror your personal account's chats.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
import sys
import urllib.parse
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import _bootstrap  # noqa: F401
from wacal.config import cfg, state_path
from wacal.model import normalise_message

DB_PATH = cfg("WACAL_INBOX_DB") or str(state_path("inbox.sqlite3"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
  id         TEXT PRIMARY KEY,
  chat_id    TEXT NOT NULL,
  sender     TEXT NOT NULL,
  ts         TEXT NOT NULL,
  text       TEXT NOT NULL,
  reply_to   TEXT,
  media_type TEXT,
  raw        TEXT NOT NULL,
  received_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS messages_ts ON messages(ts);
CREATE INDEX IF NOT EXISTS messages_chat_ts ON messages(chat_id, ts);
"""


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.executescript(SCHEMA)
    return conn


def extract_messages(payload: dict) -> list[dict]:
    """Flatten a Cloud API webhook payload into normalised messages."""
    out: list[dict] = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            names = {c.get("wa_id"): (c.get("profile") or {}).get("name") for c in value.get("contacts", [])}
            phone_id = (value.get("metadata") or {}).get("phone_number_id", "")
            for m in value.get("messages", []):
                mtype = m.get("type")
                if mtype == "text":
                    text = (m.get("text") or {}).get("body", "")
                elif mtype in ("image", "video", "document", "audio"):
                    text = (m.get(mtype) or {}).get("caption", "") or f"[{mtype}]"
                elif mtype == "location":
                    loc = m.get("location") or {}
                    text = f"[location] {loc.get('name','')} {loc.get('address','')} ({loc.get('latitude')},{loc.get('longitude')})"
                else:
                    text = f"[{mtype}]"
                sender_id = m.get("from", "")
                # Cloud API is 1:1 with the business number; the "chat" is the
                # counterpart's wa_id (group ids arrive in `group_id` if enabled).
                chat_id = m.get("group_id") or f"{phone_id}:{sender_id}"
                ts = datetime.fromtimestamp(int(m.get("timestamp", "0")), tz=timezone.utc)
                out.append({
                    **normalise_message(
                        id=m["id"], chat_id=chat_id,
                        sender=names.get(sender_id) or sender_id,
                        timestamp=ts, text=text,
                        reply_to=(m.get("context") or {}).get("id"),
                        media_type=None if mtype == "text" else mtype,
                    ),
                    "raw": m,
                })
    return out


class Handler(BaseHTTPRequestHandler):
    server_version = "wacal-inbox/1"

    def _send(self, code: int, body: bytes | str = b"", ctype: str = "text/plain") -> None:
        data = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _authed(self) -> bool:
        want = cfg("WACAL_INBOX_TOKEN", required=True)
        got = self.headers.get("Authorization", "")
        return hmac.compare_digest(got, f"Bearer {want}")

    def do_GET(self) -> None:  # noqa: N802
        url = urllib.parse.urlparse(self.path)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()}
        if url.path == "/healthz":
            return self._send(200, "ok")
        if url.path == "/webhook":
            if q.get("hub.mode") == "subscribe" and hmac.compare_digest(
                    q.get("hub.verify_token", ""), cfg("WACAL_META_VERIFY_TOKEN", required=True)):
                return self._send(200, q.get("hub.challenge", ""))
            return self._send(403, "verify token mismatch")
        if url.path == "/messages":
            if not self._authed():
                return self._send(401, "unauthorized")
            limit = max(1, min(int(q.get("limit", "300")), 2000))
            sql, params = "SELECT id, chat_id, sender, ts, text, reply_to, media_type FROM messages WHERE 1=1", []
            if q.get("since"):
                sql += " AND ts > ?"; params.append(datetime.fromisoformat(q["since"]).astimezone(timezone.utc).isoformat())
            if q.get("chat_id"):
                sql += " AND chat_id = ?"; params.append(q["chat_id"])
            sql += " ORDER BY ts ASC LIMIT ?"; params.append(limit)
            rows = self.server.conn.execute(sql, params).fetchall()  # type: ignore[attr-defined]
            msgs = [dict(zip(("id", "chat_id", "sender", "timestamp", "text", "reply_to", "media_type"), r)) for r in rows]
            return self._send(200, json.dumps({"messages": msgs}, ensure_ascii=False), "application/json")
        self._send(404, "not found")

    def do_POST(self) -> None:  # noqa: N802
        if urllib.parse.urlparse(self.path).path != "/webhook":
            return self._send(404, "not found")
        raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        secret = cfg("WACAL_META_APP_SECRET", required=True)
        expected = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(self.headers.get("X-Hub-Signature-256", ""), expected):
            return self._send(401, "bad signature")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return self._send(400, "bad json")
        now = datetime.now(timezone.utc).isoformat()
        conn = self.server.conn  # type: ignore[attr-defined]
        with conn:
            for m in extract_messages(payload):
                conn.execute(
                    "INSERT OR IGNORE INTO messages (id, chat_id, sender, ts, text, reply_to, media_type, raw, received_at)"
                    " VALUES (?,?,?,?,?,?,?,?,?)",
                    (m["id"], m["chat_id"], m["sender"], m["timestamp"], m["text"],
                     m["reply_to"], m["media_type"], json.dumps(m["raw"]), now),
                )
        self._send(200, "ok")

    def log_message(self, fmt: str, *args) -> None:  # quieter default log
        sys.stderr.write("%s %s\n" % (self.address_string(), fmt % args))


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8080")))
    port = ap.parse_args().port
    srv = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    srv.conn = db()  # type: ignore[attr-defined]
    print(f"inbox listening on :{port}, db={DB_PATH}", file=sys.stderr)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
