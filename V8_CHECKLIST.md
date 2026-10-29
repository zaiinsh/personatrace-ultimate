# PersonaTrace v8.0.0 — Checklist: scope, what was tested, honest limits

## Scope built in this version (on top of v7.0.0, v7 ZIP not overwritten)
All new code lives in `personatrace/features/v8.py` (pattern of v3–v7),
wired into `cli.py`, `gui/server.py` and the static GUI. Two small
shared edits: `adapters/free.py` (GitHub token header + 403 web
fallback) and `features/social.py` (configurable comment limit).

- [x] #1 Direct Profile Mode — seed type `profile` (+ `--direct` on
      url seeds, GUI toggle): parse (v7 hosts + GitLab/Twitch/Kick/
      Medium/Substack/Dev.to/SoundCloud/Vimeo/Flickr/Steam/Keybase/
      ProductHunt/PlayStation/Spotify + any Mastodon instance), then
      FETCH the exact profile: GitHub API (token + retry/backoff) →
      public-web OG fallback; GitLab/Bluesky/Mastodon-instance APIs;
      YouTube oEmbed; Reddit .json (stop on 403); aggregator route
      for Instagram/TikTok/X/LinkedIn with a key, else one public-web
      fetch, labelled gated_paid/blocked; ANY unknown host → generic
      OG fetch (never blank). Post URLs: exact post page fetched
      (OG/meta + SHA256), comments/likers NOT claimed without a key.
      Anchor = Profile status `confirmed_anchor`, graph centre
      (network_graph.centre), snapshot saved as
      direct_profile_snapshot.json/.html + SHA256 in the dossier, and
      profile_proof.png (a Pillow snapshot proof card — NOT a browser
      screenshot). Then normal username expansion (parallel) + all
      dossier features.
- [x] #2 GitHub-403 fix in the normal username adapter too: token
      from keys/env, and on API 403 one public-web fallback via the
      shared v8 helper (429 keeps the v2 slow-retry-then-degraded
      behaviour — the fallback never hammers a rate limit).
- [x] #3 Key verification harness: `verify_all_keys()` + CLI
      `--verify-keys` (writes key_verification.json) + GUI
      POST /api/keys/verify. Statuses: verified / invalid / blocked /
      present_unverified / not_checked.
- [x] #4 Gated full-data wiring: aggregator profile call requests
      posts, comments, followers, following, likers, stories,
      highlights (`include=` list in code) and parses them into the
      case. Mocked tests only — NOT live-proven (no key supplied).
- [x] #5 Name search without a key: free chain SearXNG public
      instance(s) → DuckDuckGo HTML, results labelled search_snippet,
      candidates capped ≤79 with innocent explanations (v7 machinery).
- [x] #6 Parallel runs: ThreadPool pre-run of adapter searches with
      per-source progress lines, cached results handed to the normal
      engine. Default 4 workers for v8 profile/company/wallet/plate
      runs and direct mode; sequential path unchanged.
- [x] #7 More free sources: 24 v8 site-presence/archive entries
      (Lemmy, Medium, Substack, Dev.to, Quora, Pinterest, Snapchat,
      Twitch, Kick, Steam, Xbox, PlayStation, Spotify, SoundCloud,
      Vimeo, Dailymotion, Flickr, Goodreads, Strava, Product Hunt,
      AngelList, Keybase, Gravatar + Reddit archive) — presence-check
      only unless a live check is explicitly run; a constructed URL
      is never a claim an account exists.
- [x] #8 Company seed: domain → fetch the site's own /, /about,
      /about-us, /team, /our-team, /company, /people (single hop);
      staff/author candidates are LEADS with source URLs; + domain
      investigation.
- [x] #9 Email depth: Gravatar linked accounts expanded one hop into
      parsed URL-seed leads.
- [x] #10 Smarter matching: score_pair_v8 adds shared bio-link
      domain, shared website, shared language, shared outbound links,
      and posting-hours overlap (fed in as the timing signal, so the
      core 25-point style/timing cap still applies) with explained
      drivers from the core scorer.
