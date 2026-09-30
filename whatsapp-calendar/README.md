# whatsapp-calendar (wacal)

Glue for a scheduled agent routine that reads a WhatsApp chat, spots events
and important dates, and puts them in Google Calendar.

The design splits the job in two:

| Who | Does | How |
|---|---|---|
| **Scripts** (this repo) | Fetch messages, remember where we got to, create/update calendar events idempotently | Deterministic Python, stdlib only |
| **Agent** (the routine) | Read the messages and decide what is an event, when it is, and how sure it is | `ROUTINE.md` prompt + `events.schema.json` |

The agent never touches an API directly and the scripts never interpret
language. That keeps the scripts small and testable, and lets you change how
extraction works by editing a prompt.

```
                ┌──────────────────────┐
  WhatsApp ───▶ │ source               │  fetch_messages.py ──▶ messages JSON
                │  export | inbox      │         │
                └──────────────────────┘         ▼
                                            agent reads, extracts
                                                 │
                                                 ▼ events JSON (events.schema.json)
                                      calendar_search.py  (look for twins)
                                      calendar_upsert.py  (idempotent write)
                                                 │
                                                 ▼
                                      ack.py (advance cursor)
```

## Read this first: getting at the WhatsApp messages

There is no OAuth API that reads a personal WhatsApp account's chats. Two
supported paths are wired in; pick with `WACAL_SOURCE`:

| Source | What it is | Pros | Cons |
|---|---|---|---|
| `export` (default) | You use WhatsApp's **Export chat** and drop the `.txt` into `inbox-exports/` | No API, works for any chat including groups, five minutes to set up | Manual step each time (or a phone automation that shares the export to a synced folder) |
| `inbox` | **WhatsApp Business Cloud API** webhooks → `scripts/inbox_server.py` (a tiny always-on receiver you host) | Fully automatic; real OAuth-style credentials from Meta | Only sees messages sent *to your business number*; needs a Meta developer app and a public HTTPS host |

If you want a personal/group chat *and* full automation, the remaining
option is a third-party linked-device bridge (Whapi, Green API, and similar,
or the open-source Baileys/whatsapp-web.js libraries). Those work but are
against WhatsApp's terms and accounts do get banned, so they are not built
in. Adding one is a single function; see `wacal/sources/__init__.py`.

## Setup

```bash
cd whatsapp-calendar
cp .env.example .env            # fill in TIMEZONE and the Google client id/secret
python scripts/google_auth.py   # one-time consent; writes state/google_token.json
python scripts/calendar_search.py --days 7   # proves Calendar access works
```

Google side: enable the Calendar API in a Cloud project, create an OAuth
client of type **Desktop app**, and add your account as a test user while the
app is unpublished. Scope requested is `calendar.events` only.

For a routine whose container starts empty each run, put
`GOOGLE_REFRESH_TOKEN` (from `google_auth.py --print-refresh-token`) plus the
client id/secret in the environment's secrets instead of shipping the token
file, and persist `state/cursor.json` somewhere (commit it, or store it in a
bucket). The cursor is the only state the routine needs between runs.

### Source: export

1. In WhatsApp open the chat → ⋮ → More → **Export chat** → Without media.
2. Save the `.txt` into `inbox-exports/` (any filename; the stem becomes `chat_id`).
3. Set `WACAL_EXPORT_DATE_ORDER=MDY` if your phone writes US-style dates.

Re-exporting the same chat later is fine: messages are deduplicated.

### Source: inbox

1. Create a Meta app with the WhatsApp product, note the **App secret** and
   generate a permanent **System User token** for the business.
2. Deploy `scripts/inbox_server.py` somewhere with HTTPS, with
   `WACAL_META_VERIFY_TOKEN`, `WACAL_META_APP_SECRET`, `WACAL_INBOX_TOKEN`
   set. Point the app's webhook at `https://host/webhook` and subscribe to
   the `messages` field.
3. On the routine side set `WACAL_SOURCE=inbox`, `WACAL_INBOX_URL`,
   `WACAL_INBOX_TOKEN`.

## The scripts

All are `python scripts/<name>.py --help` friendly and print JSON.

| Script | Purpose |
|---|---|
| `fetch_messages.py` | New messages since the cursor (or `--since`), oldest first. Read-only. |
| `calendar_search.py` | Existing events in a date window, by text, or by `wacal_key`; `--delete-key` removes one we created. |
| `calendar_upsert.py` | Validate events JSON and create/update them. `--dry-run` previews. Skips anything below `--min-confidence`. |
| `ack.py` | Move the cursor forward once a batch is safely in the calendar. |
| `google_auth.py` | One-time OAuth consent. |
| `inbox_server.py` | Webhook receiver + message API for the `inbox` source. |

### Idempotency

Every event written gets a private extended property `wacal_key`, derived
from the chat, the earliest source message id and the normalised title. Upsert
searches for that key first and PATCHes if found. So re-running over the same
messages is harmless, a plan that changes across messages updates in place,
and an event you delete by hand in Google Calendar stays deleted unless you
pass `--force`.

## Running it as a routine

Schedule `ROUTINE.md` as the prompt of a Claude Code routine (hourly or daily
is plenty). The agent runs the scripts in order: fetch → extract → search →
upsert (dry-run, then real) → ack → report. If a step fails it stops before
`ack`, so the next run picks the same messages up again.

## Tests

```bash
cd whatsapp-calendar && python -m unittest discover -s tests -v
```

Covers the export parser (several locale formats, multi-line messages,
dedup), event validation and key stability, the Calendar request body
builder, and the webhook payload flattening plus signature check. No network
access needed.
