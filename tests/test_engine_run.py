"""engine.api.run_full with the paid docling-graph call mocked; PipelineConfig is real."""
import importlib
import json

from engine.api import RunContext, run_full


def _ctx(workspace):
    src = workspace / "uploads" / "abcd1234_doc.txt"
    src.write_text("Acme Corp. signed the Master Agreement.", encoding="utf-8")
    out = workspace / "outputs" / "r1"
    out.mkdir(parents=True)
    return RunContext(run_id="r1", file_id="abcd1234", file_path=src, output_dir=out)


def test_run_full_produces_compatible_files(workspace, fake_docling):
    ctx = run_full(_ctx(workspace))
    assert ctx.doc_ctx is not None
    out = workspace / "outputs" / "r1"
    assert (out / "manifest.json").exists()
    data = json.loads((out / "output.json").read_text(encoding="utf-8"))
    assert len(data["entities"]) == 3


def test_pipeline_config_targets_openai_gpt4o_template(workspace, fake_docling):
    run_full(_ctx(workspace))
    cfg = fake_docling[0]
    assert cfg.backend == "llm"
    assert cfg.inference == "remote"
    assert cfg.provider_override == "openai"
    assert cfg.model_override == "gpt-4o"
    assert cfg.template == "engine.template.OntologyDocument"


def test_configured_template_is_importable():
    mod_name, _, cls = "engine.template.OntologyDocument".rpartition(".")
    assert hasattr(importlib.import_module(mod_name), cls)
