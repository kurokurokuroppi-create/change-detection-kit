# Change Detection Kit

A small reusable engine that watches external sources, detects meaningful
changes, summarises them in three lines of Japanese, and notifies people.

## Quick Start

```bash
# One-shot poll (cron-friendly)
python -m watchkit run --app status-watchdog

# Long-running scheduler
python -m watchkit serve --app status-watchdog

# Static HTML status board
python -m watchkit dashboard --app status-watchdog
```

## Applications

| App | Description |
|-----|-------------|
| `status-watchdog` | Monitors Azure, M365, AWS, GitHub, Cloudflare status feeds |
| `exam-watcher`    | Monitors Japanese AI/IT certification pages for changes |

## Configuration

Each application is a single JSON file under `apps/`.  Adding a new watched
source requires only editing (or creating) the JSON — no Python needed.

### App config schema

```json
{
  "app": "my-app",
  "state_dir": "state",
  "notify": [ {"type": "log"} ],
  "sources": [
    {
      "name": "example-rss",
      "type": "rss",
      "url": "https://example.com/feed.rss",
      "interval_minutes": 15
    },
    {
      "name": "example-json",
      "type": "json",
      "url": "https://api.example.com/status.json",
      "interval_minutes": 5,
      "options": {
        "items_field": "incidents",
        "id_field": "id",
        "title_field": "name",
        "body_field": "body"
      }
    },
    {
      "name": "example-html",
      "type": "html",
      "url": "https://example.com/page.html",
      "interval_minutes": 60,
      "options": {
        "selector": "main"
      }
    }
  ]
}
```

### Notifiers

| Type | Credentials |
|------|-------------|
| `log` (dry-run) | none — always works |
| `webhook` | `url` field in config |
| `email` | `smtp_host`, `smtp_port`, `from`, `to`, `username`/`password` or env vars |

### Summarizer

Set `WATCHKIT_LLM_API_KEY` (and optionally `WATCHKIT_LLM_BASE_URL`,
`WATCHKIT_LLM_MODEL`) for LLM summaries; otherwise the built-in Japanese
template is used.

## Layout

```
watchkit/   — engine package
apps/       — application JSON configs
state/      — runtime state (gitignored)
tests/      — unit tests
```
