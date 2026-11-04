# API reference

Base URL `http://localhost:8000`. CORS allows only `http://localhost:5173`. No authentication. Source: [`api/main.py`](../api/main.py).

## Uploads

### `POST /api/uploads`
Multipart form with a `file` field.

```json
{ "upload_id": "5a4fd93d", "filename": "test-synthetic.txt", "stored_filename": "5a4fd93d_test-synthetic.txt" }
```

### `GET /api/uploads`
```json
[{ "upload_id": "5a4fd93d", "filename": "test-synthetic.txt", "stored_filename": "5a4fd93d_test-synthetic.txt",
   "size_bytes": 2048, "uploaded_at": "2026-10-31T13:46:01.123456" }]
```

### `POST /api/uploads/{upload_id}/run`
Starts extraction in the background. `404` if the upload does not exist.

```json
{ "run_id": "20261031_134601", "status": "pending" }
```

### `GET /api/uploads/{upload_id}/document`
`.txt` returns `{upload_id, type: "text", content}`; `.pdf` returns a "not implemented" message; other types `400`.

## Runs

### `GET /api/runs`
```json
[{ "run_id": "20261031_134601", "source_file": "uploads\\5a4fd93d_zero1.txt", "created_at": "2026-10-31T13:46:15.310912" }]
```

### `GET /api/runs/{run_id}`
Pending (no `output.json` yet, **also returned for crashed runs and unknown ids**):
```json
{ "run_id": "20261031_134601", "status": "pending" }
```
Completed:
```json
{
  "run_id": "20261031_134601",
  "status": "completed",
  "entities": [{
    "entity_id": "Company_91aeb0cfd4ac6884",
    "canonical_name": "Northbridge Risk Holdings",
    "entity_type": "Company",
    "aliases": [],
    "citations": [{ "file_id": "2f1b…", "chunk_id": 0, "start_char": 0, "end_char": 0, "quote": "#/texts/0" }]
  }],
  "relationships": [{
    "source_entity_id": "Person_…", "target_entity_id": "Company_…", "relationship_type": "controls",
    "citation": { "file_id": "NA", "chunk_id": 0, "start_char": 0, "end_char": 0, "quote": "" }
  }]
}
```

### `GET /api/runs/{run_id}/manifest`
`{run_id, created_at, source_file, seed, chunk_max_chars, chunk_overlap_chars}`; `404` if missing.

### `GET /api/runs/{run_id}/graph`
```json
{ "nodes": [{ "id": "Company_…", "label": "Northbridge Risk Holdings", "entity_type": "Company" }],
  "edges": [{ "source": "Person_…", "target": "Company_…", "relationship": "controls", "evidence": "" }] }
```
`404` if the run has no `output.json`. Edges whose endpoints are not entities are skipped.

### `GET /api/runs/{run_id}/document`
`{run_id, document}` with the source text; `404` if the run or source file is missing.

## Not used by the UI (legacy-era, kept for compatibility)
`GET /api/runs/{run_id}/entities`, `POST /api/runs/{run_id}/relationships`, `GET /` (health), `GET /debug` (remove before exposing the API).
