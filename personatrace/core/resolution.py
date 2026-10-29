"""Entity resolution — standardise, score, threshold, merge/unmerge.

Thresholds (CONTRACT.md, mirrored in confidence.py):
  score >= 80  -> auto-merge candidate (still logged, reversible)
  score 50-79  -> possible-match queue, never auto-merged
  score < 50   -> reject / keep separate

Never merge on stylometry/timing alone: style/timing contribution is
capped at 25 points in confidence.py, so a style-only signal scores at
most 25 and therefore always lands in ``reject``.

Survivorship (when an entity view is assembled from merged profiles):
  display_name = longest non-empty; bio = longest non-empty;
  avatar_hash = most common non-empty (tie: first seen);
  bio_links = union, order-preserving, case-insensitive dedup;
  follower/following = max non-None; evidence = concatenation of all.
Profiles themselves are never collapsed in place — a merge marks the
candidate ``confirmed``, adds one Edge, and logs an audit entry carrying
the previous status and the edge identity, which is exactly what
:meth:`unmerge` needs to reverse it.
"""

from __future__ import annotations

import re
from collections import Counter

from .confidence import SIGNAL_WEIGHTS, band_for, classify_merge, edge_confidence
from .models import Edge, Investigation, Profile
from .provenance import utc_now_iso
from .variations import generate_variations


def standardise(text: str) -> str:
    """Normalise a username for comparison: strip, drop leading @, lower."""
    if text is None:
        return ""
    cleaned = str(text).strip().lstrip("@").lower()
    return re.sub(r"\s+", "_", cleaned)


# British-spelling alias (module name in the task uses "standardise").
standardize = standardise


def profile_id(profile: Profile) -> str:
    """Stable edge endpoint id: ``platform:standardised-username``."""
    return f"{str(profile.platform).lower()}:{standardise(profile.username)}"


def standardise_profile(profile: Profile) -> Profile:
    """Return a copy of ``profile`` with standardised username/links."""
    from dataclasses import replace

    links = []
    for link in profile.bio_links or []:
        norm = _normalize_link(link)
        if norm and norm not in links:
            links.append(norm)
    return replace(
        profile,
        username=standardise(profile.username),
        display_name=(profile.display_name or "").strip(),
        bio=(profile.bio or "").strip(),
        bio_links=links,
    )


def _normalize_link(link: str) -> str:
    if link is None:
        return ""
    return str(link).strip().lower().rstrip("/")


def _hamming_hex(a: str, b: str) -> int | None:
    """Hamming distance for two equal-length hex hashes, else None."""
    try:
        if len(a) != len(b) or not a or not b:
            return None
        int(a, 16)
        int(b, 16)
    except ValueError:
        return None
    return bin(int(a, 16) ^ int(b, 16)).count("1")


def _avatar_reuse(a: str, b: str) -> bool:
    """Same avatar? Exact match, or 64-bit pHash Hamming distance <= 10."""
    a = (a or "").strip().lower()
    b = (b or "").strip().lower()
    if not a or not b:
        return False
    if a == b:
        return True
    distance = _hamming_hex(a, b)
    return distance is not None and distance <= 10


def _edge_kind_for(reasons: list[str]) -> str:
    """Primary edge kind, strongest signal first."""
    joined = " ".join(reasons)
    if "exact username" in joined:
        return "same_username"
    if "avatar" in joined:
        return "avatar_reuse"
    if "bio link" in joined:
        return "bio_link"
    if "username variant" in joined:
        return "username_variant"
    if "style" in joined or "timing" in joined:
        return "style_timing"
    if "network" in joined:
        return "network_overlap"
    return "manual_note"


def _audit(inv: Investigation, action: str, detail: dict) -> dict:
    entry = {
        "ts_utc": utc_now_iso(),
        "actor": "core.resolution",
        "action": action,
        "detail": detail,
    }
    inv.audit.append(entry)
    return entry


