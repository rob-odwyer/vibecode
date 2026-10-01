"""statesync against a fake in-memory Drive (the REST layer is monkeypatched)."""
import json
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from wacal import statesync


class FakeDrive:
    def __init__(self):
        self.files = {}   # id -> {"name", "parents", "data", "modifiedTime"}
        self.n = 0

    def _new_id(self):
        self.n += 1
        return f"f{self.n}"

    def api(self, method, url, *, params=None, body=None, headers=None, raw=False):
        params = params or {}
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        if method == "GET" and url.endswith("/files"):
            q = params["q"]
            if "mimeType" in q:
                hits = [f for f in self.files.values() if f["name"] == statesync.cfg("WACAL_DRIVE_FOLDER", "wacal-state")]
            else:
                folder = q.split("'")[1]
                hits = [f for f in self.files.values() if folder in f.get("parents", [])]
            return {"files": [{"id": i, "name": f["name"], "modifiedTime": f["modifiedTime"],
                               "size": str(len(f.get("data", b"")))}
                              for i, f in self.files.items() if f in hits]}
        if method == "GET" and params.get("alt") == "media":
            return self.files[url.rsplit("/", 1)[1]]["data"]
        if method == "POST" and url.endswith("/files") and headers.get("Content-Type") == "application/json":
            meta = json.loads(body); fid = self._new_id()
            self.files[fid] = {"name": meta["name"], "parents": [], "modifiedTime": now}
            return {"id": fid}
        if method == "POST" and "upload" in url:
            raw_body = body.decode("latin1")
            meta_json = raw_body.split("\r\n\r\n", 1)[1].split("\r\n--", 1)[0]
            meta = json.loads(meta_json)
            data = body.split(b"application/octet-stream\r\n\r\n", 1)[1].rsplit(b"\r\n--", 1)[0]
            fid = self._new_id()
            self.files[fid] = {"name": meta["name"], "parents": meta["parents"], "data": data, "modifiedTime": now}
            return {"id": fid, "name": meta["name"]}
        if method == "PATCH":
            fid = url.rsplit("/", 1)[1].split("?")[0]
            self.files[fid]["data"] = body; self.files[fid]["modifiedTime"] = now
            return {"id": fid}
        if method == "DELETE":
            self.files.pop(url.rsplit("/", 1)[1], None)
            return b""
        raise AssertionError(f"unexpected {method} {url} {params}")

    def names(self):
        return sorted(f["name"] for f in self.files.values() if f.get("parents"))

    def by_name(self, name):
        return next(f for f in self.files.values() if f["name"] == name)


class StateSyncTests(unittest.TestCase):
    def setUp(self):
        self.drive = FakeDrive()
        self.tmp = Path(tempfile.mkdtemp())
        patches = [
            mock.patch.object(statesync, "_api", self.drive.api),
            mock.patch.object(statesync, "STATE_DIR", self.tmp),
            mock.patch.object(statesync, "state_path", lambda n: self.tmp / n),
        ]
        for p in patches:
            p.start(); self.addCleanup(p.stop)
        os.environ.pop("WACAL_STATE_PASSPHRASE", None)

    def _seed_local(self):
        con = sqlite3.connect(self.tmp / "wa-messages.sqlite3")
        con.execute("PRAGMA journal_mode=WAL"); con.execute("CREATE TABLE t(x)"); con.execute("INSERT INTO t VALUES (1)")
        con.commit(); con.close()
        (self.tmp / "cursor.json").write_text('{"last_seen_ts": "2026-09-29T08:00:00Z"}')

    def test_push_then_pull_roundtrip(self):
        self._seed_local()
        out = statesync.push()
        self.assertEqual(sorted(out["files"]), ["cursor.json", "wa-messages.sqlite3"])
        self.assertEqual(out["skipped"], ["whatsmeow.db"])
        self.assertFalse((self.tmp / "wa-messages.sqlite3-wal").exists() and
                         (self.tmp / "wa-messages.sqlite3-wal").stat().st_size > 0, "WAL should be checkpointed")

        # wipe local, pull back
        for f in self.tmp.iterdir():
            f.unlink()
        out = statesync.pull()
        self.assertEqual(sorted(out["files"]), ["cursor.json", "wa-messages.sqlite3"])
        self.assertIn("whatsmeow.db", out["missing"])
        con = sqlite3.connect(self.tmp / "wa-messages.sqlite3")
        self.assertEqual(con.execute("SELECT x FROM t").fetchone(), (1,))
        self.assertIn("lock.json", self.drive.names())
        self.assertTrue((self.tmp / ".lease").exists())

        statesync.push()
        self.assertNotIn("lock.json", self.drive.names())

    def test_second_pull_is_refused_while_leased(self):
        self._seed_local(); statesync.push(); statesync.pull()
        with self.assertRaises(statesync.Locked):
            statesync.pull()
        statesync.pull(force=True)  # explicit override works
        statesync.unlock()
        self.assertNotIn("lock.json", self.drive.names())

    def test_stale_lease_is_taken_over(self):
        self._seed_local(); statesync.push(); statesync.pull()
        lock = self.drive.by_name("lock.json")
        old = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        lock["data"] = json.dumps({"acquired_at": old}).encode()
        statesync.pull()  # no exception: ttl 30 min exceeded

    def test_push_updates_in_place_not_duplicates(self):
        self._seed_local(); statesync.push()
        (self.tmp / "cursor.json").write_text('{"last_seen_ts": "2026-09-30T08:00:00Z"}')
        statesync.push(files=("cursor.json",), release=False)
        self.assertEqual(self.drive.names().count("cursor.json"), 1)
        self.assertIn(b"2026-09-30", self.drive.by_name("cursor.json")["data"])

    def test_encryption_roundtrip(self):
        os.environ["WACAL_STATE_PASSPHRASE"] = "correct horse"
        self._seed_local(); statesync.push()
        self.assertIn("cursor.json.enc", self.drive.names())
        self.assertNotIn(b"last_seen_ts", self.drive.by_name("cursor.json.enc")["data"])
        (self.tmp / "cursor.json").unlink()
        statesync.pull(lock=False)
        self.assertIn("last_seen_ts", (self.tmp / "cursor.json").read_text())

        # Turning encryption off replaces the .enc copy instead of leaving both.
        os.environ.pop("WACAL_STATE_PASSPHRASE")
        statesync.push(files=("cursor.json",))
        self.assertIn("cursor.json", self.drive.names())
        self.assertNotIn("cursor.json.enc", self.drive.names())

    def test_pull_without_passphrase_fails_clearly(self):
        os.environ["WACAL_STATE_PASSPHRASE"] = "pw"
        self._seed_local(); statesync.push()
        os.environ.pop("WACAL_STATE_PASSPHRASE")
        with self.assertRaises(statesync.StateSyncError) as cm:
            statesync.pull(lock=False)
        self.assertIn("WACAL_STATE_PASSPHRASE", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
