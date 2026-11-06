"""uv run python -m evalkit <command>   (see `-h`).

    datasets                              list cards with provenance/licence/coverage
    fetch <name>                          download raw sources (pinned by sha256 in fetch.lock.json)
    prepare <name> [--limit N --max-chars C --seed S]
                                          raw -> prepared gold.jsonl + plain-text docs the pipeline can ingest
    score --gold G --run R [--run R2 ...] score EXISTING runs against labels (no pipeline involved)
    run <name> --backend docling --yes    run the pipeline over a prepared dataset, then score (costs API credits)
    history | compare A B | gate          trend table, two-report diff, regression gate for CI
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime
from pathlib import Path

import observability

from . import datasets as ds
from .engine_stats import aggregate as engine_aggregate
from .evaluate import evaluate, headline
from .loaders import Card, load_dataset
from .matching import MatchConfig
from .predictions import load_generic, load_run
from .report import append_history, check_regression, console, save
from .schema import GoldDocument, Prediction

ROOT = ds.ROOT
OUTPUTS = ROOT / "outputs"
EVAL_RUNS = ROOT / "eval_runs"
HISTORY = ROOT / "metrics" / "history.csv"


# ----------------------------------------------------------------------------- helpers

def resolve_gold(spec: str, card_path: str | None = None, gold_path: str | None = None) -> tuple[list[GoldDocument], str]:
    """Gold from: a prepared dataset name/dir/gold.jsonl, a legacy *.gt.json, or any raw file + --card."""
    if card_path:
        card = ds.get_card(card_path)
        return list(load_dataset(card, Path(gold_path or spec))), card.name
    if spec.endswith(".gt.json"):
        card = Card({"name": Path(spec).name.removesuffix(".gt.json"), "loader": "legacy_gt", "has_coref": False})
        return list(load_dataset(card, Path(spec))), card.name
    docs, _ = ds.load_prepared(spec)
    p = Path(spec)
    return docs, (p.parent.parent.name if p.suffix == ".jsonl" else p.name)


def find_run(run: str) -> Path:
    for cand in (Path(run), OUTPUTS / run, *EVAL_RUNS.glob(f"*/runs/{run}")):
        if (cand / "output.json").exists():
            return cand
    raise FileNotFoundError(f"no output.json for run {run!r} (looked in outputs/ and eval_runs/*/runs/)")


def latest_run() -> str:
    files = list(OUTPUTS.glob("*/output.json"))
    if not files:
        raise FileNotFoundError("no completed runs in outputs/")
    return max(files, key=lambda f: f.stat().st_mtime).parent.name


def _sum_dicts(items):
    out: dict = {}
    for d in items:
        for k, v in d.items():
            out[k] = out.get(k, 0) + v
    return {k: round(v, 3) for k, v in out.items()}


def aggregate_ops(run_dirs: list[Path]) -> dict | None:
    rows = [json.loads((d / "ops.json").read_text(encoding="utf-8")) for d in run_dirs if (d / "ops.json").exists()]
    if not rows:
        return None
    failed_cost = sum(r["llm"]["cost_usd"] for r in rows if r["status"] != "completed")
    return {"runs": len(rows), "latency_s": sum(r["latency_s"] for r in rows), "wasted_usd_failed_runs": failed_cost,
            "per_run": [{"run_id": r["run_id"], "status": r["status"], "error": r["error"], "latency_s": r["latency_s"],
                         "calls": r["llm"]["calls"], "prompt_tokens": r["llm"]["prompt_tokens"],
                         "completion_tokens": r["llm"]["completion_tokens"], "cost_usd": r["llm"]["cost_usd"]} for r in rows],
            "llm_calls": sum(r["llm"]["calls"] for r in rows),
            "prompt_tokens": sum(r["llm"]["prompt_tokens"] for r in rows),
            "completion_tokens": sum(r["llm"]["completion_tokens"] for r in rows),
            "cost_usd": sum(r["llm"]["cost_usd"] for r in rows),
            "stages_s": _sum_dicts(r["stages_s"] for r in rows),
            "failed": [r["run_id"] for r in rows if r["status"] != "completed"],
            "models": sorted({m for r in rows for m in r["llm"]["by_model"]})}


def efficiency(report: dict, chars: int, ops: dict) -> dict:
    """Cost/latency per unit of work. The projection is a straight-line extrapolation from the sample (labelled as such)."""
    tp = report["summary"]["entity_lenient"]["tp"]
    docs, tokens = max(ops["runs"], 1), max(chars / 4, 1)
    per_1k = ops["cost_usd"] / (chars / 1000) if chars else None
    matter_chars = 300 * 3000      # roadmap gate: 300 pages at ~3000 chars/page (assumption)
    return {
        "cost_per_doc_usd": ops["cost_usd"] / docs, "cost_per_1k_chars_usd": per_1k,
        "cost_per_correct_entity_usd": ops["cost_usd"] / tp if tp else None,
        "prompt_tokens_per_doc_token": ops["prompt_tokens"] / tokens, "llm_calls_per_doc": ops["llm_calls"] / docs,
        "seconds_per_1k_chars": ops["latency_s"] / (chars / 1000) if chars else None,
        "projected_300_page_matter_usd": per_1k * matter_chars / 1000 if per_1k else None,
        "projected_300_page_matter_minutes_sequential": ops["latency_s"] / (chars / 1000) * matter_chars / 1000 / 60 if chars else None,
        "projection_note": "linear extrapolation from short documents; real cost depends on chunking, gleaning and consolidation passes",
    }


def push_to_langfuse(report: dict, run_dirs: dict[str, Path], eval_id: str) -> int:
    """Per-run scores on each run's own trace (found via ops.json), aggregate scores on the evaluation session."""
    sent = 0
    for per in report["per_doc"]:
        rd = run_dirs.get(per["doc_id"])
        if rd is None:
            continue
        metrics = {k: per[k] for k in ("entity_lenient_f1", "entity_strict_f1", "relation_end_to_end_strict_f1") if per.get(k) is not None}
        ops_file = rd / "ops.json"
        tid = json.loads(ops_file.read_text(encoding="utf-8")).get("trace_id") if ops_file.exists() else None
        if tid:
            sent += observability.record_scores(metrics, trace_id=tid, comment=report["meta"]["dataset"])
        else:                                          # run predates ops.json: attach to a fresh evaluation trace
            observability.eval_trace(f"eval:{rd.name}", rd.name, metrics, {"dataset": report["meta"]["dataset"]})
    sent += observability.record_scores(report["headline"], session_id=eval_id, comment=report["meta"]["dataset"])
    return sent


