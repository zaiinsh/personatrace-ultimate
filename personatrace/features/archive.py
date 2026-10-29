"""Public-profile archive snapshots and diffs.

A snapshot records the observable fields of a public profile at one
moment; a diff lists only fields that changed. No private data, no
location, no identity inference.
"""

__all__ = ["snapshot", "diff_snapshots"]

_FIELDS = (
    "platform",
    "username",
    "display_name",
    "bio",
    "bio_links",
    "follower_count",
    "following_count",
    "created_at",
    "avatar_hash",
    "status",
)


def _get(obj, field):
    if isinstance(obj, dict):
        return obj.get(field)
    return getattr(obj, field, None)


def snapshot(profile) -> dict:
    """Return a plain-dict snapshot of a profile (object or dict)."""
    snap = {}
    for field in _FIELDS:
        value = _get(profile, field)
        snap[field] = list(value) if isinstance(value, list) else value
    return snap


def diff_snapshots(old, new) -> dict:
    """Diff two profiles (or snapshots) -> {field: {old, new}}.

    Only changed fields are included. An empty dict means no change.
    """
    old_snap = old if isinstance(old, dict) and set(old) <= set(_FIELDS) else snapshot(old)
    new_snap = new if isinstance(new, dict) and set(new) <= set(_FIELDS) else snapshot(new)
    diff = {}
    for field in _FIELDS:
        if old_snap.get(field) != new_snap.get(field):
            diff[field] = {"old": old_snap.get(field), "new": new_snap.get(field)}
    return diff
