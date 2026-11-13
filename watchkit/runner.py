"""watchkit/runner.py — Poll-once and scheduler-loop pipeline.

This module implements the core poll pipeline:

    fetch → normalize → hash/diff vs state → events → summarize → notify → persist

:func:`poll_app_once` runs all sources of an application once and returns.
:func:`serve_app`     runs in an infinite scheduler loop, honouring per-source
                      interval_minutes settings.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Sequence

from watchkit.config import AppConfig, SourceConfig
from watchkit.diff import content_hash, diff_excerpt, has_changed, item_hash
from watchkit.fetchers import Document, Item, fetch_source
from watchkit.notify import send_notification
from watchkit.state import Event, StateStore
from watchkit.summarize import get_summarizer

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Resolution keywords for incident tracking (status feeds)
# ---------------------------------------------------------------------------
_RESOLUTION_KEYWORDS = (
    "resolved", "recovered", "fixed", "closed", "postmortem",
    "解決", "復旧", "正常", "回復",
)

def _looks_like_resolution(title: str, body: str) -> bool:
    """Return True when the item text suggests an incident resolution."""
    text = (title + " " + body).lower()
    return any(kw in text for kw in _RESOLUTION_KEYWORDS)


# ---------------------------------------------------------------------------
# Per-source processing
# ---------------------------------------------------------------------------

def _process_rss_source(
    source: SourceConfig,
    store: StateStore,
    items: list[Item],
) -> list[Event]:
    """Detect incident lifecycle changes in an RSS/Atom feed."""
    events: list[Event] = []

    # Compute an aggregate hash over all item IDs (order-stable set)
    item_ids = sorted(item.id for item in items)
    agg_hash = content_hash(" ".join(item_ids), source.volatile_tokens)

    stored_hash = store.get_hash(source.name)
    if not has_changed(agg_hash, stored_hash):
        logger.debug("[%s] No change (hash %s).", source.name, agg_hash)
        store.set_hash(source.name, agg_hash)  # always seed on first run
        return events

    # Build new item map
    new_items: dict[str, dict] = {
        item.id: {"title": item.title, "link": item.link,
                  "published": item.published, "body": item.body}
        for item in items
    }
    old_items = store.get_items(source.name)
    old_incidents = store.get_incidents(source.name)

    # Detect new items (potential incident opens)
    for item_id, item_data in new_items.items():
        if item_id not in old_items:
            title = item_data["title"]
            body  = item_data["body"]
            if _looks_like_resolution(title, body):
                # New resolution-looking item closes a matching incident if open
                # Try to find a matching open incident by title similarity
                matched_id = _find_matching_open_incident(
                    title, old_incidents
                )
                if matched_id:
                    events.append(
                        store.close_incident(source.name, matched_id, title)
                    )
                else:
                    # No matching open incident; open and immediately close
                    events.append(store.open_incident(source.name, item_id, title))
                    events.append(store.close_incident(source.name, item_id, title))
            else:
                events.append(store.open_incident(source.name, item_id, title))

    # Detect items that disappeared (implicit resolution)
    for item_id in old_items:
        if item_id not in new_items:
            # Item gone — close if there was an open incident for it
            if item_id in old_incidents and old_incidents[item_id]["status"] == "open":
                title = old_incidents[item_id]["title"]
                events.append(store.close_incident(source.name, item_id, title))

    # Detect content changes in existing items
    for item_id, item_data in new_items.items():
        if item_id in old_items:
            new_h = item_hash(item_data["title"], item_data["body"],
                              source.volatile_tokens)
            old_h = item_hash(
                old_items[item_id]["title"], old_items[item_id]["body"],
                source.volatile_tokens,
            )
            if new_h != old_h:
                events.append(
                    store.update_incident(
                        source.name, item_id,
                        item_data["title"],
                        item_data["body"][:200],
                    )
                )

    store.set_items(source.name, new_items)
    store.set_hash(source.name, agg_hash)
    return events


def _find_matching_open_incident(
    resolution_title: str,
    incidents: dict[str, dict],
) -> str | None:
    """Find an open incident whose title is a rough substring match."""
    resolution_lower = resolution_title.lower()
    for inc_id, inc in incidents.items():
        if inc.get("status") == "open":
            inc_lower = inc["title"].lower()
            # Simple heuristic: share at least 5 characters in common
            if _common_words(resolution_lower, inc_lower):
                return inc_id
    return None


def _common_words(a: str, b: str) -> bool:
    words_a = set(a.split())
    words_b = set(b.split())
    # Exclude very short stop words
    meaningful = {w for w in words_a & words_b if len(w) > 3}
    return bool(meaningful)


def _process_json_source(
    source: SourceConfig,
    store: StateStore,
    items: list[Item],
) -> list[Event]:
    """JSON sources are treated the same as RSS (incident lifecycle)."""
    return _process_rss_source(source, store, items)


def _process_html_source(
    source: SourceConfig,
    store: StateStore,
    doc: Document,
) -> list[Event]:
    """Detect page-level content changes for an HTML source."""
    events: list[Event] = []

    new_hash = content_hash(doc.text, source.volatile_tokens)
    stored_hash = store.get_hash(source.name)

    if not has_changed(new_hash, stored_hash):
        logger.debug("[%s] No change (hash %s).", source.name, new_hash)
        store.set_hash(source.name, new_hash)  # seed on first run
        return events

    # Reconstruct the previous text from items store (we store raw text there)
    old_text = store.get_items(source.name).get("__text__", "")
    diff = diff_excerpt(old_text, doc.text)

    events.append(
        store.record_page_change(
            source.name,
            title=f"{source.name} ページが更新されました",
            diff_text=diff or "（差分の取得ができませんでした）",
        )
    )

    # Persist the new text for future diffing
    store.set_items(source.name, {"__text__": doc.text})
    store.set_hash(source.name, new_hash)
    return events


# ---------------------------------------------------------------------------
# Poll pipeline — single source
# ---------------------------------------------------------------------------

def _poll_source(
    source: SourceConfig,
    store: StateStore,
) -> list[Event]:
    """Fetch *source*, diff against stored state, return new :class:`Event` list."""
    logger.info("Polling source: %s (%s)", source.name, source.type)
    try:
        result = fetch_source(source)
    except Exception as exc:
        logger.error("[%s] Fetch failed: %s", source.name, exc)
        return []

    if isinstance(result, Document):
        return _process_html_source(source, store, result)
    else:
        # list[Item] — RSS or JSON
        if source.type == "json":
            return _process_json_source(source, store, result)
        else:
            return _process_rss_source(source, store, result)


# ---------------------------------------------------------------------------
# Poll pipeline — full app, one shot
# ---------------------------------------------------------------------------

def poll_app_once(config: AppConfig) -> int:
    """Poll all sources for *config* once and dispatch notifications.

    Returns the number of events detected.
    """
    # Ensure state directory exists
    config.state_path.mkdir(parents=True, exist_ok=True)

    store = StateStore(config)
    store.load()

    summarizer = get_summarizer()
    total_events = 0

    for source in config.sources:
        events = _poll_source(source, store)
        for event in events:
            total_events += 1
            try:
                summary = summarizer.summarize(event)
            except Exception as exc:
                logger.error("Summarizer failed for event %s: %s", event.kind, exc)
                summary = f"{event.title}\n影響範囲不明\n公式情報を確認してください。"
            send_notification(event, summary, config.notify)

    store.save()
    logger.info(
        "Poll complete for '%s': %d event(s) across %d source(s).",
        config.app, total_events, len(config.sources),
    )
    return total_events


# ---------------------------------------------------------------------------
# Scheduler loop
# ---------------------------------------------------------------------------

def serve_app(config: AppConfig) -> None:
    """Run the poll loop indefinitely, honouring per-source intervals.

    Each source tracks its own next-poll time.  The loop sleeps for 10 seconds
    between checks so it is not a busy-wait.

    Press Ctrl-C to stop.
    """
    logger.info("Starting scheduler for app '%s'.", config.app)

    # Initialise next-poll timestamps: poll everything immediately on start
    next_poll: dict[str, float] = {src.name: 0.0 for src in config.sources}

    # Ensure state directory exists
    config.state_path.mkdir(parents=True, exist_ok=True)

    summarizer = get_summarizer()

    try:
        while True:
            now = time.monotonic()

            # Collect sources due for polling
            due = [src for src in config.sources if now >= next_poll[src.name]]

            if due:
                store = StateStore(config)
                store.load()

                for source in due:
                    events = _poll_source(source, store)
                    for event in events:
                        try:
                            summary = summarizer.summarize(event)
                        except Exception as exc:
                            logger.error(
                                "Summarizer failed for %s: %s", event.kind, exc
                            )
                            summary = (
                                f"{event.title}\n影響範囲不明\n公式情報を確認してください。"
                            )
                        send_notification(event, summary, config.notify)
                    # Schedule next poll for this source
                    next_poll[source.name] = now + source.interval_minutes * 60

                store.save()

            time.sleep(10)  # check every 10 seconds

    except KeyboardInterrupt:
        logger.info("Scheduler stopped by user.")
