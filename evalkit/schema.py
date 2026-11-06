"""Canonical data model. Every dataset loader produces GoldDocument; every pipeline output becomes Prediction."""
from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field


class Mention(BaseModel):
    text: str
    start: Optional[int] = None  # char offsets into GoldDocument.text, when the source has them
    end: Optional[int] = None


class GoldEntity(BaseModel):
    id: str
    name: str                         # canonical surface form
    type: str = "other"               # ontology type after loader mapping
    aliases: list[str] = Field(default_factory=list)   # other surface forms of the SAME entity
    mentions: list[Mention] = Field(default_factory=list)

    def surface_forms(self) -> list[str]:
        seen, out = set(), []
        for s in [self.name, *self.aliases, *(m.text for m in self.mentions)]:
            if s and s not in seen:
                seen.add(s)
                out.append(s)
        return out


class GoldRelation(BaseModel):
    source: str       # GoldEntity.id
    type: str
    target: str       # GoldEntity.id
    evidence: Optional[str] = None


class Coverage(BaseModel):
    """What the annotators labelled. Precision is only meaningful on exhaustively labelled types."""
    exhaustive_entity_types: Optional[list[str]] = None   # None => all types exhaustive
    exhaustive_relations: bool = True
    has_coref: bool = True       # False => aliases/clusters are heuristic (grouped by identical surface text)
    has_types: bool = True       # False => type-agnostic matching only


class GoldDocument(BaseModel):
    doc_id: str
    text: str = ""                   # reconstructed plain text the pipeline will read
    entities: list[GoldEntity] = Field(default_factory=list)
    relations: list[GoldRelation] = Field(default_factory=list)
    coverage: Coverage = Field(default_factory=Coverage)
    meta: dict = Field(default_factory=dict)


class PredEntity(BaseModel):
    id: str
    name: str
    type: str = "other"
    aliases: list[str] = Field(default_factory=list)
    quotes: list[str] = Field(default_factory=list)       # citation quotes
    spans: list[tuple[int, int]] = Field(default_factory=list)  # citation offsets (0,0 placeholders dropped)


class PredRelation(BaseModel):
    source: str       # PredEntity.id
    type: str
    target: str
    quote: str = ""


class Prediction(BaseModel):
    doc_id: str
    entities: list[PredEntity] = Field(default_factory=list)
    relations: list[PredRelation] = Field(default_factory=list)
    ops: dict = Field(default_factory=dict)   # latency_s, tokens, cost_usd, ... when known
