"""PersonaTrace core engine — models, confidence, variations, resolution,
provenance and the investigation engine."""

from .confidence import (
    SIGNAL_WEIGHTS,
    band_for,
    classify_merge,
    edge_confidence,
    entity_confidence,
    merge_decision,
)
from .engine import run_investigation
from .models import Edge, Evidence, Investigation, Profile
from .provenance import build_evidence, make_evidence, utc_now_iso
from .resolution import (
    accept_possible_match,
    candidates_for_seed,
    merge_candidate,
    profile_id,
    queue_possible_match,
    reject_candidate,
    reject_possible_match,
    resolve_candidate,
    score_pair,
    standardise,
    standardize,
    survivorship,
    unmerge,
)
from .variations import generate_variations

__all__ = [
    "Edge",
    "Evidence",
    "Investigation",
    "Profile",
    "SIGNAL_WEIGHTS",
    "accept_possible_match",
    "band_for",
    "build_evidence",
    "candidates_for_seed",
    "classify_merge",
    "edge_confidence",
    "entity_confidence",
    "generate_variations",
    "make_evidence",
    "merge_candidate",
    "merge_decision",
    "profile_id",
    "queue_possible_match",
    "reject_candidate",
    "reject_possible_match",
    "resolve_candidate",
    "score_pair",
    "standardise",
    "standardize",
    "survivorship",
    "unmerge",
    "utc_now_iso",
    "run_investigation",
]
