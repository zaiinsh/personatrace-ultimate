"""Alerts for genuinely new graph edges only.

An alert fires when an edge appears in the new edge set that was not
in the old set (matched on from_id + to_id + kind). Edges that already
existed, or that disappeared, produce no alert here.
"""

from datetime import datetime, timezone

__all__ = ["check_new_edges"]


def _key(edge):
    if isinstance(edge, dict):
        return (edge.get("from_id"), edge.get("to_id"), edge.get("kind"))
    return (getattr(edge, "from_id", None), getattr(edge, "to_id", None), getattr(edge, "kind", None))


def _confidence(edge):
    if isinstance(edge, dict):
        return edge.get("confidence")
    return getattr(edge, "confidence", None)


def check_new_edges(old_edges, new_edges) -> list:
    """Return one alert dict per edge present only in *new_edges*."""
    old_keys = {_key(e) for e in (old_edges or [])}
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    alerts = []
    for edge in new_edges or []:
        from_id, to_id, kind = _key(edge)
        if (from_id, to_id, kind) in old_keys:
            continue
        alerts.append(
            {
                "kind": "new_edge",
                "edge_kind": kind,
                "from_id": from_id,
                "to_id": to_id,
                "confidence": _confidence(edge),
                "ts_utc": now,
                "message": f"New edge: {from_id} -> {to_id} ({kind}).",
            }
        )
    return alerts
