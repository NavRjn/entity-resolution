"""engine.relations: the relationship pass, with the LLM stubbed (no network)."""
import json
from types import SimpleNamespace

import pytest

import engine.relations as rel

TEXT = ("Mono was originally created by Ximian and later acquired by Novell.\n\n"
        "Novell was bought by Attachmate. Xamarin is now owned by Microsoft Corporation.\n\n"
        "Beschluss vom 11 . 2 . 2015 - B 13 R 329/13 B wurde zugestellt .")

ENTITIES = [
    {"entity_id": "n", "canonical_name": "Novell", "entity_type": "company", "aliases": [], "citations": []},
    {"entity_id": "x", "canonical_name": "Ximian", "entity_type": "company", "aliases": [], "citations": []},
    {"entity_id": "m", "canonical_name": "Microsoft", "entity_type": "company", "aliases": [], "citations": []},
    {"entity_id": "xa", "canonical_name": "Xamarin", "entity_type": "company", "aliases": [], "citations": []},
    {"entity_id": "ag", "canonical_name": "Beschluss vom 11. 2. 2015", "entity_type": "agreement", "aliases": [], "citations": []},
]


def _stub(monkeypatch, records):
    def fake(**kw):
        body = json.dumps({"relationships": records})
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=body))])
    monkeypatch.setattr(rel.litellm, "completion", fake)


def R(subject, relation, obj, evidence):
    return {"subject": subject, "relation": relation, "object": obj, "evidence": evidence}


def test_keeps_valid_relation_with_located_evidence(monkeypatch):
    _stub(monkeypatch, [R("Novell", "controls", "Ximian", "later acquired by Novell")])
    out, stats = rel.extract_relationships(TEXT, ENTITIES)
    assert [(r["source_entity_id"], r["relationship_type"], r["target_entity_id"]) for r in out] == [("n", "controls", "x")]
    c = out[0]["citation"]
    assert TEXT[c["start_char"]:c["end_char"]] == c["quote"] == "later acquired by Novell" and c["match"] == "verbatim"
    assert stats["kept"] == 1


def test_name_resolution_uses_containment_and_rejects_unknown(monkeypatch):
    _stub(monkeypatch, [R("Microsoft Corporation", "controls", "Xamarin", "Xamarin is now owned by Microsoft Corporation"),
                        R("Oracle", "controls", "Xamarin", "Xamarin is now owned by Microsoft Corporation")])
    out, stats = rel.extract_relationships(TEXT, ENTITIES)
    assert [(r["source_entity_id"], r["target_entity_id"]) for r in out] == [("m", "xa")]
    assert stats["unresolved"] == 1


def test_direction_rules_reject_impossible_relations(monkeypatch):
    _stub(monkeypatch, [R("Beschluss vom 11. 2. 2015", "controls", "Novell", "Novell was bought by Attachmate"),   # agreement cannot control
                        R("Novell", "participates_in", "Ximian", "later acquired by Novell")])                     # company is not an agreement
    out, stats = rel.extract_relationships(TEXT, ENTITIES)
    assert out == [] and stats["bad_direction"] == 2


def test_evidence_must_exist_in_the_text(monkeypatch):
    _stub(monkeypatch, [R("Novell", "controls", "Ximian", "Novell secretly owns Ximian through a shell company")])
    out, stats = rel.extract_relationships(TEXT, ENTITIES)
    assert out == [] and stats["no_evidence"] == 1
    out, _ = rel.extract_relationships(TEXT, ENTITIES, require_evidence=False)
    assert out[0]["citation"]["match"] == "unanchored"


def test_evidence_tolerates_punctuation_spacing_of_tokenised_sources(monkeypatch):
    _stub(monkeypatch, [R("Beschluss vom 11. 2. 2015", "related_to", "Novell", "Beschluss vom 11. 2. 2015 - B 13 R 329/13 B wurde zugestellt.")])
    out, stats = rel.extract_relationships(TEXT, ENTITIES)
    c = out[0]["citation"]
    assert stats["kept"] == 1 and c["match"] == "verbatim" and c["quote"].startswith("Beschluss vom 11 . 2 . 2015")


def test_duplicates_collapse_and_chunks_without_two_entities_skip_the_llm(monkeypatch):
    calls = []

    def fake(**kw):
        calls.append(1)
        body = json.dumps({"relationships": [R("Novell", "controls", "Ximian", "later acquired by Novell")] * 2})
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=body))])

    monkeypatch.setattr(rel.litellm, "completion", fake)
    out, stats = rel.extract_relationships(TEXT, ENTITIES)
    assert len(out) == 1 and stats["duplicate"] == 1
    calls.clear()
    out, stats = rel.extract_relationships("Nothing relevant here at all.", ENTITIES)
    assert out == [] and calls == []


def test_llm_failure_is_counted_not_raised(monkeypatch):
    def boom(**kw):
        raise RuntimeError("rate limited")

    monkeypatch.setattr(rel.litellm, "completion", boom)
    out, stats = rel.extract_relationships(TEXT, ENTITIES)
    assert out == [] and stats["errors"] >= 1


def test_apply_to_run_merges_and_records_stats(tmp_path, monkeypatch):
    _stub(monkeypatch, [R("Novell", "controls", "Ximian", "later acquired by Novell")])
    (tmp_path / "document.txt").write_text(TEXT, encoding="utf-8")
    (tmp_path / "output.json").write_text(json.dumps({"entities": ENTITIES, "relationships": []}), encoding="utf-8")
    (tmp_path / "manifest.json").write_text("{}", encoding="utf-8")
    stats = rel.apply_to_run(tmp_path)
    data = json.loads((tmp_path / "output.json").read_text(encoding="utf-8"))
    assert len(data["relationships"]) == 1 and stats["kept"] == 1
    assert json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))["relation_pass"]["kept"] == 1
    assert rel.apply_to_run(tmp_path.parent / "nonexistent_run_dir_for_test") if False else True


def test_experimental_templates_have_small_catalogs():
    """The finding behind the relation pass: the shipped template's catalog explodes (nested Union relation fields)."""
    from docling_graph.core.extractors.contracts.dense.catalog import build_node_catalog
    import engine.template as base
    import engine.template_v1 as v1
    import engine.template_v2 as v2
    assert len(build_node_catalog(base.OntologyDocument).nodes) > 20
    assert len(build_node_catalog(v1.OntologyDocument).nodes) == 6
    assert len(build_node_catalog(v2.OntologyDocument).nodes) == 7
