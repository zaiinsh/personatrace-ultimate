"""Analyst notes + checklist inside a case.

A note is the investigator's own text, stored with a timestamp, and
never presented as collected evidence. The checklist is a fixed set
of human-review steps (verify identity, check innocent explanations,
review the possible-match queue, check source statuses, acknowledge
alerts) — each starts undone; the investigator marks items done.
Nothing here auto-merges, auto-concludes or auto-acts.
"""

from __future__ import annotations

from datetime import datetime, timezone


def default_checklist() -> list:
    return [
        {"item": "Verify the seed identity against at least one source URL.", "done": False},
        {"item": "Check the innocent explanation for every risk signal.", "done": False},
        {"item": "Review the possible-match queue (merge, reject, or keep separate).", "done": False},
        {"item": "Check per-source statuses: a not_checked source is a gap, not a negative.", "done": False},
        {"item": "Acknowledge every alert in the case file.", "done": False},
        {"item": "Confirm no private data, live location or face data is in this case.", "done": False},
    ]


def add_note(inv, text: str, author: str = "investigator") -> dict:
    note = {
        "ts_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "author": author,
        "text": text,
    }
    if not hasattr(inv, "notes") or inv.notes is None:
        inv.notes = []
    inv.notes.append(note)
    if hasattr(inv, "audit"):
        inv.audit.append({
            "ts_utc": note["ts_utc"], "actor": "analyst",
            "action": "note_added", "detail": {"author": author},
        })
    return note


def ensure_checklist(inv):
    if not hasattr(inv, "checklist") or not inv.checklist:
        inv.checklist = default_checklist()
    return inv.checklist
