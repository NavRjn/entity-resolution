"""engine/template.py: the schema docling-graph extracts into (this is what the paid call is shaped by)."""
import typing

import pytest

from engine import template
from engine.template import Agreement, Asset, Company, OntologyDocument, OtherEntity, Person

ENTITY_MODELS = [Person, Company, Agreement, Asset, OtherEntity]
ALL_MODELS = ENTITY_MODELS + [OntologyDocument]


def _edge_fields(model):
    for name, f in model.model_fields.items():
        extra = f.json_schema_extra or {}
        if "edge_label" in extra:
            yield name, extra["edge_label"], f


def _target_types(field):
    """Flatten List[Union[A, B]] into the entity_type literals of A, B."""
    out = set()

    def walk(t):
        if isinstance(t, type) and hasattr(t, "model_fields") and "entity_type" in t.model_fields:
            out.add(t.model_fields["entity_type"].default)
        for a in typing.get_args(t):
            walk(a)

    walk(field.annotation)
    return out


def test_json_schema_builds():
    schema = OntologyDocument.model_json_schema()
    assert schema["properties"]["persons"]


def test_minimal_document_validates():
    doc = OntologyDocument(document_name="d", persons=[{"name": "A"}], companies=[{"name": "B"}])
    assert doc.persons[0].entity_type == "person"
    assert doc.companies[0].name == "B"


def test_empty_document_is_valid():
    assert OntologyDocument(document_name="d").persons == []


@pytest.mark.parametrize("model", ENTITY_MODELS, ids=lambda m: m.__name__)
def test_entity_edge_labels_are_allowed_relationships(model):
    for name, label, _ in _edge_fields(model):
        assert label in template.ALLOWED_RELATIONSHIPS, f"{model.__name__}.{name}: {label}"
        assert name == label, f"{model.__name__}.{name} should be named after its edge label"


@pytest.mark.parametrize("model", ENTITY_MODELS, ids=lambda m: m.__name__)
def test_entity_type_literal_is_allowed(model):
    assert model.model_fields["entity_type"].default in template.ALLOWED_ENTITIES


@pytest.mark.parametrize("model", ENTITY_MODELS, ids=lambda m: m.__name__)
def test_edges_respect_direction_rules(model):
    """Every field's source/target entity types must be permitted by ENTITY_RELATIONSHIP_DIRECTION_RULES."""
    src = model.model_fields["entity_type"].default
    for name, label, f in _edge_fields(model):
        rule = template.ENTITY_RELATIONSHIP_DIRECTION_RULES[label]
        if rule["source"] != "any":
            assert src in rule["source"], f"{model.__name__}.{name}: {src} cannot be source of {label}"
        if rule["target"] != "any":
            bad = _target_types(f) - rule["target"]
            assert not bad, f"{model.__name__}.{name}: targets {bad} not allowed for {label}"


@pytest.mark.parametrize(
    "model",
    ALL_MODELS,
    ids=lambda m: m.__name__,
)
def test_graph_id_fields_exist(model):
    ids = model.model_config.get("graph_id_fields", [])
    assert ids and set(ids) <= set(model.model_fields), f"{model.__name__}: {ids}"
