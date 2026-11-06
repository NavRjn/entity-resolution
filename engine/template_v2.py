"""
Ontology template V2: relations as first-class extracted records.

Entities carry only their identity. Relationships are a root list of (subject, relation, object, evidence) records with a verbatim evidence passage; engine/api.py turns them into relationships, resolving subject/object by name.

Generated shape; see docs/evaluation.md ("Relationship extraction investigation").
"""
from __future__ import annotations
from typing import Any, List, Literal
from pydantic import BaseModel, ConfigDict, Field

ALLOWED_ENTITIES = {"person", "company", "agreement", "asset", "other"}
ALLOWED_RELATIONSHIPS = {"controls", "participates_in", "represents", "transfers_to", "governs", "related_to"}


def edge(label: str, *, reference: bool = False, **kwargs: Any) -> Any:
    """Field with graph edge metadata. reference=True marks an identity-only link (docling-graph `graph_reference`):
    the PARENT's own fill call emits the target's name and graph assembly resolves it onto the canonical node."""
    extra = dict(kwargs.pop("json_schema_extra", {}) or {})
    extra["edge_label"] = label
    if reference:
        extra["graph_reference"] = True
    return Field(default_factory=kwargs.pop("default_factory", list), json_schema_extra=extra, **kwargs)


class Person(BaseModel):
    """A natural person mentioned in the source documents."""
    model_config = ConfigDict(graph_id_fields=["name"])
    entity_type: Literal["person"] = "person"
    name: str = Field(description="Full name of the person")


class Company(BaseModel):
    """A company or legal organization."""
    model_config = ConfigDict(graph_id_fields=["name"])
    entity_type: Literal["company"] = "company"
    name: str = Field(description="Legal or commonly used company name")


class Agreement(BaseModel):
    """A contract, agreement, or other legally relevant arrangement."""
    model_config = ConfigDict(graph_id_fields=["name"])
    entity_type: Literal["agreement"] = "agreement"
    name: str = Field(description="Agreement name or identifier")


class Asset(BaseModel):
    """An asset, property, right, or other identifiable resource."""
    model_config = ConfigDict(graph_id_fields=["name"])
    entity_type: Literal["asset"] = "asset"
    name: str = Field(description="Asset name or identifier")


class OtherEntity(BaseModel):
    """An entity that does not fit the other defined entity categories."""
    model_config = ConfigDict(graph_id_fields=["name"])
    entity_type: Literal["other"] = "other"
    name: str = Field(description="Name or identifier of the entity")


class Relationship(BaseModel):
    """A relationship between two entities that the document states explicitly."""
    model_config = ConfigDict(graph_id_fields=["subject", "relation", "object"])
    subject: str = Field(description="Exact name of the source entity, as listed in persons/companies/agreements/assets/others")
    relation: Literal["controls", "participates_in", "represents", "transfers_to", "governs", "related_to"] = Field(
        description=("controls: a person/company owns, operates, manages or is the parent of a person/company/asset. "
                     "participates_in: a person/company is a party to an agreement. "
                     "represents: a person/company acts for another person/company. "
                     "transfers_to: an agreement/asset passes to a person/company. "
                     "governs: an agreement/asset governs a person/company/asset. "
                     "related_to: only when none of the above fits."))
    object: str = Field(description="Exact name of the target entity, as listed in persons/companies/agreements/assets/others")
    evidence: str = Field(description="The sentence or passage from the document, copied verbatim, that states this relationship")


for _m in (Person, Company, Agreement, Asset, OtherEntity, Relationship):
    _m.model_rebuild()


class OntologyDocument(BaseModel):
    """Root extraction model: all entities and the relationships stated between them."""

    model_config = ConfigDict(graph_id_fields=["document_name"], extra="ignore", populate_by_name=True)

    document_name: str = Field(description="Document title or identifiable document reference")

    persons: List[Person] = edge("MENTIONS_PERSON", description="Unique people identified in the document")
    companies: List[Company] = edge("MENTIONS_COMPANY", description="Unique companies identified in the document")
    agreements: List[Agreement] = edge("CONTAINS_AGREEMENT", description="Agreements identified in the document")
    assets: List[Asset] = edge("MENTIONS_ASSET", description="Assets identified in the document")
    others: List[OtherEntity] = edge("MENTIONS_OTHER_ENTITY", description="Other entities mentioned in the document")
    relationships: List[Relationship] = edge(
        "HAS_RELATIONSHIP", description="Relationships between the entities above that the document states explicitly")
