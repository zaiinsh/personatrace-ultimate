"""Single-case export (HTML + JSON) with full provenance + audit.

Exports exactly ONE investigation. Every fact carries source_url,
captured_at_utc, method and confidence. No bulk export is possible
through this module: it accepts a single investigation object only.
"""

import html
import json
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path

__all__ = ["export_case"]


def _as_dict(obj):
    if is_dataclass(obj):
        return asdict(obj)
    if isinstance(obj, dict):
        return obj
    return {"value": str(obj)}


def _get(obj, field, default=None):
    if isinstance(obj, dict):
        return obj.get(field, default)
    return getattr(obj, field, default)


def _facts(inv) -> list:
    """Flatten every evidence fact of every profile, with provenance."""
    facts = []
    for profile in _get(inv, "profiles", []) or []:
        platform = _get(profile, "platform", "")
        username = _get(profile, "username", "")
        for ev in _get(profile, "evidence", []) or []:
            facts.append(
                {
                    "platform": platform,
                    "username": username,
                    "field": _get(ev, "field", ""),
                    "value": _get(ev, "value", ""),
                    "source_url": _get(ev, "source_url", ""),
                    "captured_at_utc": _get(ev, "captured_at_utc", ""),
                    "method": _get(ev, "method", ""),
                    "confidence": _get(ev, "confidence", ""),
                }
            )
    return facts


def export_case(inv, out_dir, fmt: str = "html") -> str:
    """Export one investigation to *out_dir*; returns the file path.

    fmt="html" -> case.html, fmt="json" -> case.json, fmt="pdf" -> case.pdf.
    Anything else raises ValueError.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    if fmt == "pdf":
        from .export_pdf import export_pdf

        return export_pdf(inv, out_dir)
    if fmt == "csv":
        import csv as _csv

        path = out / "case.csv"
        with path.open("w", newline="", encoding="utf-8") as fh:
            writer = _csv.writer(fh)
            writer.writerow(["platform", "username", "field", "value", "source_url", "captured_at_utc", "method", "confidence"])
            for fact in _facts(inv):
                writer.writerow([fact["platform"], fact["username"], fact["field"], fact["value"], fact["source_url"], fact["captured_at_utc"], fact["method"], fact["confidence"]])
        return str(path)
    if fmt not in ("html", "json"):
        raise ValueError(f"unsupported export format: {fmt!r}")
    facts = _facts(inv)
    case_id = _get(inv, "case_id", "case")
    exported_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    if fmt == "json":
        payload = {
            "case_id": case_id,
            "seed": _get(inv, "seed", ""),
            "seed_type": _get(inv, "seed_type", "username"),
            "exported_at_utc": exported_at,
            "single_case_only": True,
            "profiles": [_as_dict(p) for p in _get(inv, "profiles", []) or []],
            "edges": [_as_dict(e) for e in _get(inv, "edges", []) or []],
            "possible_matches": [_as_dict(p) for p in _get(inv, "possible_matches", []) or []],
            "alerts": [_as_dict(a) for a in _get(inv, "alerts", []) or []],
            "audit": [_as_dict(a) for a in _get(inv, "audit", []) or []],
            "timeline": [_as_dict(t) for t in _get(inv, "timeline", []) or []] if _get(inv, "timeline") is not None else [],
            "notes": _get(inv, "notes", []) or [],
            "checklist": _get(inv, "checklist", []) or [],
            "provenance": facts,
        }
        path = out / "case.json"
        path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        return str(path)

    rows = "".join(
        "<tr><td>{platform}</td><td>{username}</td><td>{field}</td>"
        "<td>{value}</td><td>{source_url}</td><td>{captured_at_utc}</td>"
        "<td>{method}</td><td>{confidence}</td></tr>\n".format(
            **{k: html.escape(str(v)) for k, v in fact.items()}
        )
        for fact in facts
    )
    audit_rows = "".join(
        "<li>{}</li>\n".format(html.escape(json.dumps(_as_dict(a), default=str)))
        for a in _get(inv, "audit", []) or []
    )
    _analysis = _get(inv, "analysis", {}) or {}
    if isinstance(_analysis, dict):
        _risk_rows = "".join(
            "<li>{}</li>\n".format(html.escape(json.dumps(r, default=str)))
            for r in _analysis.get("risk_signals", []) or []
        )
        _step_rows = "".join(
            "<li>{}</li>\n".format(html.escape(json.dumps(s, default=str)))
            for s in _analysis.get("next_steps", []) or []
        )
        _analysis_section = f"<h2>Risk signals (list only, never a verdict)</h2><ul>{_risk_rows}</ul><h2>Planner: next steps</h2><ul>{_step_rows}</ul>"
    else:
        _analysis_section = ""
    doc = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>PersonaTrace case export: {html.escape(str(case_id))}</title></head>
<body>
<h1>PersonaTrace case export (single case)</h1>
<p>Case: {html.escape(str(case_id))} | Seed: {html.escape(str(_get(inv, "seed", "")))} | Exported (UTC): {html.escape(exported_at)}</p>
<p>Scope note: public data only. No private accounts, no live location, no face identification.</p>
<h2>Provenance: every fact</h2>
<table border="1">
<tr><th>Platform</th><th>Username</th><th>Field</th><th>Value</th>
<th>Source URL</th><th>Captured (UTC)</th><th>Method</th><th>Confidence</th></tr>
{rows}</table>
{_analysis_section}
<h2>Audit log</h2>
<ul>
{audit_rows}</ul>
</body></html>
"""
    path = out / "case.html"
    path.write_text(doc, encoding="utf-8")
    return str(path)
