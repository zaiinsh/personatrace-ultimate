# PersonaTrace Ultimate — BUILD_LOG

## Phase 0 — Scaffold (2026-10-28, coordinator)
- Read final blueprint research report (~/workspace/research_notes/personatrace-osint-profiler-research-20261028-1756/report.md, §§1-6) and the locked scope from the parent task.
- Created ~/workspace/personatrace-app/ (new folder; ~/workspace/personatrace/ mockups untouched).
- Wrote CONTRACT.md — binding interfaces for core, adapters, storage, features, AI, GUI, demo, tests — so parallel module builders do not diverge.
- Locked scope restated in CONTRACT.md: public data only; no face ID (even via API, even with human approval); no private data, live/person location or movement tracking, bulk export; no bypassing CAPTCHAs/rate limits/login walls; provenance + possible-match queue + human verification + single-case export; fictional dummy data only.
- Plan: 4 parallel module builders (core / adapters+storage / features+AI / GUI), then coordinator integration, tests, demo run, README, verification report to parent. No final package delivery to the user from this coordinator — parent verifies and delivers.
- Status: scaffold done, module builders spawning next.

## Update — Autonomy confirmed (2026-10-28, parent handoff)
- User is sleeping; coordinator has full access and must NOT ask permission or stop for approval on ordinary design choices.
- Coordinator will make architecture/module/improvement decisions autonomously WITHIN the locked scope. Hard guardrails are NOT overridden by this autonomy: public data only, no face identification, no private access, no live/person tracking, no bulk export, no bypassing platform protections.
- Progress reported only to parent, not directly to the user. Module builders (core / adapters+storage / features+AI / GUI) already running in parallel; integration follows on their reports.

## Phase 1 — GUI module complete (2026-10-28, worker 3/4, coordinator-verified)
- Files: personatrace/gui/__init__.py, server.py (stdlib ThreadingHTTPServer, run_gui port 8787), demo_data.py, static/index.html, app.js, styles.css, tests/test_gui.py.
- Coverage: centre-node SVG graph (seed centre, three rings, bridge class, thick strong / thin dashed weak links), left profile panel with confidence drivers, right evidence panel with clickable source links, top search + platform filters + confidence slider + confirmed-only toggle, bottom timeline slider, alerts panel, compare placeholder, Settings with Active vs Not checked toggles, before-run panel, cost-before-run placeholder, all REST endpoints in CONTRACT.
- Verification (coordinator re-ran): python3 -m unittest tests.test_gui -v => 11 tests OK. Worker live-checked HTTP 200 for /, /api/investigation, /api/settings, /api/export json+html.
- Limitation carried forward: GUI runs on labelled demo data only until storage/core integration lands (lazy import fallback in server.py _load_investigation). Key POST stores name only, never echoes value. No face UI, no person-tracking map, no bulk export.
- Still running: core (1/4), features+AI (2/4), adapters+storage (4/4). Integration pending their reports.

## Phase 2 — Features + AI + demo complete (2026-10-28, worker 2/4, coordinator-verified)
- Files: personatrace/features/{phash, archive, biolink, coordinated, language, alerts, stylometry, export, phrase, manual, infra_location}.py, personatrace/ai/layer.py, demo/fixtures.py, personatrace/demo_run.py, tests/test_features.py, tests/test_ai.py, tests/__init__.py.
- Coverage: aHash reuse (threshold 10, non-image bytes never claimed as reuse), archive diffs, bio-link domains, coordinated crowd-check (signals + innocent explanations, verdict "pattern, not proof", no account "bot" label), script-based language detection with originals preserved, new-edge-only alerts, stylometry weak-signal with <500-word warning and 25% cap noted (enforcement in core), bio phrase search over supplied corpus, manual place clue (single public photo, analyst note only, no coordinates/face/movement), infrastructure-only location (domain/IP, not_checked placeholder), single-case HTML+JSON export with provenance per fact, AI local template (model local-template-v1, no key/network) and LLM-no-key -> not_checked.
- Verification (coordinator re-ran): python3 -m unittest tests.test_features tests.test_ai tests.test_gui => 38 tests OK (27 features+AI + 11 GUI). Demo CLI re-ran to /tmp/pt-demo-check, wrote investigation.json, case.html, case.json.
- Integration note carried forward: demo/fixtures.py currently defines dataclasses itself because core did not exist yet when this builder ran; export/AI consume duck-typed investigations, so they work with either source — coordinator will unify on core models at integration. pHash supports BMP/PNG/PPM only in stdlib; expand_domain/infra_location are honest not_checked placeholders, no network faked. pytest is NOT installed in this environment; unittest is the verified runner (tests are pytest-compatible).
- Still running: core (1/4), adapters+storage (4/4). Integration pending their reports.

