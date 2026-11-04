"""Legacy EntityResolutionPipeline end-to-end with a mocked LLM (no network)."""
import json

import run
from conftest import DOC_TEXT


def _ctx(workspace, seed=1):
    src = workspace / "doc.txt"
    src.write_text(DOC_TEXT, encoding="utf-8")
    return run.RunContext(run_id="r1", file_id="f1", seed=seed, file_path=src, output_dir=run.get_run_dir("r1"))


def test_run_full_writes_all_artifacts(workspace, fake_llm):
    ctx = _ctx(workspace)
    run.EntityResolutionPipeline().run_full(ctx)

    d = workspace / "outputs" / "r1"
    for name in ("manifest.json", "chunks.json", "entities.json", "output.json"):
        assert (d / name).exists(), name

    out = json.loads((d / "output.json").read_text(encoding="utf-8"))
    names = {e["canonical_name"] for e in out["entities"]}
    assert names == {"Acme Corp.", "Master Agreement", "John Smith"}
    assert out["relationships"][0]["relationship_type"] == "participates_in"


def test_hallucination_and_junk_are_counted_and_dropped(workspace, fake_llm):
    ctx = _ctx(workspace)
    run.EntityResolutionPipeline().run_entities(ctx)
    assert ctx.hallucination_count == 2  # "Initech" + "Section 5"
    assert "Initech" not in {c.canonical_name for c in ctx.canonicals}


def test_llm_is_mocked_and_called(workspace, fake_llm):
    run.EntityResolutionPipeline().run_full(_ctx(workspace))
    assert fake_llm, "LLM was never invoked"
    assert all(c["provider"] == "openai" for c in fake_llm)


def test_relationships_only_rerun(workspace, fake_llm):
    run.EntityResolutionPipeline().run_entities(_ctx(workspace))
    fake_llm.clear()
    ctx = run.EntityResolutionPipeline().run_relationships_only("r1")
    assert len(ctx.relationships) == 1
    assert (workspace / "outputs" / "r1" / "output.json").exists()


def test_llm_failure_degrades_to_empty_not_crash(workspace, monkeypatch):
    """A failing LLM call must not blow up the run (it is logged and returns {})."""
    def boom(*a, **k):
        raise RuntimeError("api down")
    monkeypatch.setattr(run, "_llm_backend", boom)
    ctx = _ctx(workspace)
    run.EntityResolutionPipeline().run_entities(ctx)
    assert ctx.canonicals == []
