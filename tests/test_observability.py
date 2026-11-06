"""observability.py: never breaks a run, records ops.json, wraps litellm with tokens/cost. No network."""
import json
from contextlib import contextmanager

import pytest

import observability


class RecordingClient:
    def __init__(self):
        self.observations, self.scores, self.updates = [], [], []

    @contextmanager
    def start_as_current_observation(self, **kw):
        self.observations.append(kw)
        client = self

        class Span:
            def update(self, **u):
                client.updates.append(u)
        yield Span()

    def get_current_trace_id(self):
        return "trace-123"

    def create_score(self, **kw):
        self.scores.append(kw)

    def flush(self):
        pass


@pytest.fixture
def fake_client(monkeypatch):
    c = RecordingClient()
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk")
    monkeypatch.setattr(observability, "client", lambda: c)
    return c


def test_disabled_without_keys(monkeypatch):
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    assert observability.client() is None and not observability.enabled()
    assert observability.record_scores({"x": 1.0}, trace_id="t") == 0


def test_run_trace_writes_ops_json_and_stage_times(tmp_path, fake_client):
    with observability.run_trace("r1", backend="docling", output_dir=tmp_path, tags=["t"]) as ops:
        with observability.stage("convert", n=3):
            pass
    d = json.loads((tmp_path / "ops.json").read_text(encoding="utf-8"))
    assert d["status"] == "completed" and d["trace_id"] == "trace-123" and "convert" in d["stages_s"]
    assert {o["name"] for o in fake_client.observations} >= {"entity_resolution_run", "convert"}


def test_failed_run_is_recorded_and_exception_propagates(tmp_path, fake_client):
    with pytest.raises(ValueError):
        with observability.run_trace("r2", backend="legacy", output_dir=tmp_path):
            raise ValueError("boom")
    d = json.loads((tmp_path / "ops.json").read_text(encoding="utf-8"))
    assert d["status"] == "failed" and "boom" in d["error"]


def test_broken_langfuse_never_breaks_the_run(tmp_path, monkeypatch):
    class Exploding:
        def start_as_current_observation(self, **kw):
            raise RuntimeError("langfuse down")

        def get_current_trace_id(self):
            raise RuntimeError("langfuse down")

        def flush(self):
            raise RuntimeError("langfuse down")

    monkeypatch.setattr(observability, "client", lambda: Exploding())
    with observability.run_trace("r3", backend="docling", output_dir=tmp_path):
        with observability.stage("x"):
            pass
    assert json.loads((tmp_path / "ops.json").read_text(encoding="utf-8"))["status"] == "completed"


def test_litellm_wrapper_records_tokens_cost_and_hides_content(tmp_path, fake_client, monkeypatch):
    import litellm
    monkeypatch.setattr(litellm, "completion", litellm.completion)       # restored after the test
    assert observability.instrument_litellm() and observability.instrument_litellm()      # idempotent
    import sys
    monkeypatch.delitem(sys.modules, "langfuse.openai", raising=False)   # run.py imports it; this test needs the wrapper to emit
    with observability.run_trace("r4", backend="docling", output_dir=tmp_path) as ops:
        litellm.completion(model="gpt-4o", messages=[{"role": "user", "content": "SECRET CLIENT TEXT"}], mock_response="ok")
    assert ops.llm["calls"] == 1 and ops.llm["prompt_tokens"] > 0 and ops.llm["completion_tokens"] > 0
    gen = next(o for o in fake_client.observations if o["as_type"] == "generation")
    assert "SECRET CLIENT TEXT" not in json.dumps(gen, default=str)          # content stays out of Langfuse by default
    assert any("usage_details" in u for u in fake_client.updates)


def test_litellm_wrapper_skips_generation_when_openai_integration_already_traces(tmp_path, fake_client, monkeypatch):
    import sys
    import litellm
    monkeypatch.setattr(litellm, "completion", litellm.completion)
    monkeypatch.setitem(sys.modules, "langfuse.openai", object())
    observability.instrument_litellm()
    with observability.run_trace("r5", backend="docling", output_dir=tmp_path) as ops:
        litellm.completion(model="gpt-4o", messages=[{"role": "user", "content": "x"}], mock_response="ok")
    assert ops.llm["calls"] == 1 and ops.llm["cost_usd"] > 0                  # accounting still happens
    assert not [o for o in fake_client.observations if o["as_type"] == "generation"]   # no duplicate generation


def test_mask_redacts_strings_keeps_numbers():
    m = observability._mask({"messages": [{"role": "user", "content": "SECRET"}], "n": 3})
    assert "SECRET" not in str(m) and m["n"] == 3 and "6 chars" in str(m)


def test_record_scores_only_sends_numbers(fake_client):
    n = observability.record_scores({"a": 0.5, "b": None, "c": True, "d": "x", "e": 1}, trace_id="t")
    assert n == 2 and {s["name"] for s in fake_client.scores} == {"eval/a", "eval/e"}
