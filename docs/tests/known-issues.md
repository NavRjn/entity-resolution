# Known issues found by the test suite

Each of the 8 issues below is pinned by `xfail(strict=True)` tests (9 expected failures in total: #1 has two). Fixing the bug turns that test red (XPASS); then remove the marker and the entry here. Product code was deliberately not changed when these were found.

## Real bugs (have an xfail test)

| # | Where | Symptom | Test | Suggested fix |
|---|---|---|---|---|
| 1 | `engine/api.py:70` | No `merged_aliases` column → `aliases=[None]`. `GET /api/runs/{id}/graph` runs `CanonicalEntity.model_validate` → **500 on every docling run** (graph page breaks). | `test_engine_convert::test_output_validates_against_api_models`, `test_e2e_offline::test_graph_for_docling_run` | Build aliases as a list of non-empty strings (`[]` when absent) |
| 2 | `engine/api.py:69` | `entity_type` is the class name (`"Company"`); frontend compares lowercase (`"company"`), so RunDetail's company/person/agreement groups are empty and GraphView node sizing falls back to the default for docling runs. | `test_engine_convert::test_entity_type_matches_legacy_vocabulary` | `.lower()` it (or use the `entity_type` column) |
| 3 | `engine/api.py:73` | Node whose provenance has `"chunks": []` → `IndexError`; background task dies and the run stays "pending" forever. | `test_engine_convert::test_node_with_empty_chunk_list_does_not_crash` | Default `chunk_id` to 0 when empty |
| 4 | `engine/api.py:37-38` | docling-graph produced no output → bare `StopIteration` from `next(glob)`; opaque in a background task. The `if not graph_path.exists()` branch below is unreachable. | `test_engine_convert::test_missing_output_error_is_not_stopiteration` | Raise `FileNotFoundError` with the searched path |
| 5 | `frontend/src/pages/UploadNew.jsx:28` | POSTs to `/api/runs`, which only serves GET (405). Currently harmless because `RunCreating` starts the run via `/api/uploads/{id}/run`, but it is a dead call. | `test_frontend_contract` (`UploadNew.jsx-POST-/api/runs`) | Delete the call |
| 6 | `engine/template.py:235` | `OntologyDocument` has `graph_id_fields=["reference_document"]`, which is not a field (the field is `document_name`). May affect root-node identity in docling-graph. | `test_template::test_graph_id_fields_exist[OntologyDocument]` | Use `["document_name"]` |
| 7 | `run.py:405` | `validate_relationship` ends with `return True`; its checks (quote in chunk, valid type, valid ids) are computed but ignored, so no relationship is ever dropped. The `dropped` counter is always 0. | `test_pipeline_units::test_validate_relationship_rejects_bad_type` | Return `valid` (was probably disabled while tuning) |
| 8 | `run.py:241-245` | A first sentence longer than `max_chars` makes `chunk_text_with_overlap` emit an empty chunk (wasted/odd LLM call on `""`). | `test_pipeline_units::test_chunk_oversized_first_sentence_has_no_empty_chunk` | Skip appending when `current_chunk` is empty |

## Observed, not pinned by a test

- **Failed runs look pending forever.** `GET /api/runs/{id}` returns `{"status": "pending"}` for any run without `output.json`, including runs whose background task crashed (`outputs/` currently has several dirs without `output.json`). `RunCreating.jsx` polls until the status becomes `completed`, so a crashed run never resolves. During a demo this looks like a hang. Needs a status file or error artifact.
- **Docling runs have no `entities.json` / `chunks.json`.** `GET /api/runs/{id}/entities` → 404 and `POST /api/runs/{id}/relationships` → 500 for them. Neither endpoint is used by the frontend today.
- **5 saved legacy runs use an old relationship schema** (`evidence_quote`, no `citation`): `20260605_155241`, `_165147`, `_171038`, `_173918`, `_173918_COPY`. Their graph page would 500. `preflight.py` flags these; avoid them in a demo.
- **Frontend lint: 11 errors / 2 warnings, all pre-existing** (unused `React` imports, `react-refresh/only-export-components`, unused `isDenseMode` in GraphView, `__dirname` in `vite.config.js`). Reported as WARN by `check.py`; the build passes.
- **`GET /debug`** returns `sys.path`, cwd and PID with no auth. Remove it before exposing the API beyond localhost.
- **Importing `docling_graph` prints a Windows `0xc0000139` (entry point not found) fault trace under faulthandler**, from an optional native module that fails to load. It is harmless (the import succeeds); pytest runs with `-p no:faulthandler` to keep output readable.
- **`api/main.py` creates `uploads/` and `outputs/` relative to the cwd at import**, so starting uvicorn from another directory silently uses a different data folder.
