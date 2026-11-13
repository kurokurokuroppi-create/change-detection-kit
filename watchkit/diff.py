"""watchkit/diff.py — Content hashing, noise filtering, and diff excerpts.

Responsibilities:
* Normalise text to strip noise (extra whitespace, HTML tags, volatile tokens).
* Compute a stable SHA-256 content hash for feed items and HTML documents.
* Produce a short unified-diff excerpt (≤40 lines) when an HTML page changes.
"""

from __future__ import annotations

import difflib
import hashlib
import html.parser
import re


# ---------------------------------------------------------------------------
# Text normalisation / noise filtering
# ---------------------------------------------------------------------------

class _TagStripper(html.parser.HTMLParser):
    """Minimal HTML tag stripper that respects convert_charrefs."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    def result(self) -> str:
        return " ".join(self._parts)


def strip_tags(text: str) -> str:
    """Remove HTML tags from *text*. Returns plain text."""
    if "<" not in text:
        return text
    parser = _TagStripper()
    parser.feed(text)
    return parser.result()


def normalise(text: str, volatile_tokens: list[str] | None = None) -> str:
    """Normalise *text* for change detection.

    Steps applied in order:
    1. Strip HTML tags.
    2. Strip volatile tokens (e.g. timestamps, session IDs) supplied by config.
    3. Replace runs of whitespace (including newlines) with a single space.
    4. Strip leading/trailing whitespace.

    Whitespace collapsing is intentionally performed *after* token removal so
    that removing a token that sits between spaces does not leave double spaces
    that would prevent two otherwise-identical texts from matching.
    """
    text = strip_tags(text)
    # Remove configured volatile tokens before whitespace collapsing
    if volatile_tokens:
        for token in volatile_tokens:
            text = text.replace(token, "")
    # Collapse all whitespace runs → single space
    text = re.sub(r"\s+", " ", text)
    return text.strip()


# ---------------------------------------------------------------------------
# Content hashing
# ---------------------------------------------------------------------------

def content_hash(text: str, volatile_tokens: list[str] | None = None) -> str:
    """Return a 16-hex-char SHA-256 digest of the normalised *text*.

    Args:
        text: Raw source text (may contain HTML).
        volatile_tokens: Tokens to strip before hashing (noise filter).

    Returns:
        A lowercase 16-character hex string.
    """
    normalised = normalise(text, volatile_tokens)
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()[:16]


def item_hash(title: str, body: str, volatile_tokens: list[str] | None = None) -> str:
    """Hash a feed item from its title and body combined."""
    combined = f"{title}\n{body}"
    return content_hash(combined, volatile_tokens)


# ---------------------------------------------------------------------------
# Diff excerpt for HTML document changes
# ---------------------------------------------------------------------------

def diff_excerpt(old_text: str, new_text: str, max_lines: int = 40) -> str:
    """Produce a short unified-diff excerpt comparing *old_text* and *new_text*.

    Both texts are normalised before diffing so whitespace churn is ignored.
    The result is capped at *max_lines* lines (default 40).

    Returns:
        A string containing the diff excerpt, or an empty string if the
        normalised texts are identical.
    """
    # Split into lines for line-by-line diff
    old_lines = normalise(old_text).splitlines(keepends=True)
    new_lines = normalise(new_text).splitlines(keepends=True)

    if old_lines == new_lines:
        return ""

    # Use difflib unified diff; context=3 is the standard
    diff_lines = list(
        difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile="previous",
            tofile="current",
            lineterm="",
            n=3,
        )
    )

    # Cap at max_lines
    if len(diff_lines) > max_lines:
        diff_lines = diff_lines[:max_lines]
        diff_lines.append(f"... (truncated at {max_lines} lines)")

    return "\n".join(diff_lines)


# ---------------------------------------------------------------------------
# Change detection helpers
# ---------------------------------------------------------------------------

def has_changed(new_hash: str, stored_hash: str | None) -> bool:
    """Return True when *new_hash* differs from *stored_hash*.

    ``stored_hash=None`` means the source has never been seen before;
    we treat the first observation as *not* a change (no event fired)
    so users are not spammed on first run.
    """
    if stored_hash is None:
        return False          # first observation — seed the state silently
    return new_hash != stored_hash
