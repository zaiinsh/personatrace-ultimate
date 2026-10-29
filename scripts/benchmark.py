#!/usr/bin/env python3
"""PersonaTrace v9 benchmark (#11): run a fixed list of 20+ real
public usernames (+ nonexistent controls that MUST return ~0) in
username mode, time-budgeted, and write BENCHMARK.md with the real
numbers — profiles, edges, wall time and run fingerprint per seed.

Usage:  python scripts/benchmark.py [--out BENCHMARK.md] [--budget 30]
Public data only. Results reflect the network and source statuses at
run time; degraded sources are reported, never hidden.
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

SEEDS = [
    "octocat", "torvalds", "gaearon", "sindresorhus", "yyx990803",
    "defunkt", "mojombo", "kelseyhightower", "btholt", "sarah_edo",
    "github", "microsoft", "google", "netflix", "spotify",
    "iamshaunjp", "bradtraversy", "fireship-io", "ThePrimeagen",
    "tj", "mitchellh", "antirez", "mrdoob",
]
CONTROLS = [
    "pt-no-such-user-9f3k2x7q", "zzqxv-not-a-person-4411", "no-such-handle-xqzw-778",
]


def _run_one(seed, budget):
    from dataclasses import asdict
    from personatrace.features.v9 import investigate_v9, run_fingerprint
    started = time.time()
    inv, _v7, _v8, _v9 = investigate_v9(
        seed, "username", keys={}, parallel=6, time_budget=budget,
        use_cache=False, live_extras=False, progress=False)
    wall = round(time.time() - started, 2)
    profiles = [asdict(p) if not isinstance(p, dict) else p for p in inv.profiles]
    fp = run_fingerprint(profiles)
    src = {}
    for row in (inv.audit or []):
        if isinstance(row, dict) and row.get("action") == "adapter_search":
            d = row.get("detail", {})
            src[d.get("platform")] = d.get("status")
    degraded = sorted(k for k, v in src.items() if v not in ("ok", "active", "found"))
    return {"seed": seed, "profiles": len(inv.profiles), "edges": len(inv.edges),
            "possible_matches": len(inv.possible_matches or []), "wall_seconds": wall,
            "fingerprint": fp["sha256"][:12], "timed_out": (_v9.get("timing") or {}).get("timed_out_adapters") or [],
            "degraded_or_other_sources": degraded}


def main(argv=None):
    ap = argparse.ArgumentParser(description="PersonaTrace v9 live benchmark")
    ap.add_argument("--out", default="BENCHMARK.md")
    ap.add_argument("--budget", type=int, default=30)
    args = ap.parse_args(argv)
    rows, controls = [], []
    for seed in SEEDS:
        try:
            r = _run_one(seed, args.budget)
        except Exception as exc:
            r = {"seed": seed, "profiles": 0, "edges": 0, "possible_matches": 0,
                 "wall_seconds": 0, "fingerprint": "-", "timed_out": [],
                 "degraded_or_other_sources": [f"run failed: {str(exc)[:100]}"]}
        rows.append(r)
        print(f"{seed}: {r['profiles']} profiles, {r['wall_seconds']}s")
    for seed in CONTROLS:
        try:
            r = _run_one(seed, args.budget)
        except Exception as exc:
            r = {"seed": seed, "profiles": 0, "edges": 0, "possible_matches": 0,
                 "wall_seconds": 0, "fingerprint": "-", "timed_out": [],
                 "degraded_or_other_sources": [f"run failed: {str(exc)[:100]}"]}
        controls.append(r)
        print(f"CONTROL {seed}: {r['profiles']} profiles")
    total_profiles = sum(r["profiles"] for r in rows)
    total_time = round(sum(r["wall_seconds"] for r in rows + controls), 1)
    lines = [
        "# PersonaTrace v9 — live benchmark",
        "",
        f"Seeds run: {len(rows)} real public usernames + {len(controls)} nonexistent controls.",
        f"Total profiles across seeds: {total_profiles}. Total wall time: {total_time}s "
        f"(per-seed time budget {args.budget}s, parallel adapters, no keys, no cache).",
        "Controls must return ~0 profiles; anything else would be a false-positive bug and is shown as-is.",
        "",
        "| seed | profiles | edges | possible | wall (s) | fingerprint | timed-out adapters | degraded/other sources |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in rows + controls:
        tag = " (CONTROL)" if r in controls else ""
        lines.append(f"| {r['seed']}{tag} | {r['profiles']} | {r['edges']} | {r['possible_matches']} | "
                     f"{r['wall_seconds']} | {r['fingerprint']} | {', '.join(r['timed_out']) or '—'} | "
                     f"{', '.join(r['degraded_or_other_sources']) or '—'} |")
    lines += ["", "Notes: numbers are the real live outcome at run time. A seed with few "
              "profiles usually means its owner is quiet on the free sources PersonaTrace "
              "checks (GitHub/GitLab/Bluesky/Mastodon/HN/StackOverflow/Telegram + site checks), "
              "not that the person has no accounts. Gated platforms (Instagram/X/TikTok/Reddit/"
              "YouTube full data) are not_checked without the investigator's own keys and are "
              "excluded from this no-key benchmark by design."]
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print(f"BENCHMARK.md written: {args.out} (total profiles {total_profiles}, total {total_time}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
