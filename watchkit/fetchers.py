"""watchkit/fetchers.py — Source adapters.

Three adapter types are provided, all returning a common result type:

* ``RSSFetcher``  — parses RSS 2.0 / Atom feeds → list[Item]
* ``JSONFetcher`` — fetches a JSON document, extracts items via field map → list[Item]
* ``HTMLFetcher`` — fetches an HTML page, strips tags → Document

The public entry point is :func:`fetch_source`, which dispatches to the
correct adapter based on ``SourceConfig.type``.
"""

from __future__ import annotations

import html as _html_mod
import html.parser
import json
import logging
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any

from watchkit.config import SourceConfig

logger = logging.getLogger(__name__)

# HTTP timeout (seconds) as required by the design doc
HTTP_TIMEOUT = 20
USER_AGENT = "watchkit/0.1 (+https://github.com/change-detection-kit)"


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class Item:
    """A single feed item (RSS entry, JSON record, etc.)."""
    id: str           # stable content-based ID (hash of link+title)
    title: str
    link: str
    published: str    # ISO-8601 string or empty
    body: str         # summary / description text


@dataclass
class Document:
    """A single fetched HTML page, normalised to plain text."""
    source_name: str
    text: str         # stripped plain text


# ---------------------------------------------------------------------------
# Shared HTTP helper
# ---------------------------------------------------------------------------

def _http_get(url: str) -> bytes:
    """Fetch *url* and return raw bytes; raises on HTTP errors."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
        return resp.read()


# ---------------------------------------------------------------------------
# RSS / Atom fetcher
# ---------------------------------------------------------------------------

# Atom namespace prefix
_ATOM_NS = "http://www.w3.org/2005/Atom"

def _rss_text(elem: ET.Element, tag: str) -> str:
    """Return stripped text of *tag* child of *elem*, or ''."""
    child = elem.find(tag)
    return (child.text or "").strip() if child is not None else ""


def _atom_text(elem: ET.Element, tag: str) -> str:
    """Return stripped text of Atom-namespaced *tag* child, or ''."""
    child = elem.find(f"{{{_ATOM_NS}}}{tag}")
    return (child.text or "").strip() if child is not None else ""


def _make_item_id(link: str, title: str) -> str:
    """Stable 12-hex-char ID derived from link + title."""
    import hashlib
    return hashlib.sha256(f"{link}|{title}".encode()).hexdigest()[:12]


class _TextStripper(html.parser.HTMLParser):
    """Minimal HTML-to-text converter for feed summaries."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    def get_text(self) -> str:
        return " ".join(self._parts).strip()


def _strip_html(text: str) -> str:
    """Strip HTML tags from *text*."""
    if "<" not in text:
        return text
    parser = _TextStripper()
    parser.feed(text)
    return parser.get_text()


def fetch_rss(source: SourceConfig) -> list[Item]:
    """Fetch and parse an RSS 2.0 or Atom feed.

    Returns a list of :class:`Item`, newest-first order preserved from feed.
    """
    raw = _http_get(source.url)
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise ValueError(f"RSS/Atom parse error for {source.url}: {exc}") from exc

    # Detect feed format
    tag = root.tag
    items: list[Item] = []

    if tag == "rss" or tag.endswith("}rss"):
        # RSS 2.0
        channel = root.find("channel")
        if channel is None:
            return []
        for entry in channel.findall("item"):
            title = _rss_text(entry, "title")
            link  = _rss_text(entry, "link")
            pub   = _rss_text(entry, "pubDate")
            body  = _strip_html(_rss_text(entry, "description"))
            # Prefer guid as stable identifier
            guid  = _rss_text(entry, "guid") or link
            item_id = _make_item_id(guid, title)
            items.append(Item(id=item_id, title=title, link=link,
                               published=pub, body=body))
    elif tag == f"{{{_ATOM_NS}}}feed" or "feed" in tag:
        # Atom
        for entry in root.findall(f"{{{_ATOM_NS}}}entry"):
            title = _atom_text(entry, "title")
            # Atom link is in an attribute
            link_elem = entry.find(f"{{{_ATOM_NS}}}link")
            link = (link_elem.get("href") or "") if link_elem is not None else ""
            pub  = _atom_text(entry, "updated") or _atom_text(entry, "published")
            # summary or content
            body_elem = entry.find(f"{{{_ATOM_NS}}}summary") or \
                        entry.find(f"{{{_ATOM_NS}}}content")
            body = _strip_html((body_elem.text or "").strip()) if body_elem is not None else ""
            atom_id = _atom_text(entry, "id") or link
            item_id = _make_item_id(atom_id, title)
            items.append(Item(id=item_id, title=title, link=link,
                               published=pub, body=body))
    else:
        logger.warning("Unknown feed format for %s (root tag: %s)", source.url, tag)

    return items


# ---------------------------------------------------------------------------
# JSON fetcher
# ---------------------------------------------------------------------------

