"""watchkit/config.py — App configuration loading and validation.

Each application is described by a single JSON file under apps/.
This module loads the file, validates its structure, and returns
typed dataclasses so the rest of the engine never touches raw dicts.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class SourceConfig:
    """Configuration for a single watched source."""
    name: str
    type: str                       # "rss" | "json" | "html"
    url: str
    interval_minutes: int = 15
    options: dict[str, Any] = field(default_factory=dict)

    # Convenience: volatile tokens to strip before hashing (noise filter)
    @property
    def volatile_tokens(self) -> list[str]:
        return self.options.get("volatile_tokens", [])

    # CSS selector for html sources
    @property
    def selector(self) -> str | None:
        return self.options.get("selector")

    # JSON source field mappings
    @property
    def items_field(self) -> str:
        return self.options.get("items_field", "items")

    @property
    def id_field(self) -> str:
        return self.options.get("id_field", "id")

    @property
    def title_field(self) -> str:
        return self.options.get("title_field", "title")

    @property
    def body_field(self) -> str:
        return self.options.get("body_field", "body")

    @property
    def link_field(self) -> str:
        return self.options.get("link_field", "link")

    @property
    def published_field(self) -> str:
        return self.options.get("published_field", "published_at")


@dataclass
class NotifyConfig:
    """Configuration for a single notification channel."""
    type: str                        # "log" | "webhook" | "email"
    options: dict[str, Any] = field(default_factory=dict)

    # Webhook
    @property
    def webhook_url(self) -> str | None:
        return self.options.get("url")

    # Email
    @property
    def smtp_host(self) -> str:
        return self.options.get("smtp_host", "localhost")

    @property
    def smtp_port(self) -> int:
        return int(self.options.get("smtp_port", 587))

    @property
    def from_addr(self) -> str:
        return self.options.get("from", "watchkit@localhost")

    @property
    def to_addrs(self) -> list[str]:
        raw = self.options.get("to", [])
        return [raw] if isinstance(raw, str) else raw

    @property
    def smtp_username(self) -> str | None:
        return self.options.get("username") or os.environ.get("WATCHKIT_SMTP_USER")

    @property
    def smtp_password(self) -> str | None:
        return self.options.get("password") or os.environ.get("WATCHKIT_SMTP_PASS")


@dataclass
class AppConfig:
    """Top-level application configuration."""
    app: str
    state_dir: str
    sources: list[SourceConfig]
    notify: list[NotifyConfig]

    # Resolved absolute path to the state directory for this app.
    @property
    def state_path(self) -> Path:
        return Path(self.state_dir)

    @property
    def state_file(self) -> Path:
        return self.state_path / f"{self.app}.json"

    @property
    def event_log_file(self) -> Path:
        return self.state_path / f"{self.app}.events.jsonl"


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

_REQUIRED_APP_KEYS = {"app", "sources"}
_REQUIRED_SOURCE_KEYS = {"name", "type", "url"}
_VALID_SOURCE_TYPES = {"rss", "json", "html"}
_VALID_NOTIFY_TYPES = {"log", "webhook", "email"}


def load_config(path: str | Path) -> AppConfig:
    """Load and validate an application JSON config file.

    Args:
        path: Path to the JSON file (e.g. ``apps/status-watchdog.json``).

    Returns:
        A validated :class:`AppConfig` instance.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If the config is structurally invalid.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with path.open(encoding="utf-8") as fh:
        raw = json.load(fh)

    return _parse_config(raw, path)


def _parse_config(raw: dict[str, Any], source_file: Path) -> AppConfig:
    """Parse and validate a raw config dict."""
    missing = _REQUIRED_APP_KEYS - raw.keys()
    if missing:
        raise ValueError(f"Config missing required keys: {missing}")

    app_name: str = raw["app"]
    state_dir: str = raw.get("state_dir", "state")

    # Parse sources
    sources: list[SourceConfig] = []
    for i, src in enumerate(raw["sources"]):
        missing_src = _REQUIRED_SOURCE_KEYS - src.keys()
        if missing_src:
            raise ValueError(
                f"Source #{i} in {source_file} missing keys: {missing_src}"
            )
        src_type = src["type"]
        if src_type not in _VALID_SOURCE_TYPES:
            raise ValueError(
                f"Source '{src['name']}' has unknown type '{src_type}'. "
                f"Valid: {_VALID_SOURCE_TYPES}"
            )
        sources.append(
            SourceConfig(
                name=src["name"],
                type=src_type,
                url=src["url"],
                interval_minutes=int(src.get("interval_minutes", 15)),
                options=src.get("options", {}),
            )
        )

    # Parse notifiers (default: dry-run log)
    notify_list: list[NotifyConfig] = []
    for nc in raw.get("notify", [{"type": "log"}]):
        nc_type = nc.get("type", "log")
        if nc_type not in _VALID_NOTIFY_TYPES:
            raise ValueError(
                f"Notifier has unknown type '{nc_type}'. "
                f"Valid: {_VALID_NOTIFY_TYPES}"
            )
        opts = {k: v for k, v in nc.items() if k != "type"}
        notify_list.append(NotifyConfig(type=nc_type, options=opts))

    if not notify_list:
        # Always keep at least the log notifier as a safety net
        notify_list.append(NotifyConfig(type="log"))

    return AppConfig(
        app=app_name,
        state_dir=state_dir,
        sources=sources,
        notify=notify_list,
    )
