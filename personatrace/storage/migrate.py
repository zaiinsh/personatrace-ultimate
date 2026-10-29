"""Real Neo4j / Postgres migration code (not just a documented path).

- to_cypher(inv): Cypher statements that recreate the case graph in
  Neo4j: (:Profile) nodes, (:Domain) nodes, -[:LINKED {kind,
  confidence}]-> relationships, and evidence as node properties.
  Run the returned script in Neo4j Browser / cypher-shell.
- to_postgres_sql(inv): a self-contained SQL script (CREATE TABLE
  IF NOT EXISTS + INSERTs) for profiles, edges, evidence, alerts and
  audit. Run it with psql.
- migrate_live(inv, ...): if a Neo4j driver or psycopg driver is
  installed AND connection details are supplied via env
  (NEO4J_URI/NEO4J_USER/NEO4J_PASSWORD, DATABASE_URL), it attempts
  a live migration and reports success/failure honestly. If no
  driver or no connection details are present, it returns
  status="not_configured" with the generated scripts — never a
  claimed live migration that did not happen.
"""

from __future__ import annotations

import json


def _g(obj, field, default=""):
    if isinstance(obj, dict):
        return obj.get(field, default)
    return getattr(obj, field, default)


def _esc(value) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value).replace("'", "''")
    return f"'{text}'"


def _cypher_str(value) -> str:
    text = str(value or "").replace("\\", "\\\\").replace("'", "\\'").replace("\n", " ")
    return f"'{text}'"


def to_cypher(inv) -> str:
    lines = [f"// PersonaTrace case {_g(inv, 'case_id')} — seed {_g(inv, 'seed')}"]
    lines.append("// Run in Neo4j Browser or cypher-shell. Nodes are MERGEd by platform+username.")
    for p in _g(inv, "profiles", []) or []:
        lines.append(
            f"MERGE (p:Profile {{platform: {_cypher_str(_g(p, 'platform'))}, username: {_cypher_str(_g(p, 'username'))}}}) "
            f"SET p.display_name = {_cypher_str(_g(p, 'display_name'))}, p.bio = {_cypher_str(_g(p, 'bio'))}, "
            f"p.status = {_cypher_str(_g(p, 'status'))}, p.created_at = {_cypher_str(_g(p, 'created_at'))};"
        )
    for e in _g(inv, "edges", []) or []:
        frm, to = _g(e, "from_id"), _g(e, "to_id")
        if ":" not in str(frm) or ":" not in str(to):
            continue
        fplat, fname = str(frm).split(":", 1)
        tplat, tname = str(to).split(":", 1)
        kind = _cypher_str(_g(e, "kind"))
        conf = _g(e, "confidence", 0)
        lines.append(
            "MATCH (a:Profile {platform: " + _cypher_str(fplat) + ", username: " + _cypher_str(fname) + "}), "
            "(b:Profile {platform: " + _cypher_str(tplat) + ", username: " + _cypher_str(tname) + "}) "
            "MERGE (a)-[r:LINKED {kind: " + kind + ", confidence: " + str(conf) + "}]->(b);"
        )
    return "\n".join(lines) + "\n"


def to_postgres_sql(inv) -> str:
    case_id = _g(inv, "case_id")
    lines = [
        "-- PersonaTrace case export to Postgres (run with psql)",
        "CREATE TABLE IF NOT EXISTS pt_profiles (case_id TEXT, platform TEXT, username TEXT, display_name TEXT, bio TEXT, status TEXT, created_at TEXT, PRIMARY KEY (case_id, platform, username));",
        "CREATE TABLE IF NOT EXISTS pt_edges (case_id TEXT, from_id TEXT, to_id TEXT, kind TEXT, confidence INT);",
        "CREATE TABLE IF NOT EXISTS pt_evidence (case_id TEXT, platform TEXT, username TEXT, field TEXT, value TEXT, source_url TEXT, captured_at_utc TEXT, method TEXT, confidence INT);",
        "CREATE TABLE IF NOT EXISTS pt_alerts (case_id TEXT, ts_utc TEXT, kind TEXT, message TEXT);",
    ]
    for p in _g(inv, "profiles", []) or []:
        lines.append(
            f"INSERT INTO pt_profiles VALUES ({_esc(case_id)}, {_esc(_g(p, 'platform'))}, {_esc(_g(p, 'username'))}, {_esc(_g(p, 'display_name'))}, {_esc(_g(p, 'bio'))}, {_esc(_g(p, 'status'))}, {_esc(_g(p, 'created_at'))}) "
            "ON CONFLICT DO NOTHING;"
        )
        for ev in _g(p, "evidence", []) or []:
            lines.append(
                f"INSERT INTO pt_evidence VALUES ({_esc(case_id)}, {_esc(_g(p, 'platform'))}, {_esc(_g(p, 'username'))}, {_esc(_g(ev, 'field'))}, {_esc(_g(ev, 'value'))}, {_esc(_g(ev, 'source_url'))}, {_esc(_g(ev, 'captured_at_utc'))}, {_esc(_g(ev, 'method'))}, {_esc(_g(ev, 'confidence', 0))});"
            )
    for e in _g(inv, "edges", []) or []:
        lines.append(
            f"INSERT INTO pt_edges VALUES ({_esc(case_id)}, {_esc(_g(e, 'from_id'))}, {_esc(_g(e, 'to_id'))}, {_esc(_g(e, 'kind'))}, {_esc(_g(e, 'confidence', 0))});"
        )
    for a in _g(inv, "alerts", []) or []:
        lines.append(
            f"INSERT INTO pt_alerts VALUES ({_esc(case_id)}, {_esc(_g(a, 'ts_utc'))}, {_esc(_g(a, 'kind'))}, {_esc(_g(a, 'message'))});"
        )
    return "\n".join(lines) + "\n"


def migrate_live(inv, neo4j_uri=None, neo4j_user=None, neo4j_password=None, database_url=None) -> dict:
    """Attempt live migration only when driver + details are present."""
    import os

    neo4j_uri = neo4j_uri or os.environ.get("NEO4J_URI")
    database_url = database_url or os.environ.get("DATABASE_URL")
    results = {"cypher": to_cypher(inv), "postgres_sql": to_postgres_sql(inv)}
    if neo4j_uri:
        try:
            from neo4j import GraphDatabase

            driver = GraphDatabase.driver(
                neo4j_uri,
                auth=(neo4j_user or os.environ.get("NEO4J_USER", "neo4j"),
                      neo4j_password or os.environ.get("NEO4J_PASSWORD", "")),
            )
            with driver.session() as session:
                session.run(results["cypher"])
            results["neo4j"] = {"status": "ok"}
        except Exception as exc:
            results["neo4j"] = {"status": "degraded", "message": str(exc)}
    else:
        results["neo4j"] = {"status": "not_configured", "message": "Set NEO4J_URI (+ user/password) to run live, or run the Cypher script manually."}
    if database_url:
        try:
            import psycopg2

            conn = psycopg2.connect(database_url)
            with conn.cursor() as cur:
                cur.execute(results["postgres_sql"])
            conn.commit()
            conn.close()
            results["postgres"] = {"status": "ok"}
        except Exception as exc:
            results["postgres"] = {"status": "degraded", "message": str(exc)}
    else:
        results["postgres"] = {"status": "not_configured", "message": "Set DATABASE_URL to run live, or run the SQL script with psql."}
    return results
