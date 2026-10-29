# PersonaTrace v3.0 — checklist, checked one by one against the blueprint

Each item below was checked against the v3 code and, where it is live,
against a real run. "Done" means the code exists and is wired into
engine/CLI/GUI, not just present as a library function. "Platform-limited"
means no legitimate tool can do it without a key / API, and the app
reports not_checked with the reason, never a fake result.

## The 41-item list (v2, re-checked in v3)
1. Live Instagram/X/TikTok/Reddit without a paid key — PLATFORM-LIMITED: Reddit via Arctic Shift archive (historical, ~36h lag) in features/v3.py; X/Instagram/TikTok have no public API and their pages are JS/login-walled, so not_checked, never scraped. Aggregator key route remains.
2. Automatic live updates — DONE as polling: CLI --live-check (polling, not push, because no platform offers a push feed for arbitrary profiles).
3. Full 3–4 level graph — DONE: contacts (L1), contacts-of-contacts (L2), level3_contacts (L3) in analysis, capped, leads only.
4. Groups beyond GitHub groups — DONE: groups_v3 = GitHub orgs + shared-contact groups; other platforms' groups need their own APIs/keys and are not invented.
5. Sudden posting-habit flags — DONE: behaviour_over_time.sudden_shifts.
6. Posting routine/hours — DONE: behaviour_over_time.posting_hours, most_common_hour, sleep_gap.
7. Language/tone changes over time — DONE: behaviour_over_time.per_month + tone_change.
8. What is shown inside photos — DONE: photo_descriptions (machine) + vision_description (investigator's AI key/local vision model, people-identification forbidden). Without a model, not_checked.
9. Captions for all videos — DONE: YouTube uploads paginated up to PERSONATRACE_MAX_VIDEOS (default 50), transcripts attempted for every video in the case. Still limited to publicly listed captions — no captions = no_captions, never fabricated.
10. Google Lens photo search — DONE via SerpApi key (serpapi_reverse, google_lens engine) + manual link. No direct Lens API exists.
11. Yandex photo search — DONE via SerpApi key (yandex_images engine) + manual link. No direct Yandex API exists.
12. Sound-alike spellings — DONE: soundex in v2_variants + cross_script in score_pair.
13. Short nickname spellings — DONE: diminutives in v2_variants.
14. Name spellings in other alphabets — DONE: transliterate_to_latin + cross_script_match, now wired into score_pair.
15. Checks on hundreds of small sites — DONE: 152 template sites (template_only, approximate URLs, verify before use) + 6 reliable-404 live checks.
16. Checks a found page is real, not a login wall — DONE: site checks use 404 + not-found phrases; 403/429 = degraded, never not_found.
17. Saved copy hash — DONE: capture_hash on every evidence item.
18. Deleted-post note with old copy kept — DONE: monitor.deleted_notes, preserved=True.
19. Wayback checks for profiles — DONE: all profiles with a known profile-URL template (was first 2 only in v2).
20. Before/after view — DONE: monitor.before_after + GUI v2 panel.
21. Gap note when no capture exists — DONE: wayback_profile_snapshots.gaps (>180 days).
22. Alerts for a watched website — DONE: watchlist_alerts, watch_domains.
23. Alerts for a new certificate — DONE: watchlist_alerts, crt.sh last 30 days for watched domains.
24. Alerts when follower overlap crosses a limit — DONE: watchlist_alerts, follower_overlap_threshold.
25. Shortened links marked — DONE: bio_link_labels (shortened_link / shared_link).
26. SPF/DKIM — DONE: dns_infra via public DNS-over-HTTPS.
27. Shodan/Censys — DONE: shodan_api_key route + censys_search with real Censys API (key-gated, Basic auth). No key = not_checked.
28. Names/places in original language — DONE: native_entities + native_ner (heuristic, original preserved).
29. Matching names across alphabets — DONE: cross_script_match wired into score_pair.
30. Cost banner when quota runs out — DONE: quota_banner + quota_per_source (per-source status in analysis).
31. Saved results with expiry — DONE: cache_get/cache_put actually used for site_checks, TTL 3600s, cached vs fresh reported in cache_v3.
32. Keys stored locked with encryption — DONE: storage/vault.py, ChaCha20 + PBKDF2 + HMAC, passphrase-gated.
33. Different users with different permissions — DONE: roles viewer/analyst/admin + local user accounts (/api/users, SHA-256 hashed passwords, local only, not a network auth system).
34. Dragging graph nodes — DONE: GUI drag in app.js.
35. Watching the graph grow over time — DONE: GUI Timeline scrub + Play, filtering by date.
36. Negative clues pulling a score down — DONE: score_pair subtracts up to 30 points for language/creation-year/display-name negatives, shown in reasons/drivers.
37. More proof for common names — DONE: score_pair raises auto-merge bar to 90 for common/short names.
38. Small shared groups counting more — DONE: niche_overlap + network_overlap signal in score_pair (rarity-weighted).
39. Rejected matches not being suggested again — DONE: rejected_matches.json + engine skip + resolution rejected_ids, so a rejected candidate is not re-scored into a merge.
40. Full written report draft — DONE: report_draft + report.md + GUI sign-off button (/api/signoff, human sign-off recorded, default unsigned).
41. Local smart model option — DONE: AILayer mode=local_model (Ollama / OpenAI-compatible local server, no cloud key).
42. Waiting and retrying slowly after a rate limit — DONE: 429/503 backoff, Retry-After, 2s then 5s, max 2 retries, then degraded.

## The 26-item missing list (v3 target, re-checked)
1. Live gated without a paid key — see item 1 above (platform-limited, Reddit archive added).
2. Automatic live updates — see item 2 above (polling).
3. Full 3–4 level graph — see item 3 above.
4. Groups beyond GitHub — see item 4 above.
5. True object recognition inside photos, without face ID — see item 8 above (AI vision, people-ID forbidden).
6. Captions for every video — see item 9 above.
7. Automated Google Lens — see item 10 above.
8. Automated Yandex — see item 11 above.
9. Checks on hundreds of small sites — see item 15 above.
10. Wayback checks for every profile — see item 19 above.
11. Wayback before/after view — see item 20 above + monitor.before_after.
12. Archive.today as second archive — DONE: archive_today() in v3.py, wired into analysis for first 3 GitHub/GitLab profiles, 429 = degraded.
13. Real Censys host search — see item 27 above.
14. True native-language name/place extraction — DONE: native_ner (heuristic + original preserved; a trained NER model is only available via the investigator's AI key/local model, which is stated, not hidden).
15. Name matching across alphabets inside main scoring — see item 29 above.
16. Negative clues actually lowering scores — see item 36 above.
17. Higher proof bar for common names actually applied — see item 37 above.
18. Small shared groups counting more — see item 38 above.
19. Account age plausibility in scoring — DONE: creation-year difference >=5 years is a negative signal in score_pair.
20. Merge/reject/keep buttons in UI — DONE: GUI possible-list buttons + /api/review, audited, rejected persisted to rejected_matches.json.
21. Rejected matches feeding back into future scoring — DONE: see item 39 above.
22. Saved results that actually expire and refresh — DONE: see item 31 above.
23. Cost banner when a specific quota runs out — DONE: see item 30 above (quota_per_source).
24. Real user accounts and login system — DONE as local accounts (see item 33 above); a network-grade auth system is explicitly out of scope for a local tool and is stated as such.
25. Coordinated signals for star graphs, link pushed within an hour, identical bio templates — DONE: coordinated_v3() in v3.py, wired into analysis.
26. Full written report with human sign-off, not only a draft — DONE: report_draft + /api/signoff (human sign-off recorded; unsigned by default).

## Still honestly not built / not promised
- No face identification, no private accounts/DMs, no live person location, no bulk export, no CAPTCHA/login-wall/rate-limit bypass.
- LinkedIn depth is intentionally not promised (blueprint: do not promise depth).
- YouTube/gated platforms need the investigator's own keys for full depth.
- A local AI/vision model needs the investigator to run one (e.g. Ollama); the app does not bundle a model.
- Real multi-user network authentication is not a local tool's job; the local account system is labelled as such.