def candidates_for_seed(seed_username: str, profiles: list[Profile]) -> list[Profile]:
    """Profiles whose standardised username is the seed or a variation of it."""
    variants = set(generate_variations(seed_username))
    variants.add(standardise(seed_username))
    return [p for p in profiles if standardise(p.username) in variants]


def score_pair(
    seed_profile: Profile,
    candidate: Profile,
    style_similarity: float | None = None,
    timing_similarity: float | None = None,
    shared_contacts: list | None = None,
    rejected_patterns: list | None = None,
) -> dict:
    """Score ``candidate`` against ``seed_profile``.

    Returns a dict: ``{score, band, decision, reasons, drivers, signals}``.
    ``decision`` is one of ``auto_merge`` / ``possible`` / ``reject``.
    """
    seed_std = standardise(seed_profile.username)
    cand_std = standardise(candidate.username)

    exact = 1.0 if seed_std and seed_std == cand_std else 0.0
    variant = 0.0
    if not exact and seed_std and cand_std:
        if cand_std in set(generate_variations(seed_profile.username)) or (
            seed_std in set(generate_variations(candidate.username))
        ):
            variant = 1.0
    avatar = 1.0 if _avatar_reuse(seed_profile.avatar_hash, candidate.avatar_hash) else 0.0
    seed_links = {_normalize_link(link) for link in (seed_profile.bio_links or [])}
    cand_links = {_normalize_link(link) for link in (candidate.bio_links or [])}
    shared_links = sorted(seed_links & cand_links - {""})
    bio = 1.0 if shared_links else 0.0

    style_value = 0.0
    style_parts = [v for v in (style_similarity, timing_similarity) if v is not None]
    if style_parts:
        style_value = max(0.0, min(1.0, sum(float(v) for v in style_parts) / len(style_parts)))

    # v3.0: cross-script match (transliterated usernames equal).
    cross_script = 0.0
    if not exact and seed_std and cand_std:
        try:
            from personatrace.features.v2 import cross_script_match
            if cross_script_match(seed_profile.username, candidate.username):
                cross_script = 1.0
        except Exception:
            cross_script = 0.0
    # v3.0: niche network overlap (shared contacts, rarity-weighted).
    niche_value = 0.0
    if shared_contacts:
        try:
            from personatrace.features.v3 import niche_overlap
            niche_value = niche_overlap(shared_contacts)["niche_ratio"]
        except Exception:
            niche_value = 0.0
    signals = [
        ("exact_username", SIGNAL_WEIGHTS["exact_username"], exact),
        ("username_variant", SIGNAL_WEIGHTS["username_variant"], variant),
        ("avatar_reuse", SIGNAL_WEIGHTS["avatar_reuse"], avatar),
        ("bio_link", SIGNAL_WEIGHTS["bio_link"], bio),
        ("style_timing", SIGNAL_WEIGHTS["style_timing"], style_value),
        ("cross_script", 0.15, cross_script),
        ("network_overlap", SIGNAL_WEIGHTS.get("network_overlap", 0.20), niche_value),
    ]
    score, band, drivers = edge_confidence(signals)
    # v3.0: negative signals pull the score down, shown not hidden.
    negatives = []
    try:
        from personatrace.features.language import detect_language
        seed_lang = detect_language(seed_profile.bio or "")
        cand_lang = detect_language(candidate.bio or "")
        if seed_lang not in ("other", "") and cand_lang not in ("other", "") and seed_lang != cand_lang:
            negatives.append("Different main languages in bios")
    except Exception:
        pass
    for prof_a, prof_b in ((seed_profile, candidate),):
        ca, cb = (prof_a.created_at or "")[:4], (prof_b.created_at or "")[:4]
        if ca and cb:
            try:
                if abs(int(ca) - int(cb)) >= 5:
                    negatives.append("Account creation years 5+ years apart (account-age plausibility)")
            except ValueError:
                pass
    if seed_profile.display_name and candidate.display_name and seed_profile.display_name.lower() != candidate.display_name.lower():
        try:
            from personatrace.features.v2 import cross_script_match as _csm
            if not _csm(seed_profile.display_name, candidate.display_name):
                negatives.append("Different display names")
        except Exception:
            negatives.append("Different display names")
    if negatives:
        penalty = min(30, 10 * len(negatives))
        score = max(0, score - penalty)
        from personatrace.core.confidence import band_for as _band_for
        band = _band_for(score)
        drivers.append(f"negative signals: {'; '.join(negatives)} — penalty -{penalty}")
    # v3.0: common/short names need more proof — auto-merge only at 90+.
    is_common = False
    try:
        from personatrace.features.v2 import common_name_check
        is_common = common_name_check(seed_profile.username)["is_common"]
    except Exception:
        pass
    # v4: private account is terminal, never merged.
    if getattr(candidate, "private", False):
        return {"score": 0, "band": "reject", "decision": "private_terminal",
                "reasons": ["Private account — terminal, not a merge candidate"], "drivers": [], "signals": []}
    # v4: rejected matches change future scoring weights.
    if rejected_patterns:
        from personatrace.features.v4 import rejected_weight_penalty
        _pen, _reasons = rejected_weight_penalty(candidate.username, rejected_patterns)
        if _pen:
            score = max(0, score + _pen)
            from personatrace.core.confidence import band_for as _bf2
            band = _bf2(score)
            drivers.append(f"rejected feedback: {_reasons[0]}")
    decision = classify_merge(score)
    if is_common and decision == "auto_merge" and score < 90:
        decision = "possible"
        drivers.append("common/short name: auto-merge bar raised to 90, so this stays possible")

    reasons: list[str] = []
    if exact:
        reasons.append("exact username match")
    if variant:
        reasons.append("username variant match")
    if avatar:
        reasons.append("same avatar (reuse)")
    if shared_links:
        reasons.append(f"shared bio link: {', '.join(shared_links)}")
    if style_value > 0:
        reasons.append(f"style/timing similarity {style_value:.2f} (capped weak signal)")
    if cross_script:
        reasons.append("cross-script username match (transliterated spelling)")
    if niche_value > 0:
        reasons.append(f"niche network overlap {niche_value:.2f} (rare shared contacts weigh more than celebrity follows)")
    for neg in negatives:
        reasons.append(f"negative: {neg}")
    if not reasons:
        reasons.append("no corroborating signal")

    return {
        "score": score,
        "band": band,
        "decision": decision,
        "reasons": reasons,
        "drivers": drivers,
        "signals": signals,
    }