def fetch_json(source: SourceConfig) -> list[Item]:
    """Fetch a JSON document and extract items via the field mapping.

    The field mapping is configured in ``source.options``:
    - ``items_field``: JSON key whose value is the array of items.
    - ``id_field``, ``title_field``, ``body_field``, ``link_field``,
      ``published_field``: per-item field names.
    """
    raw = _http_get(source.url)
    try:
        data: Any = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON parse error for {source.url}: {exc}") from exc

    # Navigate to the items array; supports dot-path e.g. "data.incidents"
    items_field = source.items_field
    obj: Any = data
    for part in items_field.split("."):
        if isinstance(obj, dict):
            obj = obj.get(part, [])
        else:
            obj = []
            break

    if not isinstance(obj, list):
        logger.warning(
            "JSON source %s: items_field '%s' did not resolve to a list",
            source.name, items_field,
        )
        return []

    result: list[Item] = []
    for record in obj:
        if not isinstance(record, dict):
            continue
        raw_id    = str(record.get(source.id_field, ""))
        title     = str(record.get(source.title_field, ""))
        link      = str(record.get(source.link_field, ""))
        pub       = str(record.get(source.published_field, ""))
        body      = str(record.get(source.body_field, ""))
        item_id   = _make_item_id(raw_id or link, title) if raw_id else \
                    _make_item_id(link, title)
        result.append(Item(id=item_id, title=title, link=link,
                            published=pub, body=body))
    return result


# ---------------------------------------------------------------------------
# HTML fetcher
# ---------------------------------------------------------------------------

class _SelectorExtractor(html.parser.HTMLParser):
    """Extract text from the first element matching a simple CSS selector.

    Supports element selectors (``main``, ``article``) and ID/class
    selectors (``#content``, ``.body``).  For anything more complex the
    whole body is returned.
    """

    def __init__(self, selector: str | None) -> None:
        super().__init__(convert_charrefs=True)
        self._selector = selector
        self._target_tag: str | None = None
        self._target_id: str | None = None
        self._target_class: str | None = None
        self._capturing = False
        self._depth = 0            # nesting depth inside the target element
        self._parts: list[str] = []
        self._found = False
        self._all_parts: list[str] = []  # fallback: all text

        if selector:
            self._parse_selector(selector)
        else:
            self._capturing = True  # capture everything

    def _parse_selector(self, sel: str) -> None:
        sel = sel.strip()
        if sel.startswith("#"):
            self._target_id = sel[1:]
        elif sel.startswith("."):
            self._target_class = sel[1:]
        else:
            # Simple element name (e.g. "main", "article", "section")
            self._target_tag = sel.lower()

    def _matches(self, tag: str, attrs: dict[str, str]) -> bool:
        if self._target_tag and tag == self._target_tag:
            return True
        if self._target_id and attrs.get("id") == self._target_id:
            return True
        if self._target_class:
            classes = attrs.get("class", "").split()
            if self._target_class in classes:
                return True
        return False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_dict = {k: (v or "") for k, v in attrs}
        if not self._found and self._selector and self._matches(tag, attr_dict):
            self._capturing = True
            self._found = True
            self._depth = 1
        elif self._capturing and self._selector:
            self._depth += 1

    def handle_endtag(self, tag: str) -> None:
        if self._capturing and self._selector:
            self._depth -= 1
            if self._depth <= 0:
                self._capturing = False

    def handle_data(self, data: str) -> None:
        self._all_parts.append(data)
        if self._capturing:
            self._parts.append(data)

    def get_text(self) -> str:
        parts = self._parts if (self._found or not self._selector) else self._all_parts
        # Collapse whitespace and blank lines
        lines = []
        for chunk in parts:
            for line in chunk.splitlines():
                stripped = line.strip()
                if stripped:
                    lines.append(stripped)
        return "\n".join(lines)


def fetch_html(source: SourceConfig) -> Document:
    """Fetch an HTML page and return its main text as a :class:`Document`.

    If ``source.selector`` is set, only text inside the first matching
    element is extracted; otherwise the entire body text is used.
    """
    raw = _http_get(source.url)
    # Decode: try UTF-8, fall back to latin-1 (safe for all byte values)
    try:
        text_raw = raw.decode("utf-8")
    except UnicodeDecodeError:
        text_raw = raw.decode("latin-1")

    extractor = _SelectorExtractor(source.selector)
    extractor.feed(text_raw)
    text = extractor.get_text()
    return Document(source_name=source.name, text=text)


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

FetchResult = list[Item] | Document


def fetch_source(source: SourceConfig) -> FetchResult:
    """Fetch *source* and return items or a document depending on type.

    Raises:
        ValueError: On unsupported source type.
        urllib.error.URLError: On network errors (caller should handle).
    """
    if source.type == "rss":
        return fetch_rss(source)
    elif source.type == "json":
        return fetch_json(source)
    elif source.type == "html":
        return fetch_html(source)
    else:
        raise ValueError(f"Unknown source type: {source.type!r}")
