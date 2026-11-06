"""engine.api.save_compatible_files: docling-graph CSVs -> legacy manifest.json/output.json."""
import csv
import json
import shutil

import pytest

from engine.api import save_compatible_files
from run import ALLOWED_ENTITIES, CanonicalEntity, Relationship


def _convert(docling_output, tmp_path, source="doc.txt"):
    out = tmp_path / "run_out"
    (out / "doc_run").mkdir(parents=True)
    for item in docling_output.iterdir():
        dest = out / "doc_run" / item.name
        shutil.copytree(item, dest) if item.is_dir() else shutil.copy(item, dest)
    save_compatible_files("rid", tmp_path / source, out)
    return out, json.loads((out / "output.json").read_text(encoding="utf-8"))


def _rewrite_nodes(docling_output, fn):
    p = docling_output / "docling_graph" / "nodes.csv"
    rows = list(csv.DictReader(p.open(encoding="utf-8", newline="")))
    rows = fn(rows)
    with p.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()), quoting=csv.QUOTE_ALL)
        w.writeheader()
        w.writerows(rows)


def test_manifest_written(docling_output, tmp_path):
    out, _ = _convert(docling_output, tmp_path)
    m = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert m["run_id"] == "rid"
    assert m["created_at"] == "2026-01-01T12:00:00.000000"
    assert m["source_file"].endswith("doc.txt")


def test_entities_exclude_root_document_node(docling_output, tmp_path):
    _, data = _convert(docling_output, tmp_path)
    assert {e["canonical_name"] for e in data["entities"]} == {"John Smith", "Acme Corp", "Master Agreement"}


def test_relationships_exclude_root_edges(docling_output, tmp_path):
    _, data = _convert(docling_output, tmp_path)
    kinds = {(r["source_entity_id"], r["relationship_type"], r["target_entity_id"]) for r in data["relationships"]}
    assert kinds == {
        ("Person_1111", "represents", "Company_2222"),
        ("Company_2222", "participates_in", "Agreement_3333"),
    }


def test_citations_carry_file_and_chunk_and_never_a_placeholder_quote(docling_output, tmp_path):
    _, data = _convert(docling_output, tmp_path)
    john = next(e for e in data["entities"] if e["canonical_name"] == "John Smith")
    assert john["citations"] and all(c["chunk_id"] == 0 and c["file_id"] == "doc1" for c in john["citations"])
    assert not any(c["quote"].startswith("#/") for e in data["entities"] for c in e["citations"])   # docling refs are not quotes


def test_output_validates_against_api_models(docling_output, tmp_path):
    """GET /api/runs/{id}/graph does CanonicalEntity.model_validate on every entity."""
    _, data = _convert(docling_output, tmp_path)
    for e in data["entities"]:
        CanonicalEntity.model_validate(e)
    for r in data["relationships"]:
        Relationship.model_validate(r)


def test_entity_type_matches_legacy_vocabulary(docling_output, tmp_path):
    _, data = _convert(docling_output, tmp_path)
    assert {e["entity_type"] for e in data["entities"]} <= ALLOWED_ENTITIES


def test_node_with_empty_chunk_list_does_not_crash(docling_output, tmp_path):
    def edit(rows):
        for r in rows:
            if r["id"] == "Person_1111":
                r["__provenance__"] = json.dumps({"document_id": "d", "chunks": [], "refs": ["#/texts/1"]})
        return rows

    _rewrite_nodes(docling_output, edit)
    _, data = _convert(docling_output, tmp_path)
    assert len(data["entities"]) == 3


def test_missing_output_fails_loudly(tmp_path):
    """No docling output must raise, never silently write an empty result."""
    out = tmp_path / "empty_out"
    out.mkdir()
    with pytest.raises(Exception):
        save_compatible_files("rid", tmp_path / "doc.txt", out)
    assert not (out / "output.json").exists()


def test_missing_output_error_is_not_stopiteration(tmp_path):
    out = tmp_path / "empty_out"
    out.mkdir()
    with pytest.raises((FileNotFoundError, ValueError, RuntimeError)):
        save_compatible_files("rid", tmp_path / "doc.txt", out)