## Phase 3 — Adapters + Storage complete (2026-10-28, worker 4/4, coordinator-verified)
- Files: personatrace/adapters/{base, registry, site_lists, free, gated, mock_data}.py, personatrace/storage/db.py, tests/test_adapters.py, tests/test_storage.py.
- Coverage: free adapters (github, youtube, bluesky, mastodon, wayback, crtsh, dns), gated LicensedAggregatorAdapter for x/instagram/reddit/tiktok (missing key -> not_checked + zero profiles + Settings prompt, never "not found"; missing-key wins even in demo mode), demo mode labelled demo_* with method="demo", 429 -> degraded with exactly 1 HTTP call (mocked, never retried), site list URL templates only (github/youtube/bluesky/mastodon/gitlab; closed platforms excluded), SQLite round-trip preserving profiles/edges/evidence/timeline/audit/alerts, save idempotent.
- Verification (coordinator re-ran): python3 -m unittest tests.test_adapters tests.test_storage tests.test_features tests.test_ai tests.test_gui => 55 tests OK. Also python3 -m pytest tests/test_adapters.py tests/test_storage.py -q => 17 passed (pytest is available in this run, contrary to earlier workers' reports — verified directly).
- Honest split (worker): live-capable single public GET (5s timeout, no retry, no login wall) = github, bluesky, mastodon.social lookup only, wayback/crtsh/dns for domain seeds only, any failure -> degraded; demo-only = youtube (no live call attempted, Data API needs key/quota); gated = no live endpoint configured yet, key+demo -> labelled demo, key without demo -> degraded, no key -> not_checked. Live paths implemented but NOT verified against real network (tests use demo/mocked HTTP).
- Contract deviations / integration debt to resolve at integration: (1) Investigation gained defaulted timeline + purpose fields (CONTRACT had no field for them); (2) possible_matches and Edge.evidence are NOT persisted (no CONTRACT table/column) — load returns [] for both; (3) profile confidence stored as max evidence confidence but not restored onto Profile (no confidence field in CONTRACT model); (4) load_investigation(path, case_id=None) defaults to most recent case.
- MAJOR integration debt: three model definitions now exist in the tree — adapters/base.py, demo/fixtures.py, and core/models.py (when core lands). Coordinator integration must unify on ONE canonical model and refactor the other two to import from it, without breaking the 55 passing tests.
- Still running: core (1/4) only. GUI, features+AI, adapters+storage done. Integration, README, final verification pending core.

## Phase 4 — Integration complete (2026-10-28, coordinator)
- Unified models: core/models.py is now canonical. Added defaulted fields (Profile.confidence, Investigation.timeline, Investigation.purpose) for storage compatibility; adapters/base.py and demo/fixtures.py now import from core.models and re-export (no duplicate dataclasses). Demo edge helper now computes band via core.confidence.band_for.
- Storage persistence fixed: possible_matches and edge evidence now persist (new possible_matches and edge_evidence tables, JSON-serialised profile/reasons); profile confidence is restored on load; audit/alert/timeline dict details are JSON-serialised instead of crashing SQLite binding (integration bug found and fixed: audit detail dicts from core engine).
- Engine clustering improvement (integration, NOT a threshold change): cluster_discovered_profiles() adds Low (40) same_username edges across social platforms only (github/youtube/bluesky/mastodon/x/instagram/reddit/tiktok/gitlab; infrastructure adapters excluded) plus one pending possible-match entry, for human review. No profile is auto-confirmed by clustering alone. Username-only merges remain impossible by design (exact username alone = 40 Low).
- Fixed one stale core test: test_engine_tolerates_failing_adapter_and_missing_registry assumed no registry existed; in the integrated tree adapters=None loads the real registry, so the test now asserts no-crash + adapters_loaded, and adapters=[] is the empty case. Failing-adapter assertion unchanged.
- End-to-end verification: PERSONATRACE_DEMO=1 engine run -> 9 profiles, 6 cluster edges, 1 possible-match, 24 audit entries; save -> load round-trip preserves profiles/edges/edge evidence/possible-matches; export_case HTML written. GUI served a real saved demo case from SQLite (index 200, /api/investigation returned demo-case-01 from DB, not demo fallback).
- Full suite: python3 -m pytest tests/ -q => 82 passed (25 core + 17 adapters/storage + 27 features/AI + 11 GUI + 2 integration). Note: unittest alone finds 55 (pytest-style core tests are not collected by unittest); pytest is the verified runner.
- Deliverables: README.md, requirements.txt (pytest only; app is stdlib-only), CONTRACT.md, BUILD_LOG.md, demo/out/ (investigation.json, case.html, case.json from demo_run.py). App code ~4,300 LOC across 44 Python files (app + tests + demo).
- Remaining / not built: real licensed-aggregator endpoint wiring for gated platforms; live verification against real platform endpoints; YouTube live calls; Neo4j/Postgres team migration code (documented path only); GUI Compare and cost-before-run are placeholders in demo mode. None of these block the local demo/full-feature build, and none justify breaking a locked guardrail to fake them.
- Guardrails held throughout integration: public data only, no face ID code path, no private data, no live/person location or movement tracking, no bulk export, no CAPTCHA/rate-limit/login-wall bypass, provenance + possible-match queue + single-case export, fictional dummy data only.
- Status: INTEGRATION COMPLETE. Ready for parent verification and delivery. No package delivered to the user by this coordinator.

## v1.1.0-live — full live version (2026-10-29)
- YouTube: live via YouTube Data API v3 channel search with a key
  (youtube_api_key / YOUTUBE_API_KEY); no key -> not_checked, never
  not found; 403/429 -> degraded, no retry; 100 units per search.
- Gated: licensed aggregator now makes one live call when a key AND
  a base URL are configured (licensed_aggregator_base_url /
  PERSONATRACE_AGGREGATOR_BASE_URL), to
  {base_url}/v1/profile?platform=...&username=... with Bearer auth;
  key without base URL -> degraded; no key -> not_checked (unchanged).
- GUI: POST /api/search runs the live engine (keys used for that
  request only, never stored or echoed), GET /api/cost gives the real
  cost-before-run, POST /api/compare gives a real side-by-side
  comparison, live-search form + compare selects added to the dashboard.
- CLI: python -m personatrace.cli --seed <username> --out live_out
  writes investigation.json, case.json, case.html.
- pHash: optional Pillow path for JPEG/WebP/GIF/TIFF when Pillow is
  installed; stdlib BMP/PNG/PPM behaviour unchanged, non-images never
  claimed as reuse matches.
- Live verification: see LIVE_VERIFICATION.md (GitHub, Bluesky,
  Mastodon, Wayback, crt.sh, DNS verified live; YouTube/gated
  not_checked without keys, as designed).
- Tests: 89 passed (pytest). No face-recognition code, no private
  access, no live location, no bulk export, no bypass of any kind.
- Remaining, honestly: Neo4j/Postgres team migration is documented
  only; a gated provider whose API shape differs from the generic
  profile endpoint needs its address mapped to that shape; no keys
  are included in this package.

## v1.2.0-full — full version (2026-10-29)
- Wired analysis into the engine: every live (and demo, offline)
  run now returns analysis with bio domains, language, coordinated
  crowd check, stylometry (weak only), phrase matches, archive
  snapshots, avatar reuse, behaviour summary and alerts. GUI shows
  it in a new Analysis panel; CLI prints it and writes it into
  investigation.json.
- Live bio-link expansion: bio domains (from GitHub blog, Bluesky
  URLs, Mastodon links) are expanded live via Wayback / crt.sh /
  DNS adapters, RDAP public WHOIS, and ipwho.is for server
  infrastructure country/organisation only. crt.sh certificate
  names become level-3 domain nodes; shared bio domains are bridge
  nodes. Verified live for github.blog (RDAP registrar MarkMonitor,
  registration 2018-05-17; DNS ok; Wayback/crt.sh degraded honestly
  on 429/timeout in that run, then crt.sh succeeded on a later run
  with certificate subdomains).
- Recent public activity text: GitHub repos, Bluesky author feed,
  YouTube uploads titles/descriptions (with a key). Full video
  transcripts are NOT fetched (no public transcript API for
  arbitrary channels) — stated in the analysis note.
- Avatar reuse: public avatar URLs are now captured as evidence
  (GitHub, GitLab, Bluesky, Mastodon), downloaded once, pHashed
  (Pillow for JPEG/WebP where installed), and compared pairwise
  (Hamming <= 10). Whole-image only, never face identification.
- Monitoring: personatrace/monitor.py compares a new run with the
  previous investigation.json in the same --out directory and
  writes monitor_report.json (added / changed / no-longer-found /
  new edges). Run the CLI daily (cron) for continuous monitoring;
  there is no live stream, and a missing profile is never claimed
  as deleted without checking source statuses.
- Per-case budget: CLI --max-cost-units skips YouTube search
  (100 units) when it exceeds the budget, with an audit entry.
- New free adapter: GitLab public API (verified live for username
  "gitlab"). Telegram is added to the site-URL list only — there
  is no general public API for arbitrary Telegram channels, so it
  is never presented as a verified profile.
- Tests: 93 passed (89 in v1.1 + 4 new analysis/monitor/budget).
- Still honestly not built: LLM provider for AI mode (local
  template only), full video-transcript behaviour analysis,
  Neo4j/Postgres team migration (documented only), and a general
  Telegram/forum live adapter (no legitimate API for arbitrary
  channels/forums). No keys are included in this package.

## v1.3.0-full — full version closing the v1.2 gap list (2026-10-29)
- PDF export: export_case(fmt="pdf") writes a real case.pdf (ReportLab
  when installed, stdlib PDF writer otherwise); GUI /api/export?fmt=pdf
  serves it. Verified: %PDF header, case id extractable via pypdf.
- Real LLM provider: AILayer(mode="llm") now makes a real
  OpenAI-compatible chat-completions call (single POST, 30s timeout,
  no retry on 429) to base_url (default api.openai.com/v1, or
  PERSONATRACE_LLM_BASE_URL / keys llm_base_url) with model
  (default gpt-4o-mini, or PERSONATRACE_LLM_MODEL / keys llm_model).
  Key from keys llm_api_key / OPENAI_API_KEY / PERSONATRACE_LLM_KEY,
  sent only to that endpoint, never echoed. No key -> not_checked.
  Mock-tested (real call path, simulated success response).
- Neo4j/Postgres migration: personatrace/storage/migrate.py with
  to_cypher() (MERGE Profile nodes + LINKED relationships) and
  to_postgres_sql() (CREATE TABLE + INSERTs), plus migrate_live()
  which runs live only when a driver + NEO4J_URI / DATABASE_URL are
  present, otherwise returns not_configured with the scripts. CLI
  --export-cypher / --export-sql write case.cypher / case.sql; GUI
  /api/migrate?fmt=cypher|sql serves them. Verified live-run output.
- Telegram general adapter: live adapter via the public t.me/s/<channel>
  page (no login, private channels have no public page). Verified live:
  durov -> 1 profile (Pavel Durov, "Founder of Telegram").
  Forum adapters: Hacker News via the public Algolia user API
  (verified live: pg -> karma 157316, "Bug fixer."; octocat/durov
  found live), plus a configurable Discourse adapter
  (discourse_base_url -> that forum's public /u/<user>.json API;
  not_checked without an address, never a claimed result).
- Reverse image search engines: personatrace/features/reverse_image.py
  with real TinEye API (image_url + key) and Bing Visual Search
  (image bytes + subscription key) calls; unconfigured engines are
  not_checked. Wired into analysis for the first downloaded avatar.
- OCR / image description: personatrace/features/ocr.py — Pillow
  description (size, mode, format, dominant colours, pHash) always;
  OCR text only via pytesseract+tesseract if installed, or a
  configured OCR API (PERSONATRACE_OCR_URL + key); otherwise
  not_checked with setup instructions, never invented text.
  Wired into analysis for downloaded avatars.
- Full video transcripts: personatrace/features/transcript.py
  attempts the public YouTube timedtext track list + track fetch
  for the first YouTube video in a case; no listed captions ->
  no_captions, never a transcript fabricated from titles/descriptions
  (those remain labelled titles/descriptions). In live runs without
  a YouTube key, transcripts is empty and that is stated, not hidden.
- Investigation progress tracker in the GUI: /api/progress returns
  stages (collecting / resolving / analysing / complete), per-source
  status, profile/edge counts and analysis keys; a Progress panel
  in the dashboard renders it, and the CLI prints progress lines.
- Risk signals in the case file: personatrace/features/risk.py
  computes a list (new account, avatar reuse, bio link to a new
  domain, coordinated pattern, username-variant cluster, follower
  imbalance), each with level, evidence and an innocent explanation.
  A list only, never a verdict, never an automated action. Shown in
  GUI (Risk & planner panel), HTML export and PDF export.
- Self-checking planner: personatrace/planner.py plans the next
  steps from evidence gaps (not_checked source -> add key, degraded
  -> re-run later, possible-match queue -> human review, bridge
  domain/avatar reuse -> human review, certificate subdomains ->
  consider new cases, alerts -> acknowledge). Steps needing a key
  or a human decision are marked human_required=True and are never
  executed automatically. Refreshed after clustering, so the queue
  entry is included. GUI Risk & planner panel shows it.
- LinkedIn depth: intentionally NOT built, with code to prove it —
  LinkedInAdapter returns not_checked with the reason (no general
  public profile search API; login-walled pages are not scraped),
  exactly as the blueprint says: do not promise LinkedIn depth.
- Every language: language identification now includes a stopword
  heuristic for major Latin languages plus script detection, and
  translation via LLM (if keyed) or the free MyMemory public API,
  one call per bio, original preserved, machine translation flagged.
- Continuous monitoring: CLI --watch --watch-interval-minutes N
  --watch-runs M re-runs inside the process (default daily, 0 =
  immediate for testing) and writes archive_history.jsonl (one JSON
  line per run with snapshots + monitor report) alongside
  monitor_report.json. Verified: 2-run watch gave 2 history lines
  and a monitor comparison.
- pHash formats: Pillow is now a required dependency in
  requirements.txt (JPEG/WebP/GIF/TIFF via Pillow, stdlib
  BMP/PNG/PPM fallback only if Pillow is missing).
- Bridge person (live): contacts from public GitHub following and
  Bluesky follows lists (capped 5 each) are collected; a contact
  appearing in 2+ seed profiles' lists is a bridge person. Verified
  live: octocat's GitHub following list fetched (tekkub, wonderchook,
  cheshire137, mdo, haileys); no bridge person in that single-cluster
  case, correctly reported as [] rather than invented.
