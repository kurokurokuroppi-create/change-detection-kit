"""watchkit/state.py — JSON state store and incident lifecycle manager.

The state for each application is persisted in ``state/<app>.json``.
State schema (top-level keys):

.. code-block:: json

    {
      "sources": {
        "<source_name>": {
          "hash": "<last content hash>",
          "items": {
            "<item_id>": {"title": "...", "link": "...", "published": "...", "body": "..."}
          },
          "incidents": {
            "<item_id>": {
              "title": "...",
              "opened_at": "<ISO-8601>",
              "status": "open | resolved"
            }
          }
        }
      }
    }

Events are also appended as JSONL to ``state/<app>.events.jsonl`` so the
dashboard can render a history.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from watchkit.config import AppConfig

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Event data model
# ---------------------------------------------------------------------------

@dataclass
class Event:
    """A detected change event."""
    kind: str           # incident_opened | incident_updated | incident_resolved | page_changed
    source: str         # source name
    title: str          # human-readable title
    detail: str         # diff excerpt, body snippet, or resolution note
    occurred_at: str    # ISO-8601 UTC

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# State store
# ---------------------------------------------------------------------------

class StateStore:
    """Manages per-app state: source hashes, item cache, incident tracker.

    Usage::

        store = StateStore(app_config)
        store.load()
        # ... process events ...
        store.save()
    """

    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._state: dict[str, Any] = {"sources": {}}
        self._events_this_run: list[Event] = []

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def load(self) -> None:
        """Load state from disk. Creates an empty state if file is absent."""
        state_file = self._config.state_file
        if state_file.exists():
            try:
                with state_file.open(encoding="utf-8") as fh:
                    self._state = json.load(fh)
                logger.debug("State loaded from %s", state_file)
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Could not load state (%s); starting fresh.", exc)
                self._state = {"sources": {}}
        else:
            logger.debug("No state file at %s; starting fresh.", state_file)
            self._state = {"sources": {}}

    def save(self) -> None:
        """Persist current state and flush buffered events to the JSONL log."""
        state_file = self._config.state_file
        # Ensure the directory exists
        state_file.parent.mkdir(parents=True, exist_ok=True)
        with state_file.open("w", encoding="utf-8") as fh:
            json.dump(self._state, fh, ensure_ascii=False, indent=2)
        logger.debug("State saved to %s", state_file)
        self._flush_events()

    def _flush_events(self) -> None:
        """Append buffered events to the JSONL event log."""
        if not self._events_this_run:
            return
        log_file = self._config.event_log_file
        log_file.parent.mkdir(parents=True, exist_ok=True)
        with log_file.open("a", encoding="utf-8") as fh:
            for ev in self._events_this_run:
                fh.write(json.dumps(ev.to_dict(), ensure_ascii=False) + "\n")
        self._events_this_run.clear()

    # ------------------------------------------------------------------
    # Source-level accessors
    # ------------------------------------------------------------------

    def _source_state(self, source_name: str) -> dict[str, Any]:
        """Return (and create if absent) the state dict for *source_name*."""
        sources = self._state.setdefault("sources", {})
        if source_name not in sources:
            sources[source_name] = {"hash": None, "items": {}, "incidents": {}}
        return sources[source_name]

    def get_hash(self, source_name: str) -> str | None:
        """Return the stored hash for *source_name*, or None if unseen."""
        return self._source_state(source_name).get("hash")

    def set_hash(self, source_name: str, new_hash: str) -> None:
        """Update the stored hash for *source_name*."""
        self._source_state(source_name)["hash"] = new_hash

    def get_items(self, source_name: str) -> dict[str, Any]:
        """Return the stored item dict (item_id → item data) for *source_name*."""
        return self._source_state(source_name).get("items", {})

    def set_items(self, source_name: str, items: dict[str, Any]) -> None:
        """Replace the entire item dict for *source_name*."""
        self._source_state(source_name)["items"] = items

    # ------------------------------------------------------------------
    # Incident lifecycle
    # ------------------------------------------------------------------

    def get_incidents(self, source_name: str) -> dict[str, Any]:
        """Return the incidents dict for *source_name*."""
        return self._source_state(source_name).get("incidents", {})

    def open_incident(self, source_name: str, item_id: str, title: str) -> Event:
        """Open a new incident and emit an ``incident_opened`` event."""
        incidents = self._source_state(source_name).setdefault("incidents", {})
        now = _now_iso()
        incidents[item_id] = {
            "title": title,
            "opened_at": now,
            "status": "open",
        }
        event = Event(
            kind="incident_opened",
            source=source_name,
            title=title,
            detail=f"Incident opened at {now}",
            occurred_at=now,
        )
        self._buffer_event(event)
        logger.info("[%s] Incident opened: %s", source_name, title)
        return event

    def update_incident(self, source_name: str, item_id: str, title: str, detail: str) -> Event:
        """Record an update to an existing incident."""
        incidents = self._source_state(source_name).setdefault("incidents", {})
        now = _now_iso()
        if item_id in incidents:
            incidents[item_id]["title"] = title
        else:
            incidents[item_id] = {"title": title, "opened_at": now, "status": "open"}
        event = Event(
            kind="incident_updated",
            source=source_name,
            title=title,
            detail=detail,
            occurred_at=now,
        )
        self._buffer_event(event)
        logger.info("[%s] Incident updated: %s", source_name, title)
        return event

    def close_incident(self, source_name: str, item_id: str, title: str) -> Event:
        """Close an open incident and emit an ``incident_resolved`` event."""
        incidents = self._source_state(source_name).setdefault("incidents", {})
        now = _now_iso()
        if item_id in incidents:
            incidents[item_id]["status"] = "resolved"
        event = Event(
            kind="incident_resolved",
            source=source_name,
            title=title,
            detail=f"Incident resolved at {now}",
            occurred_at=now,
        )
        self._buffer_event(event)
        logger.info("[%s] Incident resolved: %s", source_name, title)
        return event

    def record_page_change(
        self, source_name: str, title: str, diff_text: str
    ) -> Event:
        """Emit a ``page_changed`` event for an HTML source."""
        now = _now_iso()
        event = Event(
            kind="page_changed",
            source=source_name,
            title=title,
            detail=diff_text[:2000],  # cap stored detail size
            occurred_at=now,
        )
        self._buffer_event(event)
        logger.info("[%s] Page changed: %s", source_name, title)
        return event

    def _buffer_event(self, event: Event) -> None:
        self._events_this_run.append(event)

    # ------------------------------------------------------------------
    # Event log reader (for dashboard)
    # ------------------------------------------------------------------

    def read_event_log(self) -> list[dict[str, Any]]:
        """Read all events from the JSONL log file (newest last)."""
        log_file = self._config.event_log_file
        if not log_file.exists():
            return []
        events = []
        with log_file.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        events.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
        return events

    # ------------------------------------------------------------------
    # Convenience: full raw state access (for dashboard)
    # ------------------------------------------------------------------

    @property
    def raw_state(self) -> dict[str, Any]:
        return self._state


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    """Return current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
