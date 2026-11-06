"""Ontology constants used by label-free checks.

Deliberately duplicated from run.py (importing run.py would fetch Langfuse prompts at import time).
tests/test_evalkit.py asserts these stay identical to run.py.
"""
ALLOWED_RELATIONSHIPS = {"controls", "participates_in", "represents", "transfers_to", "governs", "related_to"}

DIRECTION_RULES = {
    "controls": {"source": {"person", "company"}, "target": {"person", "company", "asset", "claim"}},
    "participates_in": {"source": {"person", "company"}, "target": {"agreement", "claim"}},
    "represents": {"source": {"person", "company"}, "target": {"person", "company"}},
    "transfers_to": {"source": {"asset", "claim", "agreement"}, "target": {"person", "company"}},
    "governs": {"source": {"agreement", "claim", "asset"}, "target": {"person", "company", "asset"}},
    "related_to": {"source": "any", "target": "any"},
}
