"""Recall pass: a focused second look for named entities the extraction missed.

Measured gap (docs/evaluation.md): entity recall is 30-46% while precision is 80%+; misses are mostly short names and
repeated mentions. Here one cheap call per chunk sees the chunk and the names ALREADY found and lists only additional
named people/organisations. Every proposal must (a) occur verbatim in the chunk, (b) not duplicate a known entity,
and (c) carry an evidence quote located in the text; otherwise it is dropped and counted in manifest["recall_pass"].
Free post-processing (engine/aliases.py) then merges variants.
"""
from __future__ import annotations

import hashlib
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Literal

import litellm
from pydantic import BaseModel

from run import Citation

from .aliases import key, resolve
from .relations import _Index, _norm, split_chunks

Kind = Literal["person", "company", "agreement", "asset", "other"]


class _Found(BaseModel):
    name: str
    type: Kind
    quote: str


class _Missed(BaseModel):
    entities: list[_Found]


SYSTEM = """You review an entity extraction of a legal or business document excerpt and add what it MISSED.

You get the excerpt and the entities already found. List additional specific, named entities that the excerpt mentions:
- person: a named individual (including a surname alone or initials that clearly denote one person).
- company: a named organisation of any kind: company, bank, insurer, law firm, court, authority, agency, fund, club, university. Short names and abbreviations count ("SEC", "TMMK") when they name a specific organisation.
- agreement: a named or titled contract, policy, decision or document ("Credit Agreement", "Policy No. 123").
- asset / other: a named property, product, or other specific named thing the document is about.

Rules: do NOT repeat or re-spell entities already found (a shorter or longer form of a found entity is a duplicate). Do NOT list generic terms ("the Company", "the Buyer"), pronouns, roles without a name, dates, amounts, statute or section references, or places. Use the name EXACTLY as written in the excerpt. quote: copy, character for character, the shortest sentence or clause of the excerpt containing the name.
Return an empty list when nothing was missed."""


def _known_keys(entities: list[dict]) -> set[str]:
    return {key(f) for e in entities for f in [e["canonical_name"], *e.get("aliases", [])]}


def extract_missed(text: str, entities: list[dict], file_id: str = "NA", model: str = "gpt-4o", max_chars: int = 6000,
                   workers: int = 4) -> tuple[list[dict], dict]:
    stats = {"chunks": 0, "chunks_called": 0, "proposed": 0, "kept": 0, "duplicate": 0, "not_in_text": 0,
             "no_evidence": 0, "errors": 0}
    known = _known_keys(entities)
    index = _Index(text)
    jobs = []
    for ci, chunk in enumerate(split_chunks(text, max_chars)):
        stats["chunks"] += 1
        ck = _norm(chunk)
        present = [e for e in entities if _norm(e["canonical_name"]) and _norm(e["canonical_name"]) in ck]
        listing = "\n".join(f"- {e['canonical_name']} ({e['entity_type']})" for e in present) or "(none)"
        jobs.append((ci, chunk, f"ALREADY FOUND:\n{listing}\n\nEXCERPT:\n{chunk}"))

    def call(prompt: str):
        try:
            resp = litellm.completion(model=model, temperature=0, response_format=_Missed,
                                      messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}])
            return _Missed.model_validate_json(resp.choices[0].message.content).entities
        except Exception:
            return None

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        results = list(pool.map(lambda j: call(j[2]), jobs))
    out: dict[str, dict] = {}
    for (ci, chunk, _), found in zip(jobs, results):
        if found is None:
            stats["errors"] += 1
            continue
        stats["chunks_called"] += 1
        ck = _norm(chunk)
        for f in found:
            stats["proposed"] += 1
            name = f.name.strip()
            if len(_norm(name)) < 2 or _norm(name) not in ck:
                stats["not_in_text"] += 1
                continue
            if key(name) in known or key(name) in out:
                stats["duplicate"] += 1
                continue
            span = index.locate(f.quote)
            if span is None:
                stats["no_evidence"] += 1
                continue
            lo, hi = span
            cits = [Citation(file_id=file_id, chunk_id=ci, start_char=lo, end_char=hi, quote=text[lo:hi],
                             match="verbatim").model_dump()]
            for m in list(re.finditer(re.escape(name), text))[:3]:      # further located mentions of the same name
                if not (lo <= m.start() < hi):
                    cits.append(Citation(file_id=file_id, chunk_id=ci, start_char=m.start(), end_char=m.end(),
                                         quote=m.group(0), match="name_search").model_dump())
            out[key(name)] = {"entity_id": "Recall_" + hashlib.md5(name.encode()).hexdigest()[:12], "canonical_name": name,
                              "entity_type": f.type, "aliases": [], "citations": cits}
    stats["kept"] = len(out)
    return list(out.values()), stats


def apply_to_run(run_dir, model: str = "gpt-4o") -> dict:
    """Add missed entities to a converted run directory, then merge variants (free) and rewrite output.json."""
    run_dir = Path(run_dir)
    out_path, doc = run_dir / "output.json", run_dir / "document.txt"
    if not doc.exists() or not out_path.exists():
        return {"skipped": "no document.txt or output.json"}
    data = json.loads(out_path.read_text(encoding="utf-8"))
    text = doc.read_text(encoding="utf-8")
    file_id = next((c["file_id"] for e in data["entities"] for c in e["citations"]), "NA")
    new, stats = extract_missed(text, data["entities"], file_id, model)
    data["entities"] += new
    stats["merge"] = resolve(data, text)
    out_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    mf = run_dir / "manifest.json"
    if mf.exists():
        m = json.loads(mf.read_text(encoding="utf-8"))
        m["recall_pass"] = stats
        mf.write_text(json.dumps(m, indent=2, ensure_ascii=False), encoding="utf-8")
    return stats