def score_and_report(gold: list[GoldDocument], run_dirs: dict[str, Path], dataset: str, eval_id: str, *,
                     backend: str = "unknown", cfg: MatchConfig | None = None, out_dir: Path | None = None,
                     langfuse: bool = True, history: bool = True, quiet: bool = False,
                     ops_dirs: list[Path] | None = None) -> dict:
    # a value may be a run directory (outputs/<id>/) or a bare prediction .json file from any system
    preds: dict[str, Prediction] = {d: (load_generic(rd, d) if rd.is_file() else load_run(rd, d)) for d, rd in run_dirs.items()}
    run_dirs = {d: (rd.parent if rd.is_file() else rd) for d, rd in run_dirs.items()}
    for g in gold:                                    # raw text for provenance when the label source has none
        rd = run_dirs.get(g.doc_id)
        if rd and not g.text and (rd / "manifest.json").exists():
            src = Path(json.loads((rd / "manifest.json").read_text(encoding="utf-8")).get("source_file", ""))
            if src.suffix == ".txt" and src.exists():
                g.text = src.read_text(encoding="utf-8")
    report = evaluate(gold, preds, cfg)
    git = observability.git_info()
    all_dirs = ops_dirs or list(run_dirs.values())        # failed runs still cost money
    ops = aggregate_ops(all_dirs)
    report["engine"] = engine_aggregate(all_dirs)
    if ops:
        ops["efficiency"] = efficiency(report, sum(len(g.text) for g in gold), ops)
    report["meta"] = {"eval_id": eval_id, "dataset": dataset, "dataset_fp": ds.dataset_fingerprint(gold), "backend": backend,
                      "model": ",".join(ops["models"]) if ops and ops["models"] else None,
                      "git_sha": git["sha"], "git_dirty": git["dirty"],
                      "timestamp": datetime.now().isoformat(timespec="seconds"),
                      "runs": {k: str(v) for k, v in run_dirs.items()}}
    report["ops"] = ops
    report["headline"] = headline(report)
    if ops:
        e = ops.get("efficiency", {})
        report["headline"].update(cost_usd=ops["cost_usd"], latency_s=ops["latency_s"], failed_runs=len(ops["failed"]),
                                  cost_per_correct_entity_usd=e.get("cost_per_correct_entity_usd"),
                                  prompt_tokens_per_doc_token=e.get("prompt_tokens_per_doc_token"))
    ds_ = report["summary"].get("sensitivity")
    if ds_:
        report["headline"]["entity_f1_ceiling_after_filters"] = ds_["all_filters_combined (ceiling)"]["f1"]
    if out_dir:
        save(report, out_dir)
    if history:
        row = {**report["meta"], **report["headline"], "n_docs": report["n_docs"]}
        if ops:
            row.update(latency_s=ops["latency_s"], cost_usd=ops["cost_usd"],
                       prompt_tokens=ops["prompt_tokens"], completion_tokens=ops["completion_tokens"])
        append_history(row, HISTORY)
    if langfuse:
        report["langfuse_scores_sent"] = push_to_langfuse(report, run_dirs, eval_id)
    if not quiet:
        console(report)
        if out_dir:
            print(f"report: {out_dir / 'report.md'}")
        if langfuse:
            print(f"langfuse scores sent: {report['langfuse_scores_sent']}" + ("" if observability.enabled() else " (disabled: no keys)"))
    return report


