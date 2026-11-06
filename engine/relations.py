"""Relationship extraction as a focused second pass over entities that are already extracted.

Why this exists (docs/evaluation.md, "Relationship extraction investigation"): inside docling-graph's dense contract
relations are either never filled (nested full-entity fields: 0 relations on 8 documents that state ownership outright)
or filled badly and 6-10x more expensively (per-target reference fields). Here the model sees the document chunk and
the KNOWN entity names and only decides which stated relations hold, so names resolve exactly and every relation
carries a verbatim evidence quote that is located in the text.

Opt-in: ER_RELATION_PASS=1 (see engine/api.py run_full). Stats go to manifest.json["relation_pass"].
"""
from __future__ import annotations

import json
import re
from typing import Literal, Optional

import litellm
from pydantic import BaseModel

from run import ALLOWED_RELATIONSHIPS, ENTITY_RELATIONSHIP_DIRECTION_RULES, Citation

Relation = Literal["controls", "participates_in", "represents", "transfers_to", "governs", "related_to"]


class _Rel(BaseModel):
    subject: str
    relation: Relation
    object: str
    evidence: str


class _Rels(BaseModel):
    relationships: list[_Rel]


SYSTEM = """You extract relationships between KNOWN entities from a document excerpt.

Report a relationship only when the text states it explicitly or it follows unambiguously from the sentence. Never guess from background knowledge.
Use subject and object names EXACTLY as written in the entity list. Both must come from the list.
evidence: copy, character for character, the shortest sentence or clause from the excerpt that states the relationship.

Relations (subject -> object):
- controls: a person/company owns, operates, manages, acquired, or is the parent of a person/company/asset. "X acquired Y", "Y, a subsidiary of X", "X, which owns Y" => X controls Y. A hospital/department/branch operated by an organisation is controlled by it.
- participates_in: a person/company is a party to an agreement.
- represents: a person/company acts for another person/company (agent, lawyer, officer acting on its behalf).
- transfers_to: an agreement/asset passes something to a person/company.
- governs: an agreement/asset governs a person/company/asset.
- related_to: use ONLY when the text clearly connects two entities and none of the above fits.

Return an empty list when the excerpt states no such relationship."""


def split_chunks(text: str, max_chars: int = 6000) -> list[str]:
    """Paragraph-aware chunks of at most ~max_chars (a single longer paragraph is kept whole)."""
    chunks, cur = [], ""
    for para in re.split(r"\n\s*\n|\n", text):
        if cur and len(cur) + len(para) + 1 > max_chars:
            chunks.append(cur)
            cur = ""
        cur = f"{cur}\n{para}" if cur else para
    if cur.strip():
        chunks.append(cur)
    return chunks


def _norm(s: str) -> str:
    return re.sub(r"[\W_]+", "", (s or "").casefold())


def _resolve(name: str, forms: dict[str, str]) -> Optional[str]:
    key = _norm(name)
    if key in forms:
        return forms[key]
    hits = {eid for form, eid in forms.items() if len(key) >= 4 and len(form) >= 4 and (key in form or form in key)}
    return hits.pop() if len(hits) == 1 else None


def _allowed(relation: str, src_type: str, tgt_type: str) -> bool:
    rule = ENTITY_RELATIONSHIP_DIRECTION_RULES.get(relation)
    if not rule:
        return False
    ok = lambda allowed, t: allowed == "any" or t in allowed  # noqa: E731
    return ok(rule["source"], src_type) and ok(rule["target"], tgt_type)


class _Index:
    """Letters/digits-only view of a text with a map back to original offsets, so evidence copied by the model still
    matches when the source has odd punctuation spacing (pre-tokenised corpora: 'vom 11 . 2 . 2015') or hyphenation."""

    def __init__(self, text: str):
        self.text = text
        self.pos = [i for i, ch in enumerate(text) if ch.isalnum()]
        self.norm = "".join(text[i].casefold() for i in self.pos)

    def locate(self, quote: str) -> Optional[tuple[int, int]]:
        quote = (quote or "").strip()
        if not quote:
            return None
        i = self.text.find(quote)
        if i >= 0:
            return i, i + len(quote)
        q = "".join(c.casefold() for c in quote if c.isalnum())
        if len(q) < 12:                      # too short to be a trustworthy match
            return None
        j = self.norm.find(q)
        return (self.pos[j], self.pos[j + len(q) - 1] + 1) if j >= 0 else None


