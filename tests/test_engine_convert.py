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


def test_citations_carry_chunk_and_quote(docling_output, tmp_path):
    _, data = _convert(docling_output, tmp_path)
    john = next(e for e in data["entities"] if e["canonical_name"] == "John Smith")
    assert len(john["citations"]) == 2
    assert all(c["chunk_id"] == 0 and c["file_id"] == "doc1" for c in john["citations"])


@pytest.mark.xfail(strict=True, reason="no merged_aliases column -> aliases=[None], which fails CanonicalEntity validation (breaks /graph); see known-issues")
def test_output_validates_against_api_models(docling_output, tmp_path):
    """GET /api/runs/{id}/graph does CanonicalEntity.model_validate on every entity."""
    _, data = _convert(docling_output, tmp_path)
    for e in data["entities"]:
        CanonicalEntity.model_validate(e)
    for r in data["relationships"]:
        Relationship.model_validate(r)


@pytest.mark.xfail(strict=True, reason="entity_type is the class name ('Person'), frontend compares lowercase ('person'); see known-issues")
def test_entity_type_matches_legacy_vocabulary(docling_output, tmp_path):
    _, data = _convert(docling_output, tmp_path)
    assert {e["entity_type"] for e in data["entities"]} <= ALLOWED_ENTITIES


@pytest.mark.xfail(strict=True, reason="empty provenance chunks -> IndexError in save_compatible_files; see known-issues")
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


@pytest.mark.xfail(strict=True, reason="next(glob) raises bare StopIteration (opaque in a background task); see known-issues")
def test_missing_output_error_is_not_stopiteration(tmp_path):
    out = tmp_path / "empty_out"
    out.mkdir()
    with pytest.raises((FileNotFoundError, ValueError, RuntimeError)):
        save_compatible_files("rid", tmp_path / "doc.txt", out)
