"""Self-checking planner: the automatic next step, with a human gate.

Given an investigation + analysis + per-source statuses, this
module plans the next steps in priority order. It does NOT execute
any step that touches a person, a platform or a paid API on its own:
every step that costs money, needs a key, or needs a human decision
is marked human_required=True and is only a recommendation.

Steps are derived from evidence gaps, never invented:
- a not_checked gated/YouTube source -> add the key/address.
- a degraded source -> retry later (after the source's own window),
  never immediately and never by bypassing a limit.
- a possible-match queue entry -> human review (merge/reject/keep).
- an avatar-reuse or bridge-domain lead -> human review of the
  two profiles' evidence before any conclusion.
- a bio domain with certificate subdomains -> run a new case for
  each new subdomain seed (investigator starts it, planner does not).
- an analysis alert -> acknowledge it in the case file.
- if nothing is outstanding -> case is complete for this run;
  schedule the next watch run (monitor) instead of inventing work.
"""

from __future__ import annotations


def plan_next_steps(inv, analysis: dict | None = None, source_statuses: dict | None = None) -> list:
    analysis = analysis or {}
    source_statuses = source_statuses or {}
    steps = []

    def _add(priority: int, action: str, reason: str, cost: str = "0", human_required: bool = False):
        steps.append({
            "priority": priority, "action": action, "reason": reason,
            "cost": cost, "human_required": human_required,
        })

    for name, status in source_statuses.items():
        if status == "not_checked":
            _add(1, f"Add a key/address for {name} in Settings, then re-run.",
                 f"{name} was not checked, so a missing profile there would be a silent gap.", "key-dependent", True)
        elif status == "degraded":
            _add(2, f"Re-run {name} later; do not retry immediately.",
                 f"{name} was degraded (rate limit / timeout / provider error) in this run.", "0", False)
    possible = getattr(inv, "possible_matches", []) or []
    if possible:
        _add(1, "Review the possible-match queue (merge, reject, or keep separate).",
             f"{len(possible)} entr(ies) sit below the auto-merge threshold and must not auto-merge.", "0", True)
    for reuse in analysis.get("avatar_reuse", []) or []:
        _add(2, f"Human-review avatar reuse: {reuse.get('a')} vs {reuse.get('b')}.",
             "Same public avatar is a lead, not proof of same person.", "0", True)
    for domain in analysis.get("certificate_subdomains", {}) or {}:
        subs = analysis["certificate_subdomains"][domain] or []
        if subs:
            _add(3, f"Consider new cases for certificate subdomains of {domain} ({', '.join(subs[:3])}).",
                 "Certificate names are public leads from crt.sh, not confirmed accounts.", "0", True)
    for domain, profiles in (analysis.get("bridge_domains", {}) or {}).items():
        _add(2, f"Human-review bridge domain {domain} linking {', '.join(profiles)}.",
             "A shared bio domain links clusters; it does not prove common ownership.", "0", True)
    for alert in analysis.get("alerts", []) or []:
        _add(3, f"Acknowledge alert: {alert.get('message', '')}",
             "Alerts are notifications to a human, never actions.", "0", True)
    if not steps:
        _add(4, "No outstanding steps for this run. Schedule the next watch run.",
             "All checked sources returned, no queue entries and no leads pending.", "0", False)
    steps.sort(key=lambda s: s["priority"])
    return steps
