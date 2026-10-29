# PersonaTrace v7.0.0 — Checklist: scope, what was tested, honest limits

## Scope built in this version (on top of v6.0.0-final, v6 ZIP not overwritten)
- [x] Seeds: email, name (+context), profile/post URL, image/avatar URL,
      hashtag, exact phrase, IP, auto-detect, multi-seed — plus username/domain
- [x] Email: validation, domain→infra scan, Gravatar public profile (hash
      lookup; display name / profile URL / public linked accounts only),
      exact-email dork via search key (snippets only, else not_checked)
- [x] Name: dork candidates with confidence (capped ≤79), reasons,
      innocent-explanation checklist, candidate review queue — never certain
- [x] URL: parse for 12 hosts, author follow-on search, YouTube oEmbed,
      Instagram/TikTok/X item fetch labelled gated_paid without a key
- [x] Image: pHash same-photo reuse, OCR/description, reverse image (key),
      manual Lens/Yandex links — never face identification
- [x] Hashtag: Mastodon public timeline + HN search free; phrase: HN + dork
- [x] IP: RDAP + Shodan InternetDB, passive only
- [x] Key catalog v7: HikerAPI/aggregator, YouTube, Brave, Tavily, Serper,
      SerpApi, Google PSE, GitHub, Shodan, VirusTotal, SecurityTrails,
      urlscan, TinEye, Bing Visual, SerpApi Lens/Yandex, email verification
      (public only), AI key/Ollama — wizard lists all, verifies where a
      cheap endpoint exists, otherwise "present, unverified"
- [x] Exports add Maltego CSV + Obsidian case folder; keys stripped
      (v7 also fixes v6 strip_keys eating innocent `author` fields)
- [x] GUI: 11-type seed selector, email auto-detect, name-context field,
      grouped-keys note, provenance/status filter, v7.0.0 header

## Tests
- Full suite: **165 passed, 4 skipped** (17 new v7 tests, all network mocked;
  the 4 skips are the pre-existing key-gated integration tests)

## Live results (2026-10-29, no keys supplied)
- email `persona.trace.test.2026@example.com`: Gravatar **not_found**
  (correct for a fake/example address), dorks **not_checked**, domain
  example.com infra scan ran (13 domain/infra profiles — those are domain
  records, not profiles of the email owner)
- name `Barack Obama` + context: **not_checked, 0 candidates** — no search
  key was supplied, so dorking did not run; candidate pipeline is proven
  by mocked tests, not by a live key run
- URL `https://github.com/octocat`: parsed derived (github, profile,
  octocat), follow-on search **9 profiles**
- IP `8.8.8.8`: **found** — RDAP GOGL / NET-8-8-8-0-2, InternetDB found
  (dns.google, ports 53/443 as published by InternetDB)
- hashtag `#osint`: **found** — 30 posts (Mastodon + HN), 4 author profiles
- username regression `octocat`: **7 profiles, 2 edges, 1 possible match**
  — identical to v6

## Honest limits
- Key routes (HikerAPI, search APIs, Shodan full, VirusTotal, TinEye, etc.)
  are catalogued and wired where v6 already had a route, but NOT proven
  live: no investigator key was supplied during verification. Providers
  with no cheap verification endpoint are "present, unverified" by design.
- Name candidates need a search key to run live; without one the seed is
  not_checked, by design, never faked.
- Instagram public web was blocked (429) in v6 live runs and remains
  IP-dependent; full Instagram/X/TikTok data is gated_paid/gated_login.
- Email domain-scan profiles are infrastructure records for the domain,
  not evidence about the mailbox owner.
- Multi-seed merges collect profiles into one case; they do NOT merge
  identities. Link confirmation is a human decision (review queue).
- GUI live search remains slow (tens of seconds) — it runs all adapters.
- Stays out: phone people-search, password/breach dumps, private/DM,
  live location, face ID, bulk contact export, CAPTCHA bypass, port scans.
