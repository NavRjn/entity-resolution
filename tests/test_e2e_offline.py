"""The demo path (upload -> run -> view results) with the paid docling-graph call mocked."""
import pytest

from conftest import REPO


def _upload_and_run(client):
    text = (REPO / "data" / "test.txt").read_bytes()
    up = client.post("/api/uploads", files={"file": ("test.txt", text, "text/plain")}).json()
    run = client.post(f"/api/uploads/{up['upload_id']}/run")
    assert run.status_code == 200 and run.json()["status"] == "pending"
    return up, run.json()["run_id"]


def test_upload_run_results(client, fake_docling, workspace):
    up, run_id = _upload_and_run(client)

    assert len(fake_docling) == 1, "docling-graph should be invoked exactly once"
    assert fake_docling[0].source.endswith(f"{up['upload_id']}_test.txt")

    run = client.get(f"/api/runs/{run_id}").json()
    assert run["status"] == "completed"
    assert {e["canonical_name"] for e in run["entities"]} == {"John Smith", "Acme Corp", "Master Agreement"}
    assert len(run["relationships"]) == 2

    assert run_id in [r["run_id"] for r in client.get("/api/runs").json()]
    manifest = client.get(f"/api/runs/{run_id}/manifest").json()
    assert manifest["source_file"].endswith("_test.txt")


def test_graph_for_docling_run(client, fake_docling):
    _, run_id = _upload_and_run(client)
    g = client.get(f"/api/runs/{run_id}/graph")
    assert g.status_code == 200 and len(g.json()["nodes"]) == 3
