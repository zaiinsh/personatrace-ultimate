"""PersonaTrace storage — SQLite, local-first (CONTRACT.md, Storage).

File: ``<case_dir>/personatrace.db``, created by :func:`init_db`.

Tables (exactly the CONTRACT v1 set, no others):
    cases(id, seed, seed_type, created_at, purpose)
    profiles(id, case_id, platform, username, display_name, bio,
             avatar_hash, status, confidence)
    edges(id, case_id, from_id, to_id, kind, confidence, band)
    evidence(id, case_id, profile_id, source_url, captured_at_utc, method,
             platform, field, value, confidence)
    timeline(id, case_id, ts_utc, kind, description)
    audit(id, case_id, ts_utc, actor, action, detail)
    alerts(id, case_id, ts_utc, kind, message, acknowledged INTEGER)

Graph storage: nodes are the ``profiles`` rows and edges are the ``edges``
rows, all in SQLite. No graph server is required.

Neo4j / Postgres team path (documentation only, per task — no server
code, no driver, no connection is attempted here): if a future build
needs a shared graph store, the migration is a straight export of these
same rows — profiles become nodes keyed by ``(case_id, platform,
username)``, edges become relationships keyed by ``(from_id, to_id,
kind)`` with ``confidence``/``band`` as properties, and evidence,
timeline, audit and alerts become attached nodes/rows keyed by
``case_id``. Nothing in this module depends on that path, and the
SQLite store remains the local-first source of truth.

Persistence limitations (honest, by schema design):
- ``Investigation.possible_matches`` has no CONTRACT table, so it is
  NOT persisted; :func:`load_investigation` returns ``[]`` for it.
- ``Edge.evidence`` has no CONTRACT column/table, so it is NOT
  persisted; loaded edges carry ``evidence=[]``. Edge core fields
  (from/to/kind/confidence/band) are fully persisted.
- Profile ``confidence`` is stored (max evidence confidence, else 0)
  but ``Profile`` has no confidence field, so it is not restored onto
  the object on load; profile evidence (which carries the real
  per-fact confidences) is fully restored.
- ``load_investigation(path)`` loads a single case: the ``case_id``
  argument is optional and, when omitted, the most recently created
  case in the file is loaded (single-case export workflow).

Audit/alert/timeline entries may be dicts (preferred, keys as in the
table columns) or plain strings; strings are normalised to a dict with
the string as the action/message/description.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone

try:
    # Canonical shapes live in adapters/base.py (same package tree).
    from personatrace.adapters.base import Edge, Evidence, Investigation, Profile, confidence_band
except ImportError:  # pragma: no cover - fallback for unusual import paths
    from dataclasses import dataclass, field as _field

    @dataclass
    class Evidence:  # type: ignore[no-redef]
        source_url: str
        captured_at_utc: str
        method: str
        platform: str
        field: str
        value: str
        confidence: int

    @dataclass
    class Profile:  # type: ignore[no-redef]
        platform: str
        username: str
        display_name: str = ""
        bio: str = ""
        avatar_hash: str = ""
        bio_links: list = _field(default_factory=list)
        follower_count: int | None = None
        following_count: int | None = None
        created_at: str = ""
        evidence: list = _field(default_factory=list)
        status: str = "candidate"

    @dataclass
    class Edge:  # type: ignore[no-redef]
        from_id: str
        to_id: str
        kind: str
        confidence: int
        band: str
        evidence: list = _field(default_factory=list)

    @dataclass
    class Investigation:  # type: ignore[no-redef]
        case_id: str
        seed: str
        seed_type: str = "username"
        profiles: list = _field(default_factory=list)
        edges: list = _field(default_factory=list)
        possible_matches: list = _field(default_factory=list)
        alerts: list = _field(default_factory=list)
        audit: list = _field(default_factory=list)
        timeline: list = _field(default_factory=list)
        purpose: str = ""

    def confidence_band(confidence: int) -> str:  # type: ignore[no-redef]
        return "High" if confidence >= 80 else ("Medium" if confidence >= 50 else "Low")


_SCHEMA = """
CREATE TABLE IF NOT EXISTS cases(
    id TEXT PRIMARY KEY, seed TEXT, seed_type TEXT,
    created_at TEXT, purpose TEXT);
CREATE TABLE IF NOT EXISTS profiles(
    id TEXT, case_id TEXT, platform TEXT, username TEXT,
    display_name TEXT, bio TEXT, avatar_hash TEXT, status TEXT,
    confidence INTEGER);
