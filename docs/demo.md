# Demo run (local fixture feed)

A full incident lifecycle against a local demo feed
(`apps/demo-local.json`, source served from `demo/feed.xml` on localhost).

## Run 1 — healthy feed, first observation
```
Run complete for 'demo-local': 0 event(s) detected.
```
State is seeded silently; no notification spam on first sight.

## Run 2 — an incident item appears in the feed
```
Run complete for 'demo-local': 1 event(s) detected.
```
Notification (Japanese 3-line summary):
```
【障害発生】demo-cloudで新たな障害が検出されました：Service disruption: Demo Cloud database unavailable in region jp-east
影響範囲：demo-cloud のサービスが一部または全体的に影響を受けている可能性があります。
公式ステータスページを確認し、業務への影響を評価してください。
```
Running again with the same feed produces **0 events** — no duplicate alerts.

## Run 3 — the incident item disappears (recovery)
```
Run complete for 'demo-local': 1 event(s) detected.
```
```
【障害復旧】demo-cloud の障害が解決しました：Service disruption: Demo Cloud database unavailable in region jp-east
影響範囲：demo-cloud のサービスは通常状態に戻っています。
業務への影響がないことを確認し、必要に応じて関係者に周知してください。
```

Reproduce: `python3 -m http.server 8799 --directory demo` in one shell,
then `python -m watchkit run --app demo-local` while editing `demo/feed.xml`
between runs.

---

# Rehearsal — 2026-11-16 (full run-through for the demo video)

Full run-through of the shooting script (all demo-local shots), executed
2026-11-16 on Python 3.12.3 with `WATCHKIT_LLM_API_KEY` unset (template
summarizer). **Result: every shot reproduced exactly as scripted. No engine
bugs found; no code changes were needed.**

## Exact incident-item feed format (resolves the script's open question)

The incident version of the feed is kept ready-made as
`demo/feed-incident.xml`. Its full content — this exact format is what
produces the notifications below:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
<title>Demo Cloud Status</title><link>http://localhost/</link><description>demo</description>
<item>
<title>Service disruption: Demo Cloud database unavailable in region jp-east</title>
<link>http://localhost/status/incident-2026-001</link>
<guid>http://localhost/status/incident-2026-001</guid>
<pubDate>Mon, 16 Nov 2026 04:00:00 GMT</pubDate>
<description>Demo Cloud database is currently unavailable in region jp-east. Engineers are investigating the cause.</description>
</item>
</channel></rss>
```

Notes on the format:

- RSS 2.0; the item lives inside `<channel>`, next to the channel metadata.
  Only `<title>` is strictly required by the parser; `<guid>` (falling back
  to `<link>`) plus `<title>` form the stable item ID, so keep both fixed —
  changing either makes the item look "new" again.
- The description must avoid resolution keywords (`resolved`, `recovered`,
  `fixed`, `closed`, 解決, 復旧, 正常, 回復) in title and body, otherwise a
  new item is treated as a resolution notice instead of an incident opening.
- The healthy feed (`demo/feed.xml`, committed) is the same channel with
  **no `<item>` at all**.
- Swap procedure used in the rehearsal: incident =
  `cp demo/feed-incident.xml demo/feed.xml`; recovery = restore the healthy
  file (`git checkout -- demo/feed.xml` inside a clone, or keep a copy).

## Shot-by-shot results (demo-local)

Pre-step: `state/demo-local.json` and `state/demo-local.events.jsonl`
deleted (back to first-observation), feed server started with
`python3 -m http.server 8799 --directory demo`.

| Step | Command / action | Result |
|---|---|---|
| Run 1 | healthy feed, first observation | `Run complete for 'demo-local': 0 event(s) detected.` — no notification. ✅ as scripted |
| Run 2 | swap in `feed-incident.xml`, run | `1 event(s) detected.` + 【障害発生】3-line notification, byte-identical to Run 2 above. ✅ |
| Run 2b | same incident feed, run again | `0 event(s) detected.` — no duplicate notification. ✅ |
| Run 3 | restore healthy feed, run | `1 event(s) detected.` + 【障害復旧】3-line notification, byte-identical to Run 3 above. ✅ |

The event log recorded exactly two events (`incident_opened`,
`incident_resolved`) for the same title.

State note: `state/` is gitignored, so rehearsal state never pollutes the
repo. After Run 3 the state is back to the healthy-feed hash, so the flow
reproduces even without a reset — but deleting the two state files before
the shoot is still recommended so the event log starts clean.

## App A / App B checks (read-only, no state changes)

- **status-watchdog**: config lists the 5 scripted sources (Azure /
  Microsoft 365 / AWS / GitHub / Cloudflare). Live fetch check via the
  engine's fetchers: all 5 OK (azure 0 items, microsoft365 1, aws 44,
  github 50, cloudflare 50).
- **exam-watcher**: config lists the 5 scripted sources (生成AIパスポート /
  G検定 / IPA×2 / JDLA). Live fetch from this VM: GUGA and JDLA OK;
  g-test.jp and the two IPA pages are unreachable from this VM's network
  (`RemoteDisconnected`) — a known environment limitation, and the script
  already keeps App B live runs out of the main flow (config + dashboard
  only). The published dashboard `docs/exam-watcher.html` currently lists
  2 of the 5 sources (only successfully observed sources appear). Optional
  pre-shoot polish: run exam-watcher once from a network that can reach
  g-test.jp / IPA and regenerate the dashboard if all 5 should be visible.

## Unit tests

`python3 -m unittest discover -s tests` → **Ran 47 tests, OK** (matches the
script's closing shot).

## Shooting notes from this rehearsal

- This VM provides only `python3` (no `python`). On the shooting PC use
  whichever exists (`python` / `python3` / `py`); the commands are
  otherwise identical to the script.
- `python3 -m http.server` can take a second or two to start listening;
  start it before recording and confirm with
  `curl http://127.0.0.1:8799/feed.xml`.
- `--log-level`, if used, is a global option and must come **before** the
  subcommand: `python -m watchkit --log-level WARNING run --app demo-local`.
  At the default INFO level the terminal additionally shows log lines and
  the dry-run JSON payload — everything in the script still appears.
