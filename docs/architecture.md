# Architecture

Stage-by-stage walkthrough of the active pipeline. Paths are relative to the repo root.

```text
UI → POST /api/uploads → uploads/<id8>_<name>
   → POST /api/uploads/{id}/run → BackgroundTask engine.api.run_full
        → docling_graph.run_pipeline (Docling parse/chunk → LLM → graph CSVs)
        → engine.api.save_compatible_files → manifest.json + output.json
   → GET /api/runs/... → UI
```

## 1. Ingestion: `api/main.py`

| Function | Behaviour |
|---|---|
| `upload_file` (`POST /api/uploads`) | Reads the multipart `file`, writes it to `uploads/<id8>_<original name>` where `id8 = uuid4().hex[:8]`, returns `{upload_id, filename, stored_filename}`. |
| `list_uploads` | Lists `uploads/` newest first; `upload_id` is the filename prefix before the first `_`. |
| `run_upload` (`POST /api/uploads/{id}/run`) | Finds `uploads/<id>_*`, creates `run_id = now("%Y%m%d_%H%M%S")`, builds an `engine.api.RunContext`, schedules `run_full` with FastAPI `BackgroundTasks`, and returns immediately with `{run_id, status: "pending"}`. |

`get_run_dir(run_id)` (imported from `run.py`) creates `outputs/<run_id>/`. `uploads/` and `outputs/` are relative to the **current working directory**, so start the server from the repo root.

## 2. Extraction: `engine/api.py:run_full`

`run_full` builds a `docling_graph.PipelineConfig`:

| Field | Value |
|---|---|
| `source` | path of the uploaded file |
| `template` | `"engine.template.OntologyDocument"` |
| `backend` | `"llm"` |
| `inference` | `"remote"` |
| `provider_override` / `model_override` | `"openai"` / `"gpt-4o"` |
| `dump_to_disk` / `output_dir` | `True` / `outputs/<run_id>` |

`docling_graph.run_pipeline` then converts and chunks the document with Docling, asks the LLM to fill the template per chunk, merges the results into a graph, and writes `docling/` and `docling_graph/` under `outputs/<run_id>/<name>_<timestamp>/`.

## 3. Ontology template: `engine/template.py`

- `Person`, `Company`, `Agreement`, `Asset`, `OtherEntity` are Pydantic models. Each has `entity_type: Literal[...]` and `name`; `graph_id_fields=["name"]` makes `name` the node identity, so identical names merge into one node.
- Relationship fields are declared with the `edge(label, ...)` helper, which puts `edge_label` into `json_schema_extra`. docling-graph reads that label for the edge type, and the `Union[...]` type of each list constrains which target types are legal.
- `OntologyDocument` is the extraction root. Its fields (`persons`, `companies`, `agreements`, `assets`, `others`) map to root edges `MENTIONS_PERSON`, `MENTIONS_COMPANY`, `CONTAINS_AGREEMENT`, `MENTIONS_ASSET`, `MENTIONS_OTHER_ENTITY`.
- `ALLOWED_ENTITIES`, `ALLOWED_RELATIONSHIPS` and `ENTITY_RELATIONSHIP_DIRECTION_RULES` duplicate constants in `run.py`; a smoke test checks they have not drifted.

## 4. Adapter: `engine/api.py:save_compatible_files`

Reads `nodes.csv`, `edges.csv` and `metadata.json` from the docling-graph output and writes the two files the API serves.

| Output field | Source |
|---|---|
| `entities[].entity_id` | node `id` |
| `entities[].canonical_name` | node `name` |
| `entities[].entity_type` | node `label` (class name, e.g. `Company`) |
| `entities[].aliases` | node `merged_aliases` (column usually absent) |
| `entities[].citations[]` | one per `refs` entry in node `__provenance__`: `file_id=document_id`, `chunk_id=chunks[0]`, `quote=<Docling ref>`; offsets are `0` |
| `relationships[].source_entity_id / target_entity_id` | edge `source` / `target` |
| `relationships[].relationship_type` | edge `label` |
| `relationships[].citation` | empty placeholder |
| `manifest.created_at` | `metadata.json` `timestamp` |
| `manifest.source_file` | uploaded file path (used by `/document`) |

Filtering: the `OntologyDocument` root node is dropped from entities, and edges whose source is the root are dropped from relationships.

Schemas for `Citation`, `CanonicalEntity` and `Relationship` come from `run.py` and are shared by the adapter and the API.

## 5. Serving: `api/main.py`

- `get_run`: returns `{status: "pending"}` while `output.json` is absent, otherwise `{status: "completed", entities, relationships}`. Completion is purely "the file exists".
- `get_graph`: validates `output.json` into `CanonicalEntity` / `Relationship`, builds a `networkx.DiGraph` with `run.build_networkx_graph`, returns `{nodes: [{id, label, entity_type}], edges: [{source, target, relationship, evidence}]}`.
- `get_run_document`: reads `source_file` from `manifest.json` and returns the text.

## 6. Presentation

See [`frontend.md`](frontend.md): entity table, relationship table, highlighted document view, force-directed graph.

## Design notes and trade-offs

- **Stable contract over a changing engine.** The adapter is the only code that knows docling-graph's CSV layout.
- **Filesystem as store.** Simple and inspectable. Trade-off: completion is inferred from file presence, so failures are invisible (see [known issues](tests/known-issues.md)).
- **Background task, not a queue.** `BackgroundTasks` is enough for a single-user demo; a worker queue plus a status file would be the next step.
- **Test seam.** `engine.api.run_pipeline` is the only paid call, so tests patch it and keep `PipelineConfig` real.