CREATE TABLE IF NOT EXISTS edges(
    id TEXT, case_id TEXT, from_id TEXT, to_id TEXT,
    kind TEXT, confidence INTEGER, band TEXT);
CREATE TABLE IF NOT EXISTS evidence(
    id INTEGER PRIMARY KEY AUTOINCREMENT, case_id TEXT, profile_id TEXT,
    source_url TEXT, captured_at_utc TEXT, method TEXT, platform TEXT,
    field TEXT, value TEXT, confidence INTEGER);
CREATE TABLE IF NOT EXISTS timeline(
    id INTEGER PRIMARY KEY AUTOINCREMENT, case_id TEXT,
    ts_utc TEXT, kind TEXT, description TEXT);
CREATE TABLE IF NOT EXISTS audit(
    id INTEGER PRIMARY KEY AUTOINCREMENT, case_id TEXT,
    ts_utc TEXT, actor TEXT, action TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS alerts(
    id INTEGER PRIMARY KEY AUTOINCREMENT, case_id TEXT,
    ts_utc TEXT, kind TEXT, message TEXT, acknowledged INTEGER);
CREATE TABLE IF NOT EXISTS possible_matches(
    id INTEGER PRIMARY KEY AUTOINCREMENT, case_id TEXT,
    profile_json TEXT, score INTEGER, reasons TEXT, status TEXT);
CREATE TABLE IF NOT EXISTS edge_evidence(
    id INTEGER PRIMARY KEY AUTOINCREMENT, case_id TEXT, edge_id TEXT,
    source_url TEXT, captured_at_utc TEXT, method TEXT, platform TEXT,
    field TEXT, value TEXT, confidence INTEGER);
"""


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect(path: str) -> sqlite3.Connection:
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(path: str) -> str:
    """Create the database file and all CONTRACT tables. Returns path."""
    conn = _connect(path)
    try:
        conn.executescript(_SCHEMA)
        conn.commit()
    finally:
        conn.close()
    return path


def _ensure_case(conn: sqlite3.Connection, case_id: str, seed: str = "",
                 seed_type: str = "username", purpose: str = "") -> None:
    conn.execute(
        "INSERT OR IGNORE INTO cases(id, seed, seed_type, created_at, purpose)"
        " VALUES(?, ?, ?, ?, ?)",
        (case_id, seed, seed_type, _utcnow(), purpose),
    )


def _profile_id(case_id: str, profile: Profile) -> str:
    return f"{case_id}|{profile.platform}|{profile.username}"


def _norm_audit(entry, now: str) -> dict:
    if isinstance(entry, dict):
        detail = entry.get("detail", "")
        if not isinstance(detail, str):
            detail = json.dumps(detail, sort_keys=True, default=str)
        return {
            "ts_utc": entry.get("ts_utc") or entry.get("ts") or now,
            "actor": entry.get("actor", ""),
            "action": entry.get("action", ""),
            "detail": detail,
        }
    return {"ts_utc": now, "actor": "", "action": str(entry), "detail": ""}


def _norm_alert(entry, now: str) -> dict:
    if isinstance(entry, dict):
        message = entry.get("message", "")
        if not isinstance(message, str):
            message = json.dumps(message, sort_keys=True, default=str)
        return {
            "ts_utc": entry.get("ts_utc") or entry.get("ts") or now,
            "kind": entry.get("kind", ""),
            "message": message,
            "acknowledged": 1 if entry.get("acknowledged") else 0,
        }
    return {"ts_utc": now, "kind": "", "message": str(entry), "acknowledged": 0}


def _norm_timeline(entry, now: str) -> dict:
    if isinstance(entry, dict):
        description = entry.get("description", "")
        if not isinstance(description, str):
            description = json.dumps(description, sort_keys=True, default=str)
        return {
            "ts_utc": entry.get("ts_utc") or entry.get("ts") or now,
            "kind": entry.get("kind", ""),
            "description": description,
        }
    return {"ts_utc": now, "kind": "", "description": str(entry)}


def save_investigation(path: str, inv: Investigation) -> str:
    """Persist one investigation, replacing any prior rows for its case
    (save is idempotent). Returns path."""
    init_db(path)
    conn = _connect(path)
    try:
        _ensure_case(conn, inv.case_id, inv.seed, inv.seed_type,
                     getattr(inv, "purpose", ""))
        case_id = inv.case_id
        for table in ("profiles", "edges", "evidence", "timeline", "audit", "alerts", "possible_matches", "edge_evidence"):
            conn.execute(f"DELETE FROM {table} WHERE case_id = ?", (case_id,))
        now = _utcnow()
        for profile in inv.profiles:
            pid = _profile_id(case_id, profile)
            confidences = [e.confidence for e in (profile.evidence or [])]
            conn.execute(
                "INSERT INTO profiles(id, case_id, platform, username,"
                " display_name, bio, avatar_hash, status, confidence)"
                " VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (pid, case_id, profile.platform, profile.username,
                 profile.display_name, profile.bio, profile.avatar_hash,
                 profile.status, max(confidences) if confidences else 0),
            )
            for ev in profile.evidence or []:
                conn.execute(
                    "INSERT INTO evidence(case_id, profile_id, source_url,"
                    " captured_at_utc, method, platform, field, value, confidence)"
                    " VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (case_id, pid, ev.source_url, ev.captured_at_utc, ev.method,
                     ev.platform, ev.field, ev.value, ev.confidence),
                )
        for index, edge in enumerate(inv.edges):
            band = edge.band or confidence_band(edge.confidence)
            edge_id = f"{case_id}|{edge.from_id}|{edge.to_id}|{edge.kind}|{index}"
            conn.execute(
                "INSERT INTO edges(id, case_id, from_id, to_id, kind, confidence, band)"
                " VALUES(?, ?, ?, ?, ?, ?, ?)",
                (edge_id,
                 case_id, edge.from_id, edge.to_id, edge.kind, edge.confidence, band),
            )
            for ev in edge.evidence or []:
                conn.execute(
                    "INSERT INTO edge_evidence(case_id, edge_id, source_url,"
                    " captured_at_utc, method, platform, field, value, confidence)"
                    " VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (case_id, edge_id, ev.source_url, ev.captured_at_utc, ev.method,
                     ev.platform, ev.field, ev.value, ev.confidence),
                )
        for pm in inv.possible_matches or []:
            prof = pm.get("profile") if isinstance(pm, dict) else None
            if prof is not None and not isinstance(prof, dict):
                try:
                    from dataclasses import asdict as _asdict
                    prof = _asdict(prof)
                except Exception:
                    prof = {"username": str(prof)}
            conn.execute(
                "INSERT INTO possible_matches(case_id, profile_json, score, reasons, status)"
                " VALUES(?, ?, ?, ?, ?)",
                (case_id, json.dumps(prof) if prof is not None else None,
                 pm.get("score", 0) if isinstance(pm, dict) else 0,
                 json.dumps(pm.get("reasons", [])) if isinstance(pm, dict) else "[]",
                 pm.get("status", "pending") if isinstance(pm, dict) else "pending"),
            )
        for entry in getattr(inv, "timeline", []) or []:
            row = _norm_timeline(entry, now)
            conn.execute(
                "INSERT INTO timeline(case_id, ts_utc, kind, description) VALUES(?, ?, ?, ?)",
                (case_id, row["ts_utc"], row["kind"], row["description"]),
            )
        for entry in inv.audit or []:
            row = _norm_audit(entry, now)
            conn.execute(
                "INSERT INTO audit(case_id, ts_utc, actor, action, detail) VALUES(?, ?, ?, ?, ?)",
                (case_id, row["ts_utc"], row["actor"], row["action"], row["detail"]),
            )
        for entry in inv.alerts or []:
            row = _norm_alert(entry, now)
            conn.execute(
                "INSERT INTO alerts(case_id, ts_utc, kind, message, acknowledged)"
                " VALUES(?, ?, ?, ?, ?)",
                (case_id, row["ts_utc"], row["kind"], row["message"], row["acknowledged"]),
            )
        conn.commit()
    finally:
        conn.close()
    return path


def load_investigation(path: str, case_id: str | None = None) -> Investigation:
    """Load one investigation. With no case_id, the most recently created
    case is loaded. Raises FileNotFoundError / ValueError if the file or
    case does not exist."""
    if not os.path.exists(path):
        raise FileNotFoundError(f"no database file: {path}")
    init_db(path)
    conn = _connect(path)
    try:
        if case_id is None:
            row = conn.execute(
                "SELECT * FROM cases ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            if row is None:
                raise ValueError("database contains no cases")
            case_id = row["id"]
        case = conn.execute("SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone()
        if case is None:
            raise ValueError(f"unknown case_id: {case_id}")

        profiles = []
        profile_rows = conn.execute(
            "SELECT * FROM profiles WHERE case_id = ? ORDER BY rowid", (case_id,)
        ).fetchall()
        for prow in profile_rows:
            ev_rows = conn.execute(
                "SELECT * FROM evidence WHERE case_id = ? AND profile_id = ? ORDER BY id",
                (case_id, prow["id"]),
            ).fetchall()
            evidence = [
                Evidence(
                    source_url=r["source_url"],
                    captured_at_utc=r["captured_at_utc"],
                    method=r["method"],
                    platform=r["platform"],
                    field=r["field"],
                    value=r["value"],
                    confidence=r["confidence"],
                )
                for r in ev_rows
            ]
            profiles.append(
                Profile(
                    platform=prow["platform"],
                    username=prow["username"],
                    display_name=prow["display_name"] or "",
                    bio=prow["bio"] or "",
                    avatar_hash=prow["avatar_hash"] or "",
                    status=prow["status"] or "candidate",
                    evidence=evidence,
                    confidence=prow["confidence"] or 0,
                )
            )
        edges = []
        for r in conn.execute(
            "SELECT * FROM edges WHERE case_id = ? ORDER BY rowid", (case_id,)
        ).fetchall():
            ev_rows = conn.execute(
                "SELECT * FROM edge_evidence WHERE case_id = ? AND edge_id = ? ORDER BY id",
                (case_id, r["id"]),
            ).fetchall()
            edges.append(Edge(
                from_id=r["from_id"],
                to_id=r["to_id"],
                kind=r["kind"],
                confidence=r["confidence"],
                band=r["band"],
                evidence=[Evidence(
                    source_url=e["source_url"], captured_at_utc=e["captured_at_utc"],
                    method=e["method"], platform=e["platform"], field=e["field"],
                    value=e["value"], confidence=e["confidence"]) for e in ev_rows],
            ))
        possible_matches = []
        for r in conn.execute(
            "SELECT * FROM possible_matches WHERE case_id = ? ORDER BY id", (case_id,)
        ).fetchall():
            try:
                prof = json.loads(r["profile_json"]) if r["profile_json"] else None
            except Exception:
                prof = None
            try:
                reasons = json.loads(r["reasons"]) if r["reasons"] else []
            except Exception:
                reasons = []
            possible_matches.append({"profile": prof, "score": r["score"],
                                     "reasons": reasons, "status": r["status"]})
        timeline = [
            {"ts_utc": r["ts_utc"], "kind": r["kind"], "description": r["description"]}
            for r in conn.execute(
                "SELECT * FROM timeline WHERE case_id = ? ORDER BY id", (case_id,)
            ).fetchall()
        ]
        audit = [
            {"ts_utc": r["ts_utc"], "actor": r["actor"], "action": r["action"],
             "detail": r["detail"]}
            for r in conn.execute(
                "SELECT * FROM audit WHERE case_id = ? ORDER BY id", (case_id,)
            ).fetchall()
        ]
        alerts = [
            {"ts_utc": r["ts_utc"], "kind": r["kind"], "message": r["message"],
             "acknowledged": bool(r["acknowledged"])}
            for r in conn.execute(
                "SELECT * FROM alerts WHERE case_id = ? ORDER BY id", (case_id,)
            ).fetchall()
        ]
        return Investigation(
            case_id=case["id"],
            seed=case["seed"],
            seed_type=case["seed_type"] or "username",
            profiles=profiles,
            edges=edges,
            possible_matches=possible_matches,
            alerts=alerts,
            audit=audit,
            timeline=timeline,
            purpose=case["purpose"] or "",
        )
    finally:
        conn.close()


def log_audit(path: str, case_id: str, actor: str, action: str, detail: str) -> None:
    """Append one audit row (creates the DB/case row if needed)."""
    init_db(path)
    conn = _connect(path)
    try:
        _ensure_case(conn, case_id)
        conn.execute(
            "INSERT INTO audit(case_id, ts_utc, actor, action, detail) VALUES(?, ?, ?, ?, ?)",
            (case_id, _utcnow(), actor, action, detail),
        )
        conn.commit()
    finally:
        conn.close()


def add_alert(path: str, case_id: str, kind: str, message: str) -> None:
    """Append one unacknowledged alert row (creates DB/case row if needed)."""
    init_db(path)
    conn = _connect(path)
    try:
        _ensure_case(conn, case_id)
        conn.execute(
            "INSERT INTO alerts(case_id, ts_utc, kind, message, acknowledged)"
            " VALUES(?, ?, ?, ?, 0)",
            (case_id, _utcnow(), kind, message),
        )
        conn.commit()
    finally:
        conn.close()
    return None
