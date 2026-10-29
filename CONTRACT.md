# PersonaTrace Ultimate — Shared Contract (v1, binding for all modules)

## Hard rules (never break)
- Public data only. No private accounts/DMs, no live/person location tracking, no movement tracking, no bulk export.
- NO face identification, even via API, even with human approval. Image work = perceptual hash of a public image already held, for same-image reuse only.
- No bypassing CAPTCHAs, rate limits, login walls. Official APIs first, licensed aggregators behind adapters, graceful degradation.
- Every fact: source_url, captured_at_utc (ISO), method, confidence (0-100 + band Low/Medium/High).
- Merges below threshold go to possible-match queue, never auto-merged. Merges reversible, logged.
- Single-case export only, with audit log. Tests/fixtures: fictional dummy data only (demo_user_01, etc.). Never real personal data.

## Core data shapes (use these names exactly)
```python
@dataclass
class Evidence:  # one collected fact
    source_url: str; captured_at_utc: str; method: str; platform: str
    field: str; value: str; confidence: int  # 0-100

@dataclass
class Profile:  # one public account candidate
    platform: str; username: str; display_name: str = ""
    bio: str = ""; avatar_hash: str = ""; bio_links: list = field(default_factory=list)
    follower_count: int | None = None; following_count: int | None = None
    created_at: str = ""; evidence: list = field(default_factory=list)
    status: str = "candidate"  # candidate | confirmed | possible | rejected | not_checked

@dataclass
class Edge:
    from_id: str; to_id: str; kind: str  # same_username | avatar_reuse | bio_link | network_overlap | username_variant | style_timing | manual_note
    confidence: int; band: str  # Low (<50) | Medium (50-79) | High (80+)
    evidence: list = field(default_factory=list)

@dataclass
class Investigation:
    case_id: str; seed: str; seed_type: str = "username"  # username | domain
    profiles: list = field(default_factory=list); edges: list = field(default_factory=list)
    possible_matches: list = field(default_factory=list)  # dicts: {profile, score, reasons, status: pending|accepted|rejected}
    alerts: list = field(default_factory=list); audit: list = field(default_factory=list)
```

## Confidence — 3 layers (core/confidence.py)
- edge_confidence(signals: list[(name, weight, value 0-1)]) -> (score int, band str, drivers list[str])
  Weights must sum-check and be shown in drivers. Exact username alone = Low. Exact username + same avatar pHash (Hamming<=10) + same bio link = High.
- entity_confidence(edges) -> weighted combination, never >100, drivers shown.
- Merge thresholds: score >=80 auto-merge candidate (still logged, reversible); 50-79 -> possible-match queue; <50 -> reject/keep separate. Never merge on stylometry/timing alone.

## Variation engine (core/variations.py)
- generate_variations(seed_username: str, limit: int = 60) -> list[str] (ranked, deduplicated, seed first)
  Families in order: delimiters (_ . -), numeric tails (2, 99, 94, 1994, _v2), leetspeak (a->4, e->3, o->0, s->5, l->1), affixes (the, real, official, x, _ig, _x), truncations (15, 20, 24, 30, 39 chars), case variants lower only.
- No unbounded generation, no birth-year variants from a real name (seed is a username, not a person name).

## Adapters (adapters/base.py, registry.py)
```python
class AdapterResult: profiles: list[Profile]; status: str  # ok | not_checked | degraded | error; message: str; cost_units: float = 0.0
class BaseAdapter:
    name: str; platform: str; requires_key: bool; free_tier: bool
    def status(self, keys: dict) -> str  # "active" | "not_checked" | "degraded"
    def search(self, seed: str, keys: dict) -> AdapterResult
```
- Registry: ADAPTERS dict name->adapter instance. `available_adapters(keys)` returns status per adapter.
- Missing key for a gated adapter: status "not_checked", search returns status "not_checked", message prompts Settings > API Keys, zero profiles, NEVER "not found".
- Mock/demo mode: if env PERSONATRACE_DEMO=1 or no key and adapter is demo-capable, return clearly labelled dummy profiles whose usernames start with "demo_" and method="demo". Never present demo data as real.
- Free adapters: github, youtube, bluesky, mastodon, wayback, crtsh, dns. Gated: x, instagram, reddit, tiktok (via licensed_aggregator adapter, one adapter, platform field varies).
- Site lists: sherlock/maigret/whatsmyname-style lists live in adapters/site_lists.py as a small curated list of (platform, url_template) — do NOT claim live checks for closed platforms; those go through gated adapter.

