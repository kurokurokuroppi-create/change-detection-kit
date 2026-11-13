"""tests/test_state.py — Unit tests for watchkit.state."""

import json
import tempfile
import unittest
from pathlib import Path

from watchkit.config import AppConfig, NotifyConfig
from watchkit.state import Event, StateStore, _now_iso


def _make_config(state_dir: str) -> AppConfig:
    """Helper to create a minimal AppConfig pointing at a temp directory."""
    return AppConfig(
        app="test-app",
        state_dir=state_dir,
        sources=[],
        notify=[NotifyConfig(type="log")],
    )


class TestStateStoreBasics(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.config = _make_config(self.tmpdir.name)
        self.store = StateStore(self.config)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_load_missing_file_gives_empty_state(self):
        self.store.load()
        self.assertEqual(self.store.raw_state, {"sources": {}})

    def test_save_and_reload(self):
        self.store.load()
        self.store.set_hash("src-a", "abc123")
        self.store.save()

        store2 = StateStore(self.config)
        store2.load()
        self.assertEqual(store2.get_hash("src-a"), "abc123")

    def test_get_hash_before_set_returns_none(self):
        self.store.load()
        self.assertIsNone(self.store.get_hash("nonexistent"))

    def test_set_and_get_hash(self):
        self.store.load()
        self.store.set_hash("my-source", "deadbeef")
        self.assertEqual(self.store.get_hash("my-source"), "deadbeef")

    def test_set_and_get_items(self):
        self.store.load()
        items = {"item1": {"title": "T", "body": "B", "link": "", "published": ""}}
        self.store.set_items("my-source", items)
        self.assertEqual(self.store.get_items("my-source"), items)

    def test_initial_items_is_empty_dict(self):
        self.store.load()
        self.assertEqual(self.store.get_items("new-source"), {})


class TestIncidentLifecycle(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.config = _make_config(self.tmpdir.name)
        self.store = StateStore(self.config)
        self.store.load()

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_open_incident_returns_event(self):
        event = self.store.open_incident("src", "item1", "Service outage")
        self.assertEqual(event.kind, "incident_opened")
        self.assertEqual(event.source, "src")
        self.assertEqual(event.title, "Service outage")

    def test_open_incident_persisted(self):
        self.store.open_incident("src", "item1", "DB failure")
        incidents = self.store.get_incidents("src")
        self.assertIn("item1", incidents)
        self.assertEqual(incidents["item1"]["status"], "open")
        self.assertEqual(incidents["item1"]["title"], "DB failure")

    def test_close_incident_returns_resolved_event(self):
        self.store.open_incident("src", "item1", "Network issue")
        event = self.store.close_incident("src", "item1", "Network issue resolved")
        self.assertEqual(event.kind, "incident_resolved")

    def test_close_incident_updates_status(self):
        self.store.open_incident("src", "item1", "Outage")
        self.store.close_incident("src", "item1", "Outage resolved")
        incidents = self.store.get_incidents("src")
        self.assertEqual(incidents["item1"]["status"], "resolved")

    def test_update_incident_returns_updated_event(self):
        self.store.open_incident("src", "item1", "Outage")
        event = self.store.update_incident("src", "item1", "Outage (ongoing)", "details")
        self.assertEqual(event.kind, "incident_updated")
        self.assertEqual(event.title, "Outage (ongoing)")

    def test_multiple_incidents_independent(self):
        self.store.open_incident("src", "i1", "Incident A")
        self.store.open_incident("src", "i2", "Incident B")
        self.store.close_incident("src", "i1", "Incident A resolved")
        incidents = self.store.get_incidents("src")
        self.assertEqual(incidents["i1"]["status"], "resolved")
        self.assertEqual(incidents["i2"]["status"], "open")


class TestPageChangeEvent(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.config = _make_config(self.tmpdir.name)
        self.store = StateStore(self.config)
        self.store.load()

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_record_page_change_event_kind(self):
        event = self.store.record_page_change("html-src", "Page updated", "diff text here")
        self.assertEqual(event.kind, "page_changed")
        self.assertEqual(event.source, "html-src")

    def test_record_page_change_detail_capped(self):
        long_detail = "x" * 5000
        event = self.store.record_page_change("html-src", "Title", long_detail)
        self.assertLessEqual(len(event.detail), 2001)  # 2000 + possible trailing


class TestEventLog(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.config = _make_config(self.tmpdir.name)
        self.store = StateStore(self.config)
        self.store.load()

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_events_persisted_to_jsonl(self):
        self.store.open_incident("src", "i1", "Test incident")
        self.store.save()

        # Read back raw JSONL
        log_file = self.config.event_log_file
        self.assertTrue(log_file.exists())
        lines = log_file.read_text().strip().splitlines()
        self.assertEqual(len(lines), 1)
        entry = json.loads(lines[0])
        self.assertEqual(entry["kind"], "incident_opened")

    def test_read_event_log_returns_list(self):
        self.store.open_incident("src", "i1", "Incident")
        self.store.close_incident("src", "i1", "Resolved")
        self.store.save()

        events = self.store.read_event_log()
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["kind"], "incident_opened")
        self.assertEqual(events[1]["kind"], "incident_resolved")

    def test_read_event_log_empty_when_no_file(self):
        events = self.store.read_event_log()
        self.assertEqual(events, [])

    def test_multiple_saves_append_events(self):
        self.store.open_incident("src", "i1", "First incident")
        self.store.save()

        store2 = StateStore(self.config)
        store2.load()
        store2.close_incident("src", "i1", "First resolved")
        store2.save()

        events = self.store.read_event_log()
        self.assertEqual(len(events), 2)


class TestEventDataclass(unittest.TestCase):
    def test_event_to_dict(self):
        event = Event(
            kind="page_changed",
            source="my-src",
            title="Something changed",
            detail="diff here",
            occurred_at="2026-11-14T00:00:00+00:00",
        )
        d = event.to_dict()
        self.assertEqual(d["kind"], "page_changed")
        self.assertEqual(d["source"], "my-src")
        self.assertIn("occurred_at", d)

    def test_now_iso_format(self):
        ts = _now_iso()
        # Should parse without error
        from datetime import datetime
        dt = datetime.fromisoformat(ts)
        self.assertIsNotNone(dt)


if __name__ == "__main__":
    unittest.main()