- Activity caps are now configurable: CLI --domain-limit /
  --activity-limit, or env PERSONATRACE_MAX_DOMAINS /
  PERSONATRACE_MAX_ACTIVITY_PROFILES / PERSONATRACE_MAX_ACTIVITY_ITEMS
  (defaults 5 / 4 / 5, kept as rate-limit protection).
- Tests: 102 passed (93 in v1.2 + 9 new v1.3 tests).
- Still honestly not built / not promised: no keys are included, so
  YouTube and gated platforms (X, Instagram, Reddit, TikTok) remain
  not_checked until the investigator supplies a key + aggregator
  address; Reddit's public JSON was checked and is blocked without
  developer credentials, so it stays gated; YouTube transcripts
  depend on publicly listed captions; Telegram forum-style
  discussion content beyond the public channel page is not fetched.
  No face identification, no private access, no live person
  location, no bulk export, no bypass of any kind.

## v1.4.0-full — next full version (2026-10-29)
- Public comments: fetch_comments() — Hacker News comments by author
  (Algolia API), Bluesky replies via getPostThread, Mastodon replies
  via status context, YouTube commentThreads with a Data API key;
  gated platforms are not_checked for comments (aggregator profile
  endpoint does not expose threads; login pages are not scraped).
- Mentions: Hacker News search + Mastodon public search mentioning
  the seed; Bluesky searchPosts is degraded (403 in verification),
  never "no mentions". News/blog mentions via Google News public RSS.
