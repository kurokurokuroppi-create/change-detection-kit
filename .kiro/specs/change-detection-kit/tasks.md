# Tasks: Change Detection Kit

- [x] 1. Project scaffold: pyproject.toml, README.md, LICENSE (MIT),
      .gitignore, package layout
- [x] 2. Config loader with validation (watchkit/config.py)
- [x] 3. Fetchers: rss, json, html adapters (watchkit/fetchers.py)
- [x] 4. Diff engine: hashing + noise filter + diff excerpt (watchkit/diff.py)
- [x] 5. State store + incident lifecycle (watchkit/state.py)
- [x] 6. Summarizers: template + optional LLM (watchkit/summarize.py)
- [x] 7. Notifiers: webhook, email, log dry-run (watchkit/notify.py)
- [x] 8. Runner CLI: run / serve pipeline (watchkit/runner.py, __main__.py)
- [x] 9. Dashboard static HTML generator (watchkit/dashboard.py)
- [x] 10. App configs: apps/status-watchdog.json, apps/exam-watcher.json
- [x] 11. Unit tests for diff + state (tests/)
- [x] 12. Smoke run against the live Azure status RSS, dry-run notify
