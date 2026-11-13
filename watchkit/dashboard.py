"""watchkit/dashboard.py — Static HTML status board generator.

Reads the state file and event log for an application and generates a
self-contained, single-file HTML page with:

- Current incident status per source (open / resolved / unknown)
- Recent event history (last 50 events)
- Generation timestamp

No external CSS frameworks or JS libraries are used (stdlib-only).
"""

from __future__ import annotations

import html
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from watchkit.config import AppConfig
from watchkit.state import StateStore

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# CSS — inline styles kept simple and readable
# ---------------------------------------------------------------------------

_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    background: #f5f5f5;
    color: #222;
    padding: 2rem;
    line-height: 1.5;
}
h1 { font-size: 1.6rem; margin-bottom: 0.25rem; }
.meta { color: #666; font-size: 0.9rem; margin-bottom: 2rem; }
h2 { font-size: 1.1rem; margin: 1.5rem 0 0.75rem; }
table {
    width: 100%;
    border-collapse: collapse;
    background: #fff;
    border-radius: 6px;
    overflow: hidden;
    box-shadow: 0 1px 3px rgba(0,0,0,.12);
    margin-bottom: 1.5rem;
}
th {
    background: #2d2d2d;
    color: #fff;
    text-align: left;
    padding: 0.6rem 0.9rem;
    font-weight: 600;
    font-size: 0.88rem;
}
td {
    padding: 0.55rem 0.9rem;
    border-bottom: 1px solid #eee;
    font-size: 0.9rem;
    vertical-align: top;
}
tr:last-child td { border-bottom: none; }
tr:hover td { background: #fafafa; }
.badge {
    display: inline-block;
    padding: 0.15rem 0.55rem;
    border-radius: 999px;
    font-size: 0.78rem;
    font-weight: 600;
    white-space: nowrap;
}
.badge-open     { background: #fee2e2; color: #b91c1c; }
.badge-resolved { background: #d1fae5; color: #065f46; }
.badge-ok       { background: #dbeafe; color: #1d4ed8; }
.badge-unknown  { background: #f3f4f6; color: #6b7280; }
.badge-changed  { background: #fef3c7; color: #92400e; }
.kind-incident_opened   { color: #b91c1c; }
.kind-incident_updated  { color: #92400e; }
.kind-incident_resolved { color: #065f46; }
.kind-page_changed      { color: #1d4ed8; }
pre {
    background: #f8f8f8;
    border: 1px solid #e0e0e0;
    border-radius: 4px;
    padding: 0.5rem;
    font-size: 0.78rem;
    overflow-x: auto;
    white-space: pre-wrap;
    word-break: break-word;
    max-height: 10rem;
    overflow-y: auto;
}
"""

# ---------------------------------------------------------------------------
# HTML helpers
# ---------------------------------------------------------------------------

def _e(text: str) -> str:
    """HTML-escape *text*."""
    return html.escape(str(text), quote=True)


def _badge(label: str, css_class: str) -> str:
    return f'<span class="badge {css_class}">{_e(label)}</span>'


def _kind_label(kind: str) -> str:
    labels = {
        "incident_opened":   "障害発生",
        "incident_updated":  "障害更新",
        "incident_resolved": "障害復旧",
        "page_changed":      "ページ更新",
    }
    return labels.get(kind, kind)


def _kind_badge(kind: str) -> str:
    css = {
        "incident_opened":   "badge-open",
        "incident_updated":  "badge-changed",
        "incident_resolved": "badge-resolved",
        "page_changed":      "badge-changed",
    }.get(kind, "badge-unknown")
    return _badge(_kind_label(kind), css)


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------

def _build_source_status_table(state: dict[str, Any]) -> str:
    """Build the per-source status summary table."""
    sources = state.get("sources", {})
    if not sources:
        return "<p>（ソース状態データなし）</p>"

    rows = []
    for src_name, src_data in sources.items():
        incidents = src_data.get("incidents", {})
        open_count = sum(
            1 for inc in incidents.values() if inc.get("status") == "open"
        )

        if open_count > 0:
            status_badge = _badge(f"障害 {open_count}件", "badge-open")
        else:
            status_badge = _badge("正常", "badge-ok")

        # Most recent open incident title
        recent_title = ""
        for inc in incidents.values():
            if inc.get("status") == "open":
                recent_title = inc.get("title", "")
                break

        last_hash = _e(src_data.get("hash") or "未確認")
        rows.append(
            f"<tr>"
            f"<td><strong>{_e(src_name)}</strong></td>"
            f"<td>{status_badge}</td>"
            f"<td>{_e(recent_title)}</td>"
            f"<td><code>{last_hash[:12]}</code></td>"
            f"</tr>"
        )

    return (
        "<table>"
        "<thead><tr>"
        "<th>ソース</th><th>状態</th><th>最新インシデント</th><th>コンテンツハッシュ</th>"
        "</tr></thead>"
        "<tbody>" + "".join(rows) + "</tbody>"
        "</table>"
    )


def _build_event_table(events: list[dict[str, Any]], limit: int = 50) -> str:
    """Build the recent event history table (newest first, capped at *limit*)."""
    if not events:
        return "<p>（イベント履歴なし）</p>"

    # Newest first
    recent = list(reversed(events[-limit:]))

    rows = []
    for ev in recent:
        kind    = ev.get("kind", "")
        source  = ev.get("source", "")
        title   = ev.get("title", "")
        detail  = ev.get("detail", "")
        ts      = ev.get("occurred_at", "")
        # Truncate detail for display
        detail_short = (detail[:200] + "…") if len(detail) > 200 else detail

        rows.append(
            f"<tr>"
            f"<td>{_e(ts)}</td>"
            f"<td>{_kind_badge(kind)}</td>"
            f"<td>{_e(source)}</td>"
            f"<td>{_e(title)}</td>"
            f"<td><pre>{_e(detail_short)}</pre></td>"
            f"</tr>"
        )

    return (
        "<table>"
        "<thead><tr>"
        "<th>日時 (UTC)</th><th>種別</th><th>ソース</th><th>タイトル</th><th>詳細</th>"
        "</tr></thead>"
        "<tbody>" + "".join(rows) + "</tbody>"
        "</table>"
    )


# ---------------------------------------------------------------------------
# Main generator
# ---------------------------------------------------------------------------

def generate_dashboard(config: AppConfig, output_path: str | None = None) -> Path:
    """Generate a static HTML status board for *config*.

    Args:
        config: Loaded :class:`~watchkit.config.AppConfig`.
        output_path: Optional explicit output file path.
                     Defaults to ``state/<app>.html``.

    Returns:
        The :class:`Path` where the HTML was written.
    """
    store = StateStore(config)
    store.load()

    state = store.raw_state
    events = store.read_event_log()

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    app_name = config.app

    source_table = _build_source_status_table(state)
    event_table  = _build_event_table(events)

    # Count open incidents across all sources
    total_open = sum(
        sum(1 for inc in src.get("incidents", {}).values() if inc.get("status") == "open")
        for src in state.get("sources", {}).values()
    )

    overall_badge = _badge("障害あり", "badge-open") if total_open > 0 else _badge("全サービス正常", "badge-resolved")

    html_doc = f"""<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{_e(app_name)} — 状態ボード</title>
  <style>{_CSS}</style>
</head>
<body>
  <h1>{_e(app_name)} 状態ボード</h1>
  <p class="meta">
    全体状態: {overall_badge} &nbsp;|&nbsp;
    最終更新: {_e(generated_at)} &nbsp;|&nbsp;
    監視ソース数: {_e(str(len(state.get("sources", {}))))}
  </p>

  <h2>ソース別状態</h2>
  {source_table}

  <h2>イベント履歴（直近50件）</h2>
  {event_table}

  <p class="meta" style="margin-top:2rem;">
    watchkit v0.1 — Change Detection Kit
  </p>
</body>
</html>
"""

    # Determine output path
    if output_path:
        out = Path(output_path)
    else:
        out = config.state_path / f"{app_name}.html"

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html_doc, encoding="utf-8")
    logger.info("Dashboard written to %s", out)
    print(f"Dashboard generated: {out}")
    return out
