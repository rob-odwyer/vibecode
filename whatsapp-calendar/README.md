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

There is no OAuth API that reads a personal WhatsApp account's chats. Three
paths are wired in; pick with `WACAL_SOURCE`:

| Source | What it is | Pros | Cons |
|---|---|---|---|
| `whatsmeow` | A Go bridge in `bridge/` that links to your account as a **companion device** (the WhatsApp Web multidevice protocol, via [go.mau.fi/whatsmeow](https://pkg.go.dev/go.mau.fi/whatsmeow)) | Fully automatic; sees your personal and group chats; also understands WhatsApp's native group *Event* messages | Unofficial: it is not an API Meta offers, it is against WhatsApp's terms of service, and accounts do get banned. Needs a Go toolchain to build |
| `export` | You use WhatsApp's **Export chat** and drop the `.txt` into `inbox-exports/` | No API, works for any chat, five minutes to set up | Manual step each time |
| `inbox` | **WhatsApp Business Cloud API** webhooks → `scripts/inbox_server.py` (a tiny receiver you host), or `wa-bridge serve` | Official (for the Cloud API); real credentials from Meta | Cloud API only sees messages sent *to your business number*; needs a Meta app and a public HTTPS host |

`whatsmeow` is the one that does what you asked for. Use a number you can
afford to lose if Meta objects, and don't send messages through the bridge
(it only reads, which keeps it well away from spam heuristics).

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

For a routine whose container starts empty each run, see "Running it as a
remote routine" below.

### Source: whatsmeow (the Go bridge)

```bash
cd bridge && go build -o wa-bridge . && cd ..   # needs Go 1.26+ and a C compiler (sqlite)
./bridge/wa-bridge link                          # scan the QR with WhatsApp > Linked devices
./bridge/wa-bridge link --phone +447700900123    # ...or pair with a code (headless)
./bridge/wa-bridge groups                        # find the JID of the chat you care about
```

Put the JID in `WACAL_WA_CHAT_ID` (and, if you want the bridge to *store*
nothing else, in `WACAL_WA_CHATS` too) and set `WACAL_SOURCE=whatsmeow`.

How it works: `fetch_messages.py` runs `wa-bridge fetch`, which connects as
the linked device, waits for WhatsApp to deliver everything queued since the
last connection (whatsmeow's `OfflineSyncCompleted` event), stores the
decrypted messages in `state/wa-messages.sqlite3`, prints them as JSON, and
disconnects. On first link WhatsApp also sends a history sync of recent
conversations, which is stored the same way, so the first run has context.

Two files in `state/` must persist between runs: `whatsmeow.db` (the session
and Signal keys: losing it means re-linking) and `wa-messages.sqlite3`. For a
routine whose container starts empty, turn on the Drive state sync described
under "Running it as a remote routine". They are secrets: never commit them.

Message edits update the stored text under the original id; deleted
messages, reactions and stickers are dropped. Group *Event* messages are
rendered as `[event] name / start: ... / location: ...` with times already
in `TIMEZONE`, so the agent can lift them straight into an event.

If you would rather keep a daemon connected, `./bridge/wa-bridge serve`
exposes the same `GET /messages` API as `inbox_server.py`; point
`WACAL_SOURCE=inbox` and `WACAL_INBOX_URL` at it. A companion device that
stays offline for a long stretch can be unlinked by WhatsApp, so run the
routine at least daily if you use the one-shot mode.

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
| `state_sync.py` | `status` / `push` / `pull` / `unlock` the Drive-mirrored state. |
| `bridge/wa-bridge` | Go: `link`, `fetch`, `serve`, `groups` for the `whatsmeow` source. |

### Idempotency

Every event written gets a private extended property `wacal_key`, derived
from the chat, the earliest source message id and the normalised title. Upsert
searches for that key first and PATCHes if found. So re-running over the same
messages is harmless, a plan that changes across messages updates in place,
and an event you delete by hand in Google Calendar stays deleted unless you
pass `--force`.

## Running it as a remote routine

A scheduled Claude Code routine starts from an empty container every run, so
four things have to be provided by the environment rather than the repo.

**1. Network.** The environment's allowed domains must include:

| Host | Used by |
|---|---|
| `web.whatsapp.com` | the bridge's WebSocket (pairing and fetching) |
| `www.googleapis.com`, `oauth2.googleapis.com` | Calendar, Drive, token refresh |
| `proxy.golang.org`, `sum.golang.org` | building the bridge in the setup script |

**2. Secrets** (environment variables): `GOOGLE_CLIENT_ID`,
`GOOGLE_CLIENT_SECRET`, `GOOGLE_REFRESH_TOKEN` (from
`google_auth.py --print-refresh-token`), `WACAL_STATE_PASSPHRASE` (see below),
plus the plain settings `TIMEZONE`, `WACAL_SOURCE=whatsmeow`,
`WACAL_WA_CHAT_ID`, `WACAL_STATE_SYNC=drive`.

**3. The bridge binary.** Point the environment's setup script at
`whatsapp-calendar/setup-env.sh`; it builds `bridge/wa-bridge` if missing.

**4. State between runs: Google Drive.** Set `WACAL_STATE_SYNC=drive` and the
`whatsmeow` source mirrors `state/whatsmeow.db`, `state/wa-messages.sqlite3`
and `state/cursor.json` to a Drive folder (`wacal-state`) using the same
OAuth client as the calendar, with the `drive.file` scope (it can only see
files it created). Each fetch does:

```
pull (takes a lease)  →  wa-bridge fetch  →  push (releases the lease)
```

The push sits in a `finally` right after the bridge exits, because
`whatsmeow.db` carries Signal ratchet state that advances with every
decrypted message: a run that fetched but did not push would leave the next
run unable to read those messages. The lease (a `lock.json` in the folder,
stale after 30 minutes) stops two runs from decrypting with the same keys at
once; a run that finds the lease held reports it and stops rather than
forcing. `ack.py` pushes the cursor on its own.

`whatsmeow.db` lets whoever holds it read your WhatsApp as a linked device.
Set `WACAL_STATE_PASSPHRASE` and every file is AES-256 encrypted (openssl)
before it reaches Drive; the passphrase lives only in the environment's
secrets.

### One-time bootstrap (on your own machine)

```bash
cd whatsapp-calendar && cp .env.example .env    # fill in Google client id/secret, TIMEZONE
python scripts/google_auth.py --print-refresh-token   # consents to calendar + drive.file
cd bridge && go build -o wa-bridge . && cd ..
./bridge/wa-bridge link --phone +44XXXXXXXXXX          # pair; waits for history sync
./bridge/wa-bridge groups                              # pick the chat JID
WACAL_STATE_SYNC=drive WACAL_STATE_PASSPHRASE=... python scripts/state_sync.py push
python scripts/state_sync.py status                    # confirm the files landed
```

Then put the refresh token, passphrase and settings into the routine's
environment, and schedule `ROUTINE.md` as its prompt. Hourly to daily is a
sensible cadence; a linked device that stays offline for weeks can be
unlinked by WhatsApp, so do not go rarer than daily.

After the bootstrap, delete the local `state/` copies if you don't want a
second copy of the session lying around, or keep them as a backup.

## Tests

```bash
cd whatsapp-calendar && python -m unittest discover -s tests -v
cd bridge && go test ./...
```

Python: the export parser (several locale formats, multi-line messages,
dedup), event validation and key stability, the Calendar request body
builder, the webhook payload flattening plus signature check, and the
whatsmeow adapter's command line, and Drive state sync against a fake Drive (lease, stale takeover, encryption). Go: message conversion (text, captions,
replies, edits, native Events, skipped reactions) and the SQLite store. No
network access needed.
