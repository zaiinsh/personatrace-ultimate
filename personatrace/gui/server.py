"""PersonaTrace Ultimate GUI dashboard — stdlib http.server only.

Run: ``python -m personatrace.gui.server [--port 8787]`` from the app root.

``run_gui(db_path=None, port=8787)`` starts the server on a background
daemon thread and returns the server object (call ``shutdown()`` to stop
it); the ``__main__`` block serves in the foreground instead.

Data source: if a storage module is importable and ``db_path`` is given,
the server tries it; any failure falls back to the self-contained demo
data in :mod:`personatrace.gui.demo_data` (fictional ``demo_*`` data,
always labelled demo). Key handling: POST /api/settings/keys stores the
key NAME only — the value is never stored and never echoed back.
"""

import html
import json
import mimetypes
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import demo_data

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "static")


def _load_investigation(db_path):
    """Try real storage (lazy import); fall back to demo data.

    v6.0.0-final note on the demo bug: the INITIAL dashboard load is
    still labelled demo data (existing GUI tests rely on it, and it is
    clearly labelled DEMO DATA). The bug was different: AFTER a live
    search, the old demo profile stayed selected in the summary panel
    even when the live search found 0 profiles, making demo_user_01
    look like the live result. That is fixed in two places: (1) the
    handler's _investigation() below now returns the last LIVE search
    (even a 0-profile one) once a live search has run, instead of
    falling back to demo; (2) app.js clears the summary/evidence on
    every live search and shows an explicit 'no profiles found, routes
    tried' message when profiles is empty.
    """
    if db_path:
        try:
            from personatrace.storage.db import load_investigation
            inv = load_investigation(db_path)
            if inv is not None:
                return inv
        except Exception:
            pass
    return demo_data.demo_investigation()


def _investigation_to_json(inv):
    """Accept a demo dict or a contract Investigation dataclass."""
    if isinstance(inv, dict):
        return inv
    from dataclasses import asdict
    try:
        data = asdict(inv)
    except Exception:
        data = {"case_id": getattr(inv, "case_id", ""),
                "seed": getattr(inv, "seed", ""),
                "profiles": [], "edges": []}
    data.setdefault("demo", False)
    return data


def _export_json(inv):
    """Single-case export structure (this case only, never bulk)."""
    data = _investigation_to_json(inv)
    profiles = data.get("profiles", [])
    evidence = []
    for profile in profiles:
        if isinstance(profile, dict):
            evidence.extend(profile.get("evidence", []))
    return {
        "case_id": data.get("case_id"),
        "seed": data.get("seed"),
        "seed_type": data.get("seed_type", "username"),
        "demo": data.get("demo", False),
        "label": "demo" if data.get("demo") else "case",
        "profiles": profiles,
        "edges": data.get("edges", []),
        "possible_matches": data.get("possible_matches", []),
        "evidence": evidence,
        "timeline": data.get("timeline", []),
        "alerts": data.get("alerts", []),
        "audit": data.get("audit", []),
    }


def _export_html(inv):
    """Single-case HTML export: every fact with provenance."""
    data = _export_json(inv)
    rows = []
    for item in data["evidence"]:
        rows.append(
            "<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td>"
            "<td>{}</td><td>{}</td><td>{}</td></tr>".format(
                html.escape(str(item.get("platform", ""))),
                html.escape(str(item.get("field", ""))),
                html.escape(str(item.get("value", ""))),
                '<a href="{}">{}</a>'.format(
                    html.escape(str(item.get("source_url", ""))),
                    html.escape(str(item.get("source_url", "")))),
                html.escape(str(item.get("captured_at_utc", ""))),
                html.escape(str(item.get("method", ""))),
                html.escape(str(item.get("confidence", "")))))
    audit_rows = "".join(
        "<li>{} — {} — {}</li>".format(
            html.escape(str(a.get("ts_utc", ""))),
            html.escape(str(a.get("action", ""))),
            html.escape(str(a.get("detail", ""))))
        for a in data["audit"])
    return ("<!DOCTYPE html><html><head><meta charset='utf-8'>"
            "<title>PersonaTrace export: {}</title></head><body>"
            "<h1>PersonaTrace case export ({})</h1>"
            "<p>Case: {} — seed: {} — single-case export only.</p>"
            "<table><tr><th>Platform</th><th>Field</th><th>Value</th>"
            "<th>Source URL</th><th>Captured (UTC)</th><th>Method</th>"
            "<th>Confidence</th></tr>{}</table>"
            "<h2>Audit log</h2><ul>{}</ul></body></html>".format(
                html.escape(str(data["case_id"])),
                html.escape(str(data["label"])),
                html.escape(str(data["case_id"])),
                html.escape(str(data["seed"])),
                "".join(rows), audit_rows))


