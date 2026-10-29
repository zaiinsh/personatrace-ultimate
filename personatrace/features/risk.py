"""Risk signals for a case file — a list, never a verdict.

Each signal carries: level (low/medium), evidence, and an innocent
explanation that must be ruled out first. No signal, alone or
combined, labels an account as a bot, a scammer or a criminal, and
no signal triggers any automated action. A human investigator
reviews every signal before it is used anywhere.

Signals computed here (from public data already collected):
- new_account: profile created within 30 days of the run.
- avatar_reuse: same public avatar hash on 2+ profiles.
- bio_link_to_new_domain: a bio domain whose RDAP registration is
  within 90 days.
- coordinated_pattern: coordinated crowd check found a pattern.
- username_variant_cluster: possible-match queue has a variant cluster.
- follower_imbalance: following is 10x followers (or vice versa)
  on a profile with a follower count — a pattern, not proof of fakery.
"""

from __future__ import annotations

from datetime import datetime, timezone


def _parse_date(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def compute_risk_signals(inv, analysis: dict | None = None) -> list:
    analysis = analysis or {}
    signals = []
    now = datetime.now(timezone.utc)
    profiles = getattr(inv, "profiles", []) or []

    def _g(p, field, default=""):
        if isinstance(p, dict):
            return p.get(field, default)
        return getattr(p, field, default)

    for p in profiles:
        created = _parse_date(_g(p, "created_at"))
        if created and (now - created).days <= 30:
            signals.append({
                "level": "low", "signal": "new_account",
                "profile": f"{_g(p, 'platform')}:{_g(p, 'username')}",
                "evidence": f"Created {_g(p, 'created_at')} (within 30 days).",
                "innocent_explanation": "A legitimate new account, a renamed account, or a second account for a new project.",
            })
        followers = _g(p, "follower_count")
        following = _g(p, "following_count")
        if isinstance(followers, int) and isinstance(following, int) and followers > 0 and following > 0:
            if following >= followers * 10 or followers >= following * 10:
                signals.append({
                    "level": "low", "signal": "follower_imbalance",
                    "profile": f"{_g(p, 'platform')}:{_g(p, 'username')}",
                    "evidence": f"Followers {followers}, following {following}.",
                    "innocent_explanation": "A new account following many people, a curator account, or a fan account.",
                })
    for reuse in analysis.get("avatar_reuse", []) or []:
        signals.append({
            "level": "medium", "signal": "avatar_reuse",
            "profile": f"{reuse.get('a')} / {reuse.get('b')}",
            "evidence": f"Same public avatar, pHash Hamming {reuse.get('hamming')}.",
            "innocent_explanation": "The same person reusing their own photo, a shared logo, or a stock avatar.",
        })
    for domain, entry in (analysis.get("domain_expansion", {}) or {}).items():
        rdap = entry.get("rdap_whois") or {}
        events = rdap.get("events") or {}
        reg = _parse_date(events.get("registration"))
        if reg and (now - reg).days <= 90:
            signals.append({
                "level": "low", "signal": "bio_link_to_new_domain",
                "profile": domain,
                "evidence": f"Domain {domain} registered {events.get('registration')} (within 90 days).",
                "innocent_explanation": "A new legitimate site, a rebrand, or a domain recently renewed under a new registrar record.",
            })
    coordinated = analysis.get("coordinated") or {}
    if coordinated.get("signals") and "No coordinated" not in str(coordinated.get("signals")):
        signals.append({
            "level": "medium", "signal": "coordinated_pattern",
            "profile": "case",
            "evidence": "; ".join(coordinated.get("signals", [])[:3]),
            "innocent_explanation": "Colleagues, classmates, fans or an event sharing announcements — see the coordinated module's innocent explanations.",
        })
    if getattr(inv, "possible_matches", []):
        signals.append({
            "level": "low", "signal": "username_variant_cluster",
            "profile": "case",
            "evidence": f"{len(inv.possible_matches)} possible-match entr(ies) awaiting human review.",
            "innocent_explanation": "Common usernames, fans, or unrelated people sharing a handle pattern.",
        })
    return signals
