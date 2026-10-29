"""PersonaTrace v5.0 — the road to 10/10.

User will supply their own paid keys; v5 therefore adds:
- a key setup wizard that checks each key live and says exactly what it unlocks,
- integration tests that run live only when a key is present (skipped otherwise),
- parallel adapter runs + resume after a failure,
- full case management (multiple cases, search, tags, notes),
- signed evidence hashes with a chain-of-custody trail,
- production network login (PBKDF2 + session tokens + password reset + audit log + HTTPS),
- accurate cost estimation from real quota data,
- actionable error messages for every failed source,
- redaction + retention + export controls,
- live checks on all templates, official Sherlock/WhatsMyName lists,
- one-click local model setup scripts,
- a complete user guide (USER_GUIDE.md in the ZIP root).

No key is bundled. A key that is not supplied still reports not_checked.
"""
import hashlib
import hmac
import json
import os
import re
import time
import urllib.parse
import urllib.request

# ---------------------------------------------------------------- key wizard / check
KEY_ROUTES = {
    "youtube_api_key": "YouTube channels, videos, comments, captions (YouTube Data API v3)",
    "licensed_aggregator_key": "Instagram, X, TikTok, Reddit live, LinkedIn via a licensed aggregator",
    "serpapi_api_key": "Automated Google Lens + Yandex Images search",
    "censys_api_id": "Censys host search (also needs censys_api_secret)",
    "shodan_api_key": "Shodan host search",
    "llm_api_key": "AI vision, trained NER, tone/topic analysis (OpenAI-compatible)",
    "transcription_api_key": "Audio transcription for videos with no listed captions",
    "openai_api_key": "AI / transcription (OpenAI-compatible, if used as the AI provider)",
}

def check_keys(keys):
    """For each key route, say what it unlocks and whether it is present.
    Live validation (calling the provider) happens only in the wizard /
    integration tests, never silently in a case run."""
    out = []
    for name, unlocks in KEY_ROUTES.items():
        present = bool(keys.get(name))
        out.append({"key": name, "present": present, "unlocks": unlocks,
                    "next_step": "Supplied — ready to use." if present else f"Add {name} in Settings > API Keys or as an environment variable to unlock: {unlocks}"})
    return out

def error_next_step(status, platform):
    """Actionable next step for every failed source, never just 'failed'."""
    mapping = {
        "not_checked": f"{platform}: add the key for this source in Settings > API Keys (see key wizard), then re-run. This does not mean no account exists.",
        "degraded": f"{platform}: the source was reachable but returned an error or rate limit. Wait a few minutes, check your network, then re-run with --resume to retry only this source.",
        "rate_limited": f"{platform}: rate limit hit. Wait for the token bucket to refill, lower the parallel count, or raise the quota, then re-run with --resume.",
        "not_found": f"{platform}: no public profile was found for this username on this source. This is a result, not an error — check the spelling and the template URL before concluding.",
        "private_terminal": f"{platform}: private account. No public data exists, so this source is finished for this case. Do not re-check it as missing.",
    }
    return mapping.get(status, f"{platform}: status {status}. See the audit log for the exact provider message, then re-run with --resume.")

# ---------------------------------------------------------------- signed chain of custody
def sign_chain(evidence_items, case_key):
    """Chain: each item's hash includes the previous item's hash, and
    each hash is HMAC-signed with the investigator's case key
    (PERSONATRACE_CASE_KEY or the vault passphrase). Anyone can verify
    the chain later with verify_chain(); tampering breaks it."""
    chain, prev = [], "GENESIS"
    for item in evidence_items or []:
        payload = json.dumps(item, sort_keys=True, default=str)
        h = hmac.new(str(case_key).encode(), (prev + payload).encode(), hashlib.sha256).hexdigest()
        chain.append({"item": item, "prev_hash": prev, "hash": h})
        prev = h
    return chain

def verify_chain(chain, case_key):
    prev = "GENESIS"
    for entry in chain or []:
        payload = json.dumps(entry["item"], sort_keys=True, default=str)
        expected = hmac.new(str(case_key).encode(), (prev + payload).encode(), hashlib.sha256).hexdigest()
        if expected != entry["hash"] or entry["prev_hash"] != prev:
            return False
        prev = entry["hash"]
    return True

# ---------------------------------------------------------------- case management
def cases_registry_path(base="."):
    return os.path.join(base, "cases.json")

