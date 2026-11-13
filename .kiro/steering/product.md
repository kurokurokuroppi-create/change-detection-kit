# Product: Change Detection Kit

A small reusable engine that watches external sources, detects meaningful
changes, summarizes them in three lines of Japanese, and notifies people.
One skeleton, many creatures: the same engine powers two very different apps.

- App A "Status Watchdog": watches official status feeds (Azure, Microsoft 365,
  AWS, GitHub, Cloudflare), detects incidents and recoveries as paired events,
  and sends a 3-line Japanese alert (what happened / impact / what to do).
- App B "Exam Watcher": watches official pages of Japanese AI/IT certifications
  (syllabus, exam schedule, fees, announcements) and notifies subscribers when
  something changes, with a short summary of the change.

Design principles:
- Sources are configuration, not code. Adding a watched target must not
  require writing Python.
- Stdlib-first Python 3.12. No heavy frameworks.
- The summarizer is pluggable: an LLM API when a key is configured, a
  deterministic template fallback otherwise.
- Every run must work as a one-shot CLI command (cron friendly) and as a
  long-running scheduler.
