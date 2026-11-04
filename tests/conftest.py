"""Offline test harness. Nothing here may touch the network or spend API credits.

Order matters: env vars and the langfuse stub must be installed before any
project module (run.py, api.main) is imported, because run.py fetches
Langfuse prompts and builds OpenAI/Ollama clients at import time.
"""
import os
from contextlib import contextmanager
from pathlib import Path

# dummy keys: load_dotenv() does not override existing vars, so real .env keys never load
for _k, _v in {
    "OPENAI_API_KEY": "sk-test-dummy",
    "OPENAI_API_LEGALDEV": "sk-test-dummy",
    "LANGFUSE_PUBLIC_KEY": "pk-test",
    "LANGFUSE_SECRET_KEY": "sk-test",
    "LANGFUSE_HOST": "http://127.0.0.1:1",
    "LANGFUSE_TRACING_ENABLED": "false",
    # litellm (via docling-graph) downloads a price map at import; use the bundled copy
    "LITELLM_LOCAL_MODEL_COST_MAP": "True",
    "HF_HUB_OFFLINE": "1",
    "TRANSFORMERS_OFFLINE": "1",
}.items():
    os.environ[_k] = _v

import langfuse  # noqa: E402
import pytest  # noqa: E402


class _FakePrompt:
    def compile(self, **kwargs):
        return "FAKE PROMPT " + " ".join(f"{k}={v}" for k, v in kwargs.items())


class _FakeSpan:
    def update(self, **kwargs):
        pass


class _FakeLangfuse:
    def get_prompt(self, name, *a, **k):
        return _FakePrompt()

    @contextmanager
    def start_as_current_observation(self, *a, **k):
        yield _FakeSpan()

    def flush(self):
        pass


langfuse.get_client = lambda *a, **k: _FakeLangfuse()

REPO = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """Empty cwd with uploads/ and outputs/ so relative paths never hit real data."""
    (tmp_path / "uploads").mkdir()
    (tmp_path / "outputs").mkdir()
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def docling_output(tmp_path):
    """A writable copy of the canned docling-graph output tree (nodes.csv/edges.csv/metadata.json)."""
    import shutil
    dest = tmp_path / "docling_fixture"
    shutil.copytree(FIXTURES / "docling_output", dest)
    return dest


@pytest.fixture
def fake_docling(monkeypatch):
    """Patch engine.api.run_pipeline (the paid call) to drop canned output in cfg.output_dir.

    PipelineConfig stays real, so docling-graph config/API drift is still caught.
    Returns a list of the PipelineConfig objects it was called with.
    """
    import shutil
    from types import SimpleNamespace

    import engine.api

    seen = []

    def fake_run_pipeline(cfg):
        seen.append(cfg)
        target = Path(cfg.output_dir) / "doc_20260101_000000"
        shutil.copytree(FIXTURES / "docling_output", target)
        return SimpleNamespace(cfg=cfg)

    monkeypatch.setattr(engine.api, "run_pipeline", fake_run_pipeline)
    return seen


DOC_TEXT = (
    "Acme Corp. signed the Master Agreement with John Smith. "
    "John Smith represents Globex Ltd. in all matters."
)


@pytest.fixture
def fake_llm(monkeypatch):
    """Replace the OpenAI/Ollama call in run.py with canned JSON. Returns a call log."""
    import run

    calls = []

    def fake_backend(provider, schema, system_prompt, user_prompt, seed, model=None):
        calls.append({"provider": provider, "model": model, "prompt": user_prompt})
        if "Known entities" in user_prompt:  # relationship extraction
            return {"relationships": [{
                "source_entity_id": "E0",
                "target_entity_id": "E1",
                "relationship_type": "participates_in",
                "evidence_quote": "Acme Corp. signed the Master Agreement",
            }]}
        return {"entities": [
            {"entity_name": "Acme Corp.", "entity_type": "company", "exact_quote": "Acme Corp."},
            {"entity_name": "Master Agreement", "entity_type": "agreement", "exact_quote": "Master Agreement"},
            {"entity_name": "John Smith", "entity_type": "person", "exact_quote": "John Smith"},
            {"entity_name": "Initech", "entity_type": "company", "exact_quote": "Initech is not in the text"},  # hallucination
            {"entity_name": "Section 5", "entity_type": "other", "exact_quote": "Acme"},  # junk
        ]}

    monkeypatch.setattr(run, "_llm_backend", fake_backend)
    return calls
