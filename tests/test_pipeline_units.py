"""Pure-function tests for the legacy pipeline in run.py. No LLM involved."""
import pytest

import run
from run import (
    Citation, CanonicalEntity, ExtractedEntity, Relationship, ValidatedEntity,
    build_networkx_graph, chunk_text_with_overlap, extract_text, is_acronym,
    is_junk_entity, normalize_entity_name, resolve_entities, validate_guardrails,
)


# ---------- text ingestion & chunking ----------
def test_extract_text_txt(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("hello world", encoding="utf-8")
    assert extract_text(f) == "hello world"


def test_extract_text_rejects_unknown_type(tmp_path):
    f = tmp_path / "a.docx"
    f.write_text("x")
    with pytest.raises(ValueError):
        extract_text(f)


def test_chunk_short_text_single_chunk():
    assert chunk_text_with_overlap("One sentence. Two sentence.") == ["One sentence. Two sentence."]


def test_chunk_long_text_splits_and_keeps_all_sentences():
    sentences = [f"Sentence number {i} is here." for i in range(300)]
    chunks = chunk_text_with_overlap(" ".join(sentences), max_chars=500, overlap_chars=50)
    assert len(chunks) > 1
    assert all(c.strip() for c in chunks), "no empty chunks"
    joined = " ".join(chunks)
    for s in sentences:
        assert s in joined, f"lost: {s}"


@pytest.mark.xfail(strict=True, reason="chunk_text_with_overlap emits an empty chunk when the first sentence exceeds max_chars; see known-issues")
def test_chunk_oversized_first_sentence_has_no_empty_chunk():
    chunks = chunk_text_with_overlap("x" * 5000 + ". Next sentence.", max_chars=2000)
    assert all(c.strip() for c in chunks)


# ---------- guardrails ----------
def _ent(name="Acme Corp.", quote="Acme Corp."):
    return ExtractedEntity(entity_name=name, entity_type="company", exact_quote=quote)


def test_guardrail_accepts_quote_in_chunk():
    v = validate_guardrails(_ent(), "Acme Corp. signed it.", 0, "f1")
    assert v.is_valid and v.citation.start_char == 0 and v.citation.chunk_id == 0


def test_guardrail_whitespace_insensitive():
    v = validate_guardrails(_ent(quote="Acme   Corp."), "Acme Corp.\nsigned", 0, "f1")
    assert v.is_valid


def test_guardrail_rejects_hallucinated_quote():
    v = validate_guardrails(_ent(quote="never appears"), "Acme Corp. signed it.", 0, "f1")
    assert not v.is_valid and "Hallucination" in v.fail_reason


def test_guardrail_rejects_junk_name():
    v = validate_guardrails(_ent(name="Section 5", quote="Acme"), "Acme Corp.", 0, "f1")
    assert not v.is_valid


@pytest.mark.parametrize("name", ["$1,000", "USD 5.00", "Section 12", "Article 3", "Ltd.", "Inc", "the staff", "Employees"])
def test_junk_entities_detected(name):
    assert is_junk_entity(name)


@pytest.mark.parametrize("name", ["Acme Corp.", "John Smith", "Master Agreement"])
def test_real_entities_not_junk(name):
    assert not is_junk_entity(name)


# ---------- normalisation / acronyms ----------
def test_normalize_strips_suffix_and_punctuation():
    assert normalize_entity_name("Acme Corp.") == "acme"
    assert normalize_entity_name("ACME, Inc") == "acme"


def test_is_acronym():
    assert is_acronym("FDA", "Food and Drug Administration")
    assert not is_acronym("XYZ", "Food and Drug Administration")
    assert not is_acronym("A", "Alpha")  # too short


# ---------- entity resolution ----------
def _valid(name, etype="company", chunk=0):
    return ValidatedEntity(
        entity_name=name, entity_type=etype, is_valid=True,
        citation=Citation(file_id="f", chunk_id=chunk, start_char=0, end_char=1, quote=name),
    )


def test_resolve_merges_near_duplicates():
    out = resolve_entities([_valid("Acme Corp."), _valid("Acme Corporation", chunk=1), _valid("Globex")])
    assert [c.canonical_name for c in out] == ["Acme Corp.", "Globex"]
    assert "Acme Corporation" in out[0].aliases
    assert {c.chunk_id for c in out[0].citations} == {0, 1}


def test_resolve_assigns_sequential_ids():
    out = resolve_entities([_valid("Alpha Co"), _valid("Beta LLC"), _valid("Gamma")])
    assert [c.entity_id for c in out] == ["E0", "E1", "E2"]


def test_resolve_skips_invalid():
    bad = _valid("Nope")
    bad.is_valid = False
    assert resolve_entities([bad]) == []


def test_resolve_empty():
    assert resolve_entities([]) == []


# ---------- graph ----------
def _canon(eid, name, etype="company"):
    return CanonicalEntity(entity_id=eid, canonical_name=name, entity_type=etype)


def _rel(src, tgt, rtype="controls"):
    return Relationship(
        source_entity_id=src, target_entity_id=tgt, relationship_type=rtype,
        citation=Citation(file_id="f", chunk_id=0, start_char=0, end_char=1, quote="q"),
    )


def test_graph_nodes_and_edges():
    g = build_networkx_graph([_canon("E0", "A"), _canon("E1", "B")], [_rel("E0", "E1")])
    assert set(g.nodes) == {"E0", "E1"}
    assert g.edges["E0", "E1"]["relationship"] == "controls"


def test_graph_strips_brackets_in_ids():
    g = build_networkx_graph([_canon("E0", "A"), _canon("E1", "B")], [_rel("[E0]", "[E1]")])
    assert g.has_edge("E0", "E1")


def test_graph_drops_edges_to_unknown_entities():
    g = build_networkx_graph([_canon("E0", "A")], [_rel("E0", "E9")])
    assert g.number_of_edges() == 0


# ---------- relationship validation ----------
@pytest.mark.xfail(strict=True, reason="validate_relationship ends with `return True` (validation disabled); see known-issues")
def test_validate_relationship_rejects_bad_type():
    r = _rel("E0", "E1", rtype="not_a_real_type")
    assert run.validate_relationship(r, "q") is False


# ---------- artifact round trip ----------
def test_artifact_roundtrip(workspace):
    d = run.get_run_dir("rt")
    run.save_manifest(d, "x.txt", 7)
    run.save_chunks(d, ["a", "b"])
    cans = [_canon("E0", "A")]
    run.save_entities_artifact(d, [_valid("A")], cans, {0: [{"entity_id": "E0", "name": "A", "type": "company"}]})
    run.save_output(d, cans, [_rel("E0", "E0")])

    assert run.load_manifest(d)["seed"] == 7
    assert run.load_chunks(d) == ["a", "b"]
    ent = run.load_entities_artifact(d)
    assert run.rebuild_canonicals(ent["canonical_entities"])[0].canonical_name == "A"


def test_get_latest_run_id(workspace):
    run.get_run_dir("20260101_000000")
    run.get_run_dir("20260102_000000")
    assert run.get_latest_run_id() in {"20260101_000000", "20260102_000000"}


def test_get_latest_run_id_empty(workspace):
    with pytest.raises(ValueError):
        run.get_latest_run_id()