- Hashtags/topics, full timeline (activity + account creation,
  sorted by date), topics/tone summary (word-list tone heuristic,
  labelled machine-made, plus LLM text when a key is configured).
- Follower/following + name changes in monitor_report.json, with
  new/disappeared activity alerts (disappeared items carry a caution
  to check source statuses first). Fixed a v1.4 bug where asdict()
  omitted analysis, which falsely flagged all activity as disappeared.
- Post-image OCR: activity image URLs (Bluesky embed images,
  YouTube thumbnails) are described (OCR when configured, else
  description) for up to 3 images per case.
- Captions for up to 3 YouTube videos (was 1), via public timedtext.
- GitHub social: public orgs (groups), public events, PR reviews
  via the public search API, and contributions by month/type.
- Forum posts beyond HN/Discourse: new StackOverflow adapter via
  the Stack Exchange API (exact display-name match only; verified
  live: Octocat found on a later run, degraded on a timed-out run).
- Work history: GitHub company/location evidence (public fields the
  user chose to show) collected into work_history.
- Website changes: Wayback CDX snapshot timestamps per bio domain
  (verified live for github.blog: 5 snapshot timestamps).
- Username history: no platform publishes a full history, so only
  changes across the investigator's own runs are recorded (monitor
  name_changes); earlier changes are never claimed.
