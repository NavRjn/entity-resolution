# Tests

An **offline, free** safety net: it never calls OpenAI, Langfuse or Ollama, so it costs no API credits and can run any time (before a paid run, before a client demo, after a refactor).

## Run it

```sh
uv run python check.py              # everything: backend tests + frontend lint + frontend build   (~55 s)
uv run python check.py --fast       # backend tests only                                            (~40 s)
uv run python check.py --preflight  # + local readiness report (keys, saved runs, servers)
uv run python check.py --online     # + free network checks (see preflight.md)
uv run pytest                       # just pytest; add -k name, -x, -rx (list expected failures)
```

`check.py` prints PASS / WARN / FAIL per step and exits non-zero on any FAIL. **Lint is WARN only** (11 pre-existing style errors, see `known-issues.md`); a failing **build** or any failing test is a FAIL.

About 30 s of every run is `import docling_graph` (torch/docling). It is paid once per session, not per test.

## What is covered

| File | What it protects against |
|---|---|
| `test_smoke.py` | Broken imports (`run`, `engine.api`, `api.main`), invalid `config.yaml`, malformed `data/*.gt.json`, ontology constants drifting between `run.py` and `engine/template.py` |
| `test_pipeline_units.py` | Legacy pipeline logic: chunking, hallucination guardrail, junk filter, fuzzy entity merging, graph building, artifact save/load |
| `test_legacy_pipeline.py` | Whole legacy pipeline with a fake LLM: all four artifacts written, hallucinations dropped, LLM failure does not crash |
| `test_template.py` | `OntologyDocument` schema builds, edge labels and directions obey the ontology rules |
| `test_engine_convert.py` | docling-graph CSVs → `manifest.json`/`output.json` conversion (what the UI reads) |
| `test_engine_run.py` | `engine.api.run_full` with the paid call mocked but **`PipelineConfig` real**, so docling-graph config drift is caught before a paid run |
| `test_api.py` | Every FastAPI endpoint, happy path and 404s, CORS |
| `test_e2e_offline.py` | The demo path: upload → run → results, in-process |
| `test_frontend_contract.py` | Every `fetch()` in `frontend/src` hits a route and method the API really serves |
| `test_eval_script.py` | `test.py` (precision/recall evaluator) still runs |

Out of scope for now (under development): the Document page / `/document` endpoints, citation offsets.

## How "offline" is guaranteed

Three independent layers (`tests/conftest.py`, `pyproject.toml`):

1. **Socket guard**: `pytest-socket` with `--allow-hosts=127.0.0.1,::1`. Any connection to a non-loopback host fails the test with `SocketConnectBlockedError`. Verified against a raw IP, a DNS name and `httpx` → `api.openai.com`.
2. **Dummy credentials**: conftest sets fake `OPENAI_*`/`LANGFUSE_*` before anything imports. `load_dotenv()` does not override existing vars, so the real `.env` keys are never loaded in tests.
3. **Stubs/mocks**: `langfuse.get_client` is replaced (`run.py` fetches prompts at import time); `run._llm_backend` and `engine.api.run_pipeline` are patched by the `fake_llm` / `fake_docling` fixtures. litellm and HuggingFace are put in offline mode.

## Fixtures (`tests/conftest.py`)

- `workspace`: empty tmp cwd with `uploads/` and `outputs/` (the code uses relative paths; tests never touch your real data)
- `client`: in-process `TestClient`; BackgroundTasks run synchronously
- `legacy_run`: a finished legacy-format run to read from
- `fake_llm`: canned entity/relationship JSON for `run.py` (includes one hallucination and one junk entity); returns the call log
- `fake_docling`: copies `tests/fixtures/docling_output/` where docling-graph would write; returns the `PipelineConfig`s it received
- `docling_output`: a writable copy of that fixture, for conversion tests

## Adding a test

Put it in the matching file, use the fixtures above, and keep it simple. Never call a real LLM. If it needs the network the guard will fail it, which is the point.

## Expected failures (`xfail`)

Tests that expose a real bug are marked `@pytest.mark.xfail(strict=True, reason=...)` and listed in `known-issues.md`. The product code is intentionally unchanged. `strict=True` means that when someone fixes the bug the test turns red (XPASS), which is the signal to delete the `xfail` marker and the entry in `known-issues.md`. See them all with `uv run pytest -rx`.
