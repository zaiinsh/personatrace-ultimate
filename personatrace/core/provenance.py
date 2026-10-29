"""Provenance helpers — every fact carries source, UTC time, method,
platform and confidence (CONTRACT.md hard rule).

No network, no real personal data: callers supply the source URL of a
public page/API response they actually collected.
"""

from __future__ import annotations

from datetime import datetime, timezone

from .models import Evidence


def utc_now_iso() -> str:
    """Current UTC time as an ISO-8601 string ending in ``Z``."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _clamp_confidence(confidence: int) -> int:
    try:
        value = int(confidence)
    except (TypeError, ValueError):
        raise ValueError("confidence must be an int 0-100") from None
    return max(0, min(100, value))


def make_evidence(
    source_url: str,
    method: str,
    platform: str,
    field: str,
    value: str,
    confidence: int,
    captured_at_utc: str | None = None,
) -> Evidence:
    """Build one :class:`Evidence` item with a UTC capture timestamp.

    ``captured_at_utc`` defaults to now (UTC). A caller-supplied timestamp
    is kept verbatim so re-imported evidence keeps its original time.
    """
    if not source_url or not str(source_url).strip():
        raise ValueError("source_url is required for provenance")
    if not method or not str(method).strip():
        raise ValueError("method is required for provenance")
    return Evidence(
        source_url=str(source_url),
        captured_at_utc=captured_at_utc or utc_now_iso(),
        method=str(method),
        platform=str(platform),
        field=str(field),
        value=str(value),
        confidence=_clamp_confidence(confidence),
    )


# Alias: some callers naturally say "build" rather than "make".
build_evidence = make_evidence
