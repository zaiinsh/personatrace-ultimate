"""Adapter registry (CONTRACT.md).

ADAPTERS maps name -> adapter instance. Free adapters are keyed by their
platform name; gated platforms (x, instagram, reddit, tiktok) are each an
instance of the single ``licensed_aggregator`` adapter class, with the
platform field varying per instance — so ``ADAPTERS["x"].name`` is
"licensed_aggregator" while ``ADAPTERS["x"].platform`` is "x".
"""

from __future__ import annotations

from .free import FREE_ADAPTERS
from .gated import GATED_ADAPTERS
from .final import FINAL_ADAPTERS

ADAPTERS = {}
ADAPTERS.update(FREE_ADAPTERS)
ADAPTERS.update(GATED_ADAPTERS)
ADAPTERS.update(FINAL_ADAPTERS)


def available_adapters(keys: dict) -> dict:
    """Return {registry name: status} for every adapter.

    Missing-key gated adapters report "not_checked"; free adapters report
    "active" (a failed live attempt is reported by search(), not here).
    """
    if keys is None:
        keys = {}
    return {name: adapter.status(keys) for name, adapter in ADAPTERS.items()}


def cost_before_run(keys: dict) -> list:
    """Real cost-before-run estimate, per source.

    Free sources cost 0 units. YouTube search costs 100 API units
    when a key is present, otherwise it is not checked and costs 0.
    Gated sources have provider-dependent pricing: when no key or no
    aggregator address is configured they are not checked (0 units);
    when configured, the cost is the provider's own price and is
    reported as "provider" rather than invented here.
    """
    if keys is None:
        keys = {}
    from .free import _youtube_key
    from .gated import _find_base_url, _find_key

    rows = []
    for name in ("github", "gitlab", "telegram", "hackernews", "stackoverflow", "bluesky", "mastodon", "wayback", "crtsh", "dns"):
        rows.append(
            {"name": name, "platform": name, "status": "active",
             "cost_units": 0, "cost_note": "free"}
        )
    # Discourse (forum) and LinkedIn are status-driven, not free-active.
    for name in ("discourse", "linkedin"):
        status = ADAPTERS[name].status(keys) if name in ADAPTERS else "not_checked"
        rows.append(
            {"name": name, "platform": name, "status": status,
             "cost_units": 0,
             "cost_note": "free" if status == "active" else "not checked — see adapter message"}
        )
    if _youtube_key(keys):
        rows.append(
            {"name": "youtube", "platform": "youtube", "status": "active",
             "cost_units": 100, "cost_note": "100 YouTube API units per search"}
        )
    else:
        rows.append(
            {"name": "youtube", "platform": "youtube", "status": "not_checked",
             "cost_units": 0, "cost_note": "not checked — no key"}
        )
    for platform in ("x", "instagram", "reddit", "tiktok"):
        if not _find_key(platform, keys):
            rows.append(
                {"name": platform, "platform": platform,
                 "status": "not_checked", "cost_units": 0,
                 "cost_note": "not checked — no key"}
            )
        elif not _find_base_url(keys):
            rows.append(
                {"name": platform, "platform": platform,
                 "status": "degraded", "cost_units": 0,
                 "cost_note": "key present, no aggregator address — no call made"}
            )
        else:
            rows.append(
                {"name": platform, "platform": platform,
                 "status": "active", "cost_units": None,
                 "cost_note": "provider price — see your aggregator plan"}
            )
    return rows