# --------------------------------------------------------------------------- real provenance -> real citations

SRC = "Intro. John Smith, CEO of Acme Corp, signed the Master Agreement on 3 May. Later Acme Corp paid."


def _with_provenance(docling_output, tmp_path, chunk_prefix=""):
    """Add a provenance.json (docling-graph v2) whose chunk covers SRC[7:], optionally with the CDATA wrapper."""
    body = SRC[7:]
    text = chunk_prefix + body
    off = len(chunk_prefix)
    def anchor(q, nth=0):
        i = [k for k in range(len(body)) if body.startswith(q, k)][nth]
        return {"document_id": "", "chunk_id": 0, "kind": "verbatim", "span": [off + i, off + i + len(q)]}
    prov = {"version": 2, "chunks": {"0": {"chunk_id": 0, "text": text, "char_length": len(text)}}, "nodes": {
        "persons[]|name=JOHN_SMITH": {"node_type": "Person", "ids": {"name": "John Smith"}, "anchors": [{"kind": "observed", "chunk_id": 0, "span": None}, anchor("John Smith")]},
        "companies[]|name=ACME_CORP": {"node_type": "Company", "ids": {"name": "Acme Corp"}, "anchors": [anchor("Acme Corp", 0), anchor("Acme Corp", 1)]},
    }}
    (docling_output / "docling_graph" / "provenance.json").write_text(json.dumps(prov), encoding="utf-8")
    src = tmp_path / "doc.txt"
    src.write_text(SRC, encoding="utf-8")
    return src


@pytest.mark.parametrize("prefix", ["", "<text><![CDATA["])
def test_citations_use_provenance_anchors_with_real_offsets(docling_output, tmp_path, prefix):
    src = _with_provenance(docling_output, tmp_path, prefix)
    out = tmp_path / "run_out"
    (out / "doc_run").mkdir(parents=True)
    for item in docling_output.iterdir():
        shutil.copytree(item, out / "doc_run" / item.name) if item.is_dir() else shutil.copy(item, out / "doc_run" / item.name)
    save_compatible_files("rid", src, out)
    data = json.loads((out / "output.json").read_text(encoding="utf-8"))
    acme = next(e for e in data["entities"] if e["canonical_name"] == "Acme Corp")
    assert [c["match"] for c in acme["citations"]] == ["verbatim", "verbatim"]
    for c in acme["citations"]:
        assert SRC[c["start_char"]:c["end_char"]] == c["quote"] == "Acme Corp"      # offsets index the source text exactly
    assert (out / "document.txt").read_text(encoding="utf-8") == SRC
    assert json.loads((out / "manifest.json").read_text(encoding="utf-8"))["document_file"] == "document.txt"
    rel = next(r for r in data["relationships"] if r["relationship_type"] == "represents")
    assert rel["citation"]["match"] == "cooccurrence" and "John Smith" in rel["citation"]["quote"] and "Acme Corp" in rel["citation"]["quote"]


def test_node_without_anchor_falls_back_to_name_search(docling_output, tmp_path):
    src = tmp_path / "doc.txt"
    src.write_text(SRC, encoding="utf-8")                 # no provenance.json at all
    out = tmp_path / "run_out"
    (out / "doc_run").mkdir(parents=True)
    for item in docling_output.iterdir():
        shutil.copytree(item, out / "doc_run" / item.name) if item.is_dir() else shutil.copy(item, out / "doc_run" / item.name)
    save_compatible_files("rid", src, out)
    data = json.loads((out / "output.json").read_text(encoding="utf-8"))
    john = next(e for e in data["entities"] if e["canonical_name"] == "John Smith")
    assert john["citations"][0]["match"] == "name_search" and SRC[john["citations"][0]["start_char"]:john["citations"][0]["end_char"]] == "John Smith"
    agr = next(e for e in data["entities"] if e["canonical_name"] == "Master Agreement")
    assert agr["citations"][0]["match"] == "name_search"
