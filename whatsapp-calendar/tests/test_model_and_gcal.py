import unittest

from wacal.model import EventValidationError, validate_event, event_source_key
from wacal import gcal


class ValidateEventTests(unittest.TestCase):
    def test_timed_event_defaults(self):
        ev = validate_event({"title": "Dentist", "start": "2026-03-19T16:00:00+00:00",
                             "source_message_ids": ["m2", "m1"], "chat_id": "fam"})
        self.assertFalse(ev["all_day"])
        self.assertIsNone(ev["end"])
        self.assertEqual(ev["source_message_ids"], ["m1", "m2"])
        self.assertEqual(ev["confidence"], 1.0)
        self.assertTrue(ev["source_key"].startswith("wa_"))

    def test_all_day_detection(self):
        ev = validate_event({"title": "Rent due", "start": "2026-04-01", "source_message_ids": ["m1"]})
        self.assertTrue(ev["all_day"])

    def test_rejects_naive_datetime(self):
        with self.assertRaises(EventValidationError):
            validate_event({"title": "x", "start": "2026-03-19T16:00:00", "source_message_ids": ["m1"]})

    def test_rejects_missing_sources(self):
        with self.assertRaises(EventValidationError):
            validate_event({"title": "x", "start": "2026-03-19", "source_message_ids": []})

    def test_key_is_stable_and_title_normalised(self):
        a = {"title": "Dentist - Sam!", "chat_id": "fam", "source_message_ids": ["m1", "m2"]}
        b = {"title": "dentist   sam", "chat_id": "fam", "source_message_ids": ["m2", "m1"]}
        self.assertEqual(event_source_key(a), event_source_key(b))

    def test_key_changes_with_chat_or_message(self):
        base = {"title": "Dentist", "chat_id": "fam", "source_message_ids": ["m1"]}
        other_chat = {**base, "chat_id": "work"}
        other_msg = {**base, "source_message_ids": ["m9"]}
        self.assertNotEqual(event_source_key(base), event_source_key(other_chat))
        self.assertNotEqual(event_source_key(base), event_source_key(other_msg))

    def test_explicit_source_key_kept(self):
        ev = validate_event({"title": "x", "start": "2026-03-19", "source_message_ids": ["m1"],
                             "source_key": "wa_custom"})
        self.assertEqual(ev["source_key"], "wa_custom")


class EventBodyTests(unittest.TestCase):
    def test_all_day_end_is_exclusive(self):
        ev = validate_event({"title": "Trip", "start": "2026-04-20", "end": "2026-04-22",
                             "source_message_ids": ["m1"], "location": "Dublin"})
        body = gcal.event_body(ev, "Europe/London")
        self.assertEqual(body["start"], {"date": "2026-04-20"})
        self.assertEqual(body["end"], {"date": "2026-04-23"})
        self.assertEqual(body["location"], "Dublin")
        self.assertEqual(body["extendedProperties"]["private"][gcal.KEY_PROP], ev["source_key"])

    def test_timed_default_end_one_hour(self):
        ev = validate_event({"title": "Ferry", "start": "2026-04-20T08:30:00+01:00",
                             "source_message_ids": ["m1"], "confidence": 0.85})
        body = gcal.event_body(ev, "Europe/London")
        self.assertEqual(body["start"]["dateTime"], "2026-04-20T08:30:00+01:00")
        self.assertEqual(body["end"]["dateTime"], "2026-04-20T09:30:00+01:00")
        self.assertEqual(body["extendedProperties"]["private"]["wacal_confidence"], "0.85")
        self.assertIn("m1", body["description"])


if __name__ == "__main__":
    unittest.main()