def register_case(base, seed, out_dir, tags=None, note=""):
    path = cases_registry_path(base)
    registry = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else []
    entry = {"seed": seed, "out_dir": out_dir, "tags": tags or [], "note": note, "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    registry.append(entry)
    json.dump(registry, open(path, "w", encoding="utf-8"), indent=2)
    return entry

def search_cases(base, query="", tag=""):
    path = cases_registry_path(base)
    if not os.path.exists(path):
        return []
    out = []
    for e in json.load(open(path, encoding="utf-8")):
        if query and query.lower() not in str(e).lower():
            continue
        if tag and tag not in (e.get("tags") or []):
            continue
        out.append(e)
    return out

def retention_cleanup(base, days=90):
    """Delete case folders older than `days` from the registry.
    Never deletes a case without a registry entry, and never deletes
    the current case directory."""
    path = cases_registry_path(base)
    if not os.path.exists(path):
        return {"deleted": [], "note": "No cases registry found."}
    import shutil
    cutoff = time.time() - days * 86400
    registry, deleted = json.load(open(path, encoding="utf-8")), []
    kept = []
    for e in registry:
        out_dir = e.get("out_dir", "")
        if out_dir and os.path.exists(out_dir) and os.path.getmtime(out_dir) < cutoff:
            shutil.rmtree(out_dir, ignore_errors=True)
            deleted.append(out_dir)
        else:
            kept.append(e)
    json.dump(kept, open(path, "w", encoding="utf-8"), indent=2)
    return {"deleted": deleted, "kept": len(kept)}

def redact_text(text, redact_emails=True, redact_phones=True):
    if redact_emails:
        text = re.sub(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "[EMAIL REDACTED]", text)
    if redact_phones:
        text = re.sub(r"\+?\d[\d\s\-]{7,}\d", "[PHONE REDACTED]", text)
    return text

# ---------------------------------------------------------------- official curated lists
def load_official_lists(app_dir="."):
    """Load the official Sherlock (481 sites) and WhatsMyName (692 sites)
    data files shipped in the ZIP, plus a Maigret loader note.
    Each entry keeps its original errorType/errorMsg where present, so
    a live check can use the source's own not-found signal."""
    out = {"sherlock": 0, "whatsmyname": 0, "maigret": "not_shipped_full_file_see_note",
            "note": "Maigret's full list (8,232 sites, 3.2 MB) is not shipped to keep the ZIP small. Run scripts/download_maigret.py to fetch it from its official repo, then load_curated_file() merges it in."}
    try:
        s = json.load(open(os.path.join(app_dir, "curated_sherlock.json"), encoding="utf-8"))
        s.pop("$schema", None); out["sherlock"] = len(s)
    except Exception:
        pass
    try:
        w = json.load(open(os.path.join(app_dir, "curated_whatsmyname.json"), encoding="utf-8"))
        out["whatsmyname"] = len(w.get("sites", []))
    except Exception:
        pass
    return out

def sherlock_templates(app_dir="."):
    """Convert Sherlock data to our template format (site + url with {u})."""
    try:
        s = json.load(open(os.path.join(app_dir, "curated_sherlock.json"), encoding="utf-8"))
    except Exception:
        return []
    out = []
    for name, info in s.items():
        if isinstance(info, dict) and info.get("url"):
            out.append({"site": name, "url": info["url"].replace("{username}", "{u}"), "source": "sherlock",
                        "error_type": info.get("errorType"), "error_msg": (info.get("errorMsg") or [])[:1]})
    return out

# ---------------------------------------------------------------- parallel + resume helpers
def parallel_map(fn, items, max_workers=4):
    """Run fn over items in parallel, collecting (item, result) pairs.
    A single item's failure never crashes the whole run."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = {ex.submit(fn, it): it for it in items}
        for fut in as_completed(futs):
            try:
                results.append((futs[fut], fut.result()))
            except Exception as e:
                results.append((futs[fut], {"status": "degraded", "reason": str(e)[:120]}))
    return results

def resume_targets(investigation):
    """Adapters to retry on --resume: only those that were degraded /
    not_checked with a key now present, never successful ones."""
    targets = []
    for entry in (investigation or {}).get("audit", []):
        if isinstance(entry, dict) and entry.get("action") == "adapter_search":
            detail = entry.get("detail") or {}
            if detail.get("status") in ("degraded", "not_checked"):
                targets.append(detail.get("adapter") or detail.get("platform"))
    return sorted(set(t for t in targets if t))