- Contacts of contacts (level 2, capped at 3 contacts x 3 follows,
  leads only, never confirmed associates).
- Second-person comparison: CLI --compare-seed writes
  comparison.json (shared platforms/domains/contacts/hashtags);
  GUI POST /api/compare-cases does the same live (verified with
  demo data). Shared items are leads, never proof of identity.
- Analyst notes + checklist: Investigation.notes/checklist,
  CLI --note, default 6-item human-review checklist; notes appear
  in JSON/HTML/PDF exports (notes are investigator text, not evidence).
- Comment translation: non-Latin/non-English comments translated
  (LLM or MyMemory), original preserved, MT flagged, capped at 3.
- Spreadsheet export: export_case(fmt="csv") writes case.csv with
  provenance per row; CLI writes it every run, GUI /api/export?fmt=csv
  serves it (verified).
- Daily scheduled checks: watch mode + watch_summary.md (profiles,
  follower/name changes, new/disappeared activity, monitor alerts,
  cron example line) written on every monitored run.
- Tests: 106 passed (102 in v1.3 + 4 new v1.4 tests, including a
  regression test for the monitor activity bug above).
- Still honestly not built/not promised: no keys included, so
  YouTube comments and gated-platform comments stay not_checked
  without keys; Bluesky mentions degraded (searchPosts 403);
  GitHub events/reviews may be empty for accounts with no recent
  public activity (octocat: 0 events, 0 reviews — reported, not
  invented); post-image descriptions are empty when a case has no
  post images; LinkedIn depth still intentionally not promised.
  No face identification, no private access, no live person
  location, no bulk export, no bypass of any kind.

