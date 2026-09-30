import unittest
from zoneinfo import ZoneInfo

from wacal.sources.export import parse_export

TZ = ZoneInfo("Europe/London")

ANDROID_DMY = """\
12/03/2026, 14:05 - Messages and calls are end-to-end encrypted.
12/03/2026, 14:05 - Alice: Dentist for Sam is on Thursday 19th at 4pm
12/03/2026, 14:07 - Bob: 👍
12/03/2026, 14:09 - Alice: Also don't forget
Rent is due on the 1st
every month
13/03/2026, 09:00 - Bob: Booked the ferry for 20 April, 08:30 from Holyhead
"""

IOS_BRACKET = """\
[12/03/2026, 14:05:33] Alice: hello
[12/03/2026, 14:06:01] Bob: hi
"""

US_MDY = """\
3/12/26, 2:05 PM - Alice: hello
3/12/26, 12:10 AM - Bob: midnight-ish
"""


class ExportParserTests(unittest.TestCase):
    def test_android_dmy_with_continuation(self):
        msgs = parse_export(ANDROID_DMY, chat_id="fam", tz=TZ)
        self.assertEqual([m["sender"] for m in msgs], ["Alice", "Bob", "Alice", "Bob"])
        self.assertEqual(msgs[0]["timestamp"], "2026-03-12T14:05:00+00:00")
        self.assertIn("Rent is due on the 1st\nevery month", msgs[2]["text"])
        self.assertEqual(msgs[3]["timestamp"], "2026-03-13T09:00:00+00:00")
        self.assertTrue(all(m["id"].startswith("exp_") for m in msgs))
        self.assertEqual(len({m["id"] for m in msgs}), 4)

    def test_system_lines_are_ignored(self):
        msgs = parse_export(ANDROID_DMY, chat_id="fam", tz=TZ)
        self.assertNotIn("end-to-end", " ".join(m["text"] for m in msgs))

    def test_ios_bracket_format_with_seconds(self):
        msgs = parse_export(IOS_BRACKET, chat_id="c", tz=TZ)
        self.assertEqual(len(msgs), 2)
        self.assertEqual(msgs[0]["timestamp"], "2026-03-12T14:05:33+00:00")

    def test_us_mdy_12h(self):
        msgs = parse_export(US_MDY, chat_id="c", tz=TZ, date_order="MDY")
        self.assertEqual(msgs[0]["timestamp"], "2026-03-12T14:05:00+00:00")
        self.assertEqual(msgs[1]["timestamp"], "2026-03-12T00:10:00+00:00")

    def test_ids_are_stable_across_parses(self):
        a = parse_export(ANDROID_DMY, chat_id="fam", tz=TZ)
        b = parse_export(ANDROID_DMY, chat_id="fam", tz=TZ)
        self.assertEqual([m["id"] for m in a], [m["id"] for m in b])

    def test_dst_offset_applied(self):
        msgs = parse_export("20/06/2026, 10:00 - A: summer", chat_id="c", tz=TZ)
        self.assertEqual(msgs[0]["timestamp"], "2026-06-20T10:00:00+01:00")


if __name__ == "__main__":
    unittest.main()
