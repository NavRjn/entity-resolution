"""Orchestration: (gold docs, predictions) -> Report dict. Pure function, no I/O, no network."""
from __future__ import annotations

from collections import Counter
from dataclasses import asdict

from .matching import MatchConfig, align
from .metrics.clustering import cluster_metrics
from .metrics.diagnostics import diagnose, merge as merge_diag, merge_sensitivity, sensitivity
from .metrics.entities import alias_recall_counts, entity_counts, typing_stats
from .metrics.intrinsic import intrinsic
from .metrics.prf import Counts, mean_defined, sum_counts
from .metrics.provenance import ProvCounts, provenance_counts
from .metrics.relations import LEVELS, relation_counts
from .metrics.stats import bootstrap_prf
from .schema import GoldDocument, Prediction

MAX_ERRORS_PER_DOC = 40


def _agg(per_doc: list[Counts], n_boot: int, seed: int) -> dict:
    total = sum_counts(per_doc)
    d = total.as_dict()
    d["macro_f1"] = mean_defined(c.f1 for c in per_doc)
    d["ci95"] = bootstrap_prf(per_doc, n_boot, seed) if total.precision_defined else None
    return d


def evaluate(gold_docs: list[GoldDocument], preds: dict[str, Prediction], cfg: MatchConfig | None = None,
             n_boot: int = 1000, seed: int = 0) -> dict:
    cfg = cfg or MatchConfig()
    ent = {"strict": [], "lenient": []}
    ent_types = {"strict": {}, "lenient": {}}
    rel = {mode: {lv: [] for lv in LEVELS} for mode in ("end_to_end", "conditional")}
    confusion: Counter = Counter()
    alias_cov = alias_tot = 0
    clusters = []
    prov = ProvCounts()
    intr_rows, diag_rows, sens_rows = [], [], []
    per_doc, errors, missing = [], {}, []

    for g in gold_docs:
        p = preds.get(g.doc_id)
        if p is None:
            missing.append(g.doc_id)
            p = Prediction(doc_id=g.doc_id)
        al = align(g.entities, p.entities, cfg)

        row = {"doc_id": g.doc_id, "gold_entities": len(g.entities), "pred_entities": len(p.entities),
               "gold_relations": len(g.relations), "pred_relations": len(p.relations), "missing": g.doc_id in missing}
        for mode in ("strict", "lenient"):
            c, bt = entity_counts(g, p, al, strict=(mode == "strict"))
            ent[mode].append(c)
            for t, tc in bt.items():
                ent_types[mode][t] = ent_types[mode].get(t, Counts()) + tc
            row[f"entity_{mode}_f1"] = c.f1
        for mode, cond in (("end_to_end", False), ("conditional", True)):
            rc = relation_counts(g, p, al, conditional=cond)
            for lv in LEVELS:
                rel[mode][lv].append(rc[lv])
            row[f"relation_{mode}_strict_f1"] = rc["strict"].f1
        confusion.update(typing_stats(g, p, al))
        cov, tot = alias_recall_counts(g, p, al)
        alias_cov, alias_tot = alias_cov + cov, alias_tot + tot
        if g.coverage.has_coref:
            cm = cluster_metrics(g, p, al)
            if cm:
                clusters.append(cm)
        if g.text:
            prov = prov + provenance_counts(g.text, p, g, al)
        intr_rows.append(intrinsic(p))
        diag_rows.append(diagnose(g, p, al))
        sens_rows.append(sensitivity(g, p, al))
        per_doc.append(row)

        fn = [g.entities[i].name for i in range(len(g.entities)) if i not in al.gold_to_pred]
        fp = [e.name for j, e in enumerate(p.entities) if j not in al.pred_to_gold]
        wrong_type = [{"name": g.entities[i].name, "gold": g.entities[i].type, "pred": p.entities[j].type}
                      for i, j, _ in al.pairs if g.entities[i].type != p.entities[j].type]
        errors[g.doc_id] = {"missed": fn[:MAX_ERRORS_PER_DOC], "extra": fp[:MAX_ERRORS_PER_DOC],
                            "wrong_type": wrong_type[:MAX_ERRORS_PER_DOC]}

    cov = gold_docs[0].coverage if gold_docs else None
    summary = {
        "entity_strict": _agg(ent["strict"], n_boot, seed),
        "entity_lenient": _agg(ent["lenient"], n_boot, seed),
        "entity_by_type_strict": {t: c.as_dict() for t, c in sorted(ent_types["strict"].items())},
        "typing_accuracy": (sum(v for (a, b), v in confusion.items() if a == b) / sum(confusion.values())) if confusion else None,
        "type_confusion": {f"{a}->{b}": v for (a, b), v in sorted(confusion.items())},
        "alias_recall": (alias_cov / alias_tot) if alias_tot else None,
        "relations": {mode: {lv: _agg(rel[mode][lv], n_boot, seed) for lv in LEVELS} for mode in rel},
        "coreference": ({k: _mean_cluster(clusters, k) for k in ("pairwise", "b3", "muc", "ceafe")}
                        | {"conll_f1": mean_defined(c["conll_f1"] for c in clusters), "docs_scored": len(clusters)}) if clusters else None,
        "provenance": prov.rates(),
        "intrinsic": _mean_intrinsic(intr_rows),
        "diagnostics": merge_diag(diag_rows) if diag_rows else None,
        "sensitivity": merge_sensitivity(sens_rows) if sens_rows else None,
    }
    return {
        "n_docs": len(gold_docs), "missing_predictions": missing,
        "coverage": cov.model_dump() if cov else None,
        "match_config": asdict(cfg),
        "summary": summary, "per_doc": per_doc, "errors": errors,
    }


def _mean_cluster(rows: list[dict], key: str) -> dict:
    return {m: mean_defined(r[key][m] for r in rows) for m in ("precision", "recall", "f1")}


def _mean_intrinsic(rows: list[dict]) -> dict:
    keys = rows[0].keys() if rows else []
    out = {}
    for k in keys:
        vals = [r[k] for r in rows]
        out[k] = sum(v for v in vals if v is not None) if k in ("entities", "relations", "duplicate_entity_groups", "type_conflict_names") else mean_defined(vals)
    return out


def headline(report: dict) -> dict:
    """Flat dict of the numbers worth tracking over time (history.csv, Langfuse scores)."""
    s = report["summary"]
    h = {
        "entity_f1_strict": s["entity_strict"]["f1"], "entity_f1_lenient": s["entity_lenient"]["f1"],
        "entity_precision": s["entity_lenient"]["precision"], "entity_recall": s["entity_lenient"]["recall"],
        "relation_f1_strict": s["relations"]["end_to_end"]["strict"]["f1"],
        "relation_f1_undirected": s["relations"]["end_to_end"]["undirected"]["f1"],
        "relation_f1_pair": s["relations"]["end_to_end"]["pair"]["f1"],
        "relation_recall_strict": s["relations"]["end_to_end"]["strict"]["recall"],
        "typing_accuracy": s["typing_accuracy"], "alias_recall": s["alias_recall"],
        "coref_conll_f1": (s["coreference"] or {}).get("conll_f1"),
        "coref_b3_f1": ((s["coreference"] or {}).get("b3") or {}).get("f1"),
    }
    for k in ("quote_verbatim_rate", "placeholder_quote_rate", "unsupported_entity_rate", "grounding_rate"):
        h[k] = s["provenance"][k]
    for k in ("duplicate_entity_rate", "type_conflict_names", "direction_violation_rate", "orphan_entity_rate"):
        h[k] = s["intrinsic"][k]
    return h
