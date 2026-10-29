# PersonaTrace v4.0 — checklist, checked one by one against the 31-item list

User rule for v4 (2026-10-29): the investigator supplies their own paid
keys for YouTube, gated social, aggregator, SerpApi, Shodan, Censys, AI,
and transcription. If a source cannot be added free, it is added as a
key route, as the guide says. No key is bundled or invented.

1. Live Instagram, X, TikTok without a paid key — KEY ROUTE: full aggregator route (LicensedAggregatorAdapter, all gated platforms). Without a key: not_checked, never scraped. No legitimate key-free route exists.
2. Live current Reddit without a paid key — KEY ROUTE via aggregator + archive (v3) for historical. Without a key: archive only, live = not_checked.
3. Push updates — CLOSEST LEGITIMATE ROUTE: short-interval polling (CLI --live-check, 60s) + POST /api/webhook receiver for a third-party push service. No platform offers push for arbitrary profiles.
4. Fourth level of contacts — DONE: v4_level4_contacts (contacts of level-3, capped 2x2, leads only).
5. Groups beyond GitHub — DONE: v4_groups = GitHub orgs + Reddit communities from archive + Telegram channels from bio links + shared-contact groups. Private groups never listed.
6. Built-in object recognition without AI key/local model — HEURISTIC + KEY ROUTE: builtin_object_heuristic (Pillow colour/brightness/sky/skin signals, labelled not object recognition) + true recognition via AI key/local model (v3). No trained model can be bundled in a ~200 KB ZIP.
7. Built-in trained NER without AI key — HEURISTIC + KEY ROUTE: builtin_ner (gazetteer + org suffixes + capitalised phrases, labelled heuristic) + trained NER via AI key/local model (v3).
8. Audio transcription for videos with no listed captions — DONE as route: local Whisper if installed, else transcription_api_key (OpenAI-compatible audio). Without either: not_checked, never invented from titles.
9. Automated Google Lens without a third-party key — KEY ROUTE via SerpApi (v3) + manual links. No direct Lens API exists.
10. Automated Yandex without a third-party key — KEY ROUTE via SerpApi (v3) + manual links. No direct Yandex API exists.
11. Shodan/Censys without keys — KEY ROUTES: Shodan (v2) + real Censys API (v3). Without keys: not_checked.
12. YouTube without a key — KEY ROUTE: YouTube Data API v3 (v1-v3, paginated, captions for every video in case). Without a key: not_checked.
13. Gated comments without an aggregator key — KEY ROUTE via aggregator (v4_gated_comments). Without a key: not_checked, never scraped.
14. LinkedIn depth — KEY ROUTE via aggregator (platform=linkedin, v4_linkedin_gated) + URL templates. Without a key: not_checked, never scraped with a login. No general public LinkedIn API exists.
15. Real multi-user login over a network — DONE: /api/users with PBKDF2-HMAC-SHA256 (200k iterations) + salt, 24-hour session tokens, role viewer/analyst/admin. Production note: run behind HTTPS/reverse proxy; do not expose plain HTTP on a network.
16. Content diff between two Wayback captures — DONE: v4_wayback_diff (two newest captures, unified diff, up to 200 lines).
17. Archive.today for every profile — DONE: v4_archive_today_all (every profile with a URL, v3 did first few).
18. Wayback for profiles with no known pattern — DONE: v4_wayback_all (CDX query on any public profile URL, not only templated platforms).
19. Live checks on hundreds of sites — DONE in part: 152 templates + 10 reliable-404 live checks (verified 2026-10-29: dev.to, kaggle, soundcloud, producthunt, github, stackoverflow, codepen, dribbble, behance, spotify). Sites returning 200/403 for a nonexistent handle are NOT used as not_found checks. A live check on all 152 in one run would hammer sites and hit rate limits, so live checks are the reliable subset + templates for the rest.
20. Curated Sherlock/Maigret/WhatsMyName lists with self-checks — DONE: v4_curated_lists (152 built-in, labelled) + load_curated_file (investigator-supplied curated_sites.json merges in) + self_check_sites (nonexistent handle must be not_found, existent must be found).
21. Token buckets for every source — DONE: features/v4.py TokenBucket, bucket_for per source, token_buckets_status in analysis. Empty bucket = degraded, not a hammer.
22. Cached results with expiry for every source — DONE: cached_run (TTL 3600) used for wayback + site checks, v4_cache_all reports fresh/cached per source.
23. Quota banner with remaining units — DONE: v4_quota (units used + quota if supplied in keys + remaining; remaining is 'unknown' when no quota is supplied, never invented).
24. Private accounts as final private state — DONE: private_terminal (status private_terminal, terminal=True, never re-checked as not_found, never merged).
25. Entity-level confidence panel in GUI — DONE: v4_entity_confidence rendered in GUI v2 panel, with every signal and its positive/negative effect, weights from confidence.py.
26. Survivorship rules on merge — DONE: survivorship_merge (longest bio, earliest created_at, field sources recorded) + survivorship_merge_profiles in resolution.
27. Rejected matches changing future scoring weights — DONE: score_pair(..., rejected_patterns=...) applies -20 for a candidate similar (>=0.85) to a rejected username, in addition to the v3 block.
28. Vision description for every post photo — DONE as uncapped route: v4_uncapped vision_all, cap raised from 3 to PERSONATRACE_MAX_V4_ITEMS (default 20, configurable). Without AI key/local model: not_checked.
29. Reverse image for every avatar/post photo — DONE as uncapped route: v4_uncapped reverse_all, same cap, key routes + manual links without keys.
30. OCR for every post photo — DONE as uncapped route: v4_uncapped ocr_all, same cap; without tesseract/OCR API: not_checked, Pillow description remains.
31. Comment translation for every comment — DONE as uncapped route: v4_uncapped comment_translations, same cap, MT flagged, original preserved.

Still honestly not built / not promised:
- No face identification, no private access/DMs, no live person location, no bulk export, no CAPTCHA/login-wall/rate-limit bypass, no device fingerprinting, no credential-leak checks.
- No keys are included. Every paid route needs the investigator's own key.
- Push is polling + webhook, not a platform push feed (none exists for arbitrary profiles).
- Built-in recognition/NER are heuristics, labelled as such; trained versions need an AI key or local model.
