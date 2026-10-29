# PersonaTrace v9.0.0 — Checklist: the 16 no-key items, real test counts, real live numbers, honest limits

Scope: ONLY the 16 no-key items from the 10/10 list, built on v8.0.0
(features/v9.py; v8 code unchanged except where noted). The 9 key-gated
items keep their v8 wiring, untouched and still not live-proven.
Guardrails unchanged: public data only, no face ID, no private/DM,
no live location, no CAPTCHA/rate-limit/login-wall bypass, no port scans.

## Per-item status

1. **Name search without a key — DONE.** One shared free chain
   (SearXNG public instances → DuckDuckGo lite → DDG html → Bing HTML
   → Brave HTML; results labelled search_snippet, engine recorded,
   Bing redirect links unwrapped) + real free-API candidates
   (GitHub user search, GitLab user search). Candidates ≤79, reasons,
   innocent explanations, review queue. LIVE: "Barack Obama" (Chicago)
   → **20 candidates**, "Linus Torvalds" (Linux) → **20 candidates**;
   engines that answered: **bing_html + the two APIs**. SearXNG and
   DuckDuckGo returned nothing in these runs — the chain is only as
   strong as its weakest public engines, and it is slow (55s / 34s)
   because dead engines cost their timeout before Bing answers.
2. **Dorking without a key — DONE.** dork_v9 on the same chain; v7
   callers for phrase/email seeds route through it in v9 runs.
   LIVE: exact-email dork → search_snippet, **5 results** (bing_html);
   exact-phrase dork `"PersonaTrace Ultimate"` → **5 results**.
3. **Real adapters for the 24 sites — DONE with classification.**
   data_adapter (9): devto, lemmy, dailymotion, medium, keybase,
   gravatar, reddit_archive, soundcloud, vimeo. meta_adapter (7):
   substack, flickr, twitch, steam, producthunt, spotify, goodreads —
   OG/oEmbed fields only, and the meta must mention the username or
   the row is "uncertain" (generic site meta is never a profile).
   presence_only (8) — quora, pinterest, snapchat, kick, xbox,
   playstation, strava, angellist, each with its reason written in
   code + FULL_FEATURE_LIST (bot walls, login-gated data, retired or
   token-only APIs — no trustworthy public data route exists).
   LIVE (octocat, all 24): **found 11, uncertain 7, not_found 5,
   not_checked 1, blocked 0**. A presence_only "found" is the
   two-signal page-presence verdict only — no profile data is claimed.
4. **Verified site checks — DONE.** Two-signal rule (status AND body
   must agree; disagreement = uncertain, never found). The live
   self-audit (`--site-check-audit`, 11 sampled sites × existing +
   nonexistent = 22 checks) first exposed a real bug in this build:
   a bare "captcha" substring test marked GitHub "blocked" because
   GitHub pages ship an "octocaptcha" feature flag — fixed to
   robot-wall phrases only. Final audit: **false positives 1
   (gitlab — it returns 200 pages for nonexistent handles; the v2
   notes already flagged GitLab for exactly this), false negatives 1
   (kaggle's own account page), uncertain 6, blocked rows present
   (behance)**. The audit's job is to show this, not to hide it.
5. **Backup routes + determinism — DONE, with a real negative result.**
   Disk cache (24h TTL, age-labelled) behind GitHub / Wayback
   (+ archive.today route) / crt.sh (two attempts, longer timeout);
   DoH (Cloudflare → Google) behind the system resolver. Every dossier
   carries run_fingerprint. **Consistency check (octocat ×2): match =
   FALSE** — run A 9 profiles, run B 7; the extras in A were two
   crt.sh-derived domain candidates (`sni61417.cloudflaressl.com`,
   `www.github.blog`) that the intermittent crt.sh/DNS expansion did
   not return in B; adapter statuses were identical, so the variance
   sits in the analysis/domain-expansion phase. The fingerprint +
   consistency tooling exists precisely so this is visible.
6. **Real browser screenshots — DONE.** Playwright/Firefox captures,
   proof_shots/ + proof_index.json entries typed browser_screenshot
   with SHA256/UTC. The proof browser uses ignore_https_errors
   contexts because this network's TLS proxy made Firefox reject
   public-site certs (SEC_ERROR_UNKNOWN_ISSUER) — data routes are
   unaffected. LIVE: https://github.com/octocat → **shot_1.png,
   168,265 bytes**, sha256 ae30b5db…1661. GUI (v9, desktop) →
   gui-v9.png, 267,223 bytes (kept outside the ZIP, in the build
   report). Fallback to v8 snapshot cards is labelled snapshot_card.
7. **Built-in transcription — DONE (captions route live-proven).**
   Watch-page caption tracks → timedtext returned **empty bodies for
   every track** from this network (verified on 6 tracks of a
   captioned video), so a second route via the optional **yt-dlp**
   package was added: LIVE **found** — dQw4w9WgXcQ public captions,
   **2,089 chars** of real transcript text. Whisper: not installed in
   this environment (status reported honestly); scripts/
   setup_whisper.sh is the one-command install (faster-whisper +
   tiny model, ~75 MB one-time download).
8. **Built-in local NLP — DONE (deterministic pack), PARTIAL on the
   trained model (by design).** Gazetteer/rule pack: persons, orgs,
   places, language ID (incl. Urdu/Arabic script rules), topics —
   runs in every dossier. LIVE on octocat's collected texts (6 texts):
   languages {en: 6}, topics {ai_ml: 1}; the pack's unit/live samples
   extract e.g. persons [Linus Torvalds], orgs [GitHub Inc], places
   [San Francisco, Pakistan] correctly. spaCy route is wired and
   auto-detected; en_core_web_sm is **NOT bundled in the ZIP (size)**
   — scripts/setup_local_nlp.sh installs it in one command and the
   code then uses it, labelled with the model name.
9. **Speed — PARTIAL (target missed, numbers real).** Parallel is the
   default with per-adapter soft timeouts + --time-budget; adapters
   that miss the budget become degraded_timeout. LIVE octocat:
   investigation wall **80.9s** (first cold run) / **70.1s** (second
   cold run) against the 30s budget, timed-out adapters: none — the
   overrun is the engine's live **analysis phase** (activity,
   snapshots, infrastructure lookups with per-source pacing), which
   the dossier timing now reports separately from adapter time.
   The 1-hour result cache works: a repeat octocat CLI run took
   **13s total** (investigation served from cache, 0.0s) with the
   same 7 profiles / 2 edges / 1 possible match.