- [x] #11 Stronger variations: variations_v8 adds city, configurable
      birth-years, initials and first/last swap; every run records a
      variations_history audit entry (CLI --variation-city /
      --variation-years).
- [x] #12 Comment limit: --comment-limit / PERSONATRACE_COMMENT_LIMIT
      (default 100) wired into features/social.py collection (HN page
      size, YouTube maxResults, per-platform and total caps — the old
      fixed 5/20 sample caps are gone); per-source caps labelled.
- [x] #13 Follower/following overlap: real GitHub ID-set overlap +
      common followers (anchor vs --compare-seed, writes
      follower_overlap.json); not_checked when a free route returns
      no sets.
- [x] #14 Video section: public captions via the existing timedtext
      route for YouTube items; transcription-key / local-Whisper
      detection (configured-but-no-audio-route is labelled
      not_checked, never faked); title/description text as derived
      topics.
- [x] #15 Photo variant checks: original + centre-crop + resized
      whole-image pHash variants, threshold stated. Never face ID.
- [x] #16 Stories/highlights: aggregator-key route only
      (stories_highlights_section); gated_paid without a key.
- [x] #17 Archive upgrade: archive_diff returns Wayback snapshot
      list + archive.today as a second source, with change-tracking
      notes (a missing snapshot is not proof of deletion).
- [x] #18 Watch alert delivery: webhook POST, SMTP email (env
      config), Telegram (bot token + chat id) senders in
      send_watch_alert; every unconfigured channel returns
      not_configured.
- [x] #19 Graph levels 1–4 (anchor / profiles / contacts-of-contacts
      leads / shared domains) in the dossier network_graph, centre
      marker on the anchor.
- [x] #20 Coordinated upgrade: shared-rare-follower signal added to
      the crowd check, innocent explanations kept, verdict stays
      "pattern, not proof".
- [x] #21 Behaviour upgrade: reply-speed estimate (only items with
      both timestamps, denominator shown), posting-gap stats,
      topic/language shift over time.
- [x] #22 Impersonation finder: same display name + avatar hash, or
      display name + identical bio → lead with reasons + innocent
      explanations. Never an assertion.
- [x] #23 Scam/fraud signals: BTC/ETH address regex scan + links
      repeated across different accounts, from collected public text
      only, with innocent explanations.
- [x] #24 Wallet seed: BTC/ETH format validation, exact-address
      public-post search (HN + dork chain), and free public chain
      basics (Blockstream for BTC, Blockcypher for ETH) — address
      data only, never a person claim.
- [x] #25 Plate seed: public-post phrase search ONLY for the exact
      string. No vehicle database, no owner lookup — stated in the
      output itself.
- [x] #26 Case teamwork: assigned_to / lead_status fields on the v5
      case registry (CLI --assigned-to / --lead-status, GUI
      POST /api/cases/team, set_case_team()).
- [x] #27 Court-style report: court_report.md/.html — chronological,
      every fact with source URL, capture UTC, method, confidence,
      and the SHA256 of its evidence record; keys stripped.
- [x] #28 Proof: proof/ folder with one Pillow proof card (or JSON
      snapshot) per profile + proof_index.json with hashes. Cards
      are generated snapshot cards, never called screenshots.
- [x] #29 Offline mode: --offline CASE_DIR rebuilds dossier +
      exports from investigation.json with zero network calls
      (collectors disabled by construction, tested with urlopen
      rigged to raise).
- [x] #30 Mobile GUI: seed selector gains profile/company/wallet/
      plate + Direct Profile Mode toggle; new 480px CSS breakpoint
      stacks search/graph/panels full-width at ~390px (the v6/v7
      1100px/700px breakpoints are unchanged); GUI header v8.0.0.

