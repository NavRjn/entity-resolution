"""Free (no LLM) alias resolution on a converted run: defined terms and legal-form-insensitive merging.

Legal text defines its own aliases: `Aurora Holdings GmbH (nachfolgend "Aurora")`, `Acme Inc. (hereinafter the
"Company")`, `New Name AG (vormals Old Name GmbH)`. This pass reads those patterns from the document text, attaches
the alias to the entity it defines (never inventing entities), merges duplicates that differ only by legal form
("ABC GmbH" / "ABC"), and merges the same name extracted under two types. Stats go to manifest.json["alias_pass"].
"""
from __future__ import annotations

import json
import re
from pathlib import Path

LEGAL_FORM_TOKENS = {"gmbh", "ag", "kg", "ug", "ohg", "gbr", "se", "mbh", "ev", "inc", "incorporated", "llc", "ltd",
                     "limited", "plc", "corp", "corporation", "co", "company", "sa", "nv", "bv", "lp", "llp"}
ARTICLES = {"the", "der", "die", "das"}
Q = "\"'“”„‚‘’«»"
CAP = r"(?:[A-ZÄÖÜ][\w&.\-']*|&|of|und|and|de|für|\d+)"
LONG_TAIL = re.compile(rf"({CAP}(?:[ \t]+{CAP})*)[ \t]*,?[ \t]*$")
DEFINED = re.compile(
    rf"\(\s*(?:(?:hereinafter|nachfolgend|im\s+folgenden|im\s+nachfolgenden|together)(?:\s+(?:auch|also))?\s*)?"
    rf"(?:(?:the|der|die|das)\s+)?(?:(?:referred\s+to\s+as|genannt|bezeichnet\s+als)\s+)?(?:(?:the|der|die|das)\s+)?"
    rf"[{Q}]([^{Q}()]{{2,60}})[{Q}]\s*\)", re.I)
FORMERLY = re.compile(
    rf"\(\s*(?:formerly(?:\s+known\s+as)?|f/?k/?a|vormals|ehemals|früher|previously(?:\s+known\s+as)?|"
    rf"also\s+known\s+as|a/?k/?a|auch\s+bekannt\s+als)\s+[{Q}]?({CAP}(?:[ \t]+{CAP})*)[{Q}]?\s*\)", re.I)
GENERIC_SHORT = {"company", "parties", "party", "agreement", "contract", "seller", "buyer", "lender", "borrower",
                 "gesellschaft", "vertrag", "vereinbarung", "partei", "parteien", "auftraggeber", "auftragnehmer",
                 "versicherer", "versicherungsnehmer", "kunde", "bank"}


def tokens(name: str) -> list[str]:
    toks = re.findall(r"\w+", re.sub(r"\be\.\s?v\b\.?", "ev", name or "", flags=re.I).casefold())
    while toks and toks[0] in ARTICLES:
        toks.pop(0)
    return toks


def key(name: str) -> str:
    """Name without legal form, articles and punctuation: 'The ABC GmbH & Co. KG' -> 'abc'."""
    toks = tokens(name)
    while len(toks) > 1 and (toks[-1] in LEGAL_FORM_TOKENS or toks[-1] == "und" or toks[-1] == "and"):
        toks.pop()
    return " ".join(toks)


def defined_terms(text: str) -> list[tuple[str, str]]:
    """-> [(long name, alias)] from definition patterns in the text."""
    pairs = []
    for rx in (DEFINED, FORMERLY):
        for m in rx.finditer(text):
            tail = LONG_TAIL.search(text[max(0, m.start() - 120):m.start()])
            alias = m.group(1).strip()
            if tail and alias and alias.casefold() not in GENERIC_SHORT:
                long_name = re.sub(r"^(?:(?:and|und|&|of|de|für)\s+)+", "", tail.group(1).strip(" ,"))
                pairs.append((long_name, alias))
    return pairs


def _find(entities: list[dict], name: str):
    """Entity whose name/alias equals `name` (legal-form-insensitive); else the entity with the longest name contained in it."""
    k = key(name)
    for e in entities:
        if any(key(f) == k for f in [e["canonical_name"], *e["aliases"]]):
            return e
    inside = [e for e in entities if len(key(e["canonical_name"])) >= 4 and key(e["canonical_name"]) in k]
    return max(inside, key=lambda e: len(e["canonical_name"]), default=None)