## Storage (storage/db.py) — SQLite, local-first
- File: <case_dir>/personatrace.db, created by init_db(path).
- Tables: cases(id, seed, seed_type, created_at, purpose), profiles(id, case_id, platform, username, display_name, bio, avatar_hash, status, confidence), edges(id, case_id, from_id, to_id, kind, confidence, band), evidence(id, case_id, profile_id, source_url, captured_at_utc, method, platform, field, value, confidence), timeline(id, case_id, ts_utc, kind, description), audit(id, case_id, ts_utc, actor, action, detail), alerts(id, case_id, ts_utc, kind, message, acknowledged INTEGER).
- Functions: init_db(path), save_investigation(path, inv), load_investigation(path) -> Investigation, log_audit(path, case_id, actor, action, detail), add_alert(path, case_id, kind, message).
- Graph is stored as nodes (profiles) + edges in SQLite. Document Neo4j/Postgres path in README only, do not require a server.

## Features (features/*.py) — pure functions where possible
- phash.py: ahash(image_bytes) -> 64-bit int (average hash, stdlib only, no PIL dependency if possible; fallback to hashlib-based pseudo-hash documented as demo-grade if bytes are not an image — never claim a match on non-image bytes); hamming(a, b) -> int; is_reuse(a, b, threshold=10) -> bool.
- archive.py: diff_snapshots(old: Profile, new: Profile) -> dict of changed fields with old/new values; snapshot(profile) -> dict.
- biolink.py: extract_domains(bio_links, bio_text) -> list[str]; expand_domain(domain) -> dict (ct/dns placeholders, method="public_lookup", never live network calls in unit tests).
- coordinated.py: crowd_check(accounts: list[dict with posts, created_at, bio]) -> dict {signals: [...], innocent_explanations: [...], verdict: "pattern, not proof"}; never return label "bot" for an account.
- language.py: detect_language(text) -> str (script-based heuristic: latin/cyrillic/arabic/cjk/devanagari/thai/other, stdlib only); preserve original text alongside any translation placeholder.
- alerts.py: check_new_edges(old_edges, new_edges) -> list[alert dicts].
- stylometry.py: style_similarity(text_a, text_b) -> dict {score 0-1, sample_words_a, sample_words_b, weak_signal: True, warning if min sample < 500 words}; timing_similarity(hours_a, hours_b) -> float. Combined style+timing contribution capped at 25% — enforced in confidence.py, not here.
- export.py: export_case(inv, out_dir, fmt="html"|"json") -> path; HTML must list every fact with source_url + captured_at_utc + method + confidence; JSON must include provenance + audit. Single case only.

## AI layer (ai/layer.py)
- class AILayer(mode="local"|"llm", api_key=None): summarise(profiles, edges) -> dict {text, model, inputs_summary, labelled: True}; translate(text, target) -> dict; draft_report(inv) -> dict.
- Default mode "local" = deterministic template summarisation, model="local-template-v1", no network, no key. LLM mode without a key -> status "not_checked" with prompt to add a key, never fake LLM output.
- Every AI output dict must carry model, inputs_summary, and accepted/rejected = None until a human sets it (log via storage.log_audit).

## GUI (gui/server.py) — stdlib http.server only, no external web framework dependency
- run_gui(db_path=None, port=8787) starts a server serving gui/static/ (index.html, app.js, styles.css).
- REST (JSON): GET /api/investigation -> demo investigation JSON (from demo fixtures, labelled demo); GET /api/settings -> adapter statuses; POST /api/settings/keys {name, key} -> stores key name only (never echo the key value back); GET /api/timeline; GET /api/alerts; GET /api/export?fmt=json|html.
- Static page must contain: centre-node graph area (SVG/canvas, seed centre, three rings, bridge node class), left profile panel, right evidence panel, top search + platform filters + confidence slider + confirmed-only toggle, bottom timeline slider, alerts panel, compare placeholder, Settings page with Active vs Not checked toggles, missing-key prompts.
- No real personal data in static fixtures. No face identification UI. No location-tracking UI (infrastructure location only, if shown).

## Demo fixtures (demo/fixtures.py)
- demo_investigation() -> Investigation with seed demo_user_01, 6+ dummy profiles across >=4 platforms, >=8 edges incl. one bridge node, timeline events, alerts, possible-match entry, audit entries. All usernames demo_*.
- demo_run.py (CLI): python -m personatrace.demo_run --out demo/out -> writes investigation.json, case.html, case.json export, prints counts.

## Tests
- Each module ships its own test file. Tests must pass with stdlib + pytest only (no network). Mock/demo mode only for adapters in tests.
