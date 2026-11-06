"""Loader registry + helpers shared by all dataset formats.

A *loader* turns one raw source (file/dir) into an iterator of GoldDocument. It is configured only by a
plain dict (`options`) plus the dataset card's `type_map` / `relation_map`, so adding a dataset normally
needs a YAML card and no code; a new *format* needs one small function registered here.
"""
from __future__ import annotations

import re
from collections import OrderedDict
from pathlib import Path
from typing import Callable, Iterator

from ..normalize import norm_name, norm_rel, norm_type
from ..schema import Coverage, GoldDocument, GoldEntity, Mention

LoaderFn = Callable[[Path, dict, "Card"], Iterator[GoldDocument]]
LOADERS: dict[str, LoaderFn] = {}


def register(name: str):
    def deco(fn: LoaderFn) -> LoaderFn:
        LOADERS[name] = fn
        return fn
    return deco


class Card:
    """Parsed dataset card (see evalkit/cards/*.yaml)."""

    def __init__(self, raw: dict):
        self.raw = raw
        self.name: str = raw["name"]
        self.type_map: dict = {str(k).casefold(): v for k, v in (raw.get("type_map") or {}).items()}
        self.relation_map: dict = raw.get("relation_map") or {}
        self.options: dict = raw.get("options") or {}
        self.coverage = Coverage(
            exhaustive_entity_types=raw.get("exhaustive_entity_types"),
            exhaustive_relations=raw.get("exhaustive_relations", True),
            has_coref=raw.get("has_coref", True),
            has_types=raw.get("has_types", True),
        )

    def map_type(self, label: str) -> str | None:
        """Ontology type for a source label; None => drop this annotation (out of scope)."""
        key = str(label).casefold()
        if key in self.type_map:
            return self.type_map[key]            # may be None (explicit drop)
        return norm_type(label) if not self.type_map else None

    def map_relation(self, label: str) -> tuple[str, bool] | None:
        """(ontology relation, flip_direction) or None to drop."""
        if not self.relation_map:
            return norm_rel(label), False
        v = self.relation_map.get(label)
        if v is None:
            return None
        if isinstance(v, dict):
            return v["type"], bool(v.get("flip", False))
        return str(v), False


def group_mentions(mentions: list[tuple[str, str, int | None, int | None]], doc_id: str) -> list[GoldEntity]:
    """Group (text, type, start, end) mentions into entities by identical normalised text + type.

    For datasets that annotate mentions without coreference (NER corpora). The result is a distinct-name
    entity set, which is what canonicalisation should output when no aliases are labelled.
    """
    groups: "OrderedDict[tuple[str, str], GoldEntity]" = OrderedDict()
    for text, typ, s, e in mentions:
        key = (norm_name(text), typ)
        if not key[0]:
            continue
        ent = groups.get(key)
        if ent is None:
            ent = groups[key] = GoldEntity(id=f"{doc_id}#e{len(groups)}", name=text, type=typ)
        ent.mentions.append(Mention(text=text, start=s, end=e))
    return list(groups.values())


def build_text(sentences: list[list[str]]) -> tuple[str, list[list[tuple[int, int]]]]:
    """Join tokens with single spaces and sentences with newlines; return per-token char offsets."""
    parts: list[str] = []
    offsets: list[list[tuple[int, int]]] = []
    pos = 0
    for sent in sentences:
        row = []
        for i, tok in enumerate(sent):
            if i:
                parts.append(" ")
                pos += 1
            row.append((pos, pos + len(tok)))
            parts.append(tok)
            pos += len(tok)
        offsets.append(row)
        parts.append("\n")
        pos += 1
    return "".join(parts), offsets


def detok(text: str) -> str:
    """Undo tokenisation spacing around punctuation in names ('Inc .' -> 'Inc.')."""
    return re.sub(r"\s+([,.;:)])", r"\1", re.sub(r"([(])\s+", r"\1", text))


def load_dataset(card: Card, path: Path) -> Iterator[GoldDocument]:
    name = card.raw["loader"]
    if name not in LOADERS:
        raise KeyError(f"unknown loader {name!r}; known: {sorted(LOADERS)}")
    for doc in LOADERS[name](path, card.options, card):
        doc.coverage = card.coverage
        yield doc
