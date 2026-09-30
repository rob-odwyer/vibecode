import json
import os
import stat
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from wacal.sources import whatsmeow


class WhatsmeowSourceTests(unittest.TestCase):
    def setUp(self):
        # A fake wa-bridge that echoes its argv and returns two messages.
        self.tmp = Path(tempfile.mkdtemp())
        fake = self.tmp / "wa-bridge"
        fake.write_text(
            "#!/bin/sh\n"
            "echo \"$@\" > \"$(dirname \"$0\")/argv.txt\"\n"
            'printf \'%s\' \'{"messages": [{"id": "M1", "chat_id": "g@g.us", "sender": "Alice", '
            '"timestamp": "2026-09-28T13:05:00Z", "text": "hi", "reply_to": null, "media_type": null, "from_me": false}]}\'\n'
        )
        fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
        os.environ["WACAL_WA_BRIDGE_BIN"] = str(fake)
        os.environ["WACAL_WA_CHAT_ID"] = "g@g.us"

    def tearDown(self):
        os.environ.pop("WACAL_WA_BRIDGE_BIN", None)
        os.environ.pop("WACAL_WA_CHAT_ID", None)

    def test_passes_flags_and_parses(self):
        since = datetime(2026, 9, 27, tzinfo=timezone.utc)
        msgs = whatsmeow.fetch(since, 50)
        self.assertEqual([m["id"] for m in msgs], ["M1"])
        argv = (self.tmp / "argv.txt").read_text().split()
        self.assertEqual(argv[0], "fetch")
        self.assertIn("--since", argv)
        self.assertEqual(argv[argv.index("--since") + 1], "2026-09-27T00:00:00+00:00")
        self.assertEqual(argv[argv.index("--limit") + 1], "50")
        self.assertEqual(argv[argv.index("--chat") + 1], "g@g.us")

    def test_missing_binary_is_a_clear_error(self):
        os.environ["WACAL_WA_BRIDGE_BIN"] = str(self.tmp / "nope")
        with self.assertRaises(SystemExit) as cm:
            whatsmeow.fetch(None, 10)
        self.assertIn("go build", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
