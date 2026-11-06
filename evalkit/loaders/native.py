"""Native formats: our own JSONL (one GoldDocument per line) and the legacy data/*.gt.json files."""
from __future__ import annotations

import json
import warnings
from pathlib import Path
from typing import Iterator

from ..normalize import norm_name
from ..schema import GoldDocument, GoldEntity, GoldRelation
from .base import Card, register


@register("native")
def load_native(path: Path, opt: dict, card: Card) -> Iterator[GoldDocument]:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            yield GoldDocument.model_validate_json(line)


@register("legacy_gt")
def load_legacy(path: Path, opt: dict, card: Card) -> Iterator[GoldDocument]:
    """data/<name>.gt.json + data/<name>.txt: {entities:[{entity_name,entity_type,aliases?}], relationships:[{source,relationship,target}]}."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    stem = path.name.replace(".gt.json", "")
    if opt.get("text"):
        txt = path.with_name(opt["text"])
    else:      # data/test.gt.json was written for test-synthetic.txt, not test.txt: pick the candidate that contains the names
        cands = [p for p in (path.with_name(stem + ".txt"), path.with_name(stem + "-synthetic.txt")) if p.exists()]
        def hits(p: Path) -> int:
            body = p.read_text(encoding="utf-8", errors="replace")
            return sum(e["entity_name"] in body for e in raw["entities"])
        txt = max(cands, key=hits) if cands else path.with_name(stem + ".txt")
    name_to_id: dict[str, str] = {}
    ents = []
    for i, e in enumerate(raw["entities"]):
        eid = f"{card.name}#e{i}"
        name_to_id[norm_name(e["entity_name"])] = eid
        ents.append(GoldEntity(id=eid, name=e["entity_name"], type=card.map_type(e["entity_type"]) or "other",
                               aliases=e.get("aliases", [])))
    rels, implicit = [], []
    for r in raw.get("relationships", []):
        ids = []
        for name in (r["source"], r["target"]):
            key = norm_name(name)
            if key not in name_to_id:         # a relation endpoint missing from the entity list is a labelling error:
                eid = f"{card.name}#e{len(ents)}"   # keep the relation (it asserts the entity exists) but say so loudly
                name_to_id[key] = eid
                ents.append(GoldEntity(id=eid, name=name, type="other"))
                implicit.append(name)
            ids.append(name_to_id[key])
        rels.append(GoldRelation(source=ids[0], type=r["relationship"], target=ids[1]))
    if implicit:
        warnings.warn(f"{path.name}: relations reference entities missing from 'entities': {implicit}; added as type 'other'")
    yield GoldDocument(doc_id=card.name, text=txt.read_text(encoding="utf-8") if txt.exists() else "",
                       entities=ents, relations=rels, meta={"implicit_entities": implicit})
