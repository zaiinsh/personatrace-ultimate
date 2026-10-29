# PersonaTrace v9.0.0 — Full Feature List

Version everywhere (package, GUI header, guide, checklist): **9.0.0**

Everything in the v8 list below remains, unchanged. v9 adds the 16
no-key items from the 10/10 list (the 9 key-gated items keep their
v8 wiring and are unchanged):

## v9 — works with NO API keys
- **Name search that returns real candidates**: one shared free
  search chain (public SearXNG instances → DuckDuckGo lite → DDG
  html → Bing HTML (redirect links unwrapped) → Brave HTML; every
  result labelled search_snippet with its engine) PLUS real free-API
  candidates (GitHub user search, GitLab user search). Candidates
  capped at 79, with reasons + innocent explanations + review queue.
- **Dorking on the same chain** (`dork_v9`): exact-email / exact-phrase
  dorks without a key; a search key still wins when one exists.
- **24 site adapters, classified**: 9 data_adapter (Dev.to, Lemmy,
  Dailymotion, Medium RSS, Keybase, Gravatar, Reddit archive,
  SoundCloud oEmbed, Vimeo oEmbed), 7 meta_adapter (Substack, Flickr,
  Twitch, Steam, Product Hunt, Spotify, Goodreads — OG/oEmbed fields,
  and the meta must mention the username or the result is only
  "uncertain"), 8 presence_only with a written reason each (Quora,
  Pinterest, Snapchat, Kick, Xbox, PlayStation, Strava, AngelList).
- **Verified site checks**: two-signal rule (HTTP status AND body
  signal must agree; disagreement = uncertain, never found) +
  `--site-check-audit` live self-audit writing site_check_audit.json.
- **Backup routes**: disk cache (24h, age-labelled) behind GitHub,
  Wayback (+ archive.today route), crt.sh (double-attempt); DNS-over-
  HTTPS behind the system resolver. **run_fingerprint** in every
  dossier + `--consistency-check` (run twice, diff, explain).
- **Real browser screenshots as proof**: Playwright/Firefox captures
  to proof_shots/ with SHA256 + UTC in proof_index.json, typed
  "browser_screenshot"; the v8 snapshot cards stay the fallback and
  keep their own label. CLI `--screenshots`, GUI toggle.
- **Built-in transcription**: YouTube public captions (timedtext,
  with an optional yt-dlp route for networks where timedtext returns
  empty bodies) + local Whisper detection + scripts/setup_whisper.sh.
- **Built-in local NLP**: deterministic offline pack (gazetteers,
  person/org/place rules, language ID incl. Urdu/Arabic script,
  topics) in every dossier; spaCy + en_core_web_sm auto-detected
  when installed via scripts/setup_local_nlp.sh (a large trained
  model is not bundled — size).
- **Speed**: parallel by default, per-adapter soft timeouts +
  `--time-budget` (default 30s; slow adapters become
  degraded_timeout), 1-hour result cache (labelled), timing split
  (adapters vs engine/analysis) recorded in the dossier.
- **Real 4-level graph**: GitHub followers/following (capped) are
  real level-3 nodes; level-4 = bio-link domains shared by ≥2
  sampled level-3 accounts.
- **Benchmark**: scripts/benchmark.py — 23 real public usernames +
  3 nonexistent controls, BENCHMARK.md shipped with real numbers.
- **One-click installer**: packaging/ (PyInstaller spec + build
  scripts for Linux/Windows/macOS), run_personatrace.py launcher,
  INSTALL.md (3 end-user steps).
- **GUI**: dark theme refined to mockup level; v9 toggles (Direct,
  screenshots, result cache); **6 UI languages** (English, Urdu,
  Arabic, Spanish, French, German) with RTL for Urdu/Arabic and
  localStorage persistence — UI chrome only, live content untranslated.
- New CLI flags: `--time-budget`, `--no-cache`, `--site-check-audit`,
  `--consistency-check`, `--screenshots`, `--site-adapters`.

## Honest v9 limits (full detail in V9_CHECKLIST.md)
Key routes are still not live-proven (no keys exist here). Free web
search engines are fragile — SearXNG/DDG returned nothing in the
live proof and Bing HTML carried the result. A full octocat case
took ~81s of adapter+analysis time live (over the 30s budget — the
analysis phase, not adapter collection, is the slow part; see the
timing split in the dossier). Two consecutive octocat runs did NOT
produce identical fingerprints (intermittent crt.sh-derived domain
candidates) — the fingerprint exists to show exactly that.

---

# PersonaTrace v8.0.0 — Full Feature List (historical section)

Everything in the v7 list below remains, unchanged. v8 adds:

## Seeds (4 new types — CLI `--seed-type` + GUI selector)
- profile — **Direct Profile Mode**: fetch the exact profile first
  (GitHub API w/ token+retry → public-web fallback; GitLab / Bluesky /
  Mastodon-instance APIs; YouTube oEmbed; Reddit .json; aggregator
  route for Instagram/TikTok/X/LinkedIn with a key; generic OpenGraph
  fetch for ANY other/unknown host), anchor it `confirmed_anchor` as
  the graph centre, snapshot it (SHA256 + direct_profile_snapshot +
  Pillow proof card), then expand by username and run every dossier
  feature. Also `--direct` on a url seed / GUI Direct toggle.
- company — domain: staff/author LEADS from the site's own public
  /about /team-style pages (single hop, source URLs) + domain scan
