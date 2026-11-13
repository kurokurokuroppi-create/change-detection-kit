# Requirements: Change Detection Kit

## Introduction
A reusable change-detection engine plus two applications built on it
(Skeleton Crew category, Kiroween 2026). The engine fetches configured
sources, detects meaningful changes, manages an incident lifecycle,
summarizes changes in Japanese, and dispatches notifications.

## Requirements

### R1 Source adapters
- WHEN a source is configured with type `rss`, THE SYSTEM SHALL fetch and
  parse the RSS/Atom feed into items (title, link, published, summary).
- WHEN a source is configured with type `json`, THE SYSTEM SHALL fetch the
  JSON document and extract items using the configured field mapping.
- WHEN a source is configured with type `html`, THE SYSTEM SHALL fetch the
  page, extract the main text of the configured CSS selector (or the whole
  body when no selector is given), and treat it as one document.
- THE SYSTEM SHALL define sources purely in app configuration files
  (name, type, url, interval minutes, options) with no code changes.

### R2 Change detection
- THE SYSTEM SHALL compute a stable content hash per source and per feed
  item, and SHALL report a change only when the hash differs from the
  stored state.
- THE SYSTEM SHALL ignore noise: whitespace-only differences, HTML tag
  churn, and volatile tokens listed in the app configuration.
- FOR html sources, THE SYSTEM SHALL produce a short unified text diff
  excerpt (max 40 lines) describing what changed.

### R3 Incident lifecycle (status feeds)
- WHEN a status feed gains an item describing an incident, THE SYSTEM
  SHALL open an incident keyed by the item identity.
- WHEN the item disappears or a resolution message appears, THE SYSTEM
  SHALL close the incident and treat it as a recovery event.
- THE SYSTEM SHALL persist state between runs in JSON files under the
  app state directory.

### R4 Summarization
- FOR every detected change event, THE SYSTEM SHALL produce a Japanese
  3-line summary: line 1 what changed, line 2 impact/scope, line 3 the
  recommended next action.
- WHEN an LLM API key is configured (env `WATCHKIT_LLM_API_KEY`), THE
  SYSTEM SHALL use the LLM summarizer; OTHERWISE it SHALL use the
  deterministic template summarizer. Both behind one interface.

### R5 Notification
- THE SYSTEM SHALL support webhook notification (generic JSON POST,
  Discord/Slack compatible payload) and email notification (SMTP).
- WHEN a channel is not configured, THE SYSTEM SHALL log the notification
  payload instead of sending (dry-run), so demos never fail on missing
  credentials.
- Notifications SHALL be sent only for change events, never for
  unchanged polls.

### R6 Runner and scheduler
- THE SYSTEM SHALL provide `python -m watchkit run --app <name>` to poll
  all sources of an app once and exit.
- THE SYSTEM SHALL provide `python -m watchkit serve --app <name>` to
  poll repeatedly, honoring each source's interval.
- THE SYSTEM SHALL provide `python -m watchkit dashboard --app <name>`
  to render a static HTML status board from the current state.

### R7 Applications as configuration
- THE SYSTEM SHALL ship `apps/status-watchdog.json` with at least the
  Azure status RSS and Microsoft 365 status RSS as sources.
- THE SYSTEM SHALL ship `apps/exam-watcher.json` with at least three
  Japanese certification official pages as html sources (Generative AI
  Passport, G-Test, E-Test information pages).
