"""Case report draft (v2.0) and a small TTL cache (v2.0).

The report is a DRAFT for a human to review, edit and sign off. It
never says an identity is confirmed unless a human has verified it, it
never hides uncertainty, and it lists its sources so every claim can be
checked. The cache only stores public API responses for a short time
(1 hour by default) so a re-run does not re-pay quota; it never stores
keys and it never turns a cached copy into a claim that data is current.
"""
from __future__ import annotations

import hashlib
import json
import os
import time


def build_report_draft(inv, analysis: dict | None = None) -> str:
    analysis = analysis or getattr(inv, "analysis", {}) or {}
    lines = []
    lines.append("# PersonaTrace case report — DRAFT")
    lines.append("")
    lines.append("**DRAFT — human review required. Nothing in this draft is a confirmed identity unless a human has verified it and signed off.**")
    lines.append("")
    lines.append(f"Seed: `{inv.seed}`  |  Case: `{inv.case_id}`")
    lines.append("")
    lines.append("## What was found")
    lines.append("")
    for p in inv.profiles or []:
        lines.append(f"- {p.platform}/{p.username} — {p.display_name or ''} — status: {p.status}, confidence: {p.confidence}")
        if p.bio:
            lines.append(f"  - Bio: {p.bio}")
        if p.bio_links:
            lines.append(f"  - Bio links: {', '.join(p.bio_links)}")
    lines.append("")
    lines.append("## Graph")
    lines.append("")
    for e in inv.edges or []:
        lines.append(f"- {e.from_id} → {e.to_id} ({e.kind}, {e.confidence}, {e.band})")
    lines.append("")
    lines.append("## Timeline")
    lines.append("")
    for t in inv.timeline or []:
        lines.append(f"- {t.get('ts_utc', '')} — {t.get('kind', '')}: {t.get('description', '')}")
    lines.append("")
    lines.append("## Behaviour summary")
    lines.append("")
    summary = analysis.get("behaviour_summary", {})
    lines.append(summary.get("summary") or "No behaviour summary available for this case.")
    lines.append("")
    lines.append("## Risk signals (a list, never a verdict)")
    lines.append("")
    for r in analysis.get("risk_signals", []) or []:
        lines.append(f"- {r.get('signal', r)} — {r.get('innocent_explanation', '')}")
    lines.append("")
    lines.append("## Alerts")
    lines.append("")
    for a in inv.alerts or []:
        lines.append(f"- {a if isinstance(a, str) else a.get('detail', a)}")
    lines.append("")
    lines.append("## What to check next")
    lines.append("")
    for s in analysis.get("next_steps", []) or []:
        lines.append(f"- {s if isinstance(s, str) else s.get('step', s)}")
    lines.append("")
    lines.append("## Sources")
    lines.append("")
    for p in inv.profiles or []:
        for ev in p.evidence or []:
            if isinstance(ev, dict):
                lines.append(f"- {ev.get('platform', '')} {ev.get('field', '')}: {ev.get('source_url', '')}")
    lines.append("")
    lines.append("## Audit")
    lines.append("")
    for a in inv.audit or []:
        lines.append(f"- {a.get('action', '')}: {a.get('detail', a.get('details', ''))}")
    return "\n".join(lines)


# ---------------------------------------------------------------- TTL cache
def _cache_dir() -> str:
    path = os.environ.get("PERSONATRACE_CACHE_DIR") or os.path.join(os.getcwd(), ".personatrace_cache")
    os.makedirs(path, exist_ok=True)
    return path


def cache_get(key: str, ttl_seconds: int = 3600):
    """Return a cached public response, or None. Never caches keys."""
    if "key" in key.lower():
        return None
    digest = hashlib.sha256(key.encode()).hexdigest()
    path = os.path.join(_cache_dir(), digest + ".json")
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        if time.time() - data.get("saved_at", 0) <= ttl_seconds:
            return data.get("value")
    except Exception:
        pass
    return None


def cache_put(key: str, value, ttl_seconds: int = 3600):
    if "key" in key.lower():
        return
    digest = hashlib.sha256(key.encode()).hexdigest()
    path = os.path.join(_cache_dir(), digest + ".json")
    try:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"saved_at": time.time(), "ttl": ttl_seconds, "value": value}, fh)
    except Exception:
        pass
