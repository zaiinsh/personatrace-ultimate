"""Investigation engine — runs adapters, resolves, fills the case.

``run_investigation(seed, adapters, keys)`` calls each adapter's
``search()``, then builds profiles/edges via :mod:`resolution` and
fills ``possible_matches`` and ``audit`` on the Investigation.

Adapters are built by another builder and imported lazily: when
``adapters`` is None we try ``..adapters.registry`` (``ADAPTERS`` dict);
if that import fails — registry not built yet — we run with an empty
adapter list and log it, rather than crashing. A ``not_checked``
adapter result (missing key) is logged and skipped: it is never
reported as "not found" and yields zero profiles.
"""

from __future__ import annotations

import uuid

from .models import Investigation, Profile
from .provenance import utc_now_iso
from .resolution import profile_id, resolve_candidate


def _audit(inv: Investigation, action: str, detail: dict) -> None:
    inv.audit.append(
        {
            "ts_utc": utc_now_iso(),
            "actor": "core.engine",
            "action": action,
            "detail": detail,
        }
    )


def _coerce_profile(raw) -> Profile | None:
    """Accept a Profile, or a dict with Profile fields; else None."""
    if isinstance(raw, Profile):
        return raw
    if isinstance(raw, dict):
        fields = {
            "platform",
            "username",
            "display_name",
            "bio",
            "avatar_hash",
            "bio_links",
            "follower_count",
            "following_count",
            "created_at",
            "evidence",
            "status",
        }
        kwargs = {k: v for k, v in raw.items() if k in fields}
        if "platform" not in kwargs or "username" not in kwargs:
            return None
        if kwargs.get("bio_links") is None:
            kwargs["bio_links"] = []
        if kwargs.get("evidence") is None:
            kwargs["evidence"] = []
        if not kwargs.get("status"):
            kwargs["status"] = "candidate"
        return Profile(**kwargs)
    return None


def _result_parts(result):
    """Normalise an AdapterResult (object or dict) to (profiles, status, message)."""
    if isinstance(result, dict):
        return (
            result.get("profiles") or [],
            result.get("status", "ok"),
            result.get("message", ""),
        )
    return (
        getattr(result, "profiles", []) or [],
        getattr(result, "status", "ok"),
        getattr(result, "message", ""),
    )


def _load_adapters(adapters, keys: dict):
    """Resolve the adapter list; returns (list, load_note_or_None)."""
    if adapters is not None:
        if isinstance(adapters, dict):
            return list(adapters.values()), None
        return list(adapters), None
    try:
        from ..adapters.registry import ADAPTERS  # type: ignore

        return list(ADAPTERS.values()), f"loaded {len(ADAPTERS)} adapter(s) from registry"
    except Exception as exc:  # registry not built yet — tolerated by design
        return [], f"adapters.registry unavailable ({exc}); running with empty adapter list"