def merge_candidate(
    inv: Investigation,
    seed_profile: Profile,
    candidate: Profile,
    score: int | None = None,
    reasons: list[str] | None = None,
) -> Edge:
    """Auto-merge path: mark confirmed, add an Edge, log (reversible)."""
    if score is None or reasons is None:
        result = score_pair(seed_profile, candidate)
        score = result["score"] if score is None else score
        reasons = result["reasons"] if reasons is None else reasons
    previous_status = candidate.status
    candidate.status = "confirmed"
    edge = Edge(
        from_id=profile_id(seed_profile),
        to_id=profile_id(candidate),
        kind=_edge_kind_for(list(reasons)),
        confidence=int(score),
        band=band_for(int(score)),
        evidence=list(candidate.evidence or []),
    )
    inv.edges.append(edge)
    _audit(
        inv,
        "merge",
        {
            "seed_id": profile_id(seed_profile),
            "profile_id": profile_id(candidate),
            "previous_status": previous_status,
            "score": int(score),
            "reasons": list(reasons),
            "edge": {"from_id": edge.from_id, "to_id": edge.to_id, "kind": edge.kind},
        },
    )
    return edge


def queue_possible_match(
    inv: Investigation,
    candidate: Profile,
    score: int,
    reasons: list[str],
) -> dict:
    """Possible-match path: queue it, never auto-merge."""
    candidate.status = "possible"
    entry = {
        "profile": candidate,
        "score": int(score),
        "reasons": list(reasons),
        "status": "pending",
    }
    inv.possible_matches.append(entry)
    _audit(
        inv,
        "possible_match_queued",
        {"profile_id": profile_id(candidate), "score": int(score), "reasons": list(reasons)},
    )
    return entry