## v2.0.0-full — full version with all v1.4 gaps + new UI (2026-10-29)
New modules: features/v2.py (Soundex, short-name and cross-alphabet variants, site checks with reliable-404 + not-found phrases, capture hashes, Wayback profile snapshots + gaps, watchlist alerts for watched domains / new certificates / follower overlap, shortener + shared-link labels, SPF/DKIM via public DNS-over-HTTPS, Shodan/Censys key-gated, native-language entities, behaviour over time with posting hours / sleep gap / sudden shifts / tone change, machine photo descriptions beyond OCR, manual Lens/Yandex links, common-name proof bar, negative signals), storage/vault.py (ChaCha20 + PBKDF2-HMAC-SHA256 + HMAC encrypted key vault, passphrase-gated, names only in listings; roles viewer/analyst/admin), features/report.py (report draft, 1-hour public-response cache).
Wiring: analysis now returns v2_variants, site_checks, behaviour_over_time, native_entities, bio_link_labels, watchlist_alerts, quota_banner, wayback_profiles, dns_spf_dkim, shodan_censys, photo_descriptions, report_draft, common_name_check, cache note; transcripts attempted for up to 10 videos (was 3). Monitor now returns before_after view and deleted_notes with the preserved copy kept. CLI now writes report.md, rejected_matches.json (rejected candidates are not re-suggested on later runs), --watch-domains, --vault-store. GUI redesigned to the mockup layout (top bar with search + confidence slider + confirmed-only + Export, left Profile Summary, centre draggable Network Graph + Timeline scrub + Play that grows the graph over time, right Evidence + Alerts + review queue, plus Behaviour, Site checks / Wayback / Report draft panels, quota banner, export including report draft). AI: AILayer mode="local_model" (Ollama generate API or OpenAI-compatible local chat endpoint, no cloud key; localhost = data stays on the machine) in addition to cloud LLM with the investigator's own key. HTTP: 429/503 now waits slowly and retries at most twice (Retry-After, else 2s then 5s, capped 30s), then degraded — waiting for the limit, never bypassing it.
HONEST LIMITS (not faked, and shown as not_checked in the app, never as not found):
- Live Instagram, X, TikTok and Reddit WITHOUT a paid key cannot be done by any legitimate tool: their official APIs are priced/gated/research-only, Reddit public JSON/RSS returned 403 in live checks on 2026-10-29, and X/Instagram/TikTok profile pages are JS/login-walled. PersonaTrace does not scrape around those walls. The legitimate routes remain: a licensed aggregator key (already supported) or the official APIs with the investigator's own key. Gated adapters return not_checked without a key, with that reason.
- Google Lens and Yandex Images have no public search API, so PersonaTrace never scrapes their result pages. It gives a manual one-click link the investigator opens in their own browser, plus TinEye / Bing Visual Search with a key.
- No device fingerprinting and no credential-leak checking were added, even though the sample mockup showed "Device Fingerprint Match" and "Credential Overlap": those would identify a device or use leaked credentials, which are outside the public-data-only scope and the blueprint guardrails.
- Shodan/Censys, YouTube and gated platforms still need the investigator's own keys. LinkedIn depth is still intentionally not promised. Transcripts still depend on publicly listed captions. A local model still needs the investigator to run one (e.g. Ollama); the app does not bundle a model.

