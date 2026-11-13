# Design: Change Detection Kit

## Stack
Python 3.12, standard library first (urllib.request, xml.etree, json,
hashlib, difflib, smtplib, html.parser). No web framework. The dashboard
is generated static HTML.

## Layout
```
watchkit/
  __init__.py
  __main__.py        # CLI entry: run / serve / dashboard
  config.py          # app config loading + validation (dataclasses)
  fetchers.py        # rss / json / html adapters -> list[Item] | Document
  diff.py            # hashing, noise filtering, text diff excerpts
  state.py           # JSON state store, incident lifecycle
  summarize.py       # Summarizer interface, TemplateSummarizer, LLMSummarizer
  notify.py          # WebhookNotifier, EmailNotifier, LogNotifier (dry-run)
  runner.py          # poll once / scheduler loop / event pipeline
  dashboard.py       # static HTML board from state
apps/
  status-watchdog.json
  exam-watcher.json
state/               # runtime state per app (gitignored)
tests/
  test_diff.py
  test_state.py
```

## Data model
- `Item`: id (stable hash of link+title), title, link, published, body.
- `Document`: source name, text, hash.
- `Event`: kind in {incident_opened, incident_updated, incident_resolved,
  page_changed}, source, title, detail, occurred_at.
- State per app: `{sources: {name: {hash, items: {id: item}, incidents:
  {id: {title, opened_at, status}}}}}` in `state/<app>.json`.

## Pipeline (per poll)
fetch -> normalize -> hash/diff vs state -> events -> summarize ->
notify -> persist state -> append event log (JSONL) for the dashboard.

## Error handling
A failing source logs an error event and does not stop other sources.
HTTP timeouts are 20s. User-Agent identifies the kit.

## Summarizer contract
`summarize(event) -> str` returning exactly 3 lines in Japanese.
TemplateSummarizer builds the lines from event fields. LLMSummarizer
calls an OpenAI-compatible chat endpoint when env vars are set and
falls back to the template on any error.
