"""Keep the routine's state in a Google Drive folder between runs.

A remote routine starts from an empty container, but three files must
survive from one run to the next:

    whatsmeow.db          the WhatsApp session and Signal keys (the bridge)
    wa-messages.sqlite3   messages the bridge has stored
    cursor.json           how far the agent has processed

This module mirrors them to a Drive folder (default "wacal-state") using the
same OAuth client as the calendar, with the `drive.file` scope, so the app can
only see files it created itself.

Why the ceremony around pull/push: whatsmeow.db changes every time messages
are decrypted (Signal ratchets advance). If one run pulls, decrypts, and does
not push, the next run decrypts with stale keys and those messages are lost.
So `pull()` takes a lease (a lock file in the folder) and the whatsmeow
source calls `push()` in a `finally` immediately after the bridge exits.

Optional at-rest encryption: set WACAL_STATE_PASSPHRASE and files are stored
as <name>.enc, AES-256-CBC via the openssl CLI. whatsmeow.db lets its holder
read your WhatsApp as a linked device, so this is worth turning on.

Settings:
    WACAL_STATE_SYNC=drive          turn it on (anything else: off)
    WACAL_DRIVE_FOLDER=wacal-state  folder name in My Drive
    WACAL_STATE_PASSPHRASE=...      optional encryption passphrase
    WACAL_STATE_LOCK_TTL_MIN=30     a lease older than this is considered stale
"""
from __future__ import annotations

import json
import os
import socket
import sqlite3
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import gcal
from .config import cfg, state_path, STATE_DIR

SYNCED_FILES = ("whatsmeow.db", "wa-messages.sqlite3", "cursor.json")
LOCK_NAME = "lock.json"
DRIVE = "https://www.googleapis.com/drive/v3"
UPLOAD = "https://www.googleapis.com/upload/drive/v3"
FOLDER_MIME = "application/vnd.google-apps.folder"


class StateSyncError(RuntimeError):
    pass


class Locked(StateSyncError):
    pass


def enabled() -> bool:
    return (cfg("WACAL_STATE_SYNC", "") or "").lower() == "drive"


def _passphrase() -> str | None:
    return cfg("WACAL_STATE_PASSPHRASE") or None


# --------------------------------------------------------------------------
# Drive REST (urllib only)
# --------------------------------------------------------------------------

def _api(method: str, url: str, *, params: dict | None = None, body: bytes | None = None,
         headers: dict | None = None, raw: bool = False) -> Any:
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    hdrs = {"Authorization": f"Bearer {gcal.access_token()}", **(headers or {})}
    req = urllib.request.Request(url, data=body, method=method, headers=hdrs)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = resp.read()
                if raw:
                    return data
                return json.loads(data) if data else {}
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503) and attempt < 2:
                time.sleep(2 ** attempt)
                continue
            raise StateSyncError(f"{method} {url} -> {e.code}: {e.read().decode(errors='replace')}") from None
    raise StateSyncError("unreachable")


def _folder_id(create: bool = True) -> str | None:
    name = cfg("WACAL_DRIVE_FOLDER", "wacal-state")
    q = f"name = '{name}' and mimeType = '{FOLDER_MIME}' and trashed = false"
    res = _api("GET", f"{DRIVE}/files", params={"q": q, "fields": "files(id)", "spaces": "drive"})
    files = res.get("files", [])
    if files:
        return files[0]["id"]
    if not create:
        return None
    res = _api("POST", f"{DRIVE}/files", body=json.dumps({"name": name, "mimeType": FOLDER_MIME}).encode(),
               headers={"Content-Type": "application/json"})
    return res["id"]


def _list(folder_id: str) -> dict[str, dict]:
    res = _api("GET", f"{DRIVE}/files", params={
        "q": f"'{folder_id}' in parents and trashed = false",
        "fields": "files(id,name,modifiedTime,size,md5Checksum)",
        "pageSize": 100,
    })
    return {f["name"]: f for f in res.get("files", [])}


def _download(file_id: str) -> bytes:
    return _api("GET", f"{DRIVE}/files/{file_id}", params={"alt": "media"}, raw=True)


def _upload(folder_id: str, name: str, data: bytes, existing_id: str | None) -> dict:
    if existing_id:
        return _api("PATCH", f"{UPLOAD}/files/{existing_id}", params={"uploadType": "media"},
                    body=data, headers={"Content-Type": "application/octet-stream"})
    boundary = "wacal" + uuid.uuid4().hex
    meta = json.dumps({"name": name, "parents": [folder_id]}).encode()
    body = (
        f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n".encode() + meta +
        f"\r\n--{boundary}\r\nContent-Type: application/octet-stream\r\n\r\n".encode() + data +
        f"\r\n--{boundary}--".encode()
    )
    return _api("POST", f"{UPLOAD}/files", params={"uploadType": "multipart", "fields": "id,name,modifiedTime"},
                body=body, headers={"Content-Type": f"multipart/related; boundary={boundary}"})


def _delete(file_id: str) -> None:
    _api("DELETE", f"{DRIVE}/files/{file_id}", raw=True)


# --------------------------------------------------------------------------
# local helpers
# --------------------------------------------------------------------------