def extract_relationships(text: str, entities: list[dict], file_id: str = "NA", model: str = "gpt-4o",
                          max_chars: int = 6000, require_evidence: bool = True) -> tuple[list[dict], dict]:
    """-> (relationships in output.json format, stats). `entities` are output.json entity dicts."""
    by_id = {e["entity_id"]: e for e in entities}
    stats = {"chunks": 0, "chunks_called": 0, "proposed": 0, "kept": 0, "unresolved": 0, "bad_direction": 0,
             "no_evidence": 0, "duplicate": 0, "errors": 0}
    out: dict[tuple, dict] = {}
    index = _Index(text)
    for ci, chunk in enumerate(split_chunks(text, max_chars)):
        stats["chunks"] += 1
        chunk_key = _norm(chunk)      # punctuation/spacing-insensitive: entity names and tokenised sources may spell dates and hyphens differently
        present = [e for e in entities if any(len(_norm(f)) >= 2 and _norm(f) in chunk_key for f in [e["canonical_name"], *e.get("aliases", [])])]
        if len(present) < 2:
            continue
        forms: dict[str, str] = {}
        for e in present:
            for f in [e["canonical_name"], *e.get("aliases", [])]:
                forms.setdefault(_norm(f), e["entity_id"])
        listing = "\n".join(f"- {e['canonical_name']} ({e['entity_type']})" +
                            (f" aka {', '.join(e['aliases'])}" if e.get("aliases") else "") for e in present)
        try:
            resp = litellm.completion(
                model=model, temperature=0, response_format=_Rels,
                messages=[{"role": "system", "content": SYSTEM},
                          {"role": "user", "content": f"ENTITIES:\n{listing}\n\nEXCERPT:\n{chunk}"}])
            recs = _Rels.model_validate_json(resp.choices[0].message.content).relationships
        except Exception:
            stats["errors"] += 1
            continue
        stats["chunks_called"] += 1
        for r in recs:
            stats["proposed"] += 1
            src, tgt = _resolve(r.subject, forms), _resolve(r.object, forms)
            if not src or not tgt or src == tgt:
                stats["unresolved"] += 1
                continue
            if r.relation not in ALLOWED_RELATIONSHIPS or not _allowed(r.relation, by_id[src]["entity_type"], by_id[tgt]["entity_type"]):
                stats["bad_direction"] += 1
                continue
            span = index.locate(r.evidence)
            if span is None and require_evidence:
                stats["no_evidence"] += 1
                continue
            key = (src, r.relation, tgt)
            if key in out:
                stats["duplicate"] += 1
                continue
            lo, hi = span if span else (0, 0)
            out[key] = {"source_entity_id": src, "target_entity_id": tgt, "relationship_type": r.relation,
                        "citation": Citation(file_id=file_id, chunk_id=ci, start_char=lo, end_char=hi,
                                             quote=text[lo:hi] if span else r.evidence,
                                             match="verbatim" if span else "unanchored").model_dump()}
    stats["kept"] = len(out)
    return list(out.values()), stats


def apply_to_run(run_dir, model: str = "gpt-4o") -> dict:
    """Run the pass on a converted run directory (output.json + document.txt); merges with existing edges, rewrites output.json."""
    from pathlib import Path
    run_dir = Path(run_dir)
    out_path = run_dir / "output.json"
    data = json.loads(out_path.read_text(encoding="utf-8"))
    doc = run_dir / "document.txt"
    if not doc.exists():
        return {"skipped": "no document.txt"}
    file_id = next((c["file_id"] for e in data["entities"] for c in e["citations"]), "NA")
    new, stats = extract_relationships(doc.read_text(encoding="utf-8"), data["entities"], file_id, model)
    seen = {(r["source_entity_id"], r["relationship_type"], r["target_entity_id"]) for r in data["relationships"]}
    data["relationships"] += [r for r in new if (r["source_entity_id"], r["relationship_type"], r["target_entity_id"]) not in seen]
    out_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    mf = run_dir / "manifest.json"
    if mf.exists():
        m = json.loads(mf.read_text(encoding="utf-8"))
        m["relation_pass"] = stats
        mf.write_text(json.dumps(m, indent=2, ensure_ascii=False), encoding="utf-8")
    return stats