## Tests
- Full suite (source tree): **209 passed, 4 skipped** (44 new v8
  tests in tests/test_v8_full.py, all network mocked; the 4 skips
  are the pre-existing key-gated integration tests). Two v7 tests
  had assertions coupled to the package/GUI version string; they now
  assert the v7 module/seed scope they actually cover, and the v8
  tests assert the v8.0.0 strings.
- Extracted-ZIP verification: see BUILD_REPORT.md (same suite run
  from the extracted copy + a live CLI run from it).

## Live results (2026-10-29, no keys supplied, this environment)
- username `octocat`: **7 profiles, 2 edges, 1 possible match**,
  dossier found (7). GitHub API returned 200 today (the v7 403 did
  not recur), so the web fallback was not needed live; it is proven
  by mocked tests (403 → OG profile, 403+web-fail → degraded).
- profile `https://github.com/octocat` (Direct Profile Mode):
  fetch_route **github_api**, status **found**, snapshot SHA256
  recorded, graph centre `github:octocat`, expansion **7 profiles,
  2 edges**, parallel per-source progress printed;
  direct_profile_snapshot.json + profile_proof.png + court_report +
  proof/ all written.
- ip `8.8.8.8`: v7 ip section **found** (RDAP + Shodan InternetDB),
  0 profiles (those are domain/infra records, not a person).
- hashtag `osint`: **found**, 30 posts in the section, 3 profiles.
- wallet `1A1zP1…fNa` (BTC genesis address): chain basics **found**
  via Blockstream (tx_count 67172 at run time), public-post search
  found 5 HN items.
- plate `ABC-123`: public-post search **found**, 10 HN items whose
  text contains the exact string (that is all a plate seed does).
- name `Barack Obama` + context USA, no key: free chain ran
  (searxng_public → duckduckgo_html) and returned **not_checked,
  0 candidates** in this environment — the free chain is fragile,
  exactly as labelled; with a search key the v7 keyed route applies.
- company `example.com`: homepage found, /about /team-style paths
  404, **0 staff candidates** (example.com publishes none); domain
  investigation found 7 infra/domain profiles.
- `--verify-keys` with no keys: **17 providers, all not_checked**,
  key_verification.json written. That IS the honest result without
  keys.
- `--offline` on the octocat case: rebuild **found**, dossier
  version 8.0.0, public_web {} (zero network), court report written.
- GUI on a clean port: HTTP 200, header v8.0.0, seed selector shows
  the v8 types + direct toggle; POST /api/keys/verify returns all
  not_checked; POST /api/cases/team returns an honest not_found
  when no case registry exists.

## Honest limits
- Key routes (HikerAPI/aggregator full data incl. stories and
  highlights, YouTube, search APIs, Shodan full, VirusTotal, TinEye,
  transcription, etc.) are wired and mock-tested, but NOT proven
  live: no investigator key was supplied during verification.
  Providers with no cheap verification endpoint are
  "present, unverified" by design.
- The GitHub web fallback gives derived OpenGraph fields only — no
  follower counts, no dates, no bio links. It is a fallback, not a
  replacement for the API or a token.
- Name-search free fallbacks (public SearXNG instances, DDG HTML)
  are fragile: instances rate-limit, HTML layouts change, and the
  live run above returned not_checked. A search key remains the
  reliable route.
- Direct Profile Mode on Instagram/TikTok/X/LinkedIn without an
  aggregator key is one public-web fetch — usually blocked or
  OG-only, labelled gated_paid/blocked. Post comments/likers are
  never claimed without a key route returning them.
- The 24 v8 site-presence entries are URL-pattern checks: presence
  only, some services (Strava numeric IDs, Xbox gamertag URL) are
  approximate patterns a human must open and verify.
- Wallet chain basics describe an address, not a person; plate
  search finds public posts containing a string, nothing more.
- GUI live search remains slow (tens of seconds) — it runs all
  adapters; parallel mode helps adapter collection only.
- Stays out: phone people-search, password/breach dumps, private
  profiles/DMs, live location, face identification, bulk
  personal-data export, CAPTCHA/rate-limit/login-wall bypass, port
  scans. No keys are included in this package.
