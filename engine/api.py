"""
This is the basic API entrypoint for all document processing requirements

"""
import json
from dataclasses import dataclass
from typing import Optional
from pathlib import Path
import sys
import csv
import os
import re
from .template import OntologyDocument
from dotenv import load_dotenv
load_dotenv()

import observability

from docling_graph import PipelineConfig, run_pipeline, PipelineContext
from run import ALLOWED_ENTITIES, Citation, CanonicalEntity, EntityList, Relationship, RelationshipList

@dataclass
class RunContext:
    # Input fields
    run_id: str
    file_id: str
    file_path: Path # TODO: add optional support
    output_dir: Path # TODO: add optional support

    # Output fields
    doc_ctx: Optional[PipelineContext] = None


ENTITY_TYPE_BY_CLASS = {"person": "person", "company": "company", "agreement": "agreement", "asset": "asset",
                        "otherentity": "other", "other": "other"}
CDATA_OPEN = "<text><![CDATA["


def _entity_type(node: dict) -> str:
    """docling-graph's `entity_type` column is already the ontology value; the label is the class name ('Company')."""
    raw = (node.get("entity_type") or node.get("label") or "other").strip().lower()
    return ENTITY_TYPE_BY_CLASS.get(raw, raw if raw in ALLOWED_ENTITIES else "other")


def _aliases(node: dict, name: str) -> list[str]:
    raw = node.get("merged_aliases")
    if isinstance(raw, str) and raw.strip():
        try:
            raw = json.loads(raw)
        except ValueError:
            raw = [raw]
    if not isinstance(raw, list):
        raw = []
    return [a for a in dict.fromkeys(raw) if isinstance(a, str) and a.strip() and a != name]


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _reference_text(source_file: Path, graph_path: Path) -> str:
    """The text citation offsets refer to: the source itself when it is plain text, else docling's markdown rendering."""
    if source_file.suffix.lower() in (".txt", ".md") and source_file.exists():
        return source_file.read_text(encoding="utf-8")
    md = graph_path.parent / "docling" / "document.md"
    return md.read_text(encoding="utf-8") if md.exists() else ""


def _anchor(ref: str, chunk_text: str, span: list[int]) -> Optional[tuple[int, int, str]]:
    """Chunk-relative span -> (start, end, quote) in `ref`, verified by comparing the sliced text with the quote."""
    quote = chunk_text[span[0]:span[1]]
    if not quote.strip():
        return None
    if not ref:
        return 0, 0, quote
    pre = len(CDATA_OPEN) if chunk_text.startswith(CDATA_OPEN) else 0
    probe = chunk_text[pre:pre + 60]
    base = ref.find(probe) if probe else -1
    expected = base + span[0] - pre if base >= 0 else -1
    if expected >= 0 and ref[expected:expected + len(quote)] == quote:
        return expected, expected + len(quote), quote
    hits = [m.start() for m in re.finditer(re.escape(quote), ref)]
    if hits:                                             # choose the occurrence nearest the expected position
        start = min(hits, key=lambda h: abs(h - expected)) if expected >= 0 else hits[0]
        return start, start + len(quote), quote
    m = re.search(r"\s+".join(re.escape(w) for w in quote.split()), ref)    # whitespace drift
    return (m.start(), m.end(), ref[m.start():m.end()]) if m else (0, 0, quote)


def _name_search(ref: str, name: str, limit: int = 3) -> list[tuple[int, int, str]]:
    if not name or not ref:
        return []
    return [(m.start(), m.end(), m.group(0)) for m in list(re.finditer(re.escape(name), ref, re.I))[:limit]]


def _evidence(ref: str, a: list[dict], b: list[dict], max_gap: int = 400) -> dict:
    """Relationship evidence = the passage where both entities are mentioned close together (co-occurrence, not proof)."""
    best = None
    for ca in a:
        for cb in b:
            if ca["end_char"] > ca["start_char"] and cb["end_char"] > cb["start_char"]:
                lo, hi = min(ca["start_char"], cb["start_char"]), max(ca["end_char"], cb["end_char"])
                if hi - lo <= max_gap and (best is None or hi - lo < best[1] - best[0]):
                    best = (lo, hi, ca["file_id"], ca["chunk_id"])
    if not best or not ref:
        return Citation(file_id="NA", chunk_id=0, start_char=0, end_char=0, quote="", match="unanchored").model_dump()
    lo, hi, fid, cid = best
    prev = ref.rfind(". ", 0, lo)
    lo = max(prev + 2 if prev >= 0 else 0, lo - 200)
    nxt = ref.find(". ", hi)
    hi = min(nxt + 1 if nxt >= 0 else len(ref), hi + 200)
    return Citation(file_id=fid, chunk_id=cid, start_char=lo, end_char=hi, quote=ref[lo:hi], match="cooccurrence").model_dump()


