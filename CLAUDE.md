# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

LLM-aided entity resolution for legal/insurance documents: extracts entities (person, company, agreement, asset, other) and relationships (controls, participates_in, represents, transfers_to, governs, related_to) with provenance citations. Two backends coexist on the `integrate-docling` branch (see Architecture).

## Commands

Python ≥3.12, managed with `uv` (`pyproject.toml`/`uv.lock`; `requirements.txt` is stale UTF-16). The repo also contains a Windows venv `entity-res.venv/`. Secrets live in `.env` (`OPENAI_API_LEGALDEV`, `OPENAI_API_KEY`, `LANGFUSE_*`); Langfuse tracing is initialised at import time of `run.py`, and an Ollama server is expected at `127.0.0.1:11434` for local models.

```sh
# Legacy CLI pipeline (run from repo root; --file is relative to data/)
python run.py --file test.txt --seed 42            # full run -> outputs/<timestamp>/
python run.py --file test.txt --only entities
python run.py --run <run_id> --only relationship   # or --last; re-run relationships on existing run

# Evaluate a run against ground truth (data/<name>.gt.json)
python test.py --file test [--run <run_id>]        # defaults to latest run

# API server (CORS allows only http://localhost:5173)
uvicorn api.main:app --reload

# Frontend (React + Vite + Tailwind/shadcn + MUI)
cd frontend && npm run dev      # also: npm run build, npm run lint
```

There is no automated test suite; `test.py` is an evaluation script (precision/recall vs. ground truth), not pytest.

## Architecture

- **`run.py`** — the original hand-rolled pipeline and the home of shared Pydantic schemas (`Citation`, `CanonicalEntity`, `Relationship`, …). `EntityResolutionPipeline` does: text extraction → overlap chunking → per-chunk LLM entity extraction (OpenAI or Ollama, config in `config.yaml`) → guardrail validation (each entity's `exact_quote` must appear in the chunk, else counted as hallucination, logged via `debug_logger.py`) → fuzzy canonicalisation/alias merging (rapidfuzz) → relationship extraction validated against `ENTITY_RELATIONSHIP_DIRECTION_RULES`. `api/main.py` also imports `get_run_dir`, `build_networkx_graph` and `FILE_ID` from here.
- **`engine/`** — the new docling-graph backend. `engine/template.py` defines `OntologyDocument`, the Pydantic template docling-graph extracts into (duplicates the ontology constants from `run.py`; keep them in sync). `engine/api.py:run_full` calls `docling_graph.run_pipeline` (hard-coded OpenAI gpt-4o), then `save_compatible_files` converts docling-graph's `nodes.csv`/`edges.csv`/`metadata.json` into the legacy `manifest.json` + `output.json` format so the API and frontend work unchanged. Note `engine.api.RunContext` is a different class than `run.RunContext`.
- **`api/main.py`** — FastAPI app. Flow: `POST /api/uploads` stores files in `uploads/<id8>_<name>`; `POST /api/uploads/{id}/run` launches `engine.api.run_full` as a background task and returns a timestamp `run_id`; results are served from `outputs/<run_id>/` via `/api/runs/...` (manifest, entities, graph, document). The `pipeline = EntityResolutionPipeline()` object and legacy `run.py` code paths are still wired in but the run endpoint uses the docling engine.
- **`frontend/`** — Vite React app (pages: Uploads, UploadNew, Runs, RunDetail, Document, GraphView, Relationships) talking to the API at localhost:8000.
- **Data dirs** — `data/` input texts + `*.gt.json` ground truth; `outputs/` run artifacts (also a few flat JSON baselines); `uploads/`, `logs/`, `metrics/` are generated.

## Gotchas

- `pyproject.toml` pins `docling-graph` to a local editable path `../docling-graph` (sibling checkout required for `uv sync`).
- `save_compatible_files` uses `next(output_dir.glob(...))`, so it raises if docling-graph produced no output; `citations` start/end offsets are placeholders (0) in the docling path.
- `README.md` quick-start still says `pip install -r requirements.txt`; prefer `uv`.

## Architecture reference

Before answering architecture or "where is X" questions, read `.ua/knowledge-graph.json`.
It holds the file, function and class nodes, the edges between them, the layers, and a guided tour.
For questions about a specific file or function, use the `understand-anything:understand-explain` skill.
To ask questions about the codebase, use `understand-anything:understand-chat`.