def _live_investigation_to_json(inv):
    """Convert a live Investigation dataclass to dashboard JSON.

    Adds the node_id / ring fields the graph renderer needs, and a
    display confidence (highest evidence confidence) when the core
    profile confidence is 0 (unknown). Keys are never part of this
    payload: the engine audit contains no key values.
    """
    data = _investigation_to_json(inv)
    profiles = data.get("profiles", [])
    for i, profile in enumerate(profiles):
        if isinstance(profile, dict):
            profile.setdefault(
                "node_id", f"{profile.get('platform', '')}:{profile.get('username', '')}"
            )
            profile.setdefault(
                "ring", 0 if profile.get("username") == data.get("seed") and i == 0 else 1
            )
            if not profile.get("confidence"):
                ev = profile.get("evidence") or []
                profile["confidence"] = max(
                    (e.get("confidence", 0) for e in ev if isinstance(e, dict)), default=0
                )
            profile.setdefault("confidence_drivers", [])
            if not profile["confidence_drivers"] and profile.get("evidence"):
                first = profile["evidence"][0]
                if isinstance(first, dict):
                    profile["confidence_drivers"] = [
                        f"public source: {first.get('source_url', '')} "
                        f"(method {first.get('method', '')})"
                    ]
    data["demo"] = False
    data["label"] = "live"
    # Timeline from audit, so a live case has a replayable timeline.
    timeline = []
    for entry in data.get("audit", []) or []:
        if isinstance(entry, dict):
            timeline.append(
                {
                    "ts_utc": entry.get("ts_utc", ""),
                    "kind": entry.get("action", ""),
                    "description": str(entry.get("detail", "")),
                }
            )
    data["timeline"] = timeline
    return data


def _cost_rows(keys):
    try:
        from personatrace.adapters.registry import cost_before_run

        return cost_before_run(keys or {})
    except Exception:
        return []


class _State:
    """Per-server mutable state: key NAMES only, never key values.

    Live search keys are different: they are passed in a single
    /api/search request, used only for that run, and never stored in
    this state, on disk, or in any response. ``last_search`` holds
    only the investigation result, never the keys that produced it.
    """

    def __init__(self, db_path=None):
        self.db_path = db_path
        self.key_names = set()
        self.last_search = None
        self._lock = threading.Lock()

    def add_key_name(self, name):
        with self._lock:
            self.key_names.add(name)

    def snapshot_key_names(self):
        with self._lock:
            return set(self.key_names)

    def set_last_search(self, data):
        with self._lock:
            self.last_search = data

    def get_last_search(self):
        with self._lock:
            return self.last_search


