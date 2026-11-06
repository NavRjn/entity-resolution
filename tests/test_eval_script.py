"""Smoke test for test.py (the precision/recall evaluator). Loaded by path: `import test` would hit the stdlib package."""
import importlib.util
import json

from conftest import REPO


def _load_eval(workspace):
    spec = importlib.util.spec_from_file_location("eval_script", REPO / "test.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # METRICS_DIR.mkdir() lands in the tmp workspace (cwd)
    return mod


def test_evaluate_perfect_prediction(workspace):
    gt = json.loads((REPO / "data" / "test.gt.json").read_text(encoding="utf-8"))
    ents = [
        {"entity_id": f"E{i}", "canonical_name": e["entity_name"], "entity_type": e["entity_type"], "aliases": [], "citations": []}
        for i, e in enumerate(gt["entities"])
    ]
    for r in gt.get("relationships", []):   # the GT has a relation whose endpoint is missing from its entity list;
        for name in (r["source"], r["target"]):   # evalkit (rightly) rejects dangling edges, so a perfect prediction needs it
            if name not in {e["canonical_name"] for e in ents}:
                ents.append({"entity_id": f"E{len(ents)}", "canonical_name": name, "entity_type": "other", "aliases": [], "citations": []})
    by_name = {e["canonical_name"]: e["entity_id"] for e in ents}
    rels = [
        {
            "source_entity_id": by_name.get(r["source"], r["source"]),
            "target_entity_id": by_name.get(r["target"], r["target"]),
            "relationship_type": r["relationship"],
            "citation": {"file_id": "f", "chunk_id": 0, "start_char": 0, "end_char": 0, "quote": "q"},
        }
        for r in gt.get("relationships", [])
    ]
    pred = workspace / "output.json"
    pred.write_text(json.dumps({"entities": ents, "relationships": rels}), encoding="utf-8")

    mod = _load_eval(workspace)
    mod.evaluate_run(pred, REPO / "data" / "test.gt.json")

    report = json.loads((workspace / "metrics" / "output.json").read_text(encoding="utf-8"))
    assert report["f1"] > 0.9
    assert report["false_negatives"] == 0


def test_evaluate_empty_prediction_does_not_crash(workspace):
    pred = workspace / "empty.json"
    pred.write_text(json.dumps({"entities": [], "relationships": []}), encoding="utf-8")
    mod = _load_eval(workspace)
    mod.evaluate_run(pred, REPO / "data" / "test.gt.json")
    assert json.loads((workspace / "metrics" / "empty.json").read_text(encoding="utf-8"))["f1"] == 0