def _cfg(a) -> MatchConfig:
    return MatchConfig(fuzzy_threshold=a.fuzzy, use_aliases=not a.no_aliases)


# ----------------------------------------------------------------------------- commands

def cmd_datasets(a):
    for name, c in ds.list_cards().items():
        r = c.raw
        print(f"{name:18} {r.get('language'):3} {r.get('license'):22} {r.get('annotation', '')[:48]}")
        print(f"{'':18} gives: {', '.join(r.get('provides', []))}; lacks: {', '.join(r.get('lacks', []))}")
        print(f"{'':18} {r.get('home', '')}")
        prepared = ds.dataset_dir(c) / "prepared" / "gold.jsonl"
        print(f"{'':18} prepared: {'yes' if prepared.exists() else 'no'}")


def cmd_fetch(a):
    card = ds.get_card(a.name)
    print("licence:", card.raw.get("license"), "|", card.raw.get("home"))
    print("downloaded to", ds.fetch(card, force=a.force))


def cmd_prepare(a):
    card = ds.get_card(a.name)
    out = ds.prepare(card, limit=a.limit, seed=a.seed, max_chars=a.max_chars, min_relations=a.min_relations)
    docs, _ = ds.load_prepared(str(out))
    n_ent = sum(len(d.entities) for d in docs)
    n_rel = sum(len(d.relations) for d in docs)
    chars = sum(len(d.text) for d in docs)
    print(f"{card.name}: {len(docs)} docs, {n_ent} gold entities, {n_rel} gold relations, {chars:,} chars (~{chars // 4:,} tokens)")
    print("prepared:", out)


