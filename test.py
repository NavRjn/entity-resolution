"""Back-compatible entry point. The evaluation logic lives in the `evalkit` package.

    uv run python test.py --file test [--run RUN_ID]      same CLI as before
    uv run python -m evalkit -h                           full tool: datasets, post-hoc scoring, history, gating

Compared with the old script: Hungarian one-to-one alignment instead of first-fuzzy-hit, strict AND lenient
entity metrics, four relation strictness levels, label-free provenance/structure checks, bootstrap CIs, UTF-8 safe.
"""
import argparse
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("PYTHONUTF8", "1")
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

from evalkit.cli import latest_run, resolve_gold, score_and_report  # noqa: E402

DATA_DIR = Path("data")
OUTPUT_DIR = Path("outputs")
METRICS_DIR = Path("metrics")
METRICS_DIR.mkdir(exist_ok=True)


def evaluate_run(pred_file: Path, truth_file: Path, history: bool = False, langfuse: bool = False) -> dict:
    """Score one run's output.json against one data/*.gt.json. Writes metrics/<stem>.json (legacy keys + new ones)."""
    gold, dataset = resolve_gold(str(truth_file))
    report = score_and_report(gold, {gold[0].doc_id: pred_file}, dataset, pred_file.parent.name, out_dir=None,
                              history=history, langfuse=langfuse)
    rel = report["summary"]["relations"]["end_to_end"]["strict"]
    legacy = {"run_file": pred_file.name, "true_positives": rel["tp"], "false_positives": rel["fp"],
              "false_negatives": rel["fn"], "precision": rel["precision"] or 0.0, "recall": rel["recall"] or 0.0,
              "f1": rel["f1"] or 0.0, "headline": report["headline"]}
    (METRICS_DIR / f"{pred_file.stem}.json").write_text(json.dumps(legacy, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", type=str, default="test")
    parser.add_argument("--run", type=str, default=None, help="Run id under outputs/. Defaults to latest.")
    args = parser.parse_args()
    run_id = args.run or latest_run()
    evaluate_run(OUTPUT_DIR / run_id / "output.json", DATA_DIR / f"{args.file}.gt.json", history=True, langfuse=True)
