from pathlib import Path
from uuid import uuid4
import json
import datetime
from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks, APIRouter, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from run import CanonicalEntity, Relationship
from engine.api import RunContext, run_full

from run import (
    EntityResolutionPipeline,
    # RunContext,
    build_networkx_graph,
    get_run_dir,
    FILE_ID,
)
from pathlib import Path
app = FastAPI()
# router = APIRouter()
# app.include_router(router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

pipeline = EntityResolutionPipeline()

UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

OUTPUT_DIR = Path("outputs")
OUTPUT_DIR.mkdir(exist_ok=True)


@app.get("/")
def healthcheck():
    return {"status": "ok", "version": "v0.0.1"}

@app.get("/debug")
def debug():
    import os
    import sys
    return {"path": str(sys.path), "trace": str(sys.gettrace()), "cwd": os.getcwd(), "pwd": os.getpid()}


@app.post("/api/uploads")
async def upload_file(file: UploadFile = File(...)):
    upload_id = uuid4().hex[:8]
    filename = f"{upload_id}_{file.filename}"
    file_path = UPLOAD_DIR / filename
    contents = await file.read()

    with open(file_path, "wb") as f:
        f.write(contents)

    return {"upload_id": upload_id, "filename": file.filename, "stored_filename": filename}


@app.get("/api/uploads")
def list_uploads():
    uploads = []
    for path in sorted(UPLOAD_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if not path.is_file():
            continue

        upload_id = path.name.split("_", 1)[0]
        original_name = (path.name.split("_", 1)[1] if "_" in path.name else path.name)

        uploads.append(
            {
                "upload_id": upload_id,
                "filename": original_name,
                "stored_filename": path.name,
                "size_bytes": path.stat().st_size,
                "uploaded_at": datetime.datetime.fromtimestamp(
                    path.stat().st_mtime
                ).isoformat()
            }
        )

    return uploads


@app.post("/api/uploads/{upload_id}/run")
def run_upload(upload_id: str, background_tasks: BackgroundTasks):
    matches = list(UPLOAD_DIR.glob(f"{upload_id}_*"))
    if not matches:
        raise HTTPException(status_code=404, detail="Upload not found")

    upload_path = matches[0]
    run_id = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    ctx = RunContext(
        run_id=run_id,
        file_id=upload_id,
        # seed=42,
        file_path=upload_path,
        output_dir=get_run_dir(run_id)
    )

    # Launch the long run in the background
    # background_tasks.add_task(pipeline.run_full, ctx)
    background_tasks.add_task(run_full, ctx)

    # Immediately return run_id
    return {"run_id": run_id, "status": "pending"}

@app.get("/api/runs")
def list_runs():

    runs = []
    for run_dir in sorted(OUTPUT_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if not run_dir.is_dir():
            continue

        manifest_path = run_dir / "manifest.json"
        manifest = {}
        if manifest_path.exists():
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)

        status = "completed" if (run_dir / "output.json").exists() else "pending"
        ops_path = run_dir / "ops.json"
        if status == "pending" and ops_path.exists():
            status = json.loads(ops_path.read_text(encoding="utf-8")).get("status", status)
            status = "pending" if status == "running" else status

        runs.append(
            {
                "run_id": run_dir.name,
                "source_file": manifest.get("source_file"),
                "created_at": manifest.get("created_at"),
                "status": status
            }
        )
    return runs


def _normalize_run(data: dict) -> dict:
    """Make runs written before the converter fix readable: ontology-cased types, no null/blank aliases."""
    type_map = {"otherentity": "other"}
    for e in data.get("entities", []):
        t = str(e.get("entity_type") or "other").lower()
        e["entity_type"] = type_map.get(t, t)
        e["aliases"] = [a for a in (e.get("aliases") or []) if isinstance(a, str) and a.strip()]
    return data


@app.get("/api/runs/{run_id}")
def get_run(run_id: str):
    output_file = OUTPUT_DIR / run_id / "output.json"
    if not output_file.exists():
        return {"run_id": run_id, "status": "pending"}

    with open(output_file, "r", encoding="utf-8") as f:
        data = _normalize_run(json.load(f))

    return {"run_id": run_id, "status": "completed", **data}


@app.get("/api/runs/{run_id}/manifest")
def get_run_manifest(run_id: str):

    output_file = (OUTPUT_DIR / run_id / "manifest.json")
    if not output_file.exists():
        raise HTTPException(status_code=404, detail="Run not found")

    with open(output_file, "r",encoding="utf-8") as f:
        return json.load(f)


@app.get("/api/runs/{run_id}/entities")
def get_run_entities(run_id: str):

    output_file = (OUTPUT_DIR / run_id / "entities.json")
    if not output_file.exists():
        raise HTTPException(status_code=404, detail="Run not found")

    with open(output_file, "r",encoding="utf-8") as f:
        return json.load(f)


@app.post("/api/runs/{run_id}/relationships")
def rerun_relationships(run_id: str):
    try:
        ctx = pipeline.run_relationships_only(run_id)
        return {"run_id": run_id, "status": "completed", "relationships": len(ctx.relationships)}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/runs/{run_id}/graph")
def get_graph(run_id: str):
    run_dir = Path("outputs") / run_id
    output_file = run_dir / "output.json"
    if not output_file.exists():
        raise HTTPException(status_code=404, detail="Run not found")

    with open(output_file, "r", encoding="utf-8") as f:
        data = _normalize_run(json.load(f))

    entities = [CanonicalEntity.model_validate(c) for c in data.get("entities", [])]
    relationships = [Relationship.model_validate(r) for r in data.get("relationships", [])]

    graph = build_networkx_graph(entities, relationships)

    nodes = [{"id": n, **graph.nodes[n]}for n in graph.nodes]
    edges = [{"source": u, "target": v, **graph.edges[u, v]} for u, v in graph.edges]

    return {"nodes": nodes, "edges": edges}


@app.get("/api/runs/{run_id}/document")
def get_run_document(run_id: str):
    """Plain text of the run's document. Prefers <run>/document.txt: the exact text citation offsets index into
    (the source itself for .txt, docling's markdown for PDF/DOCX), so highlights and 'go to citation' always line up."""
    run_dir = OUTPUT_DIR / run_id
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.exists():
        raise HTTPException(status_code=404, detail="Run not found")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    doc_file = manifest.get("document_file")
    if doc_file and (run_dir / doc_file).exists():
        return {"run_id": run_id, "document": (run_dir / doc_file).read_text(encoding="utf-8"), "offsets_valid": True}

    source_file = manifest.get("source_file")
    if not source_file:
        raise HTTPException(status_code=400, detail="No source file linked to run")
    file_path = Path(source_file)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Source document not found")
    if file_path.suffix.lower() not in (".txt", ".md"):
        raise HTTPException(status_code=415, detail=f"{file_path.suffix} cannot be shown as text for this run (re-run to generate document.txt)")
    return {"run_id": run_id, "document": file_path.read_text(encoding="utf-8", errors="replace"), "offsets_valid": False}

@app.get("/api/uploads/{upload_id}/document")
def get_document(upload_id: str):
    matches = list(Path("uploads").glob(f"{upload_id}_*"))
    if not matches:
        raise HTTPException(status_code=404, detail="Upload not found")

    file_path = matches[0]
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File missing")

    # TEXT FILE VIEWER (MVP)
    if file_path.suffix == ".txt":
        with open(file_path, "r", encoding="utf-8") as f:
            text = f.read()

        return {"upload_id": upload_id, "type": "text", "content": text}

    # FUTURE EXTENSION POINT
    if file_path.suffix == ".pdf":
        return {"upload_id": upload_id, "type": "pdf", "message": "PDF rendering not implemented yet"}

    raise HTTPException(status_code=400, detail="Unsupported file type")

