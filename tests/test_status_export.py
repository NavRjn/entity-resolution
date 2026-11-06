"""Run status (failed runs are visible) and the XLSX register export."""
import io
import json

from openpyxl import load_workbook

OUTPUT = {
    "entities": [
        {"entity_id": "C1", "canonical_name": "Aurora Holdings GmbH", "entity_type": "company", "aliases": ["Aurora"],
         "citations": [{"file_id": "f", "chunk_id": 0, "start_char": 0, "end_char": 20, "quote": "Aurora Holdings GmbH", "match": "verbatim"}]},
        {"entity_id": "P1", "canonical_name": "Bob Stone", "entity_type": "person", "aliases": [],
         "citations": [{"file_id": "f", "chunk_id": 0, "start_char": 0, "end_char": 0, "quote": "", "match": "unanchored"}]},
    ],
    "relationships": [{"source_entity_id": "P1", "target_entity_id": "C1", "relationship_type": "represents",
                       "citation": {"quote": "Bob Stone represents Aurora", "match": "verbatim", "start_char": 25}}],
}


def _run(workspace, name, **files):
    d = workspace / "outputs" / name
    d.mkdir(parents=True)
    for fname, content in files.items():
        (d / fname).write_text(json.dumps(content), encoding="utf-8")
    return d


def test_failed_run_reports_status_and_error(client, workspace):
    _run(workspace, "r_failed", **{"ops.json": {"status": "failed", "error": "RuntimeError: boom"}})
    body = client.get("/api/runs/r_failed").json()
    assert body["status"] == "failed" and "boom" in body["error"]
    assert {r["run_id"]: r["status"] for r in client.get("/api/runs").json()}["r_failed"] == "failed"


def test_running_and_unknown_runs_stay_pending(client, workspace):
    _run(workspace, "r_running", **{"ops.json": {"status": "running"}})
    assert client.get("/api/runs/r_running").json()["status"] == "pending"
    assert client.get("/api/runs/does_not_exist").json()["status"] == "pending"


def test_xlsx_export_has_register_relationships_evidence_and_cover(client, workspace):
    _run(workspace, "r_ok", **{"output.json": OUTPUT, "manifest.json": {"source_file": "uploads/x_case.txt", "created_at": "t"},
                               "ops.json": {"status": "completed", "llm": {"cost_usd": 0.05, "calls": 3}}})
    r = client.get("/api/runs/r_ok/export.xlsx")
    assert r.status_code == 200 and "spreadsheetml" in r.headers["content-type"]
    wb = load_workbook(io.BytesIO(r.content))
    assert wb.sheetnames == ["Cover", "Register", "Relationships", "Evidence"]
    reg = [[c.value for c in row] for row in wb["Register"].iter_rows(min_row=2)]
    assert reg[0][:5] == ["Aurora Holdings GmbH", "company", "Aurora", 1, 1]
    assert reg[1][3] == 0                                           # Bob Stone has no located quote
    rel = [c.value for c in next(wb["Relationships"].iter_rows(min_row=2))]
    assert rel[:3] == ["Bob Stone", "represents", "Aurora Holdings GmbH"]
    assert "0.05" in str([c.value for row in wb["Cover"].iter_rows() for c in row])


def test_xlsx_export_404_when_not_completed(client, workspace):
    _run(workspace, "r_pending", **{"ops.json": {"status": "running"}})
    assert client.get("/api/runs/r_pending/export.xlsx").status_code == 404
