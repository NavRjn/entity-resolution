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