def reject_candidate(
    inv: Investigation,
    candidate: Profile,
    score: int,
    reasons: list[str],
) -> None:
    """Reject path: keep separate, status ``rejected``, logged.

    v3.0: the rejection is also recorded on the investigation
    (rejected_ids) so a later resolve in the same case does not
    re-suggest the same candidate, and so the CLI can persist it to
    rejected_matches.json for later runs.
    """
    candidate.status = "rejected"
    try:
        rejected = getattr(inv, "rejected_ids", None)
        if rejected is None:
            inv.rejected_ids = set()
            rejected = inv.rejected_ids
        rejected.add(profile_id(candidate))
    except Exception:
        pass
    _audit(
        inv,
        "candidate_rejected",
        {"profile_id": profile_id(candidate), "score": int(score), "reasons": list(reasons)},
    )


def resolve_candidate(
    inv: Investigation,
    seed_profile: Profile,
    candidate: Profile,
    style_similarity: float | None = None,
    timing_similarity: float | None = None,
) -> str:
    """Score one candidate and dispatch to merge / queue / reject.

    Returns the decision string (``auto_merge`` / ``possible`` / ``reject``).
    """
    # v3.0: previously rejected in this case = never re-suggested.
    if profile_id(candidate) in getattr(inv, "rejected_ids", set()):
        reject_candidate(inv, candidate, 0, ["Previously rejected by a human — not re-suggested"])
        return "reject"
    result = score_pair(seed_profile, candidate, style_similarity, timing_similarity)
    decision = result["decision"]
    if decision == "auto_merge":
        merge_candidate(inv, seed_profile, candidate, result["score"], result["reasons"])
    elif decision == "possible":
        queue_possible_match(inv, candidate, result["score"], result["reasons"])
    else:
        reject_candidate(inv, candidate, result["score"], result["reasons"])
    return decision


def _find_possible_entry(inv: Investigation, candidate: Profile) -> dict | None:
    target = profile_id(candidate)
    for entry in inv.possible_matches:
        prof = entry.get("profile")
        if prof is candidate or (prof is not None and profile_id(prof) == target):
            return entry
    return None


def accept_possible_match(inv: Investigation, candidate: Profile) -> bool:
    """Human accepts a queued possible match: confirm it, log, reversible."""
    entry = _find_possible_entry(inv, candidate)
    if entry is None or entry.get("status") != "pending":
        return False
    previous_status = candidate.status
    entry["status"] = "accepted"
    candidate.status = "confirmed"
    edge = Edge(
        from_id="seed",
        to_id=profile_id(candidate),
        kind=_edge_kind_for(list(entry.get("reasons", []))),
        confidence=int(entry.get("score", 0)),
        band=band_for(int(entry.get("score", 0))),
        evidence=list(candidate.evidence or []),
    )
    inv.edges.append(edge)
    _audit(
        inv,
        "possible_match_accepted",
        {
            "profile_id": profile_id(candidate),
            "previous_status": previous_status,
            "score": int(entry.get("score", 0)),
            "reasons": list(entry.get("reasons", [])),
            "edge": {"from_id": edge.from_id, "to_id": edge.to_id, "kind": edge.kind},
        },
    )
    return True