- wallet — BTC/ETH address: format validation, exact-address
  public-post search, free public chain basics (address data only)
- plate — public-post phrase search for the exact string ONLY
  (no vehicle database, no owner lookup)

## v8 upgrades
- GitHub-403 fix everywhere (token + retry/backoff + web fallback)
- Key verification harness: `--verify-keys` / GUI /api/keys/verify —
  verified / invalid / blocked / present_unverified / not_checked
- Gated full-data wiring: aggregator fetch requests posts, comments,
  followers, following, likers, stories, highlights
- Name search free fallbacks: SearXNG → DuckDuckGo HTML (snippets)
- Parallel adapter runs (ThreadPool, per-source progress)
- 24 extra site-presence/archive entries (presence-check only)
- Email depth: Gravatar linked accounts → URL-seed leads
- Smarter matching signals: shared bio-link domain / website /
  language / outbound links / posting-hours (timing cap kept)
- Stronger username variations: city, birth-years, initials, swap,
  with a variations_history audit entry
- Configurable comment limit (default 100) in comment collection
- GitHub follower/following overlap + common followers (real sets)
- Video section: public captions route, transcription key / local
  Whisper detection, title/description topics (never fake)
- Photo variants: centre-crop + resized pHash reuse checks
- Stories/highlights: aggregator-key route only
- Archive diff: Wayback + archive.today
- Watch alerts: webhook / SMTP email / Telegram senders
- Graph levels 1–4 with the anchor as centre
- Coordinated check + shared-rare-follower signal
- Behaviour: reply speed, posting gaps, topic/language shift
- Impersonation finder (leads) · scam signals (wallets/shared links)
- Case teamwork: assigned_to / lead_status on the case registry
- Court-style report (chronological, sourced, hashed) + proof/
  folder with hashed snapshot proof cards (not screenshots)
- Offline mode: rebuild a case with zero network calls
- Mobile GUI (~390px) + v8 seed types and Direct toggle in the GUI

---
# PersonaTrace v7.0.0 — Full Feature List

Version everywhere (package, GUI header, guide, checklist): **7.0.0**

## Seeds (11 types, CLI `--seed-type` + GUI selector + auto-detect)
- username, domain — v6, unchanged
- email — validation, domain→infra scan, Gravatar public profile (hash lookup,
  public fields only), exact-email dork (search key; snippets only)
- name (+ `--seed-context` city/company) — search candidates, review queue
- url — profile/post URL parse (12 hosts), author follow-on, YouTube oEmbed
- image — same-photo pHash reuse, OCR/description, reverse image (key),
  manual Lens/Yandex links; **never face identification**
- hashtag — Mastodon timeline + HN (free), accounts-using-it, coordinated input
- phrase — HN exact phrase (free) + dork with a search key
- ip — RDAP + Shodan InternetDB (free, passive only, no port scan)
- auto — email > URL > IP > hashtag > domain > phrase > username
- multi — `;`-separated sub-seeds, one case, provenance per seed, collected
  not identity-merged

## APIs / keys an investigator can add (key wizard, verify-where-cheap, cost preview)
HikerAPI / generic licensed aggregator · YouTube Data API · Brave · Tavily ·
Serper · SerpApi (search + Lens/Yandex) · Google PSE (+cx) · GitHub token ·
Shodan full · VirusTotal · SecurityTrails · urlscan.io · TinEye · Bing Visual
Search · email verification APIs (public verification only) · OpenAI-compatible
AI key / Ollama local model (vision, NER, tone, translation only).
Free, no key: GitHub, GitLab, Bluesky, Mastodon, Hacker News, StackOverflow,
Telegram public, Wayback, Common Crawl, crt.sh, RDAP, DNS, Shodan InternetDB,
Gravatar, YouTube oEmbed/RSS.

## Elite / investigation features
- Key-first architecture, local vault 0600, per-provider verification state,
  cost preview + per-run spend cap (all from v6, catalog extended in v7)
- Provenance/status on every field: found / not_found / not_checked / blocked /
  gated_paid / gated_login / private / search_snippet / derived
- Fallback order per field: key route → free official API → public web →
  search/dork → consented throwaway login opt-in → honest label
- Candidate review queue for name/email + possible matches, each with
  confidence, reasons, and an innocent-explanation checklist
- Pin-able evidence (every profile carries source URLs), timed analyst notes,
  audit trail — extended to all new seed types
- Monitoring / watch mode for any seed type (CLI `--watch`, daily diff summary)
- Behaviour over time, timeline (with sample denominator), interests
  (Counter over collected sample, N stated), network graph (observed edges
  only), follower/following overlap (only with two collected ID sets),
  coordinated-network check — fed by the new seeds where they return posts
- Exports: dossier JSON, profiles CSV, edges CSV, Markdown, HTML, case
  HTML/JSON/PDF/CSV, **Maltego CSV**, **Obsidian case folder**; keys stripped
- GUI: seed selector (11 types) + auto-detect (email-shaped seed), name-context
  field, paste-a-link seed field (same input, URL type), keys grouped by
  category, provenance/status filter, candidate queue in the dossier

## Hard limits — stays out
Phone people-search · password / breach-dump search · private profiles or DMs ·
live location · face identification · bulk personal-data (contact) export ·
CAPTCHA / rate-limit / login-wall bypass · request signing · active port scans.
