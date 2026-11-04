# Preflight

`preflight.py` answers "will a run / the demo work *right now*?" before you spend credits or walk into a meeting. The pytest suite answers "is the code OK?"; preflight answers "is this machine, these keys and this data OK?".

```sh
uv run python preflight.py            # local checks only
uv run python preflight.py --online   # + free network checks
uv run python check.py --preflight    # tests + preflight in one go (--online for the network checks too)
```

It never prints secret values (only "set"/"missing") and never calls an LLM. Exit code is 1 only if something is FAIL.

## What it checks

**Local (always)**

| Check | FAIL when |
|---|---|
| `.env` has `OPENAI_API_KEY`, `OPENAI_API_LEGALDEV`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` | any is missing or empty |
| `../docling-graph` sibling checkout exists | missing (needed by `uv sync`) |
| `docling_graph`, `fastapi`, `uvicorn`, `rapidfuzz`, `networkx`, `engine.template` import | any import fails (wrong venv? run through `uv run`) |
| Saved runs in `outputs/` load (valid JSON, expected keys, string aliases) | WARN only; lists runs whose graph page would 500 |
| `uploads/` readable | WARN if empty |
| API on `:8000`, frontend on `:5173` | WARN if not running, with the start command |

**Online (`--online`, still free: none of these consume LLM tokens)**

| Check | How | FAIL when |
|---|---|---|
| OpenAI keys valid and `gpt-4o` available | `GET /v1/models` | HTTP error, or `gpt-4o` not listed |
| Langfuse prompts `entity-system`, `relationship-system` exist | Langfuse public API | HTTP error (`run.py` crashes at import without them) |
| Ollama reachable | `GET :11434/api/tags` | never; WARN only (needed just for local-model runs) |

## When to run it

- **Before a client demo**: `uv run python check.py --online`, then start the API and frontend and re-run `preflight.py` to see both ports go green. Pick a run from the "loadable" set.
- **Before a paid run** on a new document: `check.py --online` catches a revoked key or a missing Langfuse prompt before the first (billed) chunk, not after.
- **After pulling or changing dependencies**: `check.py` alone.
