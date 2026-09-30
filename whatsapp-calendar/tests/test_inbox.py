import hashlib
import hmac
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

os.environ["WACAL_STATE_DIR"] = tempfile.mkdtemp()
os.environ["WACAL_INBOX_TOKEN"] = "inbox-secret"
os.environ["WACAL_META_VERIFY_TOKEN"] = "verify-me"
os.environ["WACAL_META_APP_SECRET"] = "app-secret"

import inbox_server  # noqa: E402
from http.server import ThreadingHTTPServer  # noqa: E402

PAYLOAD = {
    "object": "whatsapp_business_account",
    "entry": [{"id": "1", "changes": [{"field": "messages", "value": {
        "metadata": {"phone_number_id": "PHONE1"},
        "contacts": [{"wa_id": "4477", "profile": {"name": "Alice"}}],
        "messages": [
            {"id": "wamid.1", "from": "4477", "timestamp": "1773324300", "type": "text",
             "text": {"body": "Dentist Thursday 4pm"}},
            {"id": "wamid.2", "from": "4477", "timestamp": "1773324400", "type": "image",
             "image": {"caption": "the invite"}, "context": {"id": "wamid.1"}},
        ],
    }}]}],
}


class ExtractTests(unittest.TestCase):
    def test_flatten(self):
        msgs = inbox_server.extract_messages(PAYLOAD)
        self.assertEqual(len(msgs), 2)
        self.assertEqual(msgs[0]["sender"], "Alice")
        self.assertEqual(msgs[0]["chat_id"], "PHONE1:4477")
        self.assertEqual(msgs[0]["timestamp"], "2026-03-12T14:05:00+00:00")
        self.assertEqual(msgs[1]["text"], "the invite")
        self.assertEqual(msgs[1]["reply_to"], "wamid.1")
        self.assertEqual(msgs[1]["media_type"], "image")


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        inbox_server.DB_PATH = os.path.join(os.environ["WACAL_STATE_DIR"], "t.sqlite3")
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), inbox_server.Handler)
        cls.srv.conn = inbox_server.db()
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def _get(self, path, headers=None):
        req = urllib.request.Request(self.base + path, headers=headers or {})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()

    def _post(self, path, body: bytes, headers):
        req = urllib.request.Request(self.base + path, data=body, method="POST", headers=headers)
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()

    def test_verify_handshake(self):
        code, body = self._get("/webhook?hub.mode=subscribe&hub.verify_token=verify-me&hub.challenge=123")
        self.assertEqual((code, body), (200, "123"))
        code, _ = self._get("/webhook?hub.mode=subscribe&hub.verify_token=wrong&hub.challenge=123")
        self.assertEqual(code, 403)

    def test_post_requires_signature_then_serves_messages(self):
        raw = json.dumps(PAYLOAD).encode()
        code, _ = self._post("/webhook", raw, {"Content-Type": "application/json"})
        self.assertEqual(code, 401)

        sig = "sha256=" + hmac.new(b"app-secret", raw, hashlib.sha256).hexdigest()
        code, _ = self._post("/webhook", raw, {"Content-Type": "application/json", "X-Hub-Signature-256": sig})
        self.assertEqual(code, 200)
        # duplicate delivery is ignored
        code, _ = self._post("/webhook", raw, {"Content-Type": "application/json", "X-Hub-Signature-256": sig})
        self.assertEqual(code, 200)

        code, _ = self._get("/messages")
        self.assertEqual(code, 401)
        code, body = self._get("/messages", {"Authorization": "Bearer inbox-secret"})
        self.assertEqual(code, 200)
        msgs = json.loads(body)["messages"]
        self.assertEqual([m["id"] for m in msgs], ["wamid.1", "wamid.2"])

        code, body = self._get("/messages?since=2026-03-12T14:05:30%2B00:00", {"Authorization": "Bearer inbox-secret"})
        self.assertEqual([m["id"] for m in json.loads(body)["messages"]], ["wamid.2"])


if __name__ == "__main__":
    unittest.main()