10. **Real 4-level graph — DONE.** LIVE on octocat: level 3 = **39
    real GitHub contacts** (followers capped 30 + following, union),
    level 4 = **0** shared bio-link domains among the 8 sampled
    level-3 profiles (none shared ≥2 — reported as 0, not invented).
11. **Benchmark on 20+ real people — DONE.** scripts/benchmark.py,
    23 real public usernames + 3 nonexistent controls; BENCHMARK.md
    is shipped in the ZIP with the real per-seed numbers. Summary of
    the live run (39.1 min total): **149 profiles across 23 seeds**
    (0–16 per seed; mojombo and mitchellh 16, antirez 11; mrdoob 0 —
    every source degraded for that seed mid-run, shown as-is),
    per-seed wall 12–431s (most 60–110s; antirez 431s is a retry-
    storm outlier), and **all 3 nonexistent controls returned exactly
    0 profiles** — no false positives. The benchmark octocat
    fingerprint (3f0ea1037750…) matches the standalone CLI run's.
12. **One-click installer — DONE (Linux binary built + smoke-tested).**
    packaging/personatrace.spec + build scripts (Linux/Windows/macOS),
    run_personatrace.py launcher, INSTALL.md (3 end-user steps).
    The Linux executable was actually built here: **25 MB**, `--help`
    works, and it serves the v9 GUI (HTTP 200, /api/v9/info →
    9.0.0). It is **NOT inside the ZIP** (it would grow it ~60×);
    it sits next to the ZIP as `PersonaTrace-v9-linux-binary`.
    Windows/macOS binaries were not prebuilt in this Linux
    environment — their build scripts are shipped.
13. **GUI to mockup level — DONE.** Dark theme refined (gradient
    brand rule, panel depth, graph glow, styled scrollbars), v9
    toggles (Direct / screenshots / result cache), responsive
    breakpoints kept + RTL rules. Real screenshot: gui-v9.png
    (267,223 bytes, build folder, not in ZIP).
14. **GUI languages — DONE.** i18n.json: **59 keys × 6 languages**
    (en/ur/ar/es/fr/de) with exact key parity (tested); selector in
    the header, localStorage persistence, dir=rtl switching —
    LIVE-verified: switching to Urdu set dir=rtl and the heading
    rendered in Urdu. Only UI chrome is translated; live content
    stays in its original language (stated in the guide).
15. **Old behaviour — kept.** Full suite below; the two v8 test
    assertions that pinned the package version / GUI header version
    were moved to the v9 test, following the convention already
    recorded in test_v7_full.py.
16. **Docs — this file**, FULL_FEATURE_LIST.md and USER_GUIDE.md
    updated to v9.0.0.

## Tests
- Source tree: **236 passed, 4 skipped** (209 pre-v9 + 27 new v9
  tests; the 4 skips are the pre-existing key-gated integration tests).
- Extracted-ZIP copy: verified after packaging; the exact counts are
  recorded in BUILD_REPORT.md (kept with the build, outside the ZIP).

## Live results (2026-10-29, no keys)
- CLI octocat (cold, --no-cache): **7 profiles, 2 edges, 1 possible
  match**, dossier found, version 9.0.0, fingerprint sha256
  3f0ea103…2e (7 profiles). Timing: 80.9s investigation wall.
- Direct Profile Mode regression (v8 feature, via v9 CLI): included
  in the octocat dossier flow; direct github_api route unchanged.
- IP / hashtag / wallet / plate / company seeds: unchanged v8
  behaviour (verified in the v8 build; not re-run for v9).
- Name searches, dorks, captions, screenshots, site audit, site
  adapters, graph levels, NLP: see items 1–10 above.
- GUI on a clean port: HTTP 200, v9.0.0 header, /api/v9/info live
  (6 languages, 59 keys, 24 adapter classifications).

## Honest limits
- All **key routes remain wired + mock-tested only, NOT live-proven**
  (no keys exist in this environment) — unchanged from v8.
- Free web search is fragile and slow: SearXNG/DDG failed live;
  Bing HTML + the GitHub/GitLab APIs carried name search.
- Full-case speed target (30s) is **missed** on live runs (~70–91s);
  the cache makes repeats fast (13s) but cold runs are analysis-bound.
- Runs are **not perfectly deterministic** (consistency item 5).
- The trained NLP model and Whisper model are one-command local
  installs, **not bundled** in the ZIP.
- The Linux installer binary is built; Windows/macOS binaries are
  scripts-only in this environment.
- Screenshots generated during live runs stay out of the ZIP.
- Proof PNGs from v8 (snapshot cards) remain labelled as cards;
  only Playwright captures are labelled browser_screenshot.