def cmd_score(a):
    gold, dataset = resolve_gold(a.gold, a.card, a.gold_path)
    run_ids = [latest_run()] if a.last else a.run
    if not run_ids and not a.eval_run:
        sys.exit("give --run ID (repeatable), --last, or --eval-run EVAL_ID")
    if a.eval_run:
        mapping = json.loads((EVAL_RUNS / a.eval_run / "runs.json").read_text(encoding="utf-8"))
        run_dirs = {k: Path(v) for k, v in mapping.items() if (Path(v) / "output.json").exists()}
    else:
        pairs = dict(m.split("=", 1) for m in a.map or [])
        if len(gold) == 1 and len(run_ids) == 1 and not pairs:
            pairs = {gold[0].doc_id: run_ids[0]}
        elif not pairs and len(run_ids) == len(gold):
            pairs = {g.doc_id: r for g, r in zip(gold, run_ids)}
        if not pairs:
            sys.exit("cannot pair runs with gold documents; pass --map DOC_ID=RUN_ID")
        run_dirs = {d: find_run(r) for d, r in pairs.items()}
    # a document that was attempted but produced no output stays in the gold (scored as all-missed), never silently dropped
    attempted = {d.name for d in EVAL_RUNS.joinpath(a.eval_run, "runs").glob("*")} if a.eval_run else set(run_dirs)
    gold = [g for g in gold if g.doc_id in attempted]
    eval_id = a.eval_run or "score_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    out = EVAL_RUNS / eval_id
    all_dirs = sorted((EVAL_RUNS / a.eval_run / "runs").glob("*")) if a.eval_run else None
    score_and_report(gold, run_dirs, dataset, eval_id, backend=a.backend, cfg=_cfg(a), out_dir=out,
                     langfuse=not a.no_langfuse, ops_dirs=all_dirs)


def _run_one(backend: str, doc: GoldDocument, prepared: Path, out_dir: Path, use_pdf: bool) -> Path:
    src = prepared / "docs" / f"{doc.doc_id}.{'pdf' if use_pdf and (prepared / 'docs' / (doc.doc_id + '.pdf')).exists() else 'txt'}"
    out_dir.mkdir(parents=True, exist_ok=True)
    if backend == "docling":
        from engine.api import RunContext, run_full
        run_full(RunContext(run_id=doc.doc_id, file_id=doc.doc_id, file_path=src, output_dir=out_dir))
    else:
        from run import EntityResolutionPipeline, RunContext
        EntityResolutionPipeline().run_full(RunContext(run_id=doc.doc_id, file_id=doc.doc_id, seed=42, file_path=src, output_dir=out_dir))
    return out_dir


# Measured on three paid docling runs (gpt-4o, 2026-11-05/06): cost per document = fixed + per-1k-chars.
#   ler (8.0k chars/doc) $0.116, e_ner (8.0k) $0.116, re_docred (1.2k) $0.052  =>  ~$0.041 + $0.0094 per 1k chars.
# The fixed part is the schema/instruction prompts sent for every document (about 6-9 LLM calls even for a paragraph).
# A fit on three points: treat as +-30%, and refit after each new run.
FIXED_USD_PER_DOC = 0.041
USD_PER_1K_CHARS = 0.0094


def estimate_cost(chars: int, n_docs: int = 1, model: str = "gpt-4o") -> dict:
    """Dollar range for a docling-backend run: n_docs * fixed + chars * variable, +-30%. Prices are gpt-4o only."""
    import litellm
    price = litellm.model_cost[model]
    mid = n_docs * FIXED_USD_PER_DOC + chars / 1000 * USD_PER_1K_CHARS
    return {"model": model, "doc_tokens": int(chars / 4), "low_usd": mid * 0.7, "high_usd": mid * 1.3,
            "in_per_m": price["input_cost_per_token"] * 1e6, "out_per_m": price["output_cost_per_token"] * 1e6}