def _compatible(a: dict, b: dict) -> bool:
    ta, tb = a["entity_type"], b["entity_type"]
    return ta == tb or "other" in (ta, tb)


def _merge(data: dict, keep: dict, drop: dict) -> None:
    has_form = lambda n: bool(set(tokens(n)) & LEGAL_FORM_TOKENS)  # noqa: E731
    names = [keep["canonical_name"], drop["canonical_name"]]
    canon = max(names, key=lambda n: (has_form(n), len(n)))
    if keep["entity_type"] == "other" or (has_form(canon) and {keep["entity_type"], drop["entity_type"]} == {"person", "company"}):
        keep["entity_type"] = drop["entity_type"] if keep["entity_type"] == "other" else "company"
    aliases = [a for a in dict.fromkeys([*keep["aliases"], *drop["aliases"], *names]) if a != canon]
    keep["canonical_name"], keep["aliases"] = canon, aliases
    seen = {(c["start_char"], c["end_char"]) for c in keep["citations"] if c["end_char"] > c["start_char"]}
    keep["citations"] += [c for c in drop["citations"] if (c["start_char"], c["end_char"]) not in seen]
    data["entities"].remove(drop)
    rels, uniq = [], set()
    for r in data["relationships"]:
        for f in ("source_entity_id", "target_entity_id"):
            if r[f] == drop["entity_id"]:
                r[f] = keep["entity_id"]
        k = (r["source_entity_id"], r["relationship_type"], r["target_entity_id"])
        if r["source_entity_id"] != r["target_entity_id"] and k not in uniq:
            uniq.add(k)
            rels.append(r)
    data["relationships"] = rels


def resolve(data: dict, text: str) -> dict:
    """Mutates output.json-format `data` in place; returns stats."""
    stats = {"defined_terms": 0, "aliases_added": 0, "merged_defined": 0, "merged_same_name": 0}
    ents = data["entities"]
    for long_name, alias in defined_terms(text):
        owner = _find(ents, long_name)
        if not owner:
            continue
        stats["defined_terms"] += 1
        other = next((e for e in ents if e is not owner and key(e["canonical_name"]) == key(alias) and _compatible(owner, e)), None)
        if other:
            _merge(data, owner, other)
            stats["merged_defined"] += 1
        elif alias != owner["canonical_name"] and alias not in owner["aliases"] and not any(
                e is not owner and key(e["canonical_name"]) == key(alias) for e in ents):
            owner["aliases"].append(alias)
            stats["aliases_added"] += 1
    changed = True
    while changed:                                  # same legal-form-free name (or alias hit) => same entity
        changed = False
        for i, a in enumerate(ents):
            for b in ents[i + 1:]:
                ka = {key(f) for f in [a["canonical_name"], *a["aliases"]]}
                kb = {key(f) for f in [b["canonical_name"], *b["aliases"]]}
                ok_type = _compatible(a, b) or {a["entity_type"], b["entity_type"]} == {"person", "company"}
                if ok_type and (key(a["canonical_name"]) == key(b["canonical_name"])
                                or key(a["canonical_name"]) in kb or key(b["canonical_name"]) in ka):
                    keep, drop = (a, b) if len(a["citations"]) >= len(b["citations"]) else (b, a)
                    _merge(data, keep, drop)
                    stats["merged_same_name"] += 1
                    changed = True
                    break
            if changed:
                break
    return stats


def apply_to_run(run_dir) -> dict:
    run_dir = Path(run_dir)
    doc = run_dir / "document.txt"
    out = run_dir / "output.json"
    if not doc.exists() or not out.exists():
        return {"skipped": "no document.txt or output.json"}
    data = json.loads(out.read_text(encoding="utf-8"))
    stats = resolve(data, doc.read_text(encoding="utf-8"))
    out.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    mf = run_dir / "manifest.json"
    if mf.exists():
        m = json.loads(mf.read_text(encoding="utf-8"))
        m["alias_pass"] = stats
        mf.write_text(json.dumps(m, indent=2, ensure_ascii=False), encoding="utf-8")
    return stats
