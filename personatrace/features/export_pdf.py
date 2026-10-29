"""Single-case PDF export.

Uses ReportLab when installed, otherwise a small stdlib PDF writer
(plain text lines, Helvetica, one page per ~45 lines). Either way the
output is a real, openable PDF starting with %PDF, containing the
case id, seed, profiles, evidence with source URLs, analysis summary,
risk signals, alerts and audit — never a placeholder document.
"""

from __future__ import annotations

import html as _html
from pathlib import Path


def _lines(inv) -> list:
    def _g(obj, field, default=""):
        if isinstance(obj, dict):
            return obj.get(field, default)
        return getattr(obj, field, default)

    lines = []
    lines.append("PersonaTrace — single-case export")
    lines.append(f"Case: {_g(inv, 'case_id')}  Seed: {_g(inv, 'seed')}  Type: {_g(inv, 'seed_type', 'username')}")
    lines.append("Scope: public data only. No private accounts, no live location, no face identification.")
    lines.append("")
    lines.append("Profiles:")
    for p in _g(inv, "profiles", []) or []:
        lines.append(f"- {_g(p, 'platform')} / {_g(p, 'username')} — {_g(p, 'display_name')} — status {_g(p, 'status')} — followers {_g(p, 'follower_count')}")
        if _g(p, "bio"):
            lines.append(f"  Bio: {_g(p, 'bio')}")
    lines.append("")
    lines.append("Evidence / provenance:")
    for p in _g(inv, "profiles", []) or []:
        for ev in _g(p, "evidence", []) or []:
            lines.append(f"- {_g(p, 'platform')} / {_g(p, 'username')} — {_g(ev, 'field')}: {_g(ev, 'value')} — {_g(ev, 'source_url')} — {_g(ev, 'captured_at_utc')} — {_g(ev, 'method')} — confidence {_g(ev, 'confidence')}")
    lines.append("")
    lines.append("Edges:")
    for e in _g(inv, "edges", []) or []:
        lines.append(f"- {_g(e, 'from_id')} -> {_g(e, 'to_id')} ({_g(e, 'kind')}, confidence {_g(e, 'confidence')})")
    lines.append("")
    analysis = getattr(inv, "analysis", None)
    if isinstance(analysis, dict):
        lines.append("Analysis:")
        lines.append(f"- Behaviour: {analysis.get('behaviour_summary', {})}")
        lines.append(f"- Bio domains: {analysis.get('bio_domains', {})}")
        lines.append(f"- Avatar reuse: {analysis.get('avatar_reuse', [])}")
        lines.append(f"- Risk signals: {analysis.get('risk_signals', [])}")
        lines.append(f"- Next steps (planner): {analysis.get('next_steps', [])}")
        lines.append("")
    lines.append("Analyst notes and checklist (investigator's own notes, not collected evidence):")
    for n in _g(inv, "notes", []) or []:
        lines.append(f"- Note: {n}")
    for c in _g(inv, "checklist", []) or []:
        lines.append(f"- Checklist: {c}")
    lines.append("")
    lines.append("Possible matches (review queue, never auto-merged):")
    for pm in _g(inv, "possible_matches", []) or []:
        lines.append(f"- {pm}")
    lines.append("")
    lines.append("Alerts:")
    for a in _g(inv, "alerts", []) or []:
        lines.append(f"- {a}")
    lines.append("")
    lines.append("Audit log:")
    for a in _g(inv, "audit", []) or []:
        lines.append(f"- {a}")
    return [str(line) for line in lines]


def _escape_pdf(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _write_minimal_pdf(path: Path, lines: list) -> str:
    # Wrap long lines at ~100 chars for readability.
    wrapped = []
    for line in lines:
        line = line.encode("ascii", "replace").decode("ascii")
        while len(line) > 100:
            wrapped.append(line[:100])
            line = line[100:]
        wrapped.append(line)
    per_page = 45
    pages = [wrapped[i:i + per_page] for i in range(0, len(wrapped), per_page)] or [[]]
    objects = []
    # 1: catalog, 2: pages, then per page: page object + content object.
    page_ids = []
    content_ids = []
    for i in range(len(pages)):
        page_ids.append(3 + i * 2)
        content_ids.append(4 + i * 2)
    out = bytearray(b"%PDF-1.4\n")
    offsets = {}

    def _obj(num: int, body: bytes):
        offsets[num] = len(out)
        out.extend(f"{num} 0 obj\n".encode())
        out.extend(body)
        out.extend(b"\nendobj\n")

    kids = " ".join(f"{pid} 0 R" for pid in page_ids)
    _obj(1, f"<< /Type /Catalog /Pages 2 0 R >>".encode())
    _obj(2, f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode())
    for i, page_lines in enumerate(pages):
        _obj(page_ids[i], f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> >> >> /Contents {content_ids[i]} 0 R >>".encode())
        stream_lines = ["BT /F1 9 Tf 36 756 Td"]
        for j, line in enumerate(page_lines):
            if j:
                stream_lines.append("0 -14 Td")
            stream_lines.append(f"({_escape_pdf(line)}) Tj")
        stream_lines.append("ET")
        stream = "\n".join(stream_lines).encode()
        _obj(content_ids[i], f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream")
    xref_pos = len(out)
    max_id = max(page_ids + content_ids + [1, 2])
    out.extend(f"xref\n0 {max_id + 1}\n".encode())
    out.extend(b"0000000000 65535 f \n")
    for num in range(1, max_id + 1):
        out.extend(f"{offsets[num]:010d} 00000 n \n".encode())
    out.extend(f"trailer\n<< /Size {max_id + 1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode())
    path.write_bytes(bytes(out))
    return str(path)


def export_pdf(inv, out_dir) -> str:
    """Write case.pdf into out_dir; returns the file path."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / "case.pdf"
    lines = _lines(inv)
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        from reportlab.pdfgen import canvas

        c = canvas.Canvas(str(path), pagesize=A4)
        c.setFont("Helvetica", 9)
        y = A4[1] - 20 * mm
        for line in lines:
            text = line.encode("ascii", "replace").decode("ascii")
            while len(text) > 110:
                c.drawString(15 * mm, y, text[:110])
                text = text[110:]
                y -= 12
                if y < 20 * mm:
                    c.showPage()
                    c.setFont("Helvetica", 9)
                    y = A4[1] - 20 * mm
            c.drawString(15 * mm, y, text)
            y -= 12
            if y < 20 * mm:
                c.showPage()
                c.setFont("Helvetica", 9)
                y = A4[1] - 20 * mm
        c.save()
        return str(path)
    except Exception:
        return _write_minimal_pdf(path, lines)
