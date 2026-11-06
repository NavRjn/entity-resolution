"""Rendering and persistence: report.json, report.md, console table, metrics/history.csv, baseline gating."""
from __future__ import annotations

import csv
import json
from pathlib import Path

HISTORY_FIELDS = ["timestamp", "eval_id", "dataset", "dataset_fp", "backend", "model", "git_sha", "git_dirty", "n_docs",
                  "entity_f1_strict", "entity_f1_lenient", "entity_precision", "entity_recall",
                  "relation_f1_strict", "relation_f1_undirected", "relation_f1_pair", "typing_accuracy",
                  "alias_recall", "coref_conll_f1", "quote_verbatim_rate", "placeholder_quote_rate",
                  "unsupported_entity_rate", "duplicate_entity_rate", "type_conflict_names",
                  "latency_s", "cost_usd", "prompt_tokens", "completion_tokens"]


def _pct(x):
    return "n/a" if x is None else f"{x:.1%}"


def _ci(d):
    ci = (d or {}).get("ci95") and d["ci95"].get("f1")
    return f" [{ci[0]:.1%}, {ci[1]:.1%}]" if ci else ""


def to_markdown(report: dict) -> str:
    m, s = report["meta"], report["summary"]
    cov = report.get("coverage") or {}
    L = [f"# Evaluation: {m.get('dataset')}  ({m.get('eval_id')})", "",
         f"- docs: **{report['n_docs']}**  backend: {m.get('backend')}  model: {m.get('model')}  "
         f"git: {m.get('git_sha')}{'*' if m.get('git_dirty') else ''}  dataset fp: {m.get('dataset_fp')}",
         f"- gold coverage: exhaustive types = {cov.get('exhaustive_entity_types')}, exhaustive relations = "
         f"{cov.get('exhaustive_relations')}, coreference labels = {cov.get('has_coref')}, types = {cov.get('has_types')}"]
    if report["missing_predictions"]:
        L.append(f"- **{len(report['missing_predictions'])} documents have no prediction** (scored as all-missed)")
    L += ["", "## Entities", "", "| mode | P | R | F1 (95% CI) | macro F1 | TP | FP | FN |", "|---|---|---|---|---|---|---|---|"]
    for k in ("entity_strict", "entity_lenient"):
        e = s[k]
        L.append(f"| {k[7:]} | {_pct(e['precision'])} | {_pct(e['recall'])} | {_pct(e['f1'])}{_ci(e)} | {_pct(e['macro_f1'])} | {e['tp']} | {e['fp']} | {e['fn']} |")
    if not s["entity_strict"]["precision_defined"]:
        L.append("\nPrecision/F1 are **n/a**: the gold is partial (unlabelled entities cannot be called false positives). Read recall.")
    if s["entity_by_type_strict"]:
        L += ["", "| type | P | R | F1 | TP | FP | FN |", "|---|---|---|---|---|---|---|"]
        for t, e in s["entity_by_type_strict"].items():
            L.append(f"| {t} | {_pct(e['precision'])} | {_pct(e['recall'])} | {_pct(e['f1'])} | {e['tp']} | {e['fp']} | {e['fn']} |")
    L += ["", f"typing accuracy on aligned entities: **{_pct(s['typing_accuracy'])}**   alias recall: **{_pct(s['alias_recall'])}**"]
    if s["type_confusion"]:
        L.append("confusions: " + ", ".join(f"{k} x{v}" for k, v in s["type_confusion"].items() if k.split('->')[0] != k.split('->')[1]) or "none")

    L += ["", "## Relations", "", "| level | end-to-end P | R | F1 | conditional F1 (entities found) |", "|---|---|---|---|---|"]
    for lv, e in s["relations"]["end_to_end"].items():
        c = s["relations"]["conditional"][lv]
        L.append(f"| {lv} | {_pct(e['precision'])} | {_pct(e['recall'])} | {_pct(e['f1'])}{_ci(e)} | {_pct(c['f1'])} |")
    if s["coreference"]:
        c = s["coreference"]
        L += ["", f"## Alias / coreference (name level, {c['docs_scored']} docs)", "",
              "| metric | P | R | F1 |", "|---|---|---|---|"]
        for k in ("pairwise", "b3", "muc", "ceafe"):
            L.append(f"| {k} | {_pct(c[k]['precision'])} | {_pct(c[k]['recall'])} | {_pct(c[k]['f1'])} |")
        L.append(f"| **CoNLL avg (MUC, B3, CEAF-e)** | | | **{_pct(c['conll_f1'])}** |")
    p, i = s["provenance"], s["intrinsic"]
    L += ["", "## Provenance (label-free)", "",
          f"- quotes verbatim in source: {_pct(p['quote_verbatim_rate'])}   placeholder quotes: {_pct(p['placeholder_quote_rate'])}   "
          f"valid offsets: {_pct(p['span_valid_rate'])}",
          f"- entities with a citation: {_pct(p['entities_with_citation_rate'])}   unsupported by text (hallucination proxy): {_pct(p['unsupported_entity_rate'])}"
          f"   gold-grounded citations: {_pct(p['grounding_rate'])}",
          "", "## Structural health (label-free)", "",
          f"- duplicate entity rate: {_pct(i['duplicate_entity_rate'])}   same name with conflicting types: {i['type_conflict_names']}   orphan entities: {_pct(i['orphan_entity_rate'])}",
          f"- relation direction-rule violations: {_pct(i['direction_violation_rate'])}   dangling: {_pct(i['dangling_relation_rate'])}   "
          f"unknown relation types: {_pct(i['unknown_relation_type_rate'])}   duplicates: {_pct(i['duplicate_relation_rate'])}"]
    d = s.get("diagnostics")
    if d:
        L += ["", "## Why entities were missed or invented", "",
              "missed gold: " + (", ".join(f"{k} {v}" for k, v in sorted(d["missed_gold"].items(), key=lambda kv: -kv[1])) or "none"),
              "extra predictions: " + (", ".join(f"{k} {v}" for k, v in sorted(d["extra_pred"].items(), key=lambda kv: -kv[1])) or "none"),
              "extra by predicted type: " + (", ".join(f"{k} {v}" for k, v in sorted(d["extra_pred_by_type"].items(), key=lambda kv: -kv[1])) or "none")]
        for title, key in (("name length", "recall_by_len"), ("mentions in gold", "recall_by_mentions"), ("position in document", "recall_by_position")):
            if d[key]:
                L.append(f"- recall by {title}: " + ", ".join(f"{b} {_pct(v['recall'])} ({v['hit']}/{v['n']})" for b, v in d[key].items()))
        t = d["mean_name_tokens"]
        L.append("- mean tokens per name: " + ", ".join(f"{k} {v:.1f}" for k, v in t.items() if v is not None))
        for k, ex in d["examples"].items():
            L.append(f"- `{k}`: " + "; ".join(" -> ".join(str(x) for x in e.values() if x) for e in ex[:5]))
    if s.get("sensitivity"):
        L += ["", "## Sensitivity: how much is the dataset/ontology, how much is the system? (lenient, same matching)", "",
              "| variant | P | R | F1 | TP | FP | FN |", "|---|---|---|---|---|---|---|"]
        for k, v in s["sensitivity"].items():
            L.append(f"| {k} | {_pct(v['precision'])} | {_pct(v['recall'])} | {_pct(v['f1'])} | {v['tp']} | {v['fp']} | {v['fn']} |")
        L.append("These are post-hoc filters for diagnosis, never replacement scores; quote the baseline.")
    ops, eng = report.get("ops"), report.get("engine")
    if ops:
        L += ["", "## Cost, latency, failures", "",
              f"- {ops['runs']} runs, {ops['llm_calls']} LLM calls, tokens in/out {ops['prompt_tokens']:,}/{ops['completion_tokens']:,}, "
              f"**${ops['cost_usd']:.4f} total**, wall {ops['latency_s']:.0f}s"]
        if ops["failed"]:
            L.append(f"- **{len(ops['failed'])} failed run(s), ${ops['wasted_usd_failed_runs']:.4f} spent with no output**: " +
                     "; ".join(f"{r['run_id']}: {r['error']}" for r in ops["per_run"] if r["status"] != "completed"))
        e = ops.get("efficiency")
        if e:
            L.append(f"- per doc ${e['cost_per_doc_usd']:.3f}, {e['llm_calls_per_doc']:.1f} calls, {e['prompt_tokens_per_doc_token']:.1f} prompt tokens per document token; "
                     f"${e['cost_per_1k_chars_usd']:.4f}/1k chars, {e['seconds_per_1k_chars']:.1f}s/1k chars"
                     + (f"; ${e['cost_per_correct_entity_usd']:.3f} per correct entity" if e["cost_per_correct_entity_usd"] else ""))
            L.append(f"- straight-line projection to a 300-page matter (900k chars): ~${e['projected_300_page_matter_usd']:.0f}, "
                     f"~{e['projected_300_page_matter_minutes_sequential']:.0f} min sequential ({e['projection_note']})")
        L += ["", "| run | status | s | calls | tokens in/out | $ |", "|---|---|---|---|---|---|"]
        for r in ops["per_run"]:
            L.append(f"| {r['run_id']} | {r['status']} | {r['latency_s']:.0f} | {r['calls']} | {r['prompt_tokens']:,}/{r['completion_tokens']:,} | {r['cost_usd']:.3f} |")
    if eng:
        L += ["", "## Extraction engine telemetry (docling-graph)", "",
              f"- chunks {eng['chunks']} ({eng['chunk_tokens']:,} tokens), phase1 {eng['phase1_s']:.0f}s / phase2 {eng['phase2_s']:.0f}s, "
              f"min chunk coverage {eng['min_chunk_coverage_pct']}%, truncations {eng['truncations']}, dropped chunks {eng['dropped_chunks']}, failed batches {eng['failed_batches']}",
              "- nodes found per ontology path (before scoring): " + ", ".join(f"{k} {v}" for k, v in eng["skeleton_by_path"].items()),
              f"- **nodes with a verbatim anchor in provenance.json: {_pct(eng['verbatim_anchor_rate'])}** (real quotes are recoverable even though output.json holds placeholders)",
              f"- config: {eng['config']}"]
    worst = sorted(report["per_doc"], key=lambda r: (r["entity_lenient_f1"] is None, r["entity_lenient_f1"] or 0))[:5]
    L += ["", "## Weakest documents (lenient entity F1)", ""]
    for r in worst:
        e = report["errors"][r["doc_id"]]
        L.append(f"- `{r['doc_id']}` F1 {_pct(r['entity_lenient_f1'])}; missed: {e['missed'][:5]}; extra: {e['extra'][:5]}")
    return "\n".join(L) + "\n"