def cmd_run(a):
    gold, prepared = ds.load_prepared(a.name)
    gold = gold[: a.limit] if a.limit else gold
    chars = sum(len(d.text) for d in gold)
    est = estimate_cost(chars, len(gold))
    print(f"{len(gold)} documents, {chars:,} chars (~{est['doc_tokens']:,} document tokens) -> backend '{a.backend}'")
    print(f"estimated cost ({est['model']} ${est['in_per_m']:.2f}/M in, ${est['out_per_m']:.2f}/M out): "
          f"${est['low_usd']:.3f} - ${est['high_usd']:.3f}  (fitted on 3 measured runs: ${FIXED_USD_PER_DOC}/document + ${USD_PER_1K_CHARS}/1k chars, +-30%)")
    if not a.yes:
        sys.exit("this calls a paid LLM API. Re-run with --yes to proceed (use --limit to start small).")
    eval_id = datetime.now().strftime("%Y%m%d_%H%M%S") + f"_{a.name}"
    root = EVAL_RUNS / eval_id
    run_dirs: dict[str, Path] = {}
    with observability.eval_context(eval_id, a.name):
        for i, doc in enumerate(gold, 1):
            print(f"[{i}/{len(gold)}] {doc.doc_id}")
            try:
                run_dirs[doc.doc_id] = _run_one(a.backend, doc, prepared, root / "runs" / doc.doc_id, a.pdf)
            except Exception as e:                    # one bad document must not lose the evaluation
                print(f"  FAILED: {type(e).__name__}: {e}")
    ok = {k: v for k, v in run_dirs.items() if (v / "output.json").exists()}
    (root / "runs.json").write_text(json.dumps({k: str(v) for k, v in ok.items()}, indent=2), encoding="utf-8")
    score_and_report(gold, ok, a.name, eval_id, backend=a.backend, cfg=_cfg(a), out_dir=root, langfuse=not a.no_langfuse,
                     ops_dirs=list(run_dirs.values()))


def cmd_reconvert(a):
    """Rebuild output.json/manifest.json/document.txt of a finished evaluation from its stored docling-graph artifacts.
    Free (no LLM call). Use after converter fixes; with --export the runs also appear in the web UI (outputs/)."""
    import shutil
    from engine.api import save_compatible_files
    root = EVAL_RUNS / a.eval_id
    mapping: dict[str, str] = {}
    for run_dir in sorted((root / "runs").glob("*")):
        meta = next(run_dir.glob("*/metadata.json"), None)
        if meta is None:
            print(f"  {run_dir.name}: no docling artifacts (run failed before extraction finished), skipped")
            continue
        source = Path(json.loads(meta.read_text(encoding="utf-8"))["input"]["source"])
        save_compatible_files(run_dir.name, source, run_dir)
        mapping[run_dir.name] = str(run_dir)
        if a.export:
            dest = OUTPUTS / f"{a.eval_id}__{run_dir.name}"
            dest.mkdir(parents=True, exist_ok=True)
            for f in ("manifest.json", "output.json", "document.txt", "ops.json"):
                if (run_dir / f).exists():
                    shutil.copy(run_dir / f, dest / f)
            print(f"  exported -> {dest}")
    (root / "runs.json").write_text(json.dumps(mapping, indent=2), encoding="utf-8")
    print(f"reconverted {len(mapping)} runs; re-score with: score --gold <dataset> --eval-run {a.eval_id}")


def _read_history() -> list[dict]:
    return list(csv.DictReader(HISTORY.open(encoding="utf-8"))) if HISTORY.exists() else []


def cmd_history(a):
    rows = [r for r in _read_history() if not a.dataset or r["dataset"] == a.dataset]
    for r in rows[-a.n:]:
        f = lambda k: f"{float(r[k]):.3f}" if r.get(k) not in (None, "") else "  -  "  # noqa: E731
        print(f"{r['timestamp']}  {r['dataset']:16} {r['backend']:8} {r['git_sha']:8} docs={r['n_docs']:>3}  "
              f"entF1={f('entity_f1_lenient')} relF1={f('relation_f1_strict')} coref={f('coref_conll_f1')} cost=${f('cost_usd')}")


def _load_report(spec: str) -> dict:
    p = Path(spec)
    p = p if p.suffix == ".json" else EVAL_RUNS / spec / "report.json"
    return json.loads(p.read_text(encoding="utf-8"))


