"""Fail-fast checks: can everything import, and is config/data well-formed?"""
import json

import pytest
import yaml

from conftest import REPO


def test_import_run():
    import run  # noqa: F401


def test_import_engine():
    import engine.api  # noqa: F401
    import engine.template  # noqa: F401


def test_import_api():
    import api.main  # noqa: F401


def test_config_yaml_valid():
    cfg = yaml.safe_load((REPO / "config.yaml").read_text(encoding="utf-8"))
    assert cfg["models"]["llm"]["remote"]["model"]
    assert cfg["models"]["llm"]["remote"]["provider"]


@pytest.mark.parametrize("path", sorted((REPO / "data").glob("*.gt.json")), ids=lambda p: p.name)
def test_ground_truth_parses(path):
    assert isinstance(json.loads(path.read_text(encoding="utf-8")), (dict, list))


@pytest.mark.parametrize("path", sorted((REPO / "data").glob("*.txt")), ids=lambda p: p.name)
def test_data_text_nonempty(path):
    assert path.read_text(encoding="utf-8").strip()


def test_ontology_constants_in_sync():
    """CLAUDE.md: engine/template.py duplicates run.py ontology; keep them identical."""
    import run
    from engine import template

    assert run.ALLOWED_ENTITIES == template.ALLOWED_ENTITIES
    assert run.ALLOWED_RELATIONSHIPS == template.ALLOWED_RELATIONSHIPS
    assert run.ENTITY_RELATIONSHIP_DIRECTION_RULES == template.ENTITY_RELATIONSHIP_DIRECTION_RULES
