"""Every API call the frontend makes must hit a route (and method) that FastAPI actually serves."""
import re

import pytest
from starlette.routing import Match

from conftest import REPO

FRONTEND_SRC = REPO / "frontend" / "src"
FETCH_RE = re.compile(r"""fetch\(\s*([`"'])(?:http://localhost:8000)?(/api[^`"']*)\1""")
METHOD_RE = re.compile(r"""method:\s*["'](\w+)["']""")

# (method, path) pairs known to be broken; each is listed in docs/tests/known-issues.md
KNOWN_BROKEN = set()


def _frontend_calls():
    calls = []
    for f in sorted(FRONTEND_SRC.rglob("*.jsx")):
        text = f.read_text(encoding="utf-8")
        for m in FETCH_RE.finditer(text):
            nxt = text.find("fetch(", m.end())
            window = text[m.end(): nxt if nxt != -1 else m.end() + 300]
            method = (METHOD_RE.search(window[:300]) or [None, "GET"])[1].upper()
            path = re.sub(r"\$\{[^}]*\}", "x", m.group(2)).split("?")[0]
            calls.append((f.name, method, path))
    return sorted(set(calls))


CALLS = _frontend_calls()


def test_frontend_calls_were_found():
    """Guards the regex itself: if the frontend fetch style changes, this fails instead of silently testing nothing."""
    assert len(CALLS) >= 8, CALLS


@pytest.mark.parametrize(
    "file,method,path",
    [
        pytest.param(f, m, p, marks=pytest.mark.xfail(strict=True, reason="no such route; see known-issues"))
        if (m, p) in KNOWN_BROKEN else (f, m, p)
        for f, m, p in CALLS
    ],
    ids=lambda v: str(v),
)
def test_frontend_call_has_matching_route(file, method, path):
    import api.main

    scope = {"type": "http", "path": path, "method": method}
    results = [route.matches(scope)[0] for route in api.main.app.routes]
    assert Match.FULL in results, f"{file}: {method} {path} has no matching FastAPI route"