def run_investigation(
    seed: str,
    adapters=None,
    keys: dict | None = None,
    seed_type: str = "username",
    case_id: str | None = None,
    seed_profile: Profile | None = None,
    max_cost_units: float | None = None,
    analyse: bool = True,
) -> Investigation:
    """Run one investigation for ``seed`` and return the Investigation.

    ``seed_profile`` (optional) is an enriched reference profile for the
    seed (e.g. a known avatar hash / bio links from a confirmed account).
    Without it the reference is username-only, so per CONTRACT thresholds
    an exact-username-only adapter hit scores 40 (Low) and is rejected —
    that is contract-correct, not a bug; corroborated merges via the
    engine need the enriched reference, or use resolution directly.
    """
    keys = dict(keys or {})
    inv = Investigation(
        case_id=case_id or f"case_{uuid.uuid4().hex[:8]}",
        seed=seed,
        seed_type=seed_type,
    )
    _audit(inv, "investigation_started", {"seed": seed, "seed_type": seed_type})

    adapter_list, load_note = _load_adapters(adapters, keys)
    if load_note is not None:
        _audit(inv, "adapters_loaded", {"note": load_note, "count": len(adapter_list)})
    else:
        _audit(inv, "adapters_loaded", {"count": len(adapter_list)})

    # Internal reference profile only — never added to inv.profiles,
    # because it is not a real discovered account.
    if seed_profile is None:
        seed_profile = Profile(platform="seed", username=seed, status="confirmed")
    else:
        seed_profile = _coerce_profile(seed_profile) or Profile(
            platform="seed", username=seed, status="confirmed"
        )

    seen: set[str] = set()
    for adapter in adapter_list:
        name = getattr(adapter, "name", None) or type(adapter).__name__
        platform = getattr(adapter, "platform", None) or name
        # Per-case budget: YouTube search costs 100 units. If the
        # caller's budget is below that, skip YouTube honestly
        # instead of spending it silently.
        if (
            max_cost_units is not None
            and platform == "youtube"
            and max_cost_units < 100
        ):
            _audit(inv, "adapter_skipped_budget", {
                "adapter": name, "platform": platform,
                "cost_units": 100, "max_cost_units": max_cost_units,
            })
            continue
        try:
            result = adapter.search(seed, keys)
        except Exception as exc:
            _audit(inv, "adapter_error", {"adapter": name, "platform": platform, "error": str(exc)})
            continue
        profiles, status, message = _result_parts(result)
        found = 0
        for raw in profiles:
            profile = _coerce_profile(raw)
            if profile is None:
                continue
            pid = profile_id(profile)
            if pid in seen:
                continue
            seen.add(pid)
            inv.profiles.append(profile)
            found += 1
            # v2.0/v3.0 rejected-match memory: a candidate rejected in a
            # previous run is not re-suggested, and is not re-scored into
            # a merge. It stays rejected and is audited as such.
            _rej = keys.get("_rejected_matches") or [] if isinstance(keys, dict) else []
            _is_rejected_memory = f"{profile.platform}:{profile.username}" in _rej
            if _is_rejected_memory:
                profile.status = "rejected"
                _audit(inv, "rejected_memory_applied", {"profile_id": profile_id(profile), "reason": "Previously rejected by a human; not re-suggested and not re-scored into a merge."})
            # Resolution mutates status, adds edges / queue entries, audits.
            # Rejected-memory candidates skip resolution entirely (v3.0).
            if not _is_rejected_memory:
                resolve_candidate(inv, seed_profile, profile)
        _audit(
            inv,
            "adapter_search",
            {
                "adapter": name,
                "platform": platform,
                "status": status,
                "profiles_found": found,
                "message": message,
            },
        )

    # Wired analysis (v1.2): feature modules actually run on the case.
    # In demo mode this is offline only (no live fetches, no domain
    # expansion, no avatar downloads) so demo tests stay deterministic.
    if analyse:
        try:
            from ..features.analysis import run_analysis
            from ..adapters.base import is_demo_mode
            from .confidence import band_for
            from .models import Edge as _Edge
            from .provenance import utc_now_iso as _now

            analysis = run_analysis(inv, keys=keys)
            inv.analysis = analysis  # dynamic attribute, not a stored field
            # Avatar-reuse edges from the analysis (whole-image pHash
            # only, never face identification).
            for reuse in analysis.get("avatar_reuse", []):
                inv.edges.append(_Edge(
                    from_id=reuse["a"], to_id=reuse["b"],
                    kind="avatar_reuse", confidence=88, band=band_for(88),
                    evidence=[],
                ))
            # Level-2 domain nodes + level-3 certificate names, live only.
            if not is_demo_mode():
                from ..adapters.base import Evidence as _Evidence

                for domain, entry in analysis.get("domain_expansion", {}).items():
                    domain_id = f"domain:{domain}"
                    if domain_id not in seen:
                        seen.add(domain_id)
                        inv.profiles.append(Profile(
                            platform="domain", username=domain, status="candidate",
                            bio=f"Bio-link domain; Wayback={entry.get('wayback', {}).get('status')}, "
                                f"crt.sh={entry.get('crtsh', {}).get('status')}, "
                                f"DNS={entry.get('dns', {}).get('status')}",
                            evidence=[_Evidence(
                                source_url=f"https://{domain}/", captured_at_utc=_now(),
                                method="public_lookup", platform="domain",
                                field="domain", value=domain, confidence=90,
                            )],
                        ))
                    for pid, domains in analysis.get("bio_domains", {}).items():
                        if domain in domains:
                            inv.edges.append(_Edge(
                                from_id=pid, to_id=domain_id, kind="bio_link",
                                confidence=55, band=band_for(55), evidence=[],
                            ))
                    for sub in analysis.get("certificate_subdomains", {}).get(domain, []):
                        sub_id = f"domain:{sub}"
                        if sub_id not in seen:
                            seen.add(sub_id)
                            inv.profiles.append(Profile(
                                platform="domain", username=sub, status="candidate",
                                bio=f"Certificate name for {domain} (crt.sh, public log).",
                                evidence=[_Evidence(
                                    source_url=f"https://crt.sh/?q=%25.{domain}",
                                    captured_at_utc=_now(), method="public_lookup",
                                    platform="crtsh", field="certificate_name",
                                    value=sub, confidence=90,
                                )],
                            ))
                        inv.edges.append(_Edge(
                            from_id=domain_id, to_id=sub_id, kind="bio_link",
                            confidence=55, band=band_for(55), evidence=[],
                        ))
            for alert in analysis.get("alerts", []):
                inv.alerts.append(alert)
            _audit(inv, "analysis_completed", {
                "bio_domains": len(analysis.get("bio_domains", {})),
                "domain_expansion": len(analysis.get("domain_expansion", {})),
                "avatar_reuse": len(analysis.get("avatar_reuse", [])),
                "activity_items": analysis.get("behaviour_summary", {}).get("activity_items", 0),
                "live": analysis.get("live", False),
            })
        except Exception as exc:
            _audit(inv, "analysis_failed", {"error": str(exc)})

    try:
        from personatrace.features.analyst import ensure_checklist

        ensure_checklist(inv)
    except Exception:
        pass
    _audit(
        inv,
        "investigation_completed",
        {
            "profiles": len(inv.profiles),
            "confirmed": sum(1 for p in inv.profiles if p.status == "confirmed"),
            "possible": len(inv.possible_matches),
            "rejected": sum(1 for p in inv.profiles if p.status == "rejected"),
            "edges": len(inv.edges),
        },
    )
    return inv


