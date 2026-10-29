"""Second-person comparison: two cases, side by side, honestly.

Runs a full investigation for a second seed and compares it with
the first case: shared platforms, shared bio domains, shared
contacts, shared hashtags/topics, and any bridge person/contact
appearing in both cases. A shared username or domain is a lead,
never proof the two people are the same person or are connected —
that decision is always a human review step, and it is stated in
the output.
"""

from __future__ import annotations


def compare_cases(first, second) -> dict:
    def _profiles(inv):
        return getattr(inv, "profiles", []) or []

    def _key(p):
        if isinstance(p, dict):
            return f"{p.get('platform')}:{p.get('username')}"
        return f"{getattr(p, 'platform', '')}:{getattr(p, 'username', '')}"

    first_profiles = {_key(p): p for p in _profiles(first)}
    second_profiles = {_key(p): p for p in _profiles(second)}
    shared_platforms = sorted(set(p.split(":")[0] for p in first_profiles) & set(p.split(":")[0] for p in second_profiles))
    a1 = getattr(first, "analysis", None) or {}
    a2 = getattr(second, "analysis", None) or {}
    domains1 = set()
    for ds in (a1.get("bio_domains") or {}).values():
        domains1.update(ds)
    domains2 = set()
    for ds in (a2.get("bio_domains") or {}).values():
        domains2.update(ds)
    contacts1 = set()
    for names in (a1.get("contacts") or {}).values():
        contacts1.update(names)
    contacts2 = set()
    for names in (a2.get("contacts") or {}).values():
        contacts2.update(names)
    tags1 = set((a1.get("hashtags") or {}).keys())
    tags2 = set((a2.get("hashtags") or {}).keys())
    return {
        "first_seed": getattr(first, "seed", ""),
        "second_seed": getattr(second, "seed", ""),
        "first_profiles": sorted(first_profiles),
        "second_profiles": sorted(second_profiles),
        "shared_platforms": shared_platforms,
        "shared_bio_domains": sorted(domains1 & domains2),
        "shared_contacts": sorted(contacts1 & contacts2),
        "shared_hashtags": sorted(tags1 & tags2),
        "bridge_between_cases": sorted(contacts1 & contacts2),
        "note": "Shared usernames, domains, contacts or hashtags are leads only, never proof of identity or connection. Human review required.",
    }