## v3.0.0-full — finishing the v2 gaps, one by one (2026-10-29)
Checklist: V3_CHECKLIST.md (41-item v2 list + 26-item missing list, each checked one by one, with Done vs Platform-limited marked honestly).
New: features/v3.py (Reddit Arctic Shift archive, archive.today secondary, real Censys API key-gated, SerpApi Lens/Yandex key-gated, AI vision description with people-ID forbidden, native NER heuristic, coordinated_v3 star/link-within-hour/bio-template signals, niche_overlap rarity weighting).
Wiring: score_pair now includes cross-script, niche network overlap, negative signals (up to -30, shown), common-name auto-merge bar raised to 90, account-age plausibility (>=5 years = negative); rejected-memory candidates skip re-resolution in engine and are recorded in resolution.rejected_ids; YouTube uploads paginated to PERSONATRACE_MAX_VIDEOS (default 50) with transcripts for every video in the case; Wayback for all profiles with a known template; site templates expanded to 152 (template_only, approximate URLs); cache actually used for site_checks (TTL 3600, fresh/cached reported); quota_per_source; GUI merge/reject/keep buttons + /api/review + /api/signoff + /api/users (local hashed-password accounts, local only, not network auth); CLI --live-check polling.
Honest limits (same as v2, plus): X/Instagram/TikTok without a key remain not_checked (no public API, JS/login-walled, not scraped); Reddit live remains not_checked without a key, archive is historical only; Lens/Yandex automated only via SerpApi key; vision only via investigator's AI key/local model; trained NER only via AI key/local model (heuristic NER is labelled as such); network-grade auth is out of scope for a local tool.