def reject_possible_match(inv: Investigation, candidate: Profile) -> bool:
    """Human rejects a queued possible match."""
    entry = _find_possible_entry(inv, candidate)
    if entry is None or entry.get("status") != "pending":
        return False
    entry["status"] = "rejected"
    candidate.status = "rejected"
    _audit(
        inv,
        "possible_match_rejected",
        {"profile_id": profile_id(candidate), "score": int(entry.get("score", 0))},
    )
    return True


def unmerge(inv: Investigation, candidate: Profile) -> bool:
    """Reverse a merge (or an accepted possible match) for ``candidate``.

    Restores the candidate's pre-merge status, removes the edge created
    by that merge, and logs an ``unmerge`` audit entry. Returns False
    when no merge for this candidate is currently in effect.
    """
    target = profile_id(candidate)
    merge_detail = None
    # Walk backwards: a later "unmerge" for this profile means the merge
    # is already reversed; a merge/accept after it is the live one.
    for entry in reversed(inv.audit):
        detail = entry.get("detail") or {}
        if detail.get("profile_id") != target:
            continue
        if entry.get("action") == "unmerge":
            return False
        if entry.get("action") in ("merge", "possible_match_accepted"):
            merge_detail = detail
            break
    if merge_detail is None:
        return False

    previous_status = merge_detail.get("previous_status", "candidate")
    candidate.status = previous_status
    edge_info = merge_detail.get("edge") or {}
    for i, edge in enumerate(inv.edges):
        if (
            edge.from_id == edge_info.get("from_id")
            and edge.to_id == edge_info.get("to_id")
            and edge.kind == edge_info.get("kind")
        ):
            del inv.edges[i]
            break
    # If it came from the possible queue, reopen that entry.
    entry = _find_possible_entry(inv, candidate)
    if entry is not None and entry.get("status") == "accepted":
        entry["status"] = "pending"
    _audit(
        inv,
        "unmerge",
        {
            "profile_id": target,
            "restored_status": previous_status,
            "reversed_merge_score": merge_detail.get("score"),
        },
    )
    return True


def survivorship(profiles: list[Profile]) -> dict:
    """Winning field values for an entity assembled from ``profiles``.

    See module docstring for the rules. Returns a dict (not a Profile),
    because merged profiles span platforms and no single platform value
    can represent the entity.
    """
    if not profiles:
        return {
            "display_name": "",
            "bio": "",
            "avatar_hash": "",
            "bio_links": [],
            "follower_count": None,
            "following_count": None,
            "evidence": [],
            "source_profiles": [],
        }

    def longest(field_name: str) -> str:
        best = ""
        for prof in profiles:
            value = (getattr(prof, field_name) or "").strip()
            if len(value) > len(best):
                best = value
        return best

    avatar_counts = Counter(
        (p.avatar_hash or "").strip() for p in profiles if (p.avatar_hash or "").strip()
    )
    avatar_hash = avatar_counts.most_common(1)[0][0] if avatar_counts else ""

    links: list[str] = []
    seen_links: set[str] = set()
    for prof in profiles:
        for link in prof.bio_links or []:
            key = _normalize_link(link)
            if key and key not in seen_links:
                seen_links.add(key)
                links.append(str(link).strip())

    evidence: list = []
    for prof in profiles:
        evidence.extend(prof.evidence or [])

    followers = [p.follower_count for p in profiles if p.follower_count is not None]
    following = [p.following_count for p in profiles if p.following_count is not None]

    return {
        "display_name": longest("display_name"),
        "bio": longest("bio"),
        "avatar_hash": avatar_hash,
        "bio_links": links,
        "follower_count": max(followers) if followers else None,
        "following_count": max(following) if following else None,
        "evidence": evidence,
        "source_profiles": [profile_id(p) for p in profiles],
    }


def survivorship_merge_profiles(a, b):
    """v4: survivorship rules when two profiles merge (see features/v4.py)."""
    from personatrace.features.v4 import survivorship_merge
    return survivorship_merge(a, b)
