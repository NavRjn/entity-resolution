"""
Ontology template V1: per-target reference edges.

Each relation is split into one field per target class and declared reference=True, so the parent's fill call lists the related entities' names and docling-graph resolves them onto the canonical node of the right class. (A Union-typed reference would resolve to the Union's first class: node ids embed the class name.)

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

    controls_persons: List[Person] = edge("controls", reference=True, description="Persons controlled by this person (owned, operated, managed or parent-of). Exact names as written in the document; leave empty unless the text states it.")
    controls_companies: List[Company] = edge("controls", reference=True, description="Companies controlled by this person (owned, operated, managed or parent-of). Exact names as written in the document; leave empty unless the text states it.")
    controls_assets: List[Asset] = edge("controls", reference=True, description="Assets controlled by this person (owned, operated, managed or parent-of). Exact names as written in the document; leave empty unless the text states it.")
    participates_in: List[Agreement] = edge("participates_in", reference=True, description="Agreements in which this person is a party or participant. Exact names as written in the document; leave empty unless the text states it.")
    represents_persons: List[Person] = edge("represents", reference=True, description="Persons represented by this person (agent, attorney, officer acting for them). Exact names as written in the document; leave empty unless the text states it.")
    represents_companies: List[Company] = edge("represents", reference=True, description="Companies represented by this person (agent, attorney, officer acting for them). Exact names as written in the document; leave empty unless the text states it.")
    related_to_persons: List[Person] = edge("related_to", reference=True, description="Persons otherwise related to this person (only when no more specific relation fits). Exact names as written in the document; leave empty unless the text states it.")
    related_to_companies: List[Company] = edge("related_to", reference=True, description="Companies otherwise related to this person (only when no more specific relation fits). Exact names as written in the document; leave empty unless the text states it.")
    related_to_agreements: List[Agreement] = edge("related_to", reference=True, description="Agreements otherwise related to this person (only when no more specific relation fits). Exact names as written in the document; leave empty unless the text states it.")
    related_to_assets: List[Asset] = edge("related_to", reference=True, description="Assets otherwise related to this person (only when no more specific relation fits). Exact names as written in the document; leave empty unless the text states it.")
    related_to_others: List[OtherEntity] = edge("related_to", reference=True, description="Others otherwise related to this person (only when no more specific relation fits). Exact names as written in the document; leave empty unless the text states it.")


class Company(BaseModel):
    """A company or legal organization."""

    model_config = ConfigDict(graph_id_fields=["name"])

    entity_type: Literal["company"] = "company"
    name: str = Field(description="Legal or commonly used company name")

    controls_persons: List[Person] = edge("controls", reference=True, description="Persons controlled by this company (owned, operated, managed or parent-of). Exact names as written in the document; leave empty unless the text states it.")
    controls_companies: List[Company] = edge("controls", reference=True, description="Companies controlled by this company (owned, operated, managed or parent-of). Exact names as written in the document; leave empty unless the text states it.")
    controls_assets: List[Asset] = edge("controls", reference=True, description="Assets controlled by this company (owned, operated, managed or parent-of). Exact names as written in the document; leave empty unless the text states it.")
    participates_in: List[Agreement] = edge("participates_in", reference=True, description="Agreements in which this company is a party or participant. Exact names as written in the document; leave empty unless the text states it.")
    represents_persons: List[Person] = edge("represents", reference=True, description="Persons represented by this company (agent, attorney, officer acting for them). Exact names as written in the document; leave empty unless the text states it.")
    represents_companies: List[Company] = edge("represents", reference=True, description="Companies represented by this company (agent, attorney, officer acting for them). Exact names as written in the document; leave empty unless the text states it.")
    related_to_persons: List[Person] = edge("related_to", reference=True, description="Persons otherwise related to this company (only when no more specific relation fits). Exact names as written in the document; leave empty unless the text states it.")
    related_to_companies: List[Company] = edge("related_to", reference=True, description="Companies otherwise related to this company (only when no more specific relation fits). Exact names as written in the document; leave empty unless the text states it.")
    related_to_agreements: List[Agreement] = edge("related_to", reference=True, description="Agreements otherwise related to this company (only when no more specific relation fits). Exact names as written in the document; leave empty unless the text states it.")
    related_to_assets: List[Asset] = edge("related_to", reference=True, description="Assets otherwise related to this company (only when no more specific relation fits). Exact names as written in the document; leave empty unless the text states it.")
    related_to_others: List[OtherEntity] = edge("related_to", reference=True, description="Others otherwise related to this company (only when no more specific relation fits). Exact names as written in the document; leave empty unless the text states it.")


class Agreement(BaseModel):
    """A contract, agreement, or other legally relevant arrangement."""

    model_config = ConfigDict(graph_id_fields=["name"])

    entity_type: Literal["agreement"] = "agreement"
    name: str = Field(description="Agreement name or identifier")

    transfers_to_persons: List[Person] = edge("transfers_to", reference=True, description="Persons receiving transfers (payments, rights, assets) under this agreement. Exact names as written in the document; leave empty unless the text states it.")
    transfers_to_companies: List[Company] = edge("transfers_to", reference=True, description="Companies receiving transfers (payments, rights, assets) under this agreement. Exact names as written in the document; leave empty unless the text states it.")
    governs_persons: List[Person] = edge("governs", reference=True, description="Persons governed by this agreement. Exact names as written in the document; leave empty unless the text states it.")
    governs_companies: List[Company] = edge("governs", reference=True, description="Companies governed by this agreement. Exact names as written in the document; leave empty unless the text states it.")
    governs_assets: List[Asset] = edge("governs", reference=True, description="Assets governed by this agreement. Exact names as written in the document; leave empty unless the text states it.")
    related_to_persons: List[Person] = edge("related_to", reference=True, description="Persons otherwise related to this agreement (only when no more specific relation fits). Exact names as written in the document; leave empty unless the text states it.")
    related_to_companies: List[Company] = edge("related_to", reference=True, description="Companies otherwise related to this agreement (only when no more specific relation fits). Exact names as written in the document; leave empty unless the text states it.")
    related_to_agreements: List[Agreement] = edge("related_to", reference=True, description="Agreements otherwise related to this agreement (only when no more specific relation fits). Exact names as written in the document; leave empty unless the text states it.")
    related_to_assets: List[Asset] = edge("related_to", reference=True, description="Assets otherwise related to this agreement (only when no more specific relation fits). Exact names as written in the document; leave empty unless the text states it.")
    related_to_others: List[OtherEntity] = edge("related_to", reference=True, description="Others otherwise related to this agreement (only when no more specific relation fits). Exact names as written in the document; leave empty unless the text states it.")


class Asset(BaseModel):
    """An asset, property, right, or other identifiable resource."""

    model_config = ConfigDict(graph_id_fields=["name"])

    entity_type: Literal["asset"] = "asset"
    name: str = Field(description="Asset name or identifier")

    transfers_to_persons: List[Person] = edge("transfers_to", reference=True, description="Persons receiving transfers (payments, rights, assets) under this asset. Exact names as written in the document; leave empty unless the text states it.")
    transfers_to_companies: List[Company] = edge("transfers_to", reference=True, description="Companies receiving transfers (payments, rights, assets) under this asset. Exact names as written in the document; leave empty unless the text states it.")
    governs_persons: List[Person] = edge("governs", reference=True, description="Persons governed by this asset. Exact names as written in the document; leave empty unless the text states it.")
    governs_companies: List[Company] = edge("governs", reference=True, description="Companies governed by this asset. Exact names as written in the document; leave empty unless the text states it.")
    governs_assets: List[Asset] = edge("governs", reference=True, description="Assets governed by this asset. Exact names as written in the document; leave empty unless the text states it.")
    related_to_persons: List[Person] = edge("related_to", reference=True, description="Persons otherwise related to this asset (only when no more specific relation fits). Exact names as written in the document; leave empty unless the text states it.")
    related_to_companies: List[Company] = edge("related_to", reference=True, description="Companies otherwise related to this asset (only when no more specific relation fits). Exact names as written in the document; leave empty unless the text states it.")
    related_to_agreements: List[Agreement] = edge("related_to", reference=True, description="Agreements otherwise related to this asset (only when no more specific relation fits). Exact names as written in the document; leave empty unless the text states it.")
    related_to_assets: List[Asset] = edge("related_to", reference=True, description="Assets otherwise related to this asset (only when no more specific relation fits). Exact names as written in the document; leave empty unless the text states it.")
    related_to_others: List[OtherEntity] = edge("related_to", reference=True, description="Others otherwise related to this asset (only when no more specific relation fits). Exact names as written in the document; leave empty unless the text states it.")


class OtherEntity(BaseModel):
    """An entity that does not fit the other defined entity categories."""

    model_config = ConfigDict(graph_id_fields=["name"])

    entity_type: Literal["other"] = "other"
    name: str = Field(description="Name or identifier of the entity")

    related_to_persons: List[Person] = edge("related_to", reference=True, description="Persons otherwise related to this other (only when no more specific relation fits). Exact names as written in the document; leave empty unless the text states it.")
    related_to_companies: List[Company] = edge("related_to", reference=True, description="Companies otherwise related to this other (only when no more specific relation fits). Exact names as written in the document; leave empty unless the text states it.")
    related_to_agreements: List[Agreement] = edge("related_to", reference=True, description="Agreements otherwise related to this other (only when no more specific relation fits). Exact names as written in the document; leave empty unless the text states it.")
    related_to_assets: List[Asset] = edge("related_to", reference=True, description="Assets otherwise related to this other (only when no more specific relation fits). Exact names as written in the document; leave empty unless the text states it.")
    related_to_others: List[OtherEntity] = edge("related_to", reference=True, description="Others otherwise related to this other (only when no more specific relation fits). Exact names as written in the document; leave empty unless the text states it.")



for _m in (Person, Company, Agreement, Asset, OtherEntity):
    _m.model_rebuild()


class OntologyDocument(BaseModel):
    """Root extraction model: all entities identified in the source document."""

    model_config = ConfigDict(graph_id_fields=["document_name"], extra="ignore", populate_by_name=True)

    document_name: str = Field(description="Document title or identifiable document reference")

    persons: List[Person] = edge("MENTIONS_PERSON", description="Unique people identified in the document")
    companies: List[Company] = edge("MENTIONS_COMPANY", description="Unique companies identified in the document")
    agreements: List[Agreement] = edge("CONTAINS_AGREEMENT", description="Agreements identified in the document")
    assets: List[Asset] = edge("MENTIONS_ASSET", description="Assets identified in the document")
    others: List[OtherEntity] = edge("MENTIONS_OTHER_ENTITY", description="Other entities mentioned in the document")