def _norm(text: str) -> str:
    return re.sub(r"[\W_]+", "", (text or "").casefold())


def _resolve_entity(name: str, forms: dict[str, str]) -> Optional[str]:
    """Entity id for a name the model wrote in a relationship record: exact normalised name or alias, else a unique
    containment match ('Microsoft' -> 'Microsoft Corporation'). None when unknown or ambiguous."""
    key = _norm(name)
    if key in forms:
        return forms[key]
    hits = {eid for form, eid in forms.items() if len(key) >= 4 and len(form) >= 4 and (key in form or form in key)}
    return hits.pop() if len(hits) == 1 else None


def _quote_citation(ref: str, quote: str, file_id: str, chunk_id: int) -> Optional[dict]:
    """Locate a model-copied evidence passage in the reference text (exact, then whitespace-tolerant)."""
    quote = (quote or "").strip()
    if not quote or not ref:
        return None
    i = ref.find(quote)
    if i < 0:
        m = re.search(r"\s+".join(re.escape(w) for w in quote.split()), ref)
        if not m:
            return None
        i, quote = m.start(), ref[m.start():m.end()]
    return Citation(file_id=file_id, chunk_id=chunk_id, start_char=i, end_char=i + len(quote), quote=quote,
                    match="verbatim").model_dump()


