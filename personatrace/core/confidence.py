"""Confidence — 3-layer model from CONTRACT.md.

Bands: Low (<50) | Medium (50-79) | High (80+).

Design notes (these are what make the contract's examples hold):

* Signal ``weight`` is an *absolute contribution* (0-1 scale), not a
  share to be renormalised. ``score = sum(weight * value) * 100``,
  capped at 100. That is why an exact username alone — canonical
  weight 0.40 — scores 40 (Low), while exact username (0.40) + same
  avatar pHash (0.30) + same bio link (0.30) scores 100 (High).
* Weights are shown in every driver string (sum-check), and a note is
  added when the supplied weights sum to more than 1.0 (score capped).
* Style/timing signals are capped at a combined 25 points, enforced
  here (not in features/stylometry.py). A style-only signal therefore
  can never reach auto-merge (80), nor even the possible-match band.
"""

from __future__ import annotations

# Canonical absolute-contribution weights used by resolution.score_pair.
SIGNAL_WEIGHTS: dict[str, float] = {
    "exact_username": 0.40,
    "username_variant": 0.25,
    "avatar_reuse": 0.30,
    "bio_link": 0.30,
    "network_overlap": 0.20,
    "style_timing": 0.25,
}

STYLE_TIMING_NAMES = {"style_timing", "stylometry", "timing", "style", "style_similarity", "timing_similarity"}

#: Combined cap (points out of 100) for all style/timing signals.
STYLE_TIMING_CAP = 25.0

MERGE_AUTO_MIN = 80
POSSIBLE_MIN = 50


def band_for(score: int) -> str:
    """Band for a 0-100 score: Low (<50), Medium (50-79), High (80+)."""
    score = max(0, min(100, int(score)))
    if score >= 80:
        return "High"
    if score >= 50:
        return "Medium"
    return "Low"


def edge_confidence(signals: list) -> tuple[int, str, list[str]]:
    """Score one edge from ``[(name, weight, value 0-1), ...]``.

    Returns ``(score int 0-100, band str, drivers list[str])``.
    ``drivers`` shows each signal's weight, value and contribution, the
    weight sum-check, and any style/timing capping applied.
    """
    drivers: list[str] = []
    total_weight = 0.0
    other_points = 0.0
    style_points = 0.0

    for signal in signals or []:
        name, weight, value = signal[0], signal[1], signal[2]
        weight = float(weight)
        value = float(value)
        if weight < 0:
            raise ValueError(f"signal weight must be >= 0: {name}={weight}")
        value = max(0.0, min(1.0, value))
        total_weight += weight
        contribution = weight * value * 100.0
        if name in STYLE_TIMING_NAMES:
            style_points += contribution
        else:
            other_points += contribution
        drivers.append(
            f"{name}: weight={weight:.2f} value={value:.2f} contribution={contribution:.1f}"
        )

    capped_style = min(style_points, STYLE_TIMING_CAP)
    if style_points > STYLE_TIMING_CAP:
        drivers.append(
            f"style_timing capped: {style_points:.1f} -> {STYLE_TIMING_CAP:.1f} "
            f"(combined style/timing contribution capped at 25%)"
        )
    raw = other_points + capped_style
    score = int(round(min(100.0, raw)))
    drivers.append(f"weights sum={total_weight:.2f}; raw={raw:.1f}; score={score}")
    if total_weight > 1.0:
        drivers.append("note: weights sum > 1.0; score capped at 100")
    return score, band_for(score), drivers


def entity_confidence(edges: list) -> tuple[int, str, list[str]]:
    """Combine edges into one entity confidence, never above 100.

    Corroboration model: ``1 - prod(1 - c/100)`` — each additional
    independent edge raises confidence, a single edge keeps its own
    score, and the result is capped at 100. Drivers list every edge.
    Accepts Edge objects or dicts with ``confidence``/``kind`` keys.
    """
    if not edges:
        return 0, "Low", ["no edges: entity confidence 0 (Low)"]

    drivers: list[str] = []
    remaining = 1.0
    for edge in edges:
        if isinstance(edge, dict):
            conf = int(edge.get("confidence", 0))
            kind = edge.get("kind", "edge")
        else:
            conf = int(getattr(edge, "confidence", 0))
            kind = getattr(edge, "kind", "edge")
        conf = max(0, min(100, conf))
        drivers.append(f"{kind}: confidence={conf}")
        remaining *= 1.0 - conf / 100.0
    score = int(round(min(100.0, (1.0 - remaining) * 100.0)))
    drivers.append(f"combined (corroboration) score={score}")
    return score, band_for(score), drivers


def classify_merge(score: int) -> str:
    """Merge decision for a score: auto_merge (>=80) | possible (50-79) | reject (<50)."""
    score = max(0, min(100, int(score)))
    if score >= MERGE_AUTO_MIN:
        return "auto_merge"
    if score >= POSSIBLE_MIN:
        return "possible"
    return "reject"


# Alias matching the CONTRACT wording ("merge thresholds").
merge_decision = classify_merge
