"""watchkit/notify.py — Notification channel implementations.

Three channel types are provided:

* :class:`LogNotifier` — dry-run: logs the payload to stdout/logger.
* :class:`WebhookNotifier` — HTTP POST to a configured URL (Discord/Slack compatible).
* :class:`EmailNotifier` — sends email via SMTP.

The public entry point is :func:`send_notification`, which accepts a list of
:class:`~watchkit.config.NotifyConfig` objects and dispatches to each.

If a channel is misconfigured or raises an exception, the error is logged and
the remaining channels are still attempted.
"""

from __future__ import annotations

import json
import logging
import smtplib
import urllib.error
import urllib.request
from email.message import EmailMessage
from typing import Protocol

from watchkit.config import NotifyConfig
from watchkit.state import Event

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Notification payload
# ---------------------------------------------------------------------------

def _build_payload(event: Event, summary: str) -> dict:
    """Build a JSON-serialisable notification payload from *event* and *summary*."""
    return {
        "event_kind": event.kind,
        "source": event.source,
        "title": event.title,
        "summary": summary,
        "occurred_at": event.occurred_at,
    }


def _discord_payload(event: Event, summary: str) -> dict:
    """Build a Discord/Slack-compatible webhook payload.

    Uses ``embeds`` for Discord and ``text`` for Slack (same field set works
    for both when ``content`` is set).
    """
    # Emoji per event kind
    icon = {
        "incident_opened":   "🔴",
        "incident_updated":  "🟡",
        "incident_resolved": "🟢",
        "page_changed":      "📄",
    }.get(event.kind, "ℹ️")

    lines = summary.splitlines()
    # Pad to 3 lines defensively
    while len(lines) < 3:
        lines.append("")

    return {
        "content": f"{icon} **{event.title}**",
        "embeds": [
            {
                "description": "\n".join(lines),
                "color": {
                    "incident_opened": 0xFF0000,
                    "incident_updated": 0xFFAA00,
                    "incident_resolved": 0x00AA00,
                    "page_changed": 0x0055FF,
                }.get(event.kind, 0x888888),
                "footer": {"text": f"{event.source} · {event.occurred_at}"},
            }
        ],
        # Slack compatibility
        "text": f"{icon} {event.title}\n{summary}",
    }


# ---------------------------------------------------------------------------
# Notifier protocol
# ---------------------------------------------------------------------------

class Notifier(Protocol):
    """Interface for all notifier implementations."""

    def send(self, event: Event, summary: str) -> None:
        """Dispatch notification for *event* with the provided *summary*."""
        ...


# ---------------------------------------------------------------------------
# Log (dry-run) notifier
# ---------------------------------------------------------------------------

class LogNotifier:
    """Dry-run notifier: logs the full payload instead of sending it."""

    def send(self, event: Event, summary: str) -> None:
        payload = _build_payload(event, summary)
        logger.info(
            "[DRY-RUN] Notification payload:\n%s",
            json.dumps(payload, ensure_ascii=False, indent=2),
        )
        # Also print to stdout so it is visible in cron runs
        print(f"\n--- NOTIFICATION (dry-run) ---")
        print(f"Event  : {event.kind} @ {event.source}")
        print(f"Title  : {event.title}")
        print(f"Summary:\n{summary}")
        print("------------------------------\n")


# ---------------------------------------------------------------------------
# Webhook notifier
# ---------------------------------------------------------------------------

class WebhookNotifier:
    """HTTP POST notifier (Discord/Slack-compatible JSON payload)."""

    def __init__(self, config: NotifyConfig) -> None:
        self._url = config.webhook_url
        if not self._url:
            raise ValueError("WebhookNotifier requires a 'url' in config options.")

    def send(self, event: Event, summary: str) -> None:
        payload = _discord_payload(event, summary)
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self._url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "watchkit/0.1",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                status = resp.status
            logger.info("Webhook delivered (HTTP %s) to %s", status, self._url)
        except urllib.error.HTTPError as exc:
            logger.error(
                "Webhook HTTP error %s for %s: %s",
                exc.code, self._url, exc.reason
            )
        except urllib.error.URLError as exc:
            logger.error("Webhook connection error for %s: %s", self._url, exc.reason)


# ---------------------------------------------------------------------------
# Email notifier
# ---------------------------------------------------------------------------

class EmailNotifier:
    """SMTP email notifier."""

    def __init__(self, config: NotifyConfig) -> None:
        self._config = config

    def send(self, event: Event, summary: str) -> None:
        if not self._config.to_addrs:
            logger.warning("EmailNotifier: no 'to' addresses configured; skipping.")
            return

        msg = EmailMessage()
        msg["Subject"] = f"[watchkit] {event.title}"
        msg["From"] = self._config.from_addr
        msg["To"] = ", ".join(self._config.to_addrs)

        body = (
            f"イベント種別: {event.kind}\n"
            f"ソース: {event.source}\n"
            f"発生日時: {event.occurred_at}\n\n"
            f"サマリー:\n{summary}\n\n"
            f"詳細:\n{event.detail}\n"
        )
        msg.set_content(body)

        host = self._config.smtp_host
        port = self._config.smtp_port
        try:
            with smtplib.SMTP(host, port, timeout=20) as smtp:
                if self._config.smtp_username:
                    smtp.starttls()
                    smtp.login(
                        self._config.smtp_username,
                        self._config.smtp_password or "",
                    )
                smtp.send_message(msg)
            logger.info(
                "Email sent to %s via %s:%s",
                self._config.to_addrs, host, port
            )
        except (smtplib.SMTPException, OSError) as exc:
            logger.error("Email send failed: %s", exc)


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

def build_notifier(config: NotifyConfig) -> Notifier:
    """Instantiate the correct notifier for *config*.

    Returns :class:`LogNotifier` for unknown types as a safe fallback.
    """
    if config.type == "webhook":
        if not config.webhook_url:
            logger.warning(
                "Webhook notifier configured but 'url' is missing; falling back to log."
            )
            return LogNotifier()
        return WebhookNotifier(config)
    elif config.type == "email":
        return EmailNotifier(config)
    else:
        # "log" or anything unrecognised → dry-run
        return LogNotifier()


def send_notification(
    event: Event,
    summary: str,
    notify_configs: list[NotifyConfig],
) -> None:
    """Send notifications to all configured channels.

    Errors in individual channels are logged without stopping other channels.
    """
    for nc in notify_configs:
        try:
            notifier = build_notifier(nc)
            notifier.send(event, summary)
        except Exception as exc:
            logger.error(
                "Notifier '%s' raised an unexpected error: %s", nc.type, exc,
                exc_info=True,
            )