def make_handler(state):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        # -- helpers -------------------------------------------------
        def log_message(self, *args):  # keep test output clean
            pass

        def _send_json(self, obj, status=200):
            body = json.dumps(obj).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_text(self, body, content_type, status=200):
            data = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _send_bytes(self, data, content_type, status=200):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _serve_static(self, rel):
            safe = os.path.normpath(rel).lstrip(os.sep)
            if safe.startswith(".."):
                return self._send_json({"error": "not found"}, 404)
            path = os.path.join(STATIC_DIR, safe)
            if not os.path.isfile(path):
                return self._send_json({"error": "not found"}, 404)
            ctype, _ = mimetypes.guess_type(path)
            with open(path, "rb") as fh:
                body = fh.read()
            self.send_response(200)
            self.send_header("Content-Type",
                             ctype or "application/octet-stream")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _investigation(self):
            # v6 fix: once a live search has run, every panel (timeline,
            # alerts, export, progress) shows THAT live result — even if
            # it found 0 profiles — never the initial demo data.
            last = state.get_last_search()
            if last is not None:
                return last
            return _investigation_to_json(
                _load_investigation(state.db_path))

        # -- routing -------------------------------------------------
        def do_GET(self):
            parsed = urlparse(self.path)
            path = parsed.path
            query = parse_qs(parsed.query)
            if path in ("/", "/index.html"):
                return self._serve_static("index.html")
            if path.startswith("/static/"):
                return self._serve_static(path[len("/static/"):])
            if path in ("/app.js", "/styles.css"):
                return self._serve_static(path.lstrip("/"))
            if path == "/api/v9/info":
                try:
                    from personatrace.features.v9 import SITE_ADAPTERS_V9, VERSION as _V9
                    _i18n = {}
                    try:
                        with open(os.path.join(STATIC_DIR, "i18n.json"), encoding="utf-8") as _fh:
                            _i18n = json.load(_fh)
                    except Exception:
                        pass
                    return self._send_json({
                        "version": _V9,
                        "languages": _i18n.get("languages", ["en"]),
                        "rtl_languages": _i18n.get("rtl", []),
                        "i18n_keys_per_language": len((_i18n.get("strings") or {}).get("en", {})),
                        "site_adapter_classifications": {e["service"]: e["classification"] for e in SITE_ADAPTERS_V9},
                    })
                except Exception as _exc:
                    return self._send_json({"error": str(_exc)}, 500)
            if path == "/api/investigation":
                if query.get("live", ["0"])[0] == "1":
                    last = state.get_last_search()
                    if last is not None:
                        return self._send_json(last)
                return self._send_json(self._investigation())
            if path == "/api/cost":
                return self._send_json({"cost_before_run": _cost_rows({})})
            if path == "/api/settings":
                return self._send_json({
                    "adapters": demo_data.demo_adapters(
                        state.snapshot_key_names()),
                    "key_names": sorted(state.snapshot_key_names()),
                })
            if path == "/api/timeline":
                return self._send_json(
                    {"timeline": self._investigation().get("timeline", [])})
            if path == "/api/alerts":
                return self._send_json(
                    {"alerts": self._investigation().get("alerts", [])})
            if path == "/api/progress":
                # Investigation progress tracker: stages + per-source
                # status from the last search (or demo investigation).
                last = state.get_last_search()
                data = last if last is not None else self._investigation()
                sources = []
                for entry in data.get("audit", []) or []:
                    if isinstance(entry, dict) and entry.get("action") == "adapter_search":
                        sources.append(entry.get("detail", {}))
                done = len(sources)
                total = max(done, len(sources))
                return self._send_json({
                    "stages": [
                        {"name": "collecting", "status": "complete" if (sources or data.get("profiles")) else "pending"},
                        {"name": "resolving", "status": "complete" if data.get("profiles") else "pending"},
                        {"name": "analysing", "status": "complete" if data.get("analysis") else "pending"},
                        {"name": "complete", "status": "complete" if (sources or data.get("profiles")) else "pending"},
                    ],
                    "sources": sources,
                    "profiles": len(data.get("profiles", []) or []),
                    "edges": len(data.get("edges", []) or []),
                    "analysis_keys": sorted((data.get("analysis") or {}).keys()),
                    "progress_percent": 100 if (sources or data.get("profiles")) else 0,
                })
            if path == "/api/migrate":
                fmt = (query.get("fmt", ["cypher"])[0] or "cypher").lower()
                last = state.get_last_search()
                inv = last if last is not None else self._investigation()
                from personatrace.storage.migrate import to_cypher, to_postgres_sql

                if fmt == "sql":
                    return self._send_text(to_postgres_sql(inv), "text/plain")
                return self._send_text(to_cypher(inv), "text/plain")
            if path == "/api/export":
                fmt = (query.get("fmt", ["json"])[0] or "json").lower()
                if query.get("live", ["0"])[0] == "1":
                    last = state.get_last_search()
                    inv = last if last is not None else self._investigation()
                else:
                    inv = self._investigation()
                if fmt == "json":
                    return self._send_json(_export_json(inv))
                if fmt == "html":
                    return self._send_text(_export_html(inv), "text/html")
                if fmt == "csv":
                    import csv as _csv
                    import io as _io

                    facts = []
                    for p in inv.get("profiles", []) or []:
                        for ev in p.get("evidence", []) or []:
                            facts.append([p.get("platform"), p.get("username"), ev.get("field"), ev.get("value"), ev.get("source_url"), ev.get("captured_at_utc"), ev.get("method"), ev.get("confidence")])
                    buf = _io.StringIO()
                    writer = _csv.writer(buf)
                    writer.writerow(["platform", "username", "field", "value", "source_url", "captured_at_utc", "method", "confidence"])
                    writer.writerows(facts)
                    return self._send_text(buf.getvalue(), "text/csv")
                if fmt == "report":
                    a = inv.get("analysis") or {}
                    return self._send_text(a.get("report_draft") or "No report draft available for this case. Run a live search first.", "text/markdown")
                if fmt == "pdf":
                    import tempfile

                    from personatrace.features.export import export_case

                    # export_case needs an Investigation-like object;
                    # _export_json data is a dict, so build a minimal
                    # wrapper via the PDF exporter directly.
                    from personatrace.features.export_pdf import export_pdf

                    class _DictInv:
                        def __init__(self, data):
                            self.__dict__.update(data)

                    with tempfile.TemporaryDirectory() as tmp:
                        path = export_pdf(_DictInv(inv), tmp)
                        with open(path, "rb") as fh:
                            body = fh.read()
                    return self._send_bytes(body, "application/pdf")
                return self._send_json(
                    {"error": "fmt must be json, html or pdf"}, 400)
            return self._send_json({"error": "not found"}, 404)

        def do_POST(self):
            parsed = urlparse(self.path)
            try:
                length = int(self.headers.get("Content-Length", 0))
            except ValueError:
                length = 0
            raw = self.rfile.read(length) if length > 0 else b""
            try:
                payload = json.loads(raw.decode("utf-8")) if raw else {}
            except ValueError:
                return self._send_json({"error": "invalid JSON"}, 400)
            if parsed.path == "/api/search":
                from personatrace.storage.vault import can, role_for
                if not can(role_for(None), "can_search"):
                    return self._send_json({"error": "Role viewer cannot run searches. Set PERSONATRACE_ROLE=analyst or admin."}, 403)
                seed = str(payload.get("seed") or "").strip()
                if not seed or len(seed) > 200:
                    return self._send_json(
                        {"error": "seed is required (max 200 characters)"}, 400)
                seed_type = str(payload.get("seed_type") or "username")
                if seed_type not in ("username", "domain", "email", "name", "url", "image", "hashtag", "phrase", "ip", "auto", "multi", "profile", "company", "wallet", "plate"):
                    seed_type = "username"
                # Auto-detect: an email-shaped seed typed as username is an email seed.
                _seed_context = str(payload.get("seed_context") or "")
                if seed_type in ("username", "auto") and "@" in seed and "." in seed.rsplit("@", 1)[-1]:
                    seed_type = "email" if seed_type == "auto" else seed_type
                    if seed_type == "email":
                        pass
                if str(payload.get("seed_type") or "") in ("username",) and "@" in seed and "." in seed.rsplit("@", 1)[-1]:
                    seed_type = "email"
                # Keys in this request are used for this run only.
                # They are never stored, never written to disk, and
                # never echoed back in the response.
                keys = payload.get("keys") or {}
                if not isinstance(keys, dict):
                    keys = {}
                keys = {str(k): str(v) for k, v in keys.items() if v}
                try:
                    from personatrace.core.engine import (
                        cluster_discovered_profiles,
                        run_investigation,
                    )

                    _v7_section = None
                    _v8_section = None
                    _v9_section = None
                    if seed_type in ("profile", "company", "wallet", "plate") or payload.get("direct"):
                        from personatrace.features.v8 import investigate_v8
                        inv, _v7_section, _v8_section = investigate_v8(
                            seed, seed_type, keys=keys, context=_seed_context,
                            parallel=4, direct=bool(payload.get("direct")))
                    elif seed_type in ("username", "domain", "name"):
                        # v9 path: timed parallel runs, result cache,
                        # and the no-key name search (shared chain +
                        # free-API candidates).
                        from personatrace.features.v9 import investigate_v9
                        inv, _v7_section, _v8_section, _v9_section = investigate_v9(
                            seed, seed_type, keys=keys, context=_seed_context,
                            parallel=4, use_cache=bool(payload.get("use_cache", True)),
                            live_extras=False)
                    elif seed_type in ("email", "url", "image", "hashtag", "phrase", "ip", "auto", "multi"):
                        from personatrace.features.v7 import investigate_seed, investigate_multi
                        if seed_type == "multi":
                            inv, _v7_section = investigate_multi(seed, keys=keys, context=_seed_context)
                        else:
                            inv, _v7_section = investigate_seed(seed, seed_type, keys=keys, context=_seed_context)
                    else:
                        inv = run_investigation(seed, keys=keys, seed_type=seed_type)
                    inv = cluster_discovered_profiles(inv)
                    data = _live_investigation_to_json(inv)
                    if getattr(inv, "analysis", None) is not None:
                        data["analysis"] = inv.analysis
                    # v7 dossier (wraps v6): live results only, never demo.
                    # Public-web collectors are cache-reused for username /
                    # domain; dorks run in the CLI dossier to keep GUI fast.
                    try:
                        from personatrace.features.v7 import build_v7_dossier
                        from dataclasses import asdict as _asdict
                        _payload = _asdict(inv)
                        if getattr(inv, "analysis", None) is not None:
                            _payload["analysis"] = inv.analysis
                        if _v9_section is not None:
                            from personatrace.features.v9 import build_v9_dossier
                            data["dossier"] = build_v9_dossier(_payload, seed, seed_type=seed_type, keys=keys, v7_section=_v7_section, v8_section=_v8_section, v9_section=_v9_section, include_dorks=False)
                        elif _v8_section is not None:
                            from personatrace.features.v8 import build_v8_dossier
                            data["dossier"] = build_v8_dossier(_payload, seed, seed_type=seed_type, keys=keys, v7_section=_v7_section, v8_section=_v8_section, include_dorks=False)
                        else:
                            data["dossier"] = build_v7_dossier(_payload, seed, seed_type=seed_type, keys=keys, v7_section=_v7_section, include_dorks=False)
                        if not data["profiles"]:
                            data["no_profiles_found_note"] = data["dossier"].get("no_profiles_found_note", "")
                    except Exception as _dexc:
                        data["dossier_error"] = str(_dexc)
                    # v9: optional real browser screenshots as proof.
                    if payload.get("screenshots"):
                        try:
                            import tempfile as _tf
                            from personatrace.features.v9 import capture_screenshots
                            _urls = []
                            for _p in data.get("profiles", []) or []:
                                for _ev in (_p.get("evidence") or []):
                                    _u = _ev.get("source_url") if isinstance(_ev, dict) else ""
                                    if _u and _u not in _urls:
                                        _urls.append(_u)
                                    break
                            _shot_dir = os.path.join(_tf.gettempdir(), "personatrace_proof_shots")
                            _shots = capture_screenshots(_urls[:3], _shot_dir, cap=3)
                            data["screenshots"] = {k: _shots.get(k) for k in ("status", "proof_type", "count", "note")}
                            data["screenshots"]["files"] = [
                                {"file": r.get("file"), "bytes": r.get("bytes"), "sha256": r.get("sha256"), "url": r.get("url")}
                                for r in _shots.get("screenshots", []) if r.get("sha256")]
                        except Exception as _shexc:
                            data["screenshots"] = {"status": "degraded", "note": str(_shexc)[:140]}
                except Exception as exc:
                    return self._send_json(
                        {"error": f"live search failed: {exc}"}, 500)
                sources = []
                for entry in data.get("audit", []) or []:
                    if isinstance(entry, dict) and entry.get("action") == "adapter_search":
                        sources.append(entry.get("detail", {}))
                state.set_last_search(data)
                return self._send_json({
                    "investigation": data,
                    "sources": sources,
                    "cost_before_run": _cost_rows(keys),
                    "mode": "demo" if os.environ.get("PERSONATRACE_DEMO") == "1" else "live",
                })
            if parsed.path == "/api/compare-cases":
                seed_a = str(payload.get("a") or payload.get("seed_a") or "").strip()
                seed_b = str(payload.get("b") or payload.get("seed_b") or "").strip()
                if not seed_a or not seed_b:
                    return self._send_json({"error": "two seeds are required"}, 400)
                keys = payload.get("keys") or {}
                if not isinstance(keys, dict):
                    keys = {}
                keys = {str(k): str(v) for k, v in keys.items() if v}
                try:
                    from personatrace.core.engine import cluster_discovered_profiles, run_investigation
                    from personatrace.features.compare_cases import compare_cases

                    first = cluster_discovered_profiles(run_investigation(seed_a, keys=keys))
                    second = cluster_discovered_profiles(run_investigation(seed_b, keys=keys))
                    return self._send_json(compare_cases(first, second))
                except Exception as exc:
                    return self._send_json({"error": f"case comparison failed: {exc}"}, 500)
            if parsed.path == "/api/compare":
                a = payload.get("a") or {}
                b = payload.get("b") or {}
                if not isinstance(a, dict) or not isinstance(b, dict):
                    return self._send_json({"error": "a and b profiles are required"}, 400)
                fields = ("platform", "username", "display_name", "bio",
                          "follower_count", "following_count", "created_at",
                          "status", "confidence")
                return self._send_json({
                    "fields": list(fields),
                    "a": {f: a.get(f, "") for f in fields},
                    "b": {f: b.get(f, "") for f in fields},
                    "a_evidence": a.get("evidence") or [],
                    "b_evidence": b.get("evidence") or [],
                })
            if parsed.path == "/api/keys/verify":
                # v8 key-verification harness. The GUI never stores key
                # VALUES (names only), so with no values available this
                # honestly reports every provider not_checked. The CLI
                # --verify-keys flag runs the same harness with the
                # real env keys.
                from personatrace.features.v8 import verify_all_keys
                _supplied = payload.get("keys") or {}
                if not isinstance(_supplied, dict):
                    _supplied = {}
                return self._send_json({"verification": verify_all_keys({str(k): str(v) for k, v in _supplied.items() if v}),
                                        "note": "Statuses only; key values are never returned."})
            if parsed.path == "/api/cases/team":
                from personatrace.features.v8 import set_case_team
                _seed = str(payload.get("seed") or "")
                if not _seed:
                    return self._send_json({"error": "seed is required"}, 400)
                return self._send_json(set_case_team(".", _seed,
                                                     assigned_to=payload.get("assigned_to"),
                                                     lead_status=payload.get("lead_status")))
            if parsed.path == "/api/keys/check":
                from personatrace.features.v5 import check_keys
                return self._send_json({"keys": check_keys(state.get_keys() if hasattr(state, "get_keys") else {}), "note": "Names and unlocks only; values are never returned."})
            if parsed.path == "/api/cases":
                from personatrace.features.v5 import search_cases
                return self._send_json({"cases": search_cases(".", query=payload.get("query", ""), tag=payload.get("tag", ""))})
            if parsed.path == "/api/webhook":
                # Push receiver: a third-party push service / aggregator posts new activity here.
                # No platform pushes directly for arbitrary profiles, so this is the legitimate push route.
                try:
                    import json as _wj, os as _wo
                    _log = _wo.path.join(_wo.getcwd(), "webhook_events.jsonl")
                    with open(_log, "a") as _f:
                        _f.write(_wj.dumps({"received": payload, "note": "Webhook event recorded; run a live check to verify it against the source before merging."}) + "\n")
                except Exception:
                    pass
                return self._send_json({"message": "Webhook event recorded. It is not merged until a live check verifies it against the source.", "payload": payload})
            if parsed.path == "/api/review":
                idx = payload.get("index")
                action = payload.get("action")
                if action not in ("merge", "reject", "keep"):
                    return self._send_json({"error": "action must be merge, reject or keep"}, 400)
                last = state.get_last_search() or {}
                matches = last.get("possible_matches") or []
                try:
                    entry = matches[int(idx)] if idx is not None else None
                except Exception:
                    entry = None
                if entry is None:
                    return self._send_json({"error": "possible match not found"}, 404)
                entry["status"] = {"merge": "accepted", "reject": "rejected", "keep": "kept_separate"}[action]
                try:
                    import datetime as _dt
                    open("audit.log", "a").write(f"{_dt.datetime.now(_dt.timezone.utc).isoformat()} review {action} index={idx}\n")
                except Exception:
                    pass
                # Persist rejected matches so later runs do not re-suggest them.
                if action == "reject":
                    try:
                        import json as _json2, os as _os2
                        prof = entry.get("profile") or {}
                        rej = f"{prof.get('platform')}:{prof.get('username')}" if isinstance(prof, dict) and prof.get("platform") else str(prof)
                        path = _os2.path.join(_os2.getcwd(), "rejected_matches.json")
                        existing = _json2.loads(open(path).read()) if _os2.path.exists(path) else []
                        if rej not in existing:
                            existing.append(rej)
                            open(path, "w").write(_json2.dumps(existing, indent=2))
                    except Exception:
                        pass
                return self._send_json({"message": f"Possible match {action}ed and audited. Merge/reject/keep is a human decision, logged in the case.", "entry": entry})
            if parsed.path == "/api/signoff":
                last = state.get_last_search() or {}
                analysis = last.get("analysis") or {}
                analysis["report_signoff"] = {"signed_off": True, "signed_by": payload.get("signed_by") or "analyst", "signed_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(), "note": "Human sign-off recorded. The draft was reviewed by a human before this sign-off."}
                last["analysis"] = analysis
                state.set_last_search(last)
                return self._send_json({"message": "Report signed off by a human reviewer.", "report_signoff": analysis["report_signoff"]})
            if parsed.path == "/api/users":
                # Local user accounts: username + SHA-256 hashed password
                # stored in .personatrace_users.json (local only). This is
                # NOT a network authentication system and must not be
                # exposed on a network without a real auth layer.
                import hashlib as _hl, json as _json3, os as _os3, secrets as _sec
                _path = _os3.path.join(_os3.getcwd(), ".personatrace_users.json")
                _users = _json3.loads(open(_path).read()) if _os3.path.exists(_path) else {}
                if payload.get("action") == "register":
                    _name = str(payload.get("username") or "")
                    _pw = str(payload.get("password") or "")
                    _role = str(payload.get("role") or "analyst")
                    if not _name or not _pw or _role not in ("viewer", "analyst", "admin"):
                        return self._send_json({"error": "username, password and a valid role are required"}, 400)
                    _salt = _sec.token_hex(16); _users[_name] = {"password_hash": _hl.pbkdf2_hmac("sha256", _pw.encode(), bytes.fromhex(_salt), 200000).hex(), "salt": _salt, "role": _role}
                    open(_path, "w").write(_json3.dumps(_users, indent=2))
                    return self._send_json({"message": f"User {_name} registered locally with role {_role}. Passwords are stored hashed, never in plain text."})
                if payload.get("action") == "login":
                    _name = str(payload.get("username") or "")
                    _pw = str(payload.get("password") or "")
                    _rec = _users.get(_name)
                    if _rec and _rec.get("password_hash") == _hl.pbkdf2_hmac("sha256", _pw.encode(), bytes.fromhex(_rec.get("salt", "")), 200000).hex() if _rec.get("salt") else _rec.get("password_hash") == _hl.sha256(_pw.encode()).hexdigest():
                        _tok = _sec.token_hex(32); _rec["session_token"] = _tok; _rec["session_expires"] = __import__("time").time() + 86400; open(_path, "w").write(_json3.dumps(_users, indent=2)); return self._send_json({"message": "Login ok. Use this session token as Authorization: Bearer <token> for protected endpoints. Token expires in 24 hours.", "username": _name, "role": _rec.get("role"), "session_token": _tok})
                    return self._send_json({"error": "Invalid username or password"}, 401)
                return self._send_json({"users": sorted(_users.keys()), "note": "Usernames and roles only, never password hashes."})
            if parsed.path != "/api/settings/keys":
                return self._send_json({"error": "not found"}, 404)
            name = payload.get("name")
            key = payload.get("key")
            if not name or not key:
                return self._send_json(
                    {"error": "name and key are required"}, 400)
            # Store the NAME only; the value is discarded immediately
            # and never appears in any response.
            state.add_key_name(str(name))
            return self._send_json({
                "name": str(name),
                "status": "stored",
                "stored": "name_only",
                "message": "Key name recorded. The key value is never "
                           "stored or echoed back.",
            })

    return Handler


def run_gui(db_path=None, port=8787):
    """Start the dashboard server on a daemon thread; return it."""
    state = _State(db_path)
    server = ThreadingHTTPServer(("127.0.0.1", port),
                                 make_handler(state))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description="PersonaTrace GUI")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--db", default=None)
    args = parser.parse_args(argv)
    state = _State(args.db)
    server = ThreadingHTTPServer(("127.0.0.1", args.port),
                                 make_handler(state))
    print("PersonaTrace GUI on http://127.0.0.1:{}/".format(args.port))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