## v4.0.0-full — the 31-item list, one by one (2026-10-29)
Checklist: V4_CHECKLIST.md. User rule: investigator supplies own paid keys; if a source cannot be added free, add it as a key route per the guide. No keys bundled/invented.
New: features/v4.py (token buckets, generic cache, quota tracker, private terminal, survivorship, rejected-weight penalty, level-4 contacts, groups v4, Wayback diff/all, Archive.today all, curated lists + self-check, built-in heuristic NER/object signals, audio transcription route, push polling+webhook, entity confidence, uncapped media/comments with configurable cap default 20). Live reliable-404 checks expanded 6 -> 10 (verified 2026-10-29). GUI v4 panel + entity confidence. Server: POST /api/webhook, PBKDF2 user passwords + 24h session tokens.
Honest limits: gated/YouTube/Shodan/Censys/Lens/Yandex/LinkedIn need investigator keys; push is polling+webhook (no platform push feed for arbitrary profiles); built-in recognition/NER are heuristics, trained versions need AI key/local model; no face ID, no private access, no live location, no bulk export, no bypass.

## v5.0.0-full — the 10/10 improvements (2026-10-29)
Checklist: V5_CHECKLIST.md. Guide: USER_GUIDE.md (in ZIP root).
New: features/v5.py (key wizard check, error next-steps, signed HMAC chain, case registry/search/retention/redaction, official Sherlock 481 + WhatsMyName 692 shipped, Maigret download script, parallel map, resume targets), key_wizard.py, CLI --resume/--tag/--redact/--retention-days/--site-check-all/--parallel, GUI /api/keys/check + /api/cases + webhook audit, scripts/setup_local_model.sh/.bat, scripts/download_maigret.py, docker-compose.yml (Postgres+Neo4j), .github/workflows/ci.yml, integration tests (skipped without keys).
Honest limits: gated/paid routes need investigator keys to prove live; push is webhook+polling; bundled Whisper/Neo4j/Postgres clusters are not shipped; GUI polish is functional, not full mockup dark-mode design; full GUI localisation is not shipped.
