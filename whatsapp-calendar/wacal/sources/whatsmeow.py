"""Source: the Go bridge in ./bridge (go.mau.fi/whatsmeow, WhatsApp Web
multidevice protocol).

One-shot mode: this adapter runs `wa-bridge fetch`, which connects as the
linked companion device, drains whatever WhatsApp queued while we were
offline, prints the stored messages as JSON and exits. No daemon needed; the
only persistent state is the two SQLite files in state/.

Daemon mode (`wa-bridge serve`) exposes the same GET /messages API as
scripts/inbox_server.py, so for that you use WACAL_SOURCE=inbox instead.

Settings:
    WACAL_WA_BRIDGE_BIN   path to the binary (default ./bridge/wa-bridge)
    WACAL_WA_CHAT_ID      optional: only this chat JID (see `wa-bridge groups`)
    WACAL_WA_FETCH_WAIT   how long to wait for queued messages (default 20s)
    WACAL_WA_OFFLINE=1    don't connect; read only what is already stored
"""
from __future__ import annotations

import json
import subprocess
from datetime import datetime
from pathlib import Path

from ..config import cfg, PROJECT_ROOT


def _binary() -> Path:
    p = Path(cfg("WACAL_WA_BRIDGE_BIN", str(PROJECT_ROOT / "bridge" / "wa-bridge")))
    if not p.exists():
        raise SystemExit(
            f"wa-bridge binary not found at {p}. Build it with:\n"
            f"  cd {PROJECT_ROOT / 'bridge'} && go build -o wa-bridge .\n"
            "then link it once with `./wa-bridge link`."
        )
    return p


def fetch(since: datetime | None, limit: int) -> list[dict]:
    cmd = [str(_binary()), "fetch", "--limit", str(limit),
           "--wait", cfg("WACAL_WA_FETCH_WAIT", "20s")]
    if since is not None:
        cmd += ["--since", since.isoformat(timespec="seconds")]
    chat = cfg("WACAL_WA_CHAT_ID")
    if chat:
        cmd += ["--chat", chat]
    if cfg("WACAL_WA_OFFLINE", "") in ("1", "true", "yes"):
        cmd.append("--offline")

    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=PROJECT_ROOT)
    if proc.returncode != 0:
        raise SystemExit(f"wa-bridge fetch failed ({proc.returncode}):\n{proc.stderr.strip()}")
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise SystemExit(f"wa-bridge printed invalid JSON: {e}\n{proc.stdout[:500]}") from None
    return payload["messages"]
