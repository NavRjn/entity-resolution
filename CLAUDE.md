# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

LLM-aided entity resolution for legal/insurance documents: extracts entities (person, company, agreement, asset, other) and relationships (controls, participates_in, represents, transfers_to, governs, related_to) with provenance citations. Two backends coexist on the `integrate-docling` branch (see Architecture).

## Commands

Python ≥3.12. **Always run Python through `uv`** (`uv run ...`), never a bare `python`/`uvicorn`: `uv` manages docling and the rest of the dependency graph, and the project is not runnable outside it. `requirements.txt` is stale UTF-16. The project environment is `.venv/`, a native Windows venv (`.venv\Scripts\python.exe`, created by `uv sync`; `uv run` uses it automatically, no `--active` needed). A venv can't be shared between WSL and Windows; if `uv sync` fails with access denied on `.venv\lib64`, that is a leftover WSL symlink: remove it with `cmd /c rmdir .venv\lib64` and re-run. `entity-res.venv/` is an old venv and is not used. Secrets live in `.env` (`OPENAI_API_LEGALDEV`, `OPENAI_API_KEY`, `LANGFUSE_*`); Langfuse tracing is initialised at import time of `run.py`, and an Ollama server is expected at `127.0.0.1:11434` for local models.

```sh
# Legacy CLI pipeline (run from repo root; --file is relative to data/)
uv run python run.py --file test.txt --seed 42            # full run -> outputs/<timestamp>/
uv run python run.py --file test.txt --only entities
uv run python run.py --run <run_id> --only relationship   # or --last; re-run relationships on existing run

# Evaluate a run against ground truth (data/<name>.gt.json)
uv run python test.py --file test [--run <run_id>]        # defaults to latest run

# API server (CORS allows only http://localhost:5173)
uv run python -m uvicorn api.main:app --reload

# Frontend (React + Vite + Tailwind/shadcn + MUI)
cd frontend && npm run dev      # also: npm run build, npm run lint
```

**Tests (offline, free, no API credits):** `uv run python check.py` runs the pytest suite plus frontend lint and build (~55 s); `--fast` is pytest only, `--preflight`/`--online` add the readiness report (keys, saved runs, servers, free network checks). Details in `docs/tests/`. `test.py` is separate: an evaluation script (precision/recall vs. ground truth), not pytest.

## Browser automation (frontend verification)

- A Playwright MCP server (`playwright`, pinned `@playwright/mcp@0.0.83`) is registered at **local scope** in `~/.claude.json` for this project, launched with `cmd /c npx`. It is machine-specific and not committed, so check `claude mcp list` before assuming it exists. Its tools only appear in sessions started after it was registered.
- It runs headless, isolated Chromium with a temporary profile and no access to the user's Chrome profile or sign-ins. `--browser chromium` is required; otherwise it defaults to system Chrome. Browsing is restricted to `localhost`/`127.0.0.1` on ports 5173 and 8000; other origins are blocked, so external CDN/font requests fail (this includes the Swagger UI assets on `/docs`).
- The browser is Chromium revision 1247, in `%LOCALAPPDATA%\ms-playwright`. If the pinned package is bumped and needs a different revision, install it with `npx -y -p @playwright/mcp@<version> playwright-core install chromium`.
- Start the API and frontend first (see Commands). Use `http://localhost:5173`, not `127.0.0.1`: Vite listens on `::1` only, so `127.0.0.1:5173` is refused, and the API's CORS only allows the `localhost` origin. `/` has no route and renders only the nav bar; `/runs` and `/uploads` load data from the API.
- `--output-dir` keeps auto-named files out of the repo, in `%LOCALAPPDATA%\Temp\claude\C--Home-Directory-Uni-Research-entity-resolution\playwright-output`. Take screenshots without a `filename`: a relative `filename` is written to the repo root.
- Do not connect to the user's Chrome or open a remote-debugging port. That exposes every signed-in session. Use the Claude in Chrome extension only if the user asks for it.
- Do not write Playwright tests unless asked. The setup is for manual verification of UI changes.

## Architecture

- **`run.py`** — the original hand-rolled pipeline and the home of shared Pydantic schemas (`Citation`, `CanonicalEntity`, `Relationship`, …). `EntityResolutionPipeline` does: text extraction → overlap chunking → per-chunk LLM entity extraction (OpenAI or Ollama, config in `config.yaml`) → guardrail validation (each entity's `exact_quote` must appear in the chunk, else counted as hallucination, logged via `debug_logger.py`) → fuzzy canonicalisation/alias merging (rapidfuzz) → relationship extraction validated against `ENTITY_RELATIONSHIP_DIRECTION_RULES`. `api/main.py` also imports `get_run_dir`, `build_networkx_graph` and `FILE_ID` from here.
- **`engine/`** — the new docling-graph backend. `engine/template.py` defines `OntologyDocument`, the Pydantic template docling-graph extracts into (duplicates the ontology constants from `run.py`; keep them in sync). `engine/api.py:run_full` calls `docling_graph.run_pipeline` (hard-coded OpenAI gpt-4o), then `save_compatible_files` converts docling-graph's `nodes.csv`/`edges.csv`/`metadata.json` into the legacy `manifest.json` + `output.json` format so the API and frontend work unchanged. Note `engine.api.RunContext` is a different class than `run.RunContext`.
- **`api/main.py`** — FastAPI app. Flow: `POST /api/uploads` stores files in `uploads/<id8>_<name>`; `POST /api/uploads/{id}/run` launches `engine.api.run_full` as a background task and returns a timestamp `run_id`; results are served from `outputs/<run_id>/` via `/api/runs/...` (manifest, entities, graph, document). The `pipeline = EntityResolutionPipeline()` object and legacy `run.py` code paths are still wired in but the run endpoint uses the docling engine.
- **`frontend/`** — Vite React app (pages: Uploads, UploadNew, Runs, RunDetail, Document, GraphView, Relationships) talking to the API at localhost:8000.
- **Data dirs** — `data/` input texts + `*.gt.json` ground truth; `outputs/` run artifacts (also a few flat JSON baselines); `uploads/`, `logs/`, `metrics/` are generated.

## Gotchas

- `pyproject.toml` pins `docling-graph` to a local editable path `../docling-graph` (sibling checkout required for `uv sync`).
- `save_compatible_files` uses `next(output_dir.glob(...))`, so it raises if docling-graph produced no output; `citations` start/end offsets are placeholders (0) in the docling path.
- `README.md` quick-start still says `pip install -r requirements.txt` and `python run.py` / `uvicorn ...`; those commands are wrong for this project, use `uv` instead.

## Architecture reference

Before answering architecture or "where is X" questions, read `.ua/knowledge-graph.json`.
It holds the file, function and class nodes, the edges between them, the layers, and a guided tour.
For questions about a specific file or function, use the `understand-anything:understand-explain` skill.
To ask questions about the codebase, use `understand-anything:understand-chat`.
