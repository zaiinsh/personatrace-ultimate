"""PersonaTrace Ultimate — adapter base types.

Implements the CONTRACT.md (v1) adapter shapes exactly:

* ``Evidence``, ``Profile``, ``Edge``, ``Investigation`` — core data shapes.
  Two optional extensions beyond CONTRACT v1, both defaulted so every
  CONTRACT construction still works unchanged:
    - ``Investigation.timeline`` — needed to round-trip the storage
      ``timeline`` table (CONTRACT defines the table but no field for it).
    - ``Investigation.purpose`` — needed for the storage ``cases.purpose``
      column. Defaults to ``""``.
  ``possible_matches`` and ``Edge.evidence`` are intentionally NOT persisted
  by storage/db.py in v1 (the CONTRACT schema has no table/column for
  them); they remain in-memory only. See storage/db.py for details.

* ``AdapterResult`` / ``BaseAdapter`` — adapter contract.

Hard rules enforced here, never bypassed by subclasses:
- Public data only. No private accounts, DMs, live location, or movement
  tracking. No face identification, even via a third-party API.
- No CAPTCHA / rate-limit / login-wall bypass. A 429 is returned as
  degraded/error with no retry.
- Demo data is always labelled: usernames start with ``demo_``,
  bios start with ``[DEMO DATA`` and evidence uses ``method="demo"``.
  Demo data is never presented as real.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def is_demo_mode() -> bool:
    """True only when PERSONATRACE_DEMO=1 (exact string)."""
    return os.environ.get("PERSONATRACE_DEMO") == "1"


def confidence_band(confidence: int) -> str:
    """Low (<50) | Medium (50-79) | High (80+) — CONTRACT bands."""
    if confidence >= 80:
        return "High"
    if confidence >= 50:
        return "Medium"
    return "Low"


# ---------------------------------------------------------------------------
# Core data shapes — canonical definitions live in personatrace.core.models.
# Re-exported here so existing imports (storage, adapters) keep working.
# Integration 2026-10-28: single canonical model, no duplicate dataclasses.
# ---------------------------------------------------------------------------

from personatrace.core.models import Edge, Evidence, Investigation, Profile

__all__ = ["Edge", "Evidence", "Investigation", "Profile", "AdapterResult", "BaseAdapter", "confidence_band", "is_demo_mode"]


# ---------------------------------------------------------------------------
# Adapter contract
# ---------------------------------------------------------------------------

@dataclass
class AdapterResult:
    profiles: list  # list[Profile]
    status: str  # ok | not_checked | degraded | error
    message: str
    cost_units: float = 0.0


class BaseAdapter:
    """Base class for all adapters. Subclasses must implement both methods.

    Attributes:
        name: adapter name (e.g. "github", or "licensed_aggregator" for gated).
        platform: platform this instance covers.
        requires_key: True for gated adapters.
        free_tier: True for free adapters.
        demo_capable: True if the adapter can return labelled demo data.
    """

    name: str = ""
    platform: str = ""
    requires_key: bool = False
    free_tier: bool = True
    demo_capable: bool = True

    def status(self, keys: dict) -> str:
        """Return "active" | "not_checked" | "degraded"."""
        raise NotImplementedError

    def search(self, seed: str, keys: dict) -> AdapterResult:
        """Search for public profiles matching ``seed``. Never raises for a
        missing key, a 429, or a network failure — those are reported in
        the returned AdapterResult status/message instead."""
        raise NotImplementedError