def _checkpoint(path: Path) -> None:
    """Fold any SQLite WAL into the main file so a single file is a full copy."""
    if path.suffix not in (".db", ".sqlite3") or not path.exists():
        return
    try:
        con = sqlite3.connect(path)
        con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        con.close()
    except sqlite3.DatabaseError as e:
        raise StateSyncError(f"{path.name}: cannot checkpoint: {e}") from None


def _openssl(args: list[str], data: bytes, passphrase: str) -> bytes:
    proc = subprocess.run(["openssl", "enc", *args, "-aes-256-cbc", "-pbkdf2", "-salt", "-pass", "env:WACAL_SS_PASS"],
                          input=data, capture_output=True, env={**os.environ, "WACAL_SS_PASS": passphrase})
    if proc.returncode != 0:
        raise StateSyncError("openssl failed: " + proc.stderr.decode(errors="replace").strip())
    return proc.stdout


def _encode(data: bytes) -> tuple[bytes, str]:
    pw = _passphrase()
    return (_openssl([], data, pw), ".enc") if pw else (data, "")


def _decode(data: bytes, remote_name: str) -> bytes:
    if remote_name.endswith(".enc"):
        pw = _passphrase()
        if not pw:
            raise StateSyncError(f"{remote_name} is encrypted but WACAL_STATE_PASSPHRASE is not set")
        return _openssl(["-d"], data, pw)
    return data


def _remote_name_for(local: str, listing: dict[str, dict]) -> str | None:
    if local + ".enc" in listing:
        return local + ".enc"
    if local in listing:
        return local
    return None


def _lock_payload() -> dict:
    return {"host": socket.gethostname(), "pid": os.getpid(),
            "acquired_at": datetime.now(timezone.utc).isoformat()}


def _lock_age_minutes(lock_meta: dict) -> float:
    try:
        payload = json.loads(_download(lock_meta["id"]))
        t = datetime.fromisoformat(payload["acquired_at"])
    except Exception:  # unreadable lock: fall back to Drive's modifiedTime
        t = datetime.fromisoformat(lock_meta["modifiedTime"].replace("Z", "+00:00"))
    return (datetime.now(timezone.utc) - t).total_seconds() / 60


# --------------------------------------------------------------------------
# public API
# --------------------------------------------------------------------------

def status() -> dict:
    fid = _folder_id(create=False)
    if not fid:
        return {"folder": cfg("WACAL_DRIVE_FOLDER", "wacal-state"), "exists": False, "files": {}}
    listing = _list(fid)
    return {
        "folder": cfg("WACAL_DRIVE_FOLDER", "wacal-state"), "folder_id": fid, "exists": True,
        "encrypted": any(n.endswith(".enc") for n in listing),
        "locked": LOCK_NAME in listing,
        "files": {n: {"size": int(f.get("size", 0)), "modified": f["modifiedTime"]} for n, f in listing.items()},
    }


def pull(*, force: bool = False, lock: bool = True) -> dict:
    """Download state files into STATE_DIR. Takes the lease unless lock=False."""
    fid = _folder_id()
    listing = _list(fid)

    if lock:
        if LOCK_NAME in listing:
            age = _lock_age_minutes(listing[LOCK_NAME])
            ttl = float(cfg("WACAL_STATE_LOCK_TTL_MIN", "30"))
            if age < ttl and not force:
                raise Locked(f"another run holds the state lease ({age:.0f} min old, ttl {ttl:.0f}); "
                             f"retry later or use --force")
            _delete(listing[LOCK_NAME]["id"])
        _upload(fid, LOCK_NAME, json.dumps(_lock_payload()).encode(), None)
        state_path(".lease").write_text(fid)

    pulled, missing = [], []
    for name in SYNCED_FILES:
        remote = _remote_name_for(name, listing)
        if not remote:
            missing.append(name)
            continue
        data = _decode(_download(listing[remote]["id"]), remote)
        dest = state_path(name)
        for stale in (dest.with_name(dest.name + "-wal"), dest.with_name(dest.name + "-shm")):
            stale.unlink(missing_ok=True)
        dest.write_bytes(data)
        dest.chmod(0o600)
        pulled.append(name)
    return {"action": "pulled", "files": pulled, "missing": missing, "locked": lock}


def push(*, files: tuple[str, ...] = SYNCED_FILES, release: bool = True) -> dict:
    """Upload state files from STATE_DIR. Releases the lease by default."""
    fid = _folder_id()
    listing = _list(fid)
    pushed, skipped = [], []
    for name in files:
        src = STATE_DIR / name
        if not src.exists():
            skipped.append(name)
            continue
        _checkpoint(src)
        data, suffix = _encode(src.read_bytes())
        remote = name + suffix
        # If the encryption setting changed, remove the old variant.
        other = _remote_name_for(name, listing)
        if other and other != remote:
            _delete(listing[other]["id"])
            other = None
        _upload(fid, remote, data, listing[other]["id"] if other else None)
        pushed.append(remote)
    if release and LOCK_NAME in listing:
        _delete(listing[LOCK_NAME]["id"])
        state_path(".lease").unlink(missing_ok=True)
    return {"action": "pushed", "files": pushed, "skipped": skipped, "released": release}


def unlock() -> dict:
    fid = _folder_id(create=False)
    if not fid:
        return {"action": "noop"}
    listing = _list(fid)
    if LOCK_NAME in listing:
        _delete(listing[LOCK_NAME]["id"])
        return {"action": "unlocked"}
    return {"action": "noop", "reason": "no lock"}
