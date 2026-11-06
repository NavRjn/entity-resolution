"""engine.recall: the missed-entity pass, with the LLM stubbed (no network)."""
import json
from types import SimpleNamespace

import engine.recall as rc

TEXT = ("The SEC reviewed the filing of Ximian Inc. on Monday.\n\n"
        "Tay Brown signed for Ximian. The Company paid the fee in July.")
ENTITIES = [{"entity_id": "x", "canonical_name": "Ximian Inc.", "entity_type": "company", "aliases": [], "citations": []}]


def _stub(monkeypatch, found):
    def fake(**kw):
        body = json.dumps({"entities": found})
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=body))])
    monkeypatch.setattr(rc.litellm, "completion", fake)


def F(name, typ, quote):
    return {"name": name, "type": typ, "quote": quote}


def test_adds_missed_entities_with_located_quotes(monkeypatch):
    _stub(monkeypatch, [F("SEC", "company", "The SEC reviewed the filing of Ximian Inc. on Monday."),
                        F("Tay Brown", "person", "Tay Brown signed for Ximian.")])
    new, stats = rc.extract_missed(TEXT, ENTITIES, "f")
    assert {e["canonical_name"]: e["entity_type"] for e in new} == {"SEC": "company", "Tay Brown": "person"}
    sec = next(e for e in new if e["canonical_name"] == "SEC")
    assert TEXT[sec["citations"][0]["start_char"]:sec["citations"][0]["end_char"]] == sec["citations"][0]["quote"]
    assert stats["kept"] == 2


def test_rejects_duplicates_invented_names_and_unlocatable_quotes(monkeypatch):
    _stub(monkeypatch, [F("Ximian", "company", "Tay Brown signed for Ximian."),               # shorter form of a known entity
                        F("Acme Corp", "company", "Acme Corp was never mentioned."),           # not in the text
                        F("Tay Brown", "person", "Tay Brown secretly resigned in 2019.")])     # quote not in the text
    new, stats = rc.extract_missed(TEXT, ENTITIES, "f")
    assert new == []
    assert (stats["duplicate"], stats["not_in_text"], stats["no_evidence"]) == (1, 1, 1)


def test_llm_failure_is_counted_not_raised(monkeypatch):
    def boom(**kw):
        raise RuntimeError("api down")
    monkeypatch.setattr(rc.litellm, "completion", boom)
    new, stats = rc.extract_missed(TEXT, ENTITIES, "f")
    assert new == [] and stats["errors"] == 1


def test_apply_to_run_writes_entities_and_stats(tmp_path, monkeypatch):
    _stub(monkeypatch, [F("Tay Brown", "person", "Tay Brown signed for Ximian.")])
    (tmp_path / "document.txt").write_text(TEXT, encoding="utf-8")
    (tmp_path / "output.json").write_text(json.dumps({"entities": ENTITIES, "relationships": []}), encoding="utf-8")
    (tmp_path / "manifest.json").write_text("{}", encoding="utf-8")
    stats = rc.apply_to_run(tmp_path)
    names = [e["canonical_name"] for e in json.loads((tmp_path / "output.json").read_text(encoding="utf-8"))["entities"]]
    assert names == ["Ximian Inc.", "Tay Brown"] and stats["kept"] == 1
    assert json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))["recall_pass"]["kept"] == 1
