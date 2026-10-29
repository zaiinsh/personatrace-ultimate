"""Live CLI: python -m personatrace.cli --seed <username>

Ready-to-use, no GUI needed. Runs a real (not demo) investigation
unless --demo is passed, writes investigation.json, case.json and
case.html into the output directory, and prints a per-source summary.

Keys are read from the environment only, never from a file written
by this tool:
  YOUTUBE_API_KEY / GOOGLE_API_KEY
  PERSONATRACE_AGGREGATOR_KEY
  PERSONATRACE_AGGREGATOR_BASE_URL

Public data only. No private accounts, no live location, no face
identification, no CAPTCHA / rate-limit / login-wall bypass. A source
with no key reports "not_checked", never "not found".
"""

import argparse
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path


def _keys_from_env() -> dict:
    keys = {}
    for env_name, key_name in (
        ("YOUTUBE_API_KEY", "youtube_api_key"),
        ("GOOGLE_API_KEY", "google_api_key"),
        ("PERSONATRACE_AGGREGATOR_KEY", "licensed_aggregator_key"),
        ("PERSONATRACE_AGGREGATOR_BASE_URL", "licensed_aggregator_base_url"),
        ("HIKERAPI_KEY", "hikerapi_key"),
        ("BRAVE_SEARCH_KEY", "brave_search_key"),
        ("TAVILY_API_KEY", "tavily_api_key"),
        ("SERPER_API_KEY", "serper_api_key"),
        ("GITHUB_TOKEN", "github_token"),
        ("SHODAN_API_KEY", "shodan_api_key"),
        ("SERPAPI_KEY", "serpapi_key"),
        ("GOOGLE_PSE_KEY", "google_pse_key"),
        ("VIRUSTOTAL_API_KEY", "virustotal_api_key"),
        ("SECURITYTRAILS_API_KEY", "securitytrails_api_key"),
        ("URLSCAN_API_KEY", "urlscan_api_key"),
        ("TINEYE_API_KEY", "tineye_api_key"),
        ("BING_VISUAL_SEARCH_KEY", "bing_visual_search_key"),
        ("EMAIL_VERIFICATION_KEY", "email_verification_key"),
        ("OPENAI_API_KEY", "openai_api_key"),
        ("TRANSCRIPTION_API_KEY", "transcription_api_key"),
        ("TELEGRAM_BOT_TOKEN", "telegram_bot_token"),
        ("TELEGRAM_CHAT_ID", "telegram_chat_id"),
    ):
        value = os.environ.get(env_name)
        if value:
            keys[key_name] = value
    return keys


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Run a PersonaTrace live investigation.")
    parser.add_argument("--seed", required=True, help="Seed value: username, domain, email, name, URL, image URL, hashtag, phrase, or IP (see --seed-type)")
    parser.add_argument("--seed-type", default="username", choices=("username", "domain", "email", "name", "url", "image", "hashtag", "phrase", "ip", "auto", "multi", "profile", "company", "wallet", "plate"),
                        help="Seed type (default username). 'auto' detects email/URL/IP/hashtag/domain/phrase; 'multi' = ';'-separated sub-seeds in one case; 'name' needs a full name, use --seed-context to narrow it")
    parser.add_argument("--seed-context", default="", help="Context for a name seed, e.g. city or company, used only to rank candidates")
    parser.add_argument("--out", default="live_out", help="Output directory")
    parser.add_argument("--demo", action="store_true",
                        help="Run with labelled demo data instead of live sources")
    parser.add_argument("--max-cost-units", type=float, default=None,
                        help="Per-case budget: skip YouTube search (100 units) if it exceeds this")
    parser.add_argument("--domain-limit", type=int, default=None,
                        help="Raise the bio-domain expansion cap (default 5)")
    parser.add_argument("--activity-limit", type=int, default=None,
                        help="Raise the activity-profile cap (default 4)")
    parser.add_argument("--watch", action="store_true",
                        help="Continuous monitoring: re-run in this process instead of once")
    parser.add_argument("--watch-interval-minutes", type=float, default=1440,
                        help="Minutes between watch runs (default 1440 = daily; 0 = immediate, for testing)")
    parser.add_argument("--watch-runs", type=int, default=2,
                        help="Number of watch runs including the first (default 2)")
    parser.add_argument("--export-cypher", action="store_true",
                        help="Also write a Neo4j Cypher migration script (case.cypher)")
    parser.add_argument("--export-sql", action="store_true",
                        help="Also write a Postgres migration script (case.sql)")
    parser.add_argument("--compare-seed", default=None,
                        help="Second person to compare with this seed (writes comparison.json)")
    parser.add_argument("--resume", default=None, help="Resume a previous case: load <outdir>/investigation.json and retry only degraded/not_checked adapters")
    parser.add_argument("--tag", default=None, help="Tag for case management (comma-separated)")
    parser.add_argument("--redact", action="store_true", help="Redact emails and phone numbers in exports")
    parser.add_argument("--retention-days", type=int, default=None, help="Delete case folders older than N days from cases.json")
    parser.add_argument("--site-check-all", action="store_true", help="Live-check all 152 templates (slow, rate-limited; default is the 10 reliable sites)")
    parser.add_argument("--parallel", type=int, default=1, help="Parallel adapter workers (default 1, safe; raise to 4 for faster large cases)")
    parser.add_argument("--live-check", action="store_true",
                        help="Automatic live updates by polling: re-run at a short interval and report new activity immediately (polling, not push — no platform offers a push feed for arbitrary profiles)")
    parser.add_argument("--live-check-interval-seconds", type=float, default=300,
                        help="Seconds between live-check polls (default 300)")
    parser.add_argument("--watch-domains", default=None,
                        help="Watch domains, comma separated (alerts for bio links / new certificates)")
    parser.add_argument("--vault-store", default=None,
                        help="Store a key in the encrypted vault: NAME=VALUE (needs PERSONATRACE_VAULT_PASSPHRASE)")
    parser.add_argument("--note", default=None,
                        help="Analyst note to store in this case (investigator's own text, not evidence)")
    # --- v8.0 flags -------------------------------------------------
    parser.add_argument("--direct", action="store_true",
                        help="v8 Direct Profile Mode for a profile/post URL: fetch that exact profile first, anchor it as confirmed, then expand (same as --seed-type profile)")
    parser.add_argument("--verify-keys", action="store_true",
                        help="v8: verify every configured key against its provider's cheap endpoint, write key_verification.json to --out, and exit (no investigation is run)")
    parser.add_argument("--comment-limit", type=int, default=100,
                        help="v8: max public comments collected per case (default 100; replaces the old 5/20 sample caps)")
    parser.add_argument("--variation-city", default="",
                        help="v8: city used by the stronger username-variation generator")
    parser.add_argument("--variation-years", default=None,
                        help="v8: comma-separated birth-year suffixes for username variations, e.g. 1990,1994")
    parser.add_argument("--offline", default=None, metavar="CASE_DIR",
                        help="v8 offline mode: rebuild dossier + exports from a saved case folder (CASE_DIR/investigation.json) with zero network calls, writing to --out")
    parser.add_argument("--assigned-to", default=None,
                        help="v8 case teamwork: assignee recorded on the case registry entry for this seed")
    parser.add_argument("--lead-status", default=None,
                        help="v8 case teamwork: lead status recorded on the case registry entry for this seed")
    # --- v9.0 flags -------------------------------------------------
    parser.add_argument("--time-budget", type=int, default=30,
                        help="v9: global soft time budget in seconds for a username run (default 30); slower optional adapters are marked degraded_timeout instead of blocking")
    parser.add_argument("--no-cache", action="store_true",
                        help="v9: bypass the 1-hour result cache for this run")
    parser.add_argument("--site-check-audit", action="store_true",
                        help="v9: run the live two-signal site-check self-audit (known-existing + known-nonexisting handles per sampled site), write site_check_audit.json to --out, and exit")
    parser.add_argument("--consistency-check", action="store_true",
                        help="v9: run the seed twice with the cache off, diff the run fingerprints, write consistency.json to --out, and exit")
    parser.add_argument("--screenshots", action="store_true",
                        help="v9: capture real browser screenshots (Playwright/Firefox) of the anchor + collected profile pages into proof_shots/ and record them in proof_index.json")
    parser.add_argument("--site-adapters", action="store_true",
                        help="v9: also run the 24 classified site adapters live for a username seed and write site_adapters.json")
    args = parser.parse_args(argv)
    if getattr(args, "offline", None):
        from personatrace.features.v8 import offline_rebuild
        _out = args.out if args.out != "live_out" else "offline_out"
        _res = offline_rebuild(args.offline, out_dir=_out)
        print(f"Offline rebuild: {_res.get('status')} — {_res.get('note', '')}")
        if _res.get("status") == "found":
            print(f"  dossier: {_res['paths'].get('dossier.json')}")
            print(f"  court_report: {_res['paths'].get('court_report.md')}")
        return 0 if _res.get("status") == "found" else 1
    if getattr(args, "comment_limit", None):
        os.environ["PERSONATRACE_COMMENT_LIMIT"] = str(args.comment_limit)
    if args.demo:
        os.environ["PERSONATRACE_DEMO"] = "1"
    if args.domain_limit:
        os.environ["PERSONATRACE_MAX_DOMAINS"] = str(args.domain_limit)
    if args.activity_limit:
        os.environ["PERSONATRACE_MAX_ACTIVITY_PROFILES"] = str(args.activity_limit)

    from personatrace.adapters.registry import available_adapters, cost_before_run
    from personatrace.core.engine import cluster_discovered_profiles, run_investigation
    from personatrace.features.export import export_case

    if args.vault_store and "=" in args.vault_store:
        from personatrace.storage.vault import store_key
        _name, _val = args.vault_store.split("=", 1)
        print(store_key(_name.strip(), _val.strip()))
    keys = _keys_from_env()
    if args.watch_domains:
        keys["watch_domains"] = args.watch_domains
    # Rejected-match memory: a rejected_matches.json in the out dir
    # keeps rejected candidates rejected on later runs.
    _rej_path = Path(args.out) / "rejected_matches.json"
    if _rej_path.exists():
        try:
            keys["_rejected_matches"] = json.loads(_rej_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    if getattr(args, "verify_keys", False):
        from personatrace.features.v8 import verify_all_keys
        _vk = verify_all_keys(keys)
        _vout = Path(args.out); _vout.mkdir(parents=True, exist_ok=True)
        (_vout / "key_verification.json").write_text(json.dumps(_vk, indent=2, default=str), encoding="utf-8")
        print("Key verification (values are never printed):")
        for _row in _vk["providers"]:
            print(f"  {_row['provider']}: {_row['status']}")
        print(f"  key_verification.json: {_vout / 'key_verification.json'}")
        return 0
    if getattr(args, "site_check_audit", False):
        from personatrace.features.v9 import site_check_audit
        _sa = site_check_audit()
        _sout = Path(args.out); _sout.mkdir(parents=True, exist_ok=True)
        (_sout / "site_check_audit.json").write_text(json.dumps(_sa, indent=2, default=str), encoding="utf-8")
        print(f"Site-check audit: {_sa['sampled_sites']} sites, {_sa['checks_run']} live checks, "
              f"false positives={_sa['false_positives']}, false negatives={_sa['false_negatives']}, uncertain={_sa['uncertain']}")
        print(f"  site_check_audit.json: {_sout / 'site_check_audit.json'}")
        return 0
    if getattr(args, "consistency_check", False):
        from personatrace.features.v9 import consistency_check
        _cc = consistency_check(args.seed, args.seed_type, keys=keys)
        _cout = Path(args.out); _cout.mkdir(parents=True, exist_ok=True)
        (_cout / "consistency.json").write_text(json.dumps(_cc, indent=2, default=str), encoding="utf-8")
        print(f"Consistency check for {args.seed}: match={_cc['match']} "
              f"(run A {_cc['run_a']['count']} profiles, run B {_cc['run_b']['count']} profiles)")
        for _row in _cc.get("changed_source_statuses", []):
            print(f"  source changed: {_row['platform']}: {_row['run_a']} -> {_row['run_b']}")
        print(f"  consistency.json: {_cout / 'consistency.json'}")
        return 0
    print("Cost before run:")
    for row in cost_before_run(keys):
        cost = row["cost_units"] if row["cost_units"] is not None else row["cost_note"]
        print(f"  {row['name']}: {row['status']} — {cost}")

    import time as _time

    if getattr(args, "live_check", False):
        args.watch = True
        args.watch_runs = args.watch_runs if args.watch_runs != 2 else 3
        args.watch_interval_minutes = args.live_check_interval_seconds / 60.0
        print(f"Live check (polling): every {args.live_check_interval_seconds} seconds, reporting new activity as soon as a poll finds it.")
    total_runs = args.watch_runs if args.watch else 1
    for run_no in range(1, total_runs + 1):
        if run_no > 1:
            print(f"Watch run {run_no}/{total_runs}: waiting {args.watch_interval_minutes} minute(s)...")
            _time.sleep(args.watch_interval_minutes * 60)
        print(f"Progress: collecting (run {run_no}/{total_runs})...")
        _v7_section = None
        _v8_section = None
        _v9_section = None
        if not args.demo and args.seed_type != "multi":
            from personatrace.features.v9 import investigate_v9
            _eff_parallel = args.parallel
            if _eff_parallel <= 1:
                _eff_parallel = 6
            _years = [y.strip() for y in (args.variation_years or "").split(",") if y.strip()]
            inv, _v7_section, _v8_section, _v9_section = investigate_v9(
                args.seed, args.seed_type, keys=keys, context=args.seed_context,
                parallel=_eff_parallel, direct=getattr(args, "direct", False),
                variation_city=args.variation_city or "", variation_years=_years,
                time_budget=getattr(args, "time_budget", 30),
                use_cache=not getattr(args, "no_cache", False))
            if _v9_section and _v9_section.get("timing"):
                _t = _v9_section["timing"]
                print(f"  [v9] timing: {_t.get('wall_seconds')}s (budget {_t.get('time_budget_seconds', getattr(args, 'time_budget', 30))}s, "
                      f"timed out: {_t.get('timed_out_adapters') or 'none'})")
        elif args.seed_type in ("email", "name", "url", "image", "hashtag", "phrase", "ip", "auto", "multi"):
            from personatrace.features.v7 import investigate_seed, investigate_multi
            if args.seed_type == "multi":
                inv, _v7_section = investigate_multi(args.seed, keys=keys, context=args.seed_context)
            else:
                inv, _v7_section = investigate_seed(args.seed, args.seed_type, keys=keys, context=args.seed_context)
        else:
            inv = run_investigation(args.seed, keys=keys, seed_type=args.seed_type,
                                    max_cost_units=args.max_cost_units)
        inv = cluster_discovered_profiles(inv)
        print("Progress: resolving / analysing...")
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        # Monitoring: compare with the previous run in this directory.
        monitor_report = None
        previous_path = out / "investigation.json"
        if previous_path.exists():
            try:
                previous = json.loads(previous_path.read_text(encoding="utf-8"))
                from personatrace.monitor import compare_investigations

                # asdict() omits the dynamic analysis attribute, so
                # include it explicitly — otherwise new activity would
                # falsely appear as "disappeared" on every run.
                _new_payload = asdict(inv)
                if getattr(inv, "analysis", None) is not None:
                    _new_payload["analysis"] = inv.analysis
                monitor_report = compare_investigations(previous, _new_payload)
            except Exception as exc:
                monitor_report = {"error": str(exc)}
        if args.note:
            from personatrace.features.analyst import add_note

            add_note(inv, args.note)
        payload = asdict(inv)
        if getattr(inv, "analysis", None) is not None:
            payload["analysis"] = inv.analysis
        if monitor_report is not None:
            payload["monitor_report"] = monitor_report
            (out / "monitor_report.json").write_text(
                json.dumps(monitor_report, indent=2, default=str), encoding="utf-8"
            )
        _rejected = [m for m in (inv.possible_matches or []) if isinstance(m, dict) and m.get("status") == "rejected"]
        if _rejected:
            _existing = []
            if _rej_path.exists():
                try: _existing = json.loads(_rej_path.read_text(encoding="utf-8"))
                except Exception: _existing = []
            for m in _rejected:
                prof = m.get("profile") or {}
                entry = f"{prof.get('platform')}:{prof.get('username')}" if isinstance(prof, dict) else str(prof)
                if entry not in _existing: _existing.append(entry)
            _rej_path.write_text(json.dumps(_existing, indent=2), encoding="utf-8")
        (out / "investigation.json").write_text(
            json.dumps(payload, indent=2, default=str), encoding="utf-8"
        )
        if getattr(args, "assigned_to", None) or getattr(args, "lead_status", None):
            try:
                from personatrace.features.v5 import register_case, search_cases
                from personatrace.features.v8 import set_case_team
                if not search_cases(".", query=inv.seed):
                    register_case(".", inv.seed, str(out), tags=(args.tag or "").split(",") if args.tag else [])
                _team = set_case_team(".", inv.seed, assigned_to=args.assigned_to, lead_status=args.lead_status)
                print(f"  case team: {_team.get('status')} — assigned_to={args.assigned_to}, lead_status={args.lead_status}")
            except Exception as _texc:
                print(f"  case team update failed: {_texc}")
        # Archive history: one JSON line per run, so snapshots are
        # tracked over time (continuous archive tracking, not just
        # a snapshot in the current run).
        from datetime import datetime as _dt, timezone as _tz

        _hist = {
            "ts_utc": _dt.now(_tz.utc).isoformat().replace("+00:00", "Z"),
            "run": run_no,
            "seed": inv.seed,
            "case_id": inv.case_id,
            "snapshots": (inv.analysis or {}).get("snapshots", []) if getattr(inv, "analysis", None) else [],
            "monitor_report": monitor_report,
        }
        with (out / "archive_history.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(_hist, default=str) + "\n")
        html_path = export_case(inv, out, fmt="html")
        json_path = export_case(inv, out, fmt="json")
        pdf_path = export_case(inv, out, fmt="pdf")
        csv_path = export_case(inv, out, fmt="csv")
        # v6 full dossier (JSON+CSV+Markdown+HTML, provenance-labelled, keys stripped).
        # Dorks run here (search-key/DDG) so the GUI search stays fast.
        try:
            from personatrace.features.v7 import build_v7_dossier, export_v7_dossier
            _payload = asdict(inv)
            if getattr(inv, "analysis", None) is not None:
                _payload["analysis"] = inv.analysis
            if _v8_section is not None or _v9_section is not None:
                from personatrace.features.v9 import build_v9_dossier, export_v9
                _dossier = build_v9_dossier(_payload, args.seed, seed_type=args.seed_type, keys=keys, v7_section=_v7_section, v8_section=_v8_section, v9_section=_v9_section, include_dorks=True)
                _dexports = export_v9(_dossier, out)
                # Direct Profile Mode snapshot + proof card (#1/#28),
                # written from the v8 section (the dossier copy has the
                # snapshot payload stripped by design).
                _dp = (_v8_section or {}).get("direct_profile") or {}
                _snap = _dp.get("_snapshot_text")
                if _snap:
                    _ext = "json" if _dp.get("_snapshot_kind") == "json" else "html"
                    (out / f"direct_profile_snapshot.{_ext}").write_text(_snap, encoding="utf-8")
                    print(f"  direct_profile_snapshot.{_ext}: {out / f'direct_profile_snapshot.{_ext}'}")
                if _dp.get("profile"):
                    from personatrace.features.v8 import proof_card_png as _pcp
                    _card = _pcp({**_dp["profile"], "evidence": [{"source_url": (_dp.get("parsed") or {}).get("url", ""), "captured_at_utc": ""}]}, str(out / "profile_proof.png"))
                    if _card.get("status") == "found":
                        print(f"  profile_proof.png: {out / 'profile_proof.png'} (snapshot proof card, not a browser screenshot)")
                print(f"  court_report: {out / 'court_report.md'}")
            else:
                _dossier = build_v7_dossier(_payload, args.seed, seed_type=args.seed_type, keys=keys, v7_section=_v7_section, include_dorks=True)
                _dexports = export_v7_dossier(_dossier, out)
            print(f"  dossier: {_dexports['dossier.json']} ({_dossier.get('profile_summary_status')}, {len(_dossier.get('profile_summary', []))} profile(s))")
            if _dossier.get("no_profiles_found_note"):
                print(f"  NOTE: {_dossier['no_profiles_found_note']}")
        except Exception as _dexc:
            print(f"  dossier build failed (case files above are still valid): {_dexc}")
        if getattr(args, "site_adapters", False) and args.seed_type == "username":
            try:
                from personatrace.features.v9 import site_adapters_v9
                _sa9 = site_adapters_v9(args.seed)
                (out / "site_adapters.json").write_text(json.dumps(_sa9, indent=2, default=str), encoding="utf-8")
                print(f"  site_adapters: {_sa9['count']} sites, statuses={_sa9['status_counts']} -> {out / 'site_adapters.json'}")
            except Exception as _saexc:
                print(f"  site_adapters failed: {_saexc}")
        if getattr(args, "screenshots", False):
            try:
                from personatrace.features.v9 import capture_screenshots, write_proof_index
                _urls = []
                for _p in inv.profiles:
                    for _ev in (getattr(_p, "evidence", []) or []):
                        _u = _ev.get("source_url") if isinstance(_ev, dict) else getattr(_ev, "source_url", "")
                        if _u and _u not in _urls:
                            _urls.append(_u)
                        break
                _shots = capture_screenshots(_urls[:5], str(out / "proof_shots"))
                if _shots.get("screenshots"):
                    write_proof_index(_shots["screenshots"], str(out))
                print(f"  screenshots: {_shots.get('status')} ({_shots.get('count', 0)} browser screenshot(s), proof_type={_shots.get('proof_type')})")
            except Exception as _shexc:
                print(f"  screenshots failed: {_shexc}")
        if getattr(inv, "analysis", None) and inv.analysis.get("report_draft"):
            (out / "report.md").write_text(inv.analysis["report_draft"], encoding="utf-8")
        # Second-person comparison (v1.4), only on the final run.
        if args.compare_seed and run_no == total_runs:
            try:
                second = run_investigation(args.compare_seed, keys=keys, seed_type=args.seed_type, max_cost_units=args.max_cost_units)
                second = cluster_discovered_profiles(second)
                from personatrace.features.compare_cases import compare_cases

                comparison = compare_cases(inv, second)
                (out / "comparison.json").write_text(json.dumps(comparison, indent=2, default=str), encoding="utf-8")
                try:
                    from personatrace.features.v8 import follower_overlap
                    _anchor_user = inv.seed if args.seed_type == "username" else ((_v8_section or {}).get("direct_profile", {}).get("parsed", {}) or {}).get("username")
                    if _anchor_user:
                        _ov = follower_overlap(_anchor_user, args.compare_seed, keys=keys)
                        (out / "follower_overlap.json").write_text(json.dumps(_ov, indent=2, default=str), encoding="utf-8")
                        print(f"Follower overlap ({_anchor_user} vs {args.compare_seed}): {_ov.get('status')} — common followers: {_ov.get('common_followers_count')}")
                except Exception as _oexc:
                    print(f"Follower overlap failed: {_oexc}")
                print(f"Comparison with {args.compare_seed}: shared domains={comparison['shared_bio_domains']}, shared contacts={comparison['shared_contacts']}")
            except Exception as exc:
                print(f"Comparison failed: {exc}")
        # Daily summary report for scheduled checks (watch / cron).
        if monitor_report is not None:
            summary_lines = [
                f"# PersonaTrace daily summary — seed {inv.seed}",
                f"Run: {run_no}  Case: {inv.case_id}",
                f"Profiles: {len(inv.profiles)}  Edges: {len(inv.edges)}",
                f"Profiles added: {monitor_report.get('profiles_added')}",
                f"Follower changes: {monitor_report.get('follower_changes')}",
                f"Name changes: {monitor_report.get('name_changes')}",
                f"New activity items: {len(monitor_report.get('new_activity') or [])}",
                f"Disappeared activity items (check source statuses first): {len(monitor_report.get('disappeared_activity') or [])}",
                f"Monitor alerts: {monitor_report.get('monitor_alerts')}",
                "Schedule daily with cron, e.g.: 0 9 * * * python -m personatrace.cli --seed " + inv.seed + " --out " + str(out),
            ]
            (out / "watch_summary.md").write_text("\n".join(summary_lines) + "\n", encoding="utf-8")
        extra = []
        if args.export_cypher or args.export_sql:
            from personatrace.storage.migrate import to_cypher, to_postgres_sql

            if args.export_cypher:
                (out / "case.cypher").write_text(to_cypher(inv), encoding="utf-8")
                extra.append("case.cypher")
            if args.export_sql:
                (out / "case.sql").write_text(to_postgres_sql(inv), encoding="utf-8")
                extra.append("case.sql")
        print(f"Seed: {inv.seed}  Case: {inv.case_id}")
        print(f"Profiles: {len(inv.profiles)}  Edges: {len(inv.edges)}  "
              f"Possible matches: {len(inv.possible_matches)}")
        if getattr(inv, "analysis", None):
            a = inv.analysis
            print(f"Analysis: bio domains={a.get('bio_domains')}, "
                  f"avatar reuse={len(a.get('avatar_reuse', []))}, "
                  f"activity items={a.get('behaviour_summary', {}).get('activity_items', 0)}, "
                  f"alerts={len(a.get('alerts', []))}, "
                  f"risk signals={len(a.get('risk_signals', []))}, "
                  f"bridge persons={len(a.get('bridge_persons', []))}, "
                  f"next steps={len(a.get('next_steps', []))}")
        if monitor_report is not None:
            print(f"Monitor vs previous run: added={monitor_report.get('profiles_added')}, "
                  f"changed={list(monitor_report.get('profiles_changed', {}))}, "
                  f"new edges={len(monitor_report.get('new_edges', []))}")
        print("Sources:")
        for audit in inv.audit:
            if audit.get("action") == "adapter_search":
                detail = audit.get("detail", {})
                print(f"  {detail.get('platform')}: {detail.get('status')} — "
                      f"{detail.get('profiles_found')} profile(s)")
        print(f"  investigation.json: {out / 'investigation.json'}")
        print(f"  case.html: {html_path}")
        print(f"  case.json: {json_path}")
        print(f"  case.pdf: {pdf_path}")
        print(f"  case.csv: {csv_path}")
        if extra:
            print(f"  migration: {', '.join(extra)}")
        print("Progress: complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
