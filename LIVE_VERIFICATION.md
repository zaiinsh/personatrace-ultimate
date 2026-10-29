# PersonaTrace Ultimate v1.1.0-live — live verification (2026-10-29)

Verified by running the real adapters against real public endpoints,
not by mocked tests alone. Mocked tests (89 passed) are separate.

## Live, verified ok
- GitHub — seed `octocat` → 1 profile, The Octocat, https://github.com/octocat
- Bluesky — seed `bsky.app` → 1 profile, Bluesky, https://bsky.app/profile/bsky.app
- Mastodon — seed `Mastodon` on mastodon.social → 1 profile, https://mastodon.social/@Mastodon
- Wayback — seed `example.com` → archived snapshot found
- crt.sh — seed `example.com` → public certificate names found on a
  second attempt. First attempts returned degraded (timeout, then
  HTTP 502 from crt.sh itself). The adapter does not retry inside a
  run, so a slow crt.sh run honestly reports degraded with zero
  profiles instead of fabricated data. This flakiness is a property
  of crt.sh, not a data claim.
- DNS — seed `example.com` → public DNS records resolved

## Not checked (expected, not a failure)
- YouTube — no key supplied in verification, so status is
  `not_checked`, zero profiles. With a YouTube Data API key it calls
  the live channel search (mock-tested; 100 units per search).
- X / Instagram / Reddit / TikTok — no aggregator key or address
  supplied, so status is `not_checked`, zero profiles. With a key
  and a `licensed_aggregator_base_url` the adapter makes one live
  call to `{base_url}/v1/profile?platform=…&username=…`
  (mock-tested against a generic JSON profile shape).

## End-to-end, ready to use
- CLI: `python -m personatrace.cli --seed octocat --out live_out`
  → 2 profiles (github + mastodon), 1 edge, 1 possible match,
  investigation.json + case.json + case.html written.
- GUI: `python -m personatrace.gui.server --port 8787`, open
  http://127.0.0.1:8787/ → Live search form runs the same live
  engine; /api/search, /api/cost and /api/compare were checked
  against a running server. Keys sent in a live-search request
  are used for that request only and never stored or echoed.

## Guardrails still in force
Public data only. No private accounts, no private messages, no live
location, no face identification, no bulk export, no CAPTCHA /
rate-limit / login-wall bypass. A 429 is degraded, never retried.
Demo data is always labelled demo_* and never mixed with live
results. A source with no key is `not_checked`, never `not found`.

## v1.2.0-full verification (2026-10-29)
- Tests: 93 passed.
- CLI octocat: 3 profiles on first run (github, mastodon, domain
  github.blog), 5 on a second run after crt.sh succeeded
  (certificate subdomains added), monitor_report.json correctly
  reported added domains and changed profile.
- CLI bsky.app: Bluesky activity 5 posts fetched live, language
  latin, behaviour summary built from real activity text.
- GitLab: username "gitlab" found live via GitLab public API;
  "octocat"/"torvalds" correctly return ok with 0 profiles on GitLab.
- GUI live search: /api/search returns analysis with all keys
  (languages, bio_domains, domain_expansion, certificate_subdomains,
  activity, coordinated, stylometry, phrase_matches, snapshots,
  avatar_reuse, behaviour_summary, bridge_domains, alerts, limits).

## v1.3.0-full verification (2026-10-29)
- Tests: 102 passed.
- CLI octocat (watch, 2 runs, interval 0): 4 profiles (github,
  hackernews, mastodon, domain github.blog), 2 edges, 1 possible
  match; contacts github:octocat = tekkub, wonderchook, cheshire137,
  mdo, haileys; risk signals 3 (2 follower imbalance + 1 variant
  cluster); next steps 8 (not_checked sources + queue review +
  degraded wayback/crtsh/dns); case.pdf (%PDF, ReportLab), case.cypher
  and case.sql written; archive_history.jsonl = 2 lines; monitor
  comparison on run 2 reported no added/changed profiles.
- CLI durov: telegram ok 1 profile (Pavel Durov), hackernews ok 1,
  bridge domain vk.com linking github:durov + hackernews:durov,
  next steps 10.
- CLI pg: hackernews ok 1 (pg, karma 157316 via Algolia API).
- GUI (running server): /api/progress 200, /api/migrate?fmt=cypher
  and ?fmt=sql 200, /api/export?fmt=pdf 200 application/pdf (%PDF,
  3719 bytes for the demo case).

## v1.4.0-full verification (2026-10-29)
- Tests: 106 passed.
- CLI octocat --compare-seed pg --note ...: 4 profiles, 2 edges,
  1 possible match; mentions 5 (Hacker News), news 5 (Google News
  RSS, incl. GitHub Blog Octocat figurine story), timeline 7,
  website changes github.blog = 5 Wayback snapshots, work history
  company @github + location San Francisco (own public profile),
  contacts of contacts for tekkub/wonderchook/cheshire137,
  comparison with pg: shared platforms github/hackernews/mastodon,
  shared domains/contacts/hashtags [] (correctly empty, not invented),
  notes + 6-item checklist in investigation.json, case.csv written.
- CLI octocat second run (after monitor fix): monitor correctly
  reports new_activity [] and disappeared_activity [] (was a false
  disappeared alert before the fix); StackOverflow Octocat found
  live on that run; Telegram/StackOverflow degraded on earlier runs
  (flaky/timeout, reported honestly, not retried).
- GUI (demo data): POST /api/compare-cases 200, /api/export?fmt=csv
  200 text/csv with provenance header.

## v2.0.0-full verification (2026-10-29)
- 114 pytest tests passed (106 in v1.4 + 8 new in tests/test_v20.py).
- Live CLI octocat: 7 profiles, 5 edges, site_checks (dev.to/kaggle/soundcloud), behaviour_over_time, report.md written, all 12 v2 analysis keys present.
- GUI: real Playwright-Firefox screenshot in demo mode, workspace/personatrace-screenshot/personatrace-ui-v2.png (671 KB) — new layout: top bar, Profile Summary, draggable Network Graph, Timeline scrub + Play, Evidence, Alerts, review queue.
- Honest limits: gated platforms without a key remain not_checked (Reddit RSS/JSON 403 live-checked 2026-10-29; X/Instagram/TikTok pages are JS/login-walled, not scraped). Lens/Yandex are manual links only. No device fingerprinting or credential-leak checks were added (outside public-data scope).