def console(report: dict) -> None:
    from rich.console import Console
    from rich.table import Table
    s, c = report["summary"], Console()
    t = Table(title=f"{report['meta'].get('dataset')}  ({report['n_docs']} docs)")
    for col in ("metric", "P", "R", "F1"):
        t.add_column(col, justify="left" if col == "metric" else "right")
    rows = [("entity strict", s["entity_strict"]), ("entity lenient", s["entity_lenient"])]
    rows += [(f"relation {lv}", s["relations"]["end_to_end"][lv]) for lv in ("strict", "undirected", "untyped", "pair")]
    for name, e in rows:
        t.add_row(name, _pct(e["precision"]), _pct(e["recall"]), _pct(e["f1"]) + _ci(e))
    if s["coreference"]:
        t.add_row("coref B3", *(_pct(s["coreference"]["b3"][k]) for k in ("precision", "recall", "f1")))
        t.add_row("coref CoNLL avg", "", "", _pct(s["coreference"]["conll_f1"]))
    c.print(t)
    p = s["provenance"]
    c.print(f"quote verbatim {_pct(p['quote_verbatim_rate'])} | placeholder {_pct(p['placeholder_quote_rate'])} | "
            f"unsupported entities {_pct(p['unsupported_entity_rate'])} | dup entities {_pct(s['intrinsic']['duplicate_entity_rate'])}")


def save(report: dict, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    (out_dir / "report.md").write_text(to_markdown(report), encoding="utf-8")


def append_history(row: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    with path.open("a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=HISTORY_FIELDS, extrasaction="ignore")
        if new:
            w.writeheader()
        w.writerow(row)


def check_regression(current: dict, baseline: dict, max_drop: float, keys=("entity_f1_lenient", "relation_f1_strict")) -> list[str]:
    """Names of headline metrics that fell by more than `max_drop` (absolute) versus the baseline headline."""
    bad = []
    for k in keys:
        a, b = current.get(k), baseline.get(k)
        if a is not None and b is not None and b - a > max_drop:
            bad.append(f"{k}: {b:.3f} -> {a:.3f}")
    return bad
