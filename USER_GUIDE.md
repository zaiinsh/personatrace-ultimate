# PersonaTrace Ultimate — User Guide (v9.0.0)

## What this is
A local, public-data-only social profiler. Type a username, it checks
public profiles, builds a graph, scores matches with reasons you can
audit, and writes a full dossier you can export. It never accesses
private accounts, DMs, live location, or faces to identify people.
It never bypasses a login wall, CAPTCHA, or rate limit, and never
signs requests to evade a platform's protections.

## Quick start (5 minutes)
1. Unzip the project. You need Python 3.12 or newer.
2. Open a terminal in the unzipped folder.
3. Optional, for full images and PDFs: `pip install Pillow reportlab`
4. Run a case:
   - Windows: `python -m personatrace.cli --seed octocat --out live_out`
   - Mac/Linux: `python3 -m personatrace.cli --seed octocat --out live_out`
5. Open `live_out/dossier.html` and `live_out/dossier.md` for the dossier,
   `live_out/case.html` for the case view. Other files:
   `investigation.json` (full data), `case.json`, `case.pdf`, `case.csv`,
   `dossier.json`, `dossier_profiles.csv`, `dossier_edges.csv`, `report.md`.

## GUI in a browser
```
python -m personatrace.gui.server --port 8787
```
Then open http://127.0.0.1:8787/ . The browser is only the screen;
the app runs on your own computer. Type a username, click Search live,
review Possible Matches with Merge / Reject / Keep separate, then
Export. A human must click Sign off before a report is marked signed.

Note on the initial dashboard: before any live search it shows clearly
labelled demo data. After a live search, every panel shows THAT live
result — even a 0-profile result, which shows "No profiles found,
routes tried" and never demo data again.


## Seed types (v7) — not just username
Set with `--seed-type` in the CLI, or the Type selector in the GUI.
The GUI also auto-detects: paste an email and it runs as an email seed.

