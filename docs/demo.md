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
