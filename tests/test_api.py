"""FastAPI endpoints, in-process. (The /document endpoints are under development and not covered.)"""


def test_healthcheck(client):
    r = client.get("/")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_cors_allows_frontend_origin(client):
    r = client.options(
        "/api/runs",
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"},
    )
    assert r.headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_cors_rejects_other_origin(client):
    r = client.options(
        "/api/runs",
        headers={"Origin": "http://127.0.0.1:5173", "Access-Control-Request-Method": "GET"},
    )
    assert "access-control-allow-origin" not in r.headers


# ---------- uploads ----------
def test_list_uploads_empty(client):
    assert client.get("/api/uploads").json() == []


def test_upload_stores_file_and_lists_it(client, workspace):
    r = client.post("/api/uploads", files={"file": ("hello.txt", b"hi there", "text/plain")})
    assert r.status_code == 200
    body = r.json()
    assert body["filename"] == "hello.txt"
    assert (workspace / "uploads" / body["stored_filename"]).read_bytes() == b"hi there"

    listed = client.get("/api/uploads").json()
    assert len(listed) == 1
    assert listed[0]["upload_id"] == body["upload_id"]
    assert listed[0]["filename"] == "hello.txt"
    assert listed[0]["size_bytes"] == 8


def test_upload_without_file_is_422(client):
    assert client.post("/api/uploads").status_code == 422


def test_filename_with_underscores_roundtrips(client):
    client.post("/api/uploads", files={"file": ("my_big_file.txt", b"x", "text/plain")})
    assert client.get("/api/uploads").json()[0]["filename"] == "my_big_file.txt"


# ---------- runs ----------
def test_run_unknown_upload_404(client):
    assert client.post("/api/uploads/nope1234/run").status_code == 404


def test_list_runs_empty(client):
    assert client.get("/api/runs").json() == []


def test_list_runs_reports_manifest_fields(client, legacy_run):
    runs = client.get("/api/runs").json()
    assert runs[0]["run_id"] == legacy_run
    assert runs[0]["created_at"] == "2026-01-01T00:00:00"
    assert runs[0]["source_file"].endswith("abcd1234_doc.txt")


def test_list_runs_tolerates_dir_without_manifest(client, workspace):
    (workspace / "outputs" / "half_done").mkdir()
    runs = client.get("/api/runs").json()
    assert runs == [{"run_id": "half_done", "source_file": None, "created_at": None}]


def test_get_run_pending_before_output(client, workspace):
    (workspace / "outputs" / "r9").mkdir()
    assert client.get("/api/runs/r9").json() == {"run_id": "r9", "status": "pending"}


def test_get_run_completed(client, legacy_run):
    body = client.get(f"/api/runs/{legacy_run}").json()
    assert body["status"] == "completed"
    assert len(body["entities"]) == 2 and len(body["relationships"]) == 1


def test_manifest_and_entities(client, legacy_run):
    assert client.get(f"/api/runs/{legacy_run}/manifest").json()["seed"] == 1
    assert len(client.get(f"/api/runs/{legacy_run}/entities").json()["canonical_entities"]) == 2


def test_manifest_entities_graph_404(client):
    for suffix in ("manifest", "entities", "graph"):
        assert client.get(f"/api/runs/missing/{suffix}").status_code == 404, suffix


def test_graph_nodes_and_edges(client, legacy_run):
    g = client.get(f"/api/runs/{legacy_run}/graph").json()
    assert {n["id"] for n in g["nodes"]} == {"E0", "E1"}
    assert g["nodes"][0]["entity_type"] in {"company", "agreement"}
    assert g["edges"] == [{"source": "E0", "target": "E1", "relationship": "participates_in", "evidence": "Acme"}]


def test_rerun_relationships_legacy_run(client, legacy_run, fake_llm):
    r = client.post(f"/api/runs/{legacy_run}/relationships")
    assert r.status_code == 200 and r.json()["relationships"] == 1


def test_rerun_relationships_unknown_run_is_500_with_detail(client, fake_llm):
    r = client.post("/api/runs/missing/relationships")
    assert r.status_code == 500 and r.json()["detail"]