def cluster_discovered_profiles(inv: Investigation) -> Investigation:
    """Group adapter-discovered profiles sharing the exact seed username.

    This is an INTEGRATION improvement, not a merge-threshold change:
    it does NOT change any profile's merge status and does NOT auto-merge
    an identity. It adds Low-confidence same_username edges between
    profiles that share the exact seed username across platforms, and one
    possible-match queue entry per cluster, so a human reviewer sees the
    cluster as a lead to check — exactly what the possible-match queue is
    for. Without this step a username-only engine run shows only
    individually rejected hits and no graph, which is contract-correct
    but useless as an investigation view.
    """
    from .confidence import band_for
    from .models import Edge

    seed = inv.seed
    # Social platforms only: infrastructure adapters (wayback/crtsh/dns)
    # return placeholder profiles for domain seeds in demo mode; clustering
    # them as social accounts would misrepresent infrastructure evidence.
    _social = {"github", "youtube", "bluesky", "mastodon", "x", "instagram", "reddit", "tiktok", "gitlab"}
    group = [p for p in inv.profiles if p.username == seed and p.platform in _social]
    if len(group) < 2:
        return inv
    existing = {(e.from_id, e.to_id, e.kind) for e in inv.edges}
    for i, a in enumerate(group):
        for b in group[i + 1:]:
            fa, fb = f"{a.platform}:{a.username}", f"{b.platform}:{b.username}"
            if (fa, fb, "same_username") in existing:
                continue
            inv.edges.append(Edge(
                from_id=fa, to_id=fb, kind="same_username",
                confidence=40, band=band_for(40),
                evidence=list(a.evidence[:1]),
            ))
            existing.add((fa, fb, "same_username"))
    inv.possible_matches.append({
        "profile": {"username": seed, "platforms": [p.platform for p in group]},
        "score": 40,
        "reasons": ["exact seed username found on multiple platforms — candidate cluster for human review, not an identity merge"],
        "status": "pending",
    })
    inv.audit.append({
        "ts_utc": utc_now_iso(), "actor": "core.engine",
        "action": "candidate_cluster_built",
        "detail": {"seed": seed, "platforms": [p.platform for p in group], "score": 40},
    })
    # Refresh risk + planner now that the cluster (possible-match queue)
    # exists — analysis ran before clustering, so its planner would
    # otherwise miss the queue entry and the not_checked sources.
    if getattr(inv, "analysis", None):
        try:
            from personatrace.features.risk import compute_risk_signals
            from personatrace.planner import plan_next_steps

            inv.analysis["risk_signals"] = compute_risk_signals(inv, inv.analysis)
            source_statuses = {}
            for entry in inv.audit or []:
                if isinstance(entry, dict) and entry.get("action") == "adapter_search":
                    detail = entry.get("detail") or {}
                    adapter = detail.get("platform") or detail.get("adapter") or ""
                    if adapter:
                        source_statuses[adapter] = detail.get("status", "")
            inv.analysis["next_steps"] = plan_next_steps(inv, inv.analysis, source_statuses)
        except Exception:
            pass
    return inv