| Seed type | Example | What runs |
|---|---|---|
| `username` | `octocat` | v6 cross-platform profile search (unchanged) |
| `domain` | `example.com` | v6 domain / infra scan (unchanged) |
| `email` | `name@example.com` | Format validation, domain extracted → domain/infra scan, Gravatar public profile (hash only sent to Gravatar; only display name, profile URL and public linked accounts from Gravatar's own response), one exact-email dork `"email"` via a search key if present (snippets only, else not_checked). No password, breach, or leak data, ever. |
| `name` | `Jane Example` + `--seed-context "Berlin, Acme"` | Search/dork candidates only. Every candidate goes to the candidate review queue with confidence (capped), reasons, and innocent explanations. A name match is never a certain identity. |
| `url` | a post / profile URL | URL parsed locally (platform, kind, author handle). Author follow-on username search runs. YouTube videos also get free oEmbed. Instagram/TikTok/X item fetch is gated_paid without an aggregator key. Image URLs route to the image seed. |
| `image` | an image / avatar URL | Same-photo reuse: download, pHash, OCR + description, compare with avatars already held, reverse image with a TinEye/Bing key, manual Lens/Yandex links. Never face identification. |
| `hashtag` | `#osint` | Mastodon public hashtag timeline + HN search (free), accounts using it, coordinated check input. Instagram/X/TikTok grids are gated_paid. |
| `phrase` | `"exact phrase"` text | HN exact-phrase search (free) + a dork query when a search key is present. |
| `ip` | `8.8.8.8` | Passive only: RDAP + Shodan InternetDB (free). No port scan. An IP does not identify a person in this tool. |
| `auto` | anything | Detects email / URL / IP / hashtag / domain / phrase / username, in that order. Multi-word auto seeds are phrases — pick `name` explicitly for a person. |
| `multi` | `a@example.com; 8.8.8.8; octocat` | `;`-separated sub-seeds in ONE case file, merged with per-seed provenance. Profiles are collected, NOT identity-merged — a human confirms any link (candidate review queue). |

Examples:
```
python3 -m personatrace.cli --seed name@example.com --seed-type email --out email_out
python3 -m personatrace.cli --seed "Jane Example" --seed-type name --seed-context "Berlin, Acme" --out name_out
python3 -m personatrace.cli --seed https://github.com/octocat --seed-type url --out url_out
python3 -m personatrace.cli --seed 8.8.8.8 --seed-type ip --out ip_out
python3 -m personatrace.cli --seed "#osint" --seed-type hashtag --out tag_out
```

## What's new in v9 — the no-key upgrades

**Name search works without a key now.** `--seed-type name` runs a
shared free search chain (public SearXNG instances → DuckDuckGo lite →
DuckDuckGo html → Bing HTML → Brave HTML — every result labelled
`search_snippet` with the engine that returned it) and merges real
free-API candidates from GitHub user search and GitLab user search.
Candidates are still capped at 79% confidence, carry reasons and
innocent explanations, and wait in the review queue. Dorking
(exact-email / exact-phrase) uses the same chain. Free engines are
fragile: in the v9 live proof SearXNG and DuckDuckGo returned nothing
and Bing HTML answered — the dossier records which engines were used.

**Screenshots (real browser proof).** Add `--screenshots` to a CLI run
or tick "Browser screenshots as proof" in the GUI: Playwright/Firefox
opens the anchor + collected profile pages and saves PNGs to
`proof_shots/`, each with SHA256 + capture time in `proof_index.json`
and `proof_type: "browser_screenshot"`. Needs `pip install playwright`
and `playwright install firefox`. Without a browser, the v8 snapshot
proof cards are used and stay labelled `snapshot_card` — a card is
never called a screenshot.

**Transcription (no key).** For YouTube items the app reads the
video's public caption track: watch page → timedtext. On networks
where YouTube returns empty timedtext bodies (verified live), an
optional `pip install yt-dlp` enables a second route to the same
public captions. For audio files, a locally installed Whisper engine
is detected automatically; install it with `scripts/setup_whisper.sh`
(one command; the tiny model downloads once, ~75 MB, then everything
is offline). No captions and no Whisper = `not_checked`, never a
made-up transcript.

**Local NLP (no cloud).** Every dossier carries a `local_nlp` section
(persons / organisations / places / languages / topics) produced by a
deterministic offline pack. For a trained model, run
`scripts/setup_local_nlp.sh` once (spaCy + en_core_web_sm, ~12 MB) —
the app auto-detects it and labels results with the model name. A
large trained model is deliberately NOT bundled in the ZIP (size).

**Speed & consistency.** Username runs are parallel by default with a
soft `--time-budget` (default 30s): adapters that miss the budget are
marked `degraded_timeout` instead of blocking. Repeat runs of the
same seed within 1 hour are served from a labelled result cache
(`--no-cache` bypasses). The dossier timing splits adapter time from
engine/analysis time — analysis is the slow phase on live runs. Every
dossier has a `run_fingerprint`; check determinism yourself with
`--consistency-check` (runs the seed twice, writes consistency.json,
and explains any difference — intermittent sources like crt.sh do
cause real differences, and they are shown, not hidden).

**Site checks you can trust more.** Site checks now need two signals
to agree (HTTP status + page body) before saying `found`;
disagreement is `uncertain`. Audit the checker itself any time with
`--site-check-audit` (known-existing + known-nonexisting handles per
sampled site; writes site_check_audit.json with real false-positive /
false-negative counts). `--site-adapters` runs the 24 classified
site adapters (Dev.to, Lemmy, Medium, Keybase, SoundCloud, … — see
FULL_FEATURE_LIST.md for the data/meta/presence classification).

**Real contact graph.** For GitHub anchors the dossier's
`graph_levels_real` has real level-3 nodes (followers/following,
capped at 30 per list) and level-4 shared bio-link domains.

**Benchmark.** `python scripts/benchmark.py` re-runs the shipped
BENCHMARK.md (23 real public usernames + 3 nonexistent controls).

**Installer.** End users: see INSTALL.md (download, unzip,
double-click). Builders: `packaging/build_installer.sh` (or .bat /
_macos.sh) produces a single `PersonaTrace` executable via
PyInstaller. `run_personatrace.py` is the double-click launcher from
source.

**GUI languages.** The header language selector switches all UI
labels between English, Urdu, Arabic, Spanish, French and German
(Urdu/Arabic switch the layout to right-to-left). The choice is
remembered in your browser. Only the interface chrome is translated —
investigation results stay in their original language.

New flags:
```
python3 -m personatrace.cli --seed octocat --screenshots --site-adapters --out rich_out
python3 -m personatrace.cli --seed octocat --consistency-check --out consistency_out
python3 -m personatrace.cli --seed octocat --site-check-audit --out audit_out
python3 -m personatrace.cli --seed octocat --time-budget 45 --no-cache
```

## What's new in v8 — Direct Profile Mode and more

**Direct Profile Mode** (`--seed-type profile`, or `--direct` with a
profile/post URL, or the GUI "Direct Profile Mode" toggle): give the
app ONE exact profile link. It fetches that exact profile first —
GitHub via its API (your GitHub token is used automatically when set;
on a 403/429 it retries with backoff, then falls back to the public
profile page's OpenGraph fields), GitLab/Bluesky/Mastodon via their
public APIs, YouTube via oEmbed, Reddit via its public .json (stops
honestly on 403), Instagram/TikTok/X/LinkedIn via your aggregator key
or one public-web fetch labelled gated_paid/blocked, and ANY other
site via a generic OpenGraph fetch of the exact page (unknown sites
no longer return blank). The fetched profile is anchored as
`confirmed_anchor` — you supplied it, so it exists; whether it is the
same person as other profiles still goes through normal confidence
scoring and your review. The case folder gains
`direct_profile_snapshot.json` (or .html) with its SHA256 in the
dossier, and `profile_proof.png` — a generated snapshot proof card,
NOT a browser screenshot. Post URLs also fetch the exact post page
(OpenGraph + hash); comments/likers are only reported when an
aggregator key actually returned them.

New seed types: `company` (staff/author leads from a company's own
public about/team pages + domain scan), `wallet` (BTC/ETH address:
public posts mentioning it + public chain basics — address data,
never a person claim), `plate` (public-post search for the exact
plate string only — no vehicle database, no owner lookup exists).

New flags:
```
python3 -m personatrace.cli --seed https://github.com/octocat --seed-type profile --out direct_out
python3 -m personatrace.cli --seed octocat --verify-keys --out verify_out   # key_verification.json, no investigation
python3 -m personatrace.cli --seed octocat --offline /path/to/case --out rebuilt_out  # zero network rebuild
python3 -m personatrace.cli --seed octocat --comment-limit 200 --variation-city Lahore --variation-years 1990,1994
python3 -m personatrace.cli --seed octocat --compare-seed hubot             # + follower_overlap.json (GitHub sets)
python3 -m personatrace.cli --seed octocat --assigned-to zain --lead-status open
```
Every v8 case also exports `court_report.md` / `court_report.html`
(chronological, every fact sourced and hashed) and a `proof/` folder
with hashed snapshot proof cards + `proof_index.json`. Watch alerts
can be delivered by webhook (PERSONATRACE_ALERT_WEBHOOK_URL), email
(PERSONATRACE_SMTP_* + PERSONATRACE_ALERT_EMAIL_TO), or Telegram
(TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID) — unconfigured channels
report not_configured. Name search now falls back to free SearXNG /
DuckDuckGo HTML when no search key is set (fragile, snippets only).

## Exports (v7 additions)
Every case now also exports `maltego.csv` (Maltego entity import) and an
Obsidian case folder (`obsidian-<seed>/index.md`, `profiles/*.md`,
`timeline.md`), alongside the v6 JSON / CSV / Markdown / HTML dossier.
Keys are stripped from all exports.

## API keys you can add (v7 catalog)
Run `python -m personatrace.key_wizard --verify` (add `--save` to store).
Catalog: HikerAPI/aggregator, YouTube, Brave, Tavily, Serper, SerpApi,
Google PSE (+cx), GitHub token, Shodan, VirusTotal, SecurityTrails,
urlscan.io, TinEye, Bing Visual Search, SerpApi Lens/Yandex, email
verification (public verification only), and an OpenAI-compatible AI key
or Ollama local model (vision/NER/tone/translation only — an AI key never
substitutes for a platform key). Verification/catalogue listing does not
mean a provider is live-proven without your own key.

## Keys — key-first architecture (v6)
Free sources work with no key: GitHub, GitLab, Bluesky, Mastodon,
Hacker News, StackOverflow, Telegram public channels, Wayback, DNS, crt.sh,
plus public-web fallbacks for Instagram/X/TikTok (see below).

Gated sources need a key, which the investigator supplies. Add keys with:
```
python -m personatrace.key_wizard          # ask, never print back
python -m personatrace.key_wizard --verify # verify each key against its provider (one cheap call)
python -m personatrace.key_wizard --save   # save to local vault .personatrace_keys.json (0600, git-ignored)
```
Or in GUI Settings > API Keys, or as environment variables.
Keys are never bundled in the ZIP, never invented, never logged, and
never included in any export (dossier exports strip key-like fields).

| Key / env | Unlocks |
|---|---|
| `HIKERAPI_KEY` (hikerapi_key) | Instagram profile, posts, followers/following, comments, likers via HikerAPI — the aggregator route, runs first for Instagram when verified |
| `PERSONATRACE_AGGREGATOR_KEY` + `PERSONATRACE_AGGREGATOR_BASE_URL` | Instagram, X, TikTok, Reddit live via a licensed aggregator |
| `YOUTUBE_API_KEY` | YouTube channels, videos, comments, captions (100 units/search) |
| `BRAVE_SEARCH_KEY` / `TAVILY_API_KEY` / `SERPER_API_KEY` | Search/dork queries (site:instagram.com etc.) — snippets only, unverified until opened |
| `GITHUB_TOKEN` | GitHub 5,000 req/hour instead of 60/hour |
| `SHODAN_API_KEY` | Full Shodan host search (InternetDB below is the free no-key subset) |
| `SERPAPI_API_KEY` | Automated Google Lens + Yandex Images search |
| `CENSYS_API_ID` + `CENSYS_API_SECRET` | Censys host search |
| `LLM_API_KEY` / `OPENAI_API_KEY` | AI vision, trained NER, tone/topic |
| `TRANSCRIPTION_API_KEY` | Audio transcription for videos with no listed captions |

Without the relevant key, that source shows **not_checked** — never
"not found". Check keys in the GUI: POST /api/keys/check (names only).

### Cost preview + spend cap
Before a run, the GUI cost panel and the CLI "Cost before run" list
show which sources are active, which keys are missing, and estimated
units. HikerAPI is estimated at ~$1 per 1,000 requests in 2026 vendor
round-ups (verify the provider's current price at setup; pagination is
billed separately). Use `estimate_cost()` in features/v6.py to check a
plan against a cap before running; if the estimate exceeds the cap,
abort and reduce requests or raise the cap deliberately.

## Free fallback routes (in order, per field)
1. **Key route first** — if a verified key exists for that field, it runs first.
2. **Official free API** — GitHub, Bluesky public AppView, Mastodon public API,
   Hacker News Firebase+Algolia, YouTube oEmbed/RSS, Wayback CDX, Common Crawl CDXJ,
   crt.sh, RDAP, DNS, Shodan InternetDB (no key, weekly data, not a port scan).
3. **Public web** — Instagram `web_profile_info` (via curl_cffi if installed,
   else browser-UA HTTP), TikTok public page SIGI_STATE parse (only accepted
   when the page carries the seed as its uniqueId), X public page title
   (only accepted when the title carries (@seed)). Single-threaded,
   >=3-5s spacing in production, stop on 429/CAPTCHA/login wall.
4. **Search/dorking** — Brave/Tavily/Serper key first (capped queries),
   else self-hosted SearXNG, else fragile DuckDuckGo HTML fallback.
   Every result is labelled `search_snippet` and is unverified until opened.
   Dorks used: `site:instagram.com "<seed>"`, `site:tiktok.com/@<seed>`,
   `site:x.com "<seed>"`, plus GitHub/LinkedIn/cross-platform variants.
5. **Consented login opt-in** (separate screen, see below) — read-only,
   throwaway account only.
6. **Labelled status** — if no route returned data, the field is labelled
   `not_checked`, `blocked`, `gated_paid`, `gated_login`, `private`,
   or `not_found` (source answered: no such account). Never synthesised.

## Login opt-in (Instagram, separate from keys)
```
python -m personatrace.key_wizard --login-consent
```
You must type exactly: `I understand this may ban this account`
Only a consent record is stored (no password, ever). Then provide a
session file, not a password:
- Instaloader: `instaloader --login=YOUR_THROWAWAY --sessionfile=...`
  (session cookie stored, password not stored)
- instagrapi: `dump_settings` / `load_settings` session reuse
If no login library or session file is present, the route returns
`gated_login` with the exact steps to enable it — never fake data.
Warnings: this uses Instagram's private/web API against its Terms;
use a throwaway/research account only, never a primary account;
read-only (no follow/like/comment/DM/post); the account may be
challenged or banned; stop on challenge/429.

## Full dossier sections (filled only from collected data)
- **Profile summary** — field table, no LLM-written biography.
- **Bio links** — expanded one hop only (destination title + anchors).
- **Network graph** — edges only from observed follows/comments/tags/
  mentions/same-handle-unverified. No edge from a snippet alone.
- **Timeline** — merged, deduped, denominator stated (e.g. "20 posts
  collected of 312 total" or "total unknown").
- **Interests** — Counter over collected sample only, N stated
  ("top hashtags in 20 collected captions"). Never a persona.
- **Public comments** — capped samples from collected posts only.
- **Mentions** — by-target vs of-target kept separate.
- **Work history** — sourced rows only (GitHub company/location,
  bio-link about page, search snippet with URL). No row without a source.
- **Follower/following overlap** — only when two ID sets exist (target +
  a second handle you supply, both collected via key/login). Otherwise
  not_checked. Bulk follower contact export is prohibited.
- **Archive snapshots** — Wayback CDX + Common Crawl for profile URLs
  and bio-link domains actually found.
- **Domain/infra** — only for domains actually found in bio links/posts.
  RDAP, DNS, crt.sh, InternetDB (passive only, no active port scan;
  registrant identity is redacted in RDAP and is never unmasked).
- **Exports** — JSON + CSV + Markdown + HTML, provenance per field,
  keys never included, single-case only.

## Status taxonomy (on every field)
`found` = source answered and returned the field.
`not_found` = source answered: account/field does not exist.
`not_checked` = route not configured or not attempted.
`blocked` = 429 / login wall / CAPTCHA / challenge — stopped, not bypassed.
`gated_paid` = needs a paid/aggregator key not supplied.
`gated_login` = needs a consented login not enabled.
`private` = account/field is private; no attempt to bypass.
`search_snippet` = from a search snippet only; open the source to verify.
`derived` = computed locally from collected items only (counts, frequencies).

## Honest limits (read before relying on a dossier)
- Instagram/X/TikTok full data (followers list, full comments, likers,
  stories) need an aggregator key or a consented throwaway login;
  without either they are gated, not "not found", and not 100%.
- Search snippets are unverified until opened; absence from search is
  not absence from the platform.
- Private profiles: header only if public; no private content attempted.
- No face identification, no live location, no bulk personal-data export,
  no active port scanning, stop on 429/CAPTCHA/login wall, no request signing.
- Instagram public web is IP-dependent and throttled; TikTok SIGI_STATE
  and X public pages change often. A route that worked today may return
  blocked tomorrow — that blocked status is the honest result.
- A handle that exists only on Instagram will legitimately have thin
  non-Instagram sections. That thinness is the finding, not a failure to fake.
- Local model, no cloud key: install Ollama, then
  `bash scripts/setup_local_model.sh` (or .bat on Windows), set
  `PERSONATRACE_LOCAL_MODEL_URL=http://localhost:11434`.
- Live updates: polling (`--live-check`) + webhook receiver (`POST /api/webhook`);
  no platform offers a push feed for arbitrary profiles.
- Case management, signed evidence (HMAC chain), redaction, retention,
  Postgres/Neo4j migration: see V5_CHECKLIST.md and the CLI help.