def cmd_compare(a):
    x, y = _load_report(a.a)["headline"], _load_report(a.b)["headline"]
    print(f"{'metric':28} {'A':>8} {'B':>8} {'B-A':>8}")
    for k in x:
        if isinstance(x[k], (int, float)) and isinstance(y.get(k), (int, float)):
            print(f"{k:28} {x[k]:8.3f} {y[k]:8.3f} {y[k] - x[k]:+8.3f}")


def cmd_gate(a):
    cur, base = _load_report(a.report)["headline"], _load_report(a.baseline)["headline"]
    bad = check_regression(cur, base, a.max_drop)
    print("REGRESSION:\n  " + "\n  ".join(bad) if bad else f"ok: no headline metric dropped by more than {a.max_drop}")
    sys.exit(1 if bad else 0)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="evalkit", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp):
        sp.add_argument("--fuzzy", type=float, default=0.90, help="min name similarity for fuzzy entity matching")
        sp.add_argument("--no-aliases", action="store_true", help="match on canonical names only")
        sp.add_argument("--no-langfuse", action="store_true")
        sp.add_argument("--backend", default="unknown", help="label stored with the report (docling|legacy|other)")

    sub.add_parser("datasets").set_defaults(fn=cmd_datasets)
    s = sub.add_parser("fetch"); s.add_argument("name"); s.add_argument("--force", action="store_true"); s.set_defaults(fn=cmd_fetch)
    s = sub.add_parser("prepare"); s.add_argument("name")
    s.add_argument("--limit", type=int); s.add_argument("--seed", type=int, default=0); s.add_argument("--max-chars", type=int)
    s.add_argument("--min-relations", type=int, default=0, help="keep only documents with at least N gold relations")
    s.set_defaults(fn=cmd_prepare)
    s = sub.add_parser("score", help="score existing run(s) against labels")
    s.add_argument("--gold", required=True, help="prepared dataset name/dir/gold.jsonl, a *.gt.json, or a raw labels file with --card")
    s.add_argument("--card", help="dataset card (name or yaml path) describing a raw labels file's format")
    s.add_argument("--gold-path", help="raw labels file/dir to convert on the fly (with --card)")
    s.add_argument("--run", action="append", help="run id under outputs/ or a path; repeatable")
    s.add_argument("--last", action="store_true"); s.add_argument("--eval-run")
    s.add_argument("--map", action="append", help="DOC_ID=RUN_ID pairing; repeatable")
    common(s); s.set_defaults(fn=cmd_score)
    s = sub.add_parser("run", help="run the pipeline over a prepared dataset and score it")
    s.add_argument("name"); s.add_argument("--backend", default="docling", choices=["docling", "legacy"])
    s.add_argument("--limit", type=int); s.add_argument("--yes", action="store_true"); s.add_argument("--pdf", action="store_true")
    s.add_argument("--fuzzy", type=float, default=0.90); s.add_argument("--no-aliases", action="store_true"); s.add_argument("--no-langfuse", action="store_true")
    s.set_defaults(fn=cmd_run)
    s = sub.add_parser("reconvert", help="free: rebuild a finished evaluation's output.json from stored docling artifacts")
    s.add_argument("eval_id"); s.add_argument("--export", action="store_true", help="also copy runs into outputs/ so the web UI lists them")
    s.set_defaults(fn=cmd_reconvert)
    s = sub.add_parser("history"); s.add_argument("--dataset"); s.add_argument("-n", type=int, default=20); s.set_defaults(fn=cmd_history)
    s = sub.add_parser("compare"); s.add_argument("a"); s.add_argument("b"); s.set_defaults(fn=cmd_compare)
    s = sub.add_parser("gate", help="exit 1 if headline metrics regressed vs a baseline report")
    s.add_argument("report"); s.add_argument("--baseline", required=True); s.add_argument("--max-drop", type=float, default=0.03)
    s.set_defaults(fn=cmd_gate)
    return p


def main(argv=None):
    a = build_parser().parse_args(argv)
    a.fn(a)
