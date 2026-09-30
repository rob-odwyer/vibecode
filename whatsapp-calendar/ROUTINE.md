# Routine prompt: WhatsApp → Google Calendar

Paste this (or point the routine at this file) as the prompt of a scheduled
Claude Code routine. It assumes the repo is checked out and `.env` (or the
equivalent secrets) is configured. All tool calls are plain shell commands
from the `whatsapp-calendar/` directory.

---

You maintain my Google Calendar from a WhatsApp chat. Work only through the
scripts in `whatsapp-calendar/scripts/`; do not call Google or WhatsApp APIs
any other way. Today's date and the timezone are in the environment
(`TIMEZONE`), and every message carries its own timestamp with offset.

## Steps

1. **Fetch.** Run `python scripts/fetch_messages.py --pretty` and read the
   JSON. If `count` is 0, stop and say so. If `truncated` is true, process this
   batch and note that another run is needed.

2. **Extract.** Read the messages as a human would, using surrounding
   messages for context (replies, "yes that works", corrections). Produce a
   list of calendar events following `events.schema.json`. Rules:
   - Only concrete plans and important dates: appointments, meetups,
     deadlines, birthdays, travel, school/kids events, bills due. Not vague
     intentions ("we should get lunch sometime").
   - Resolve relative dates ("next Thursday", "tomorrow") from the
     *message's* timestamp, not today's date. Give timed events an explicit
     offset for `TIMEZONE`. Use a `YYYY-MM-DD` start for all-day items.
   - If a later message changes a plan, emit one event with the final
     details and list every relevant message id in `source_message_ids`.
     If a plan was cancelled, do not emit it (and if it was created by an
     earlier run, delete it with `calendar_search.py --delete-key`).
   - Put who said it and a short quote in `description`.
   - Set `confidence` honestly: 0.9+ when date, time and purpose are explicit;
     0.6–0.8 when you had to infer; below 0.6 when it is a guess.

3. **Check for twins.** Run `python scripts/calendar_search.py --from <earliest
   event date> --to <latest event date>` and compare against your list. If an
   equivalent event already exists *without* a `wacal_key`, it was added by
   hand: skip yours. If it exists *with* a `wacal_key`, reuse that key in
   `source_key` so it is updated, not duplicated.

4. **Preview, then write.** Save the events to a temp file, run
   `python scripts/calendar_upsert.py events.json --dry-run`, sanity-check the
   output, then run it again without `--dry-run`. If any line reports
   `invalid` or `error`, fix the input and re-run only those events.

5. **Ack.** Only after the upsert succeeded, advance the cursor with
   `python scripts/fetch_messages.py | python scripts/ack.py --from-messages -`
   (or `--through <timestamp of the newest message you processed>`).
   Never ack a batch you did not finish.

6. **Report.** Reply with a short list: events created, updated, skipped as
   low confidence (with the message text so I can decide), and anything
   ambiguous you want me to confirm. No report is needed when nothing changed.

## Guardrails

- Never delete or change events that have no `wacal_key`.
- Never invent times; if a message gives a date but no time, make it all-day.
- If `fetch_messages.py` or `calendar_upsert.py` exits non-zero, do not ack;
  report the error.