def save_compatible_files(run_id: str, source_file: Path, output_dir: Path):
    """
    Read OUTPUTDIR/*/docling_graph/{nodes,edges}.csv (+ provenance.json) and write OUTPUTDIR/manifest.json,
    output.json and document.txt in the legacy format the API and frontend consume.

    Citations carry the verbatim quote and real character offsets into document.txt, taken from
    docling-graph's provenance.json (chunk-relative spans, verified against the text). Nodes without a
    verbatim anchor fall back to a name search ("name_search"), else keep an empty quote ("unanchored").
    """
    graph_path = next(output_dir.glob("*/docling_graph"), None)
    metadata_path = next(output_dir.glob("*/metadata.json"), None)
    if graph_path is None or metadata_path is None:
        raise FileNotFoundError(f"docling-graph produced no output under {output_dir} (no */docling_graph or */metadata.json)")

    print("Reading ", str(graph_path))
    with (graph_path / "nodes.csv").open("r", encoding="utf-8", newline="") as f:
        nodes = list(csv.DictReader(f))
    with (graph_path / "edges.csv").open("r", encoding="utf-8", newline="") as f:
        edges = list(csv.DictReader(f))
    metadata = _load_json(metadata_path)
    prov = _load_json(graph_path / "provenance.json")
    prov_nodes = {(n.get("node_type"), (n.get("ids") or {}).get("name")): n for n in prov.get("nodes", {}).values()}
    chunks = prov.get("chunks", {})
    ref = _reference_text(Path(source_file), graph_path)

    manifest = {
        "run_id": str(run_id),
        "created_at": metadata.get("timestamp", ""),
        "source_file": str(source_file),
        "seed": 0,
        "chunk_max_chars": None,
        "chunk_overlap_chars": None,
        "document_file": "document.txt" if ref else None,
    }

    def citations_for(node: dict) -> list[dict]:
        csv_prov = json.loads(node.get("__provenance__") or "{}")
        file_id = csv_prov.get("document_id") or "NA"
        pnode = prov_nodes.get((node.get("label"), node.get("name")))
        cits: list[dict] = []
        seen: set = set()
        for anc in (pnode or {}).get("anchors", []):
            if anc.get("kind") != "verbatim" or not anc.get("span"):
                continue
            chunk = chunks.get(str(anc["chunk_id"]), {})
            hit = _anchor(ref, chunk.get("text", ""), anc["span"]) if chunk.get("text") else None
            if hit and (hit[0], hit[1]) not in seen:
                seen.add((hit[0], hit[1]))
                cits.append(Citation(file_id=file_id, chunk_id=int(anc["chunk_id"]), start_char=hit[0], end_char=hit[1],
                                     quote=hit[2], match="verbatim" if hit[1] else "unanchored").model_dump())
        if cits:
            return cits
        chunk_ids = csv_prov.get("chunks") or [0]
        for s, e, q in _name_search(ref, node.get("name", "")):
            cits.append(Citation(file_id=file_id, chunk_id=int(chunk_ids[0]), start_char=s, end_char=e, quote=q,
                                 match="name_search").model_dump())
        return cits or [Citation(file_id=file_id, chunk_id=int(chunk_ids[0]), start_char=0, end_char=0, quote="",
                                 match="unanchored").model_dump()]

    entities = []
    for node in nodes:
        if node.get("label") in ("OntologyDocument", "Relationship"):
            continue
        name = node.get("name", "NA")
        entities.append({
            "entity_id": node.get("id", "NA"),
            "canonical_name": name,
            "entity_type": _entity_type(node),
            "aliases": _aliases(node, name),
            "citations": citations_for(node),
        })
    cites = {e["entity_id"]: e["citations"] for e in entities}

    relationships = [{
        "source_entity_id": edge.get("source", "NA"),
        "target_entity_id": edge.get("target", "NA"),
        "relationship_type": edge.get("label", "NA"),
        "citation": _evidence(ref, cites.get(edge.get("source"), []), cites.get(edge.get("target"), [])),
    } for edge in edges if "OntologyDocument" not in edge.get("source", "")]

    forms = {}
    for e in entities:
        for form in [e["canonical_name"], *e["aliases"]]:
            forms.setdefault(_norm(form), e["entity_id"])
    dropped = 0
    for node in nodes:
        if node.get("label") != "Relationship":
            continue
        src, tgt = _resolve_entity(node.get("subject", ""), forms), _resolve_entity(node.get("object", ""), forms)
        if not src or not tgt or src == tgt:
            dropped += 1
            continue
        csv_prov = json.loads(node.get("__provenance__") or "{}")
        cit = _quote_citation(ref, node.get("evidence", ""), csv_prov.get("document_id") or "NA",
                              int((csv_prov.get("chunks") or [0])[0])) \
            or _evidence(ref, cites.get(src, []), cites.get(tgt, []))
        relationships.append({"source_entity_id": src, "target_entity_id": tgt,
                              "relationship_type": node.get("relation") or "related_to", "citation": cit})
    manifest["dropped_relationship_records"] = dropped

    with open(output_dir / "manifest.json", "w", encoding="utf-8") as f:
        print("Saving manifest.json at ", str(output_dir / "manifest.json"))
        json.dump(manifest, f, indent=2, ensure_ascii=False, default=str)
    if ref:
        (output_dir / "document.txt").write_text(ref, encoding="utf-8")
    with open(output_dir / "output.json", "w", encoding="utf-8") as f:
        print("Saving output.json at ", str(output_dir / "output.json"))
        json.dump({"entities": entities, "relationships": relationships}, f, indent=2, ensure_ascii=False, default=str)


# Experiments swap the extraction schema without code edits: ER_TEMPLATE=engine.template_v1.OntologyDocument
TEMPLATE = os.getenv("ER_TEMPLATE", "engine.template.OntologyDocument")


def run_full(ctx: RunContext) -> RunContext:

    run_id = ctx.run_id
    file_id = ctx.file_id
    file_path = ctx.file_path
    output_dir = ctx.output_dir

    print("Searching in Paths:...")
    for path in sys.path:
        print(path)

    cfg = PipelineConfig(
        source=str(file_path),
        template=TEMPLATE,
        backend="llm",
        inference="remote",
        provider_override="openai",
        model_override="gpt-4o",
        dump_to_disk=True,
        output_dir=output_dir
    )

    with observability.run_trace(run_id, backend="docling", output_dir=output_dir,
                                 metadata={"model": cfg.model_override, "file": file_path.name, "template": TEMPLATE},
                                 input={"file": file_path.name}):
        observability.instrument_litellm()
        with observability.stage("docling_graph_pipeline"):
            doc_ctx = run_pipeline(cfg)
        ctx.doc_ctx = doc_ctx

        with observability.stage("convert_outputs"):
            save_compatible_files(run_id, file_path, output_dir)

        if os.getenv("ER_RELATION_PASS") == "1":      # opt-in: see engine/relations.py
            from .relations import apply_to_run
            with observability.stage("relation_pass"):
                apply_to_run(output_dir, cfg.model_override)
    return ctx



