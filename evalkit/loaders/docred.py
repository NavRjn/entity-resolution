"""DocRED / Re-DocRED JSON: sents (tokens), vertexSet (entity = list of mentions), labels (h, t, r)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator

from ..schema import GoldDocument, GoldEntity, GoldRelation, Mention
from .base import Card, build_text, detok, register

PRONOUNS = {"he", "she", "it", "they", "his", "her", "its", "their", "him", "them", "who", "which", "this", "that", "i", "we"}


@register("docred")
def load_docred(path: Path, opt: dict, card: Card) -> Iterator[GoldDocument]:
    data = json.loads(path.read_text(encoding="utf-8"))
    for di, d in enumerate(data[: opt.get("max_docs")]):
        doc_id = f"{card.name}-{di:04d}"
        text, offs = build_text(d["sents"])
        ents: list[GoldEntity] = []
        keep: dict[int, str] = {}
        for vi, vertex in enumerate(d["vertexSet"]):
            typ = card.map_type(vertex[0]["type"])
            if typ is None:
                continue
            ments = []
            for m in vertex:
                a, b = m["pos"]
                s, e = offs[m["sent_id"]][a][0], offs[m["sent_id"]][b - 1][1]
                ments.append(Mention(text=text[s:e], start=s, end=e))
            names = [n for n in dict.fromkeys(detok(m.text) for m in ments) if n.casefold() not in PRONOUNS] or [detok(ments[0].text)]
            ent = GoldEntity(id=f"{doc_id}#v{vi}", name=names[0], type=typ, aliases=names[1:], mentions=ments)
            ents.append(ent)
            keep[vi] = ent.id
        rels = []
        for lab in d.get("labels", []):
            mapped = card.map_relation(lab["r"])
            if mapped is None or lab["h"] not in keep or lab["t"] not in keep:
                continue
            rtype, flip = mapped
            h, t = (lab["t"], lab["h"]) if flip else (lab["h"], lab["t"])
            rels.append(GoldRelation(source=keep[h], type=rtype, target=keep[t]))
        yield GoldDocument(doc_id=doc_id, text=text, entities=ents, relations=rels, meta={"title": d.get("title")})
