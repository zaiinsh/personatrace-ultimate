"""Continuous monitoring, honestly: compare a new run with the last
saved run in the same output directory.

A "watch" is not a live stream. It is: run the CLI again (by hand, or
on a daily cron), compare profiles/edges/snapshots with the previous
investigation.json, and report only what changed. Deleted or renamed
profiles are detected by comparing the old snapshot set with the new
one; a missing profile in the new run is reported as "no longer
found in this run", never as "deleted" (a degraded source can also
cause a miss, and the report says so).

Usage from the CLI: every --out run automatically writes
monitor_report.json when a previous investigation.json exists in
that directory.
"""

from __future__ import annotations

from .features.alerts import check_new_edges
from .features.archive import diff_snapshots


def _profile_key(profile):
    if isinstance(profile, dict):
        return f"{profile.get('platform', '')}:{profile.get('username', '')}"
    return f"{getattr(profile, 'platform', '')}:{getattr(profile, 'username', '')}"


def _edge_key(edge):
    if isinstance(edge, dict):
        return (edge.get("from_id"), edge.get("to_id"), edge.get("kind"))
    return (getattr(edge, "from_id", None), getattr(edge, "to_id", None), getattr(edge, "kind", None))


def compare_investigations(old, new) -> dict:
    """Compare two investigation payloads (dicts, as written by CLI)."""
    old = old or {}
    new = new or {}
    old_profiles = {_profile_key(p): p for p in (old.get("profiles") or [])}
    new_profiles = {_profile_key(p): p for p in (new.get("profiles") or [])}
    added = sorted(set(new_profiles) - set(old_profiles))
    missing = sorted(set(old_profiles) - set(new_profiles))
    changed = {}
    for key in sorted(set(old_profiles) & set(new_profiles)):
        diff = diff_snapshots(old_profiles[key], new_profiles[key])
        if diff:
            changed[key] = diff
    new_edges = check_new_edges(old.get("edges") or [], new.get("edges") or [])
    # Follower / following changes, and name changes, per profile.
    follower_changes = {}
    name_changes = []
    for key in sorted(set(old_profiles) & set(new_profiles)):
        old_p, new_p = old_profiles[key], new_profiles[key]
        def _f(p, field):
            return p.get(field) if isinstance(p, dict) else getattr(p, field, None)
        old_f, new_f = _f(old_p, "follower_count"), _f(new_p, "follower_count")
        old_g, new_g = _f(old_p, "following_count"), _f(new_p, "following_count")
        if isinstance(old_f, int) and isinstance(new_f, int) and old_f != new_f:
            follower_changes[key] = {"followers_old": old_f, "followers_new": new_f, "delta": new_f - old_f}
        if isinstance(old_g, int) and isinstance(new_g, int) and old_g != new_g:
            follower_changes.setdefault(key, {})["following_old"] = old_g
            follower_changes[key]["following_new"] = new_g
        old_name, new_name = _f(old_p, "display_name"), _f(new_p, "display_name")
        if old_name != new_name:
            name_changes.append({"profile": key, "display_name_old": old_name, "display_name_new": new_name})
    # New / disappeared activity (public posts), with a caution flag:
    # a disappeared item may be a degraded source in the new run,
    # not a deletion — check the new run's per-source statuses first.
    def _activity_texts(payload):
        texts = set()
        analysis = payload.get("analysis") or {}
        for items in (analysis.get("activity") or {}).values():
            for item in items:
                if isinstance(item, dict) and item.get("text"):
                    texts.add(item["text"])
        return texts
    old_texts, new_texts = _activity_texts(old), _activity_texts(new)
    new_activity = sorted(new_texts - old_texts)
    disappeared_activity = sorted(old_texts - new_texts)
    alerts = []
    if new_activity:
        alerts.append({"kind": "new_activity", "message": f"{len(new_activity)} new public activity item(s) since the previous run.", "count": len(new_activity)})
    if disappeared_activity:
        alerts.append({"kind": "disappeared_activity", "message": f"{len(disappeared_activity)} public activity item(s) no longer found in this run — check source statuses before concluding deletion.", "count": len(disappeared_activity), "caution": True})
    # v2.0: before/after view + deleted-post notes with preserved copy.
    before_after = {}
    for key in sorted(set(old_profiles) & set(new_profiles)):
        old_p, new_p = old_profiles[key], new_profiles[key]
        def _g(p, field):
            return p.get(field) if isinstance(p, dict) else getattr(p, field, None)
        entry = {}
        for field in ("display_name", "bio", "follower_count", "following_count"):
            ov, nv = _g(old_p, field), _g(new_p, field)
            if ov != nv:
                entry[field] = {"before": ov, "after": nv}
        if entry:
            before_after[key] = entry
    deleted_notes = []
    for text in disappeared_activity:
        deleted_notes.append({
            "text": text,
            "note": "This post was public at capture time in the previous run and is now deleted or unavailable in this run. The preserved copy above stays in the case file; the tool never re-fetches content that has gone private.",
            "preserved": True,
        })
    return {
        "before_after": before_after,
        "deleted_notes": deleted_notes,
        "previous_case_id": old.get("case_id"),
        "new_case_id": new.get("case_id"),
        "profiles_added": added,
        "profiles_no_longer_found_in_this_run": missing,
        "profiles_changed": changed,
        "follower_changes": follower_changes,
        "name_changes": name_changes,
        "new_activity": new_activity,
        "disappeared_activity": disappeared_activity,
        "monitor_alerts": alerts,
        "new_edges": new_edges,
        "note": "A profile missing from a new run may be deleted/renamed, or "
                "its source may have been degraded/not_checked in that run. "
                "Check the new run's per-source statuses before concluding.",
    }
