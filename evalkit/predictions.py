"""Pipeline output -> Prediction. Works for legacy run.py and docling runs (same output.json contract).

Also accepts a generic prediction JSON ({"entities":[{"name","type","aliases"}], "relations":[...]}) so
outputs from any other system can be scored without touching the pipeline.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .normalize import norm_rel, norm_type
from .schema import PredEntity, PredRelation, Prediction

PLACEHOLDER_QUOTE = re.compile(r"^#/|^\s*$|^NA$")   # docling refs ('#/texts/0') and empty quotes


def _clean_id(x: str) -> str:
    return str(x).strip().strip("[]")


def from_output_json(data: dict, doc_id: str, type_map: dict | None = None) -> Prediction:
    ents, ids = [], set()
    for e in data.get("entities", []):
        eid = _clean_id(e.get("entity_id") or e.get("id") or e.get("canonical_name") or e.get("name"))
        name = e.get("canonical_name") or e.get("name") or ""
        quotes, spans = [], []
        for c in e.get("citations", []) or []:
            q = c.get("quote", "")
            quotes.append(q)
            if c.get("end_char", 0) > c.get("start_char", 0):
                spans.append((c["start_char"], c["end_char"]))
        ents.append(PredEntity(
            id=eid, name=name, type=norm_type(e.get("entity_type") or e.get("type") or "other", type_map),
            aliases=[a for a in (e.get("aliases") or []) if a and a != name], quotes=quotes, spans=spans))
        ids.add(eid)
    rels = []
    for r in data.get("relationships", data.get("relations", [])):
        cit = r.get("citation") or {}
        rels.append(PredRelation(
            source=_clean_id(r.get("source_entity_id", r.get("source", ""))),
            target=_clean_id(r.get("target_entity_id", r.get("target", ""))),
            type=norm_rel(r.get("relationship_type", r.get("type", ""))),
            quote=cit.get("quote", r.get("quote", ""))))
    return Prediction(doc_id=doc_id, entities=ents, relations=rels)


def load_run(run_dir: Path, doc_id: str | None = None) -> Prediction:
    """outputs/<run_id>/ -> Prediction (+ ops from manifest/ops.json when present)."""
    out = run_dir / "output.json"
    if not out.exists():
        raise FileNotFoundError(f"{out} missing: run did not complete")
    pred = from_output_json(json.loads(out.read_text(encoding="utf-8")), doc_id or run_dir.name)
    ops = run_dir / "ops.json"
    if ops.exists():
        pred.ops = json.loads(ops.read_text(encoding="utf-8"))
    return pred


def load_generic(path: Path, doc_id: str) -> Prediction:
    return from_output_json(json.loads(path.read_text(encoding="utf-8")), doc_id)
