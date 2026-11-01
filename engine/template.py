
"""
Ontology extraction template for Docling Graph.

Extracts people, companies, agreements, assets, and other entities,
together with their permitted relationships.

The schema is designed for conversion into a knowledge graph.
"""

# --- 1. Required Imports ---
from __future__ import annotations
from typing import Any, List, Union, Literal
from pydantic import BaseModel, ConfigDict, Field


# --- 2. Ontology Definitions ---
ALLOWED_ENTITIES = {
    "person",
    "company",
    "agreement",
    "asset",
    "other",
}

ALLOWED_RELATIONSHIPS = {
    "controls",
    "participates_in",
    "represents",
    "transfers_to",
    "governs",
    "related_to",
}

ENTITY_RELATIONSHIP_DIRECTION_RULES = {
    "controls": {
        "source": {"person", "company"},
        "target": {"person", "company", "asset", "claim"},
    },
    "participates_in": {
        "source": {"person", "company"},
        "target": {"agreement", "claim"},
    },
    "represents": {
        "source": {"person", "company"},
        "target": {"person", "company"},
    },
    "transfers_to": {
        "source": {"asset", "claim", "agreement"},
        "target": {"person", "company"},
    },
    "governs": {
        "source": {"agreement", "claim", "asset"},
        "target": {"person", "company", "asset"},
    },
    "related_to": {
        "source": "any",
        "target": "any",
    },
}


# --- 3. Edge Helper Function (REQUIRED) ---
def edge(label: str, **kwargs: Any) -> Any:
    """
    Helper function to create a Pydantic Field with edge metadata.
    The edge_label defines the relationship type in the knowledge graph.
    """
    return Field(..., json_schema_extra={"edge_label": label}, **kwargs,)


# --- 4. Reusable Entities ---
class Person(BaseModel):
    """A natural person mentioned in the source documents."""

    model_config = ConfigDict(graph_id_fields=["name"])

    entity_type: Literal["person"] = "person"
    name: str = Field(description="Full name of the person")

    controls: List[Union[Person, Company, Asset]] = edge(
        label="controls",
        default_factory=list,
        description="Companies, people, or assets controlled by this person",
    )

    participates_in: List[Agreement] = edge(
        label="participates_in",
        default_factory=list,
        description="Agreements in which this person participates",
    )

    represents: List[Union[Person, Company]] = edge(
        label="represents",
        default_factory=list,
        description="People or companies represented by this person",
    )

    related_to: List[Union[Person, Company, Agreement, Asset, OtherEntity]] = edge(
        label="related_to",
        default_factory=list,
        description="Other entities related to this person",
    )


class Company(BaseModel):
    """A company or legal organization."""

    model_config = ConfigDict(graph_id_fields=["name"])

    entity_type: Literal["company"] = "company"
    name: str = Field(description="Legal or commonly used company name")

    controls: List[Union[Person, Company, Asset]] = edge(
        label="controls",
        default_factory=list,
        description="People, companies, or assets controlled by this company",
    )

    participates_in: List[Agreement] = edge(
        label="participates_in",
        default_factory=list,
        description="Agreements in which this company participates",
    )

    represents: List[Union[Person, Company]] = edge(
        label="represents",
        default_factory=list,
        description="People or companies represented by this company",
    )

    related_to: List[Union[Person, Company, Agreement, Asset, OtherEntity]] = edge(
        label="related_to",
        default_factory=list,
        description="Other entities related to this company",
    )


class Agreement(BaseModel):
    """A contract, agreement, or other legally relevant arrangement."""

    model_config = ConfigDict(graph_id_fields=["name"])

    entity_type: Literal["agreement"] = "agreement"
    name: str = Field(description="Agreement name or identifier")

    transfers_to: List[Union[Person, Company]] = edge(
        label="transfers_to",
        default_factory=list,
        description="People or companies receiving transfers under this agreement",
    )

    governs: List[Union[Person, Company, Asset]] = edge(
        label="governs",
        default_factory=list,
        description="People, companies, or assets governed by this agreement",
    )

    related_to: List[Union[Person, Company, Agreement, Asset, OtherEntity]] = edge(
        label="related_to",
        default_factory=list,
        description="Other entities related to this agreement",
    )


class Asset(BaseModel):
    """An asset, property, right, or other identifiable resource."""

    model_config = ConfigDict(graph_id_fields=["name"])

    entity_type: Literal["asset"] = "asset"
    name: str = Field(description="Asset name or identifier")

    transfers_to: List[Union[Person, Company]] = edge(
        label="transfers_to",
        default_factory=list,
        description="People or companies receiving this asset",
    )

    governs: List[Union[Person, Company, Asset]] = edge(
        label="governs",
        default_factory=list,
        description="People, companies, or assets governed by this asset",
    )

    related_to: List[Union[Person, Company, Agreement, Asset, OtherEntity]] = edge(
        label="related_to",
        default_factory=list,
        description="Other entities related to this asset",
    )


class OtherEntity(BaseModel):
    """An entity that does not fit the other defined entity categories."""

    model_config = ConfigDict(graph_id_fields=["name"])

    entity_type: Literal["other"] = "other"
    name: str = Field(description="Name or identifier of the entity")

    related_to: List[Union[Person, Company, Agreement, Asset, OtherEntity]] = edge(
        label="related_to",
        default_factory=list,
        explanation=Field(description="Explain how they are related."),
        description="Other entities related to this entity",
    )


# --- 5. Entity Union ---

Entity = Union[
    Person,
    Company,
    Agreement,
    Asset,
    OtherEntity,
]


# --- 6. Resolve Forward References ---

for model in (Person, Company, Agreement, Asset, OtherEntity):
    model.model_rebuild()


# --- 7. Root Document Model ---

class OntologyDocument(BaseModel):
    """
    Root extraction model.

    Contains all entities identified in the source document.
    """

    model_config = ConfigDict(graph_id_fields=["reference_document"], extra="ignore", populate_by_name=True)

    document_name: str = Field(
        description="Document title or identifiable document reference"
    )

    persons: List[Person] = edge(
        "MENTIONS_PERSON",
        default_factory=list,
        description="Unique people identified in the document",
    )

    companies: List[Company] = edge(
        "MENTIONS_COMPANY",
        default_factory=list,
        description="Unique Companies identified in the document",
    )

    agreements: List[Agreement] = edge(
        "CONTAINS_AGREEMENT",
        default_factory=list,
        description="Agreements identified in the document",
    )

    assets: List[Asset] = edge(
        "MENTIONS_ASSET",
        default_factory=list,
        description="Assets identified in the document",
    )

    others: List[OtherEntity] = edge(
        "MENTIONS_OTHER_ENTITY",
        default_factory=list,
        description="Other misc. or unidentified Entities mentioned in the document",
    )
