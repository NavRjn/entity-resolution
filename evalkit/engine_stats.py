"""Extraction-engine telemetry that docling-graph already writes next to each run (no extra cost to read).

Per run dir: metadata.json (timings, chunk coverage, truncations, skeleton counts per ontology path) and
docling_graph/provenance.json (per-node verbatim anchors with chunk-relative spans). Legacy runs have neither,
so everything returns None for them.
"""
from __future__ import annotations

import json
from pathlib import Path


def _first(run_dir: Path, pattern: str) -> Path | None:
    return next(run_dir.glob(pattern), None)


def run_engine_stats(run_dir: Path) -> dict | None:
    meta_p = _first(run_dir, "*/metadata.json")
    if not meta_p:
        return None
    meta = json.loads(meta_p.read_text(encoding="utf-8"))
    res, dense = meta.get("results", {}), (meta.get("results", {}).get("dense") or {})
    cfg = meta.get("config", {})
    out = {
        "pipeline_version": meta.get("pipeline_version"), "processing_s": meta.get("processing_time_seconds"),
        "nodes": res.get("nodes"), "edges": res.get("edges"),
        "phase1_s": dense.get("phase1_seconds"), "phase2_s": dense.get("phase2_seconds"),
        "chunk_coverage_pct": dense.get("chunk_coverage_pct"), "truncations": dense.get("truncation_count"),
        "dropped_chunks": len(dense.get("dropped_chunk_ids") or []), "skeleton_failed_batches": dense.get("skeleton_batches_failed"),
        "retention_pct": dense.get("retention_pct"), "skeleton_by_path": {k or "(root)": v for k, v in (dense.get("skeleton_path_counts") or {}).items()},
        "config": {k: cfg.get(k) for k in ("use_chunking", "gleaning_enabled", "parallel_workers", "provenance", "structured_output", "resolved_model")},
    }
    prov_p = _first(run_dir, "*/docling_graph/provenance.json")
    if prov_p:
        prov = json.loads(prov_p.read_text(encoding="utf-8"))
        nodes = [n for n in prov.get("nodes", {}).values() if n.get("node_type") != "OntologyDocument"]
        verbatim = sum(any(a.get("kind") == "verbatim" and a.get("span") for a in n.get("anchors", [])) for n in nodes)
        chunks = prov.get("chunks", {})
        out.update(provenance_nodes=len(nodes), provenance_verbatim_nodes=verbatim,
                   chunks=len(chunks), chunk_tokens=sum(c.get("token_count", 0) for c in chunks.values()))
    return out


def aggregate(run_dirs: list[Path]) -> dict | None:
    rows = [r for r in (run_engine_stats(d) for d in run_dirs) if r]
    if not rows:
        return None
    s = lambda k: sum(r.get(k) or 0 for r in rows)  # noqa: E731
    paths: dict[str, int] = {}
    for r in rows:
        for k, v in r["skeleton_by_path"].items():
            paths[k] = paths.get(k, 0) + v
    nodes = s("provenance_nodes")
    return {
        "runs": len(rows), "chunks": s("chunks"), "chunk_tokens": s("chunk_tokens"),
        "phase1_s": s("phase1_s"), "phase2_s": s("phase2_s"),
        "min_chunk_coverage_pct": min((r["chunk_coverage_pct"] for r in rows if r.get("chunk_coverage_pct") is not None), default=None),
        "truncations": s("truncations"), "dropped_chunks": s("dropped_chunks"), "failed_batches": s("skeleton_failed_batches"),
        "skeleton_by_path": dict(sorted(paths.items(), key=lambda kv: -kv[1])),
        "verbatim_anchor_rate": (s("provenance_verbatim_nodes") / nodes) if nodes else None,
        "config": rows[0]["config"],
    }
