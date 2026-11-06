"""XLSX export of a finished run: the analyst's party & role register, relationships, evidence and a cover sheet."""
from __future__ import annotations

import io
import json
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

HEADER_FILL = PatternFill("solid", fgColor="1F2937")
HEADER_FONT = Font(bold=True, color="FFFFFF")


def _anchored(entity: dict) -> list[dict]:
    return [c for c in entity.get("citations", []) if c.get("end_char", 0) > c.get("start_char", 0)]


def _sheet(wb: Workbook, title: str, header: list[str], rows: list[list], widths: list[int]):
    ws = wb.create_sheet(title)
    ws.append(header)
    for c in ws[1]:
        c.fill, c.font = HEADER_FILL, HEADER_FONT
    for r in rows:
        ws.append(r)
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    for row in ws.iter_rows(min_row=2):
        for c in row:
            c.alignment = Alignment(wrap_text=True, vertical="top")
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    return ws


def build_workbook(run_dir) -> bytes:
    run_dir = Path(run_dir)
    data = json.loads((run_dir / "output.json").read_text(encoding="utf-8"))
    read = lambda n: json.loads((run_dir / n).read_text(encoding="utf-8")) if (run_dir / n).exists() else {}  # noqa: E731
    manifest, ops = read("manifest.json"), read("ops.json")
    entities, rels = data.get("entities", []), data.get("relationships", [])
    by_id = {e["entity_id"]: e for e in entities}
    rel_count: dict[str, int] = {}
    for r in rels:
        for k in ("source_entity_id", "target_entity_id"):
            rel_count[r[k]] = rel_count.get(r[k], 0) + 1

    wb = Workbook()
    cover = wb.active
    cover.title = "Cover"
    llm = ops.get("llm", {})
    for row in [
        ("Party & role register", ""),
        ("Run", run_dir.name),
        ("Source file", Path(str(manifest.get("source_file", ""))).name),
        ("Created", manifest.get("created_at", "")),
        ("Entities", len(entities)),
        ("Relationships", len(rels)),
        ("Entities with no located quote", sum(1 for e in entities if not _anchored(e))),
        ("LLM cost (USD)", round(llm.get("cost_usd", 0.0), 4) if llm else "n/a"),
        ("LLM calls", llm.get("calls", "n/a")),
        ("Alias pass", json.dumps(manifest.get("alias_pass", {}))),
        ("Relation pass", json.dumps(manifest.get("relation_pass", {}))),
        ("Status of content", "Machine-extracted. Every row must be reviewed against its quote before use."),
    ]:
        cover.append(row)
    cover["A1"].font = Font(bold=True, size=14)
    cover.column_dimensions["A"].width = 32
    cover.column_dimensions["B"].width = 90

    _sheet(wb, "Register",
           ["Name", "Type", "Aliases / former names", "Mentions located", "Relationships", "First quote", "Offset"],
           [[e["canonical_name"], e["entity_type"], "; ".join(e.get("aliases", [])), len(_anchored(e)),
             rel_count.get(e["entity_id"], 0), (_anchored(e)[0]["quote"][:300] if _anchored(e) else ""),
             (_anchored(e)[0]["start_char"] if _anchored(e) else "")]
            for e in sorted(entities, key=lambda e: (e["entity_type"], e["canonical_name"].casefold()))],
           [36, 12, 36, 10, 10, 70, 10])

    _sheet(wb, "Relationships", ["Source", "Relation", "Target", "Evidence quote", "Match", "Offset"],
           [[by_id.get(r["source_entity_id"], {}).get("canonical_name", r["source_entity_id"]), r["relationship_type"],
             by_id.get(r["target_entity_id"], {}).get("canonical_name", r["target_entity_id"]),
             (r.get("citation") or {}).get("quote", "")[:500], (r.get("citation") or {}).get("match", ""),
             (r.get("citation") or {}).get("start_char", "")] for r in rels],
           [32, 16, 32, 80, 14, 10])

    _sheet(wb, "Evidence", ["Entity", "Type", "Quote", "Start", "End", "Match"],
           [[e["canonical_name"], e["entity_type"], c.get("quote", "")[:500], c.get("start_char", ""),
             c.get("end_char", ""), c.get("match", "")] for e in entities for c in e.get("citations", [])],
           [36, 12, 80, 10, 10, 14])

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
