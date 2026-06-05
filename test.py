import argparse
import json
import re
from pathlib import Path
from rapidfuzz import fuzz
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from collections import defaultdict

console = Console()

DATA_DIR = Path('data')
OUTPUT_DIR = Path('outputs')
METRICS_DIR = Path('metrics')
METRICS_DIR.mkdir(exist_ok=True)


def normalize(text: str) -> str:
    if not text: return ""
    return re.sub(r'[^a-z0-9]', '', str(text).lower())


def canon(text: str) -> str:
    """
    Canonicalize text for relationship evaluation:
    - Lowercase
    - Strip parenthetical suffixes like (CTSA), (FICB)
    - Remove non-alphanumeric characters
    """
    if not text:
        return ""
    text = text.lower()
    text = re.sub(r'\(.*?\)', '', text)  # Remove parentheses content
    return re.sub(r'[^a-z0-9]', '', text)


def get_latest_run() -> Path:
    files = list(OUTPUT_DIR.glob("*.json"))
    if not files:
        raise FileNotFoundError("No run files found in outputs/")
    return max(files, key=lambda f: f.stat().st_mtime)


def evaluate_run(pred_file: Path, truth_file: Path):

    with open(truth_file) as f:
        truth_data = json.load(f)

    with open(pred_file) as f:
        pred_data = json.load(f)

    # --- ENTITIES ---
    truth_entities = truth_data["entities"]
    pred_entities = pred_data["entities"]

    matched_truth = set()
    matched_preds = set()
    # truth_id_to_name = {ent["entity_id"]: ent["entity_name"] for ent in truth_entities}
    pred_id_to_name = {ent["entity_id"]: ent["canonical_name"] for ent in pred_entities}

    for t_idx, t_ent in enumerate(truth_entities):
        t_norm = normalize(t_ent["entity_name"])

        for p_idx, p_ent in enumerate(pred_entities):
            if p_idx in matched_preds:
                continue

            candidates = [p_ent["canonical_name"]] + p_ent.get("aliases", [])
            if any(fuzz.ratio(t_norm, normalize(c)) > 90 for c in candidates):
                matched_truth.add(t_idx)
                matched_preds.add(p_idx)
                break

    entity_tp = len(matched_truth)
    entity_fn = len(truth_entities) - entity_tp
    entity_fp = len(pred_entities) - len(matched_preds)

    entity_precision = entity_tp / (entity_tp + entity_fp) if (entity_tp + entity_fp) else 0
    entity_recall = entity_tp / (entity_tp + entity_fn) if (entity_tp + entity_fn) else 0
    entity_f1 = (
        2 * entity_precision * entity_recall / (entity_precision + entity_recall)
        if (entity_precision + entity_recall) else 0
    )

    # --- RELATIONSHIPS ---
    truth_edges = set(
        (canon(rel["source"]), rel["relationship"].lower(), canon(rel["target"]))
        for rel in truth_data.get("relationships", [])
    )

    pred_edges = set()
    for rel in pred_data.get("relationships", []):
        src_id = rel["source_entity_id"].strip("[]")
        tgt_id = rel["target_entity_id"].strip("[]")
        source_name = pred_id_to_name.get(src_id, src_id)
        target_name = pred_id_to_name.get(tgt_id, tgt_id)
        pred_edges.add((canon(source_name), rel["relationship_type"].lower(), canon(target_name)))

    tp_edges = truth_edges & pred_edges
    fp_edges = pred_edges - truth_edges
    fn_edges = truth_edges - pred_edges

    rel_tp = len(tp_edges)
    rel_fp = len(fp_edges)
    rel_fn = len(fn_edges)

    rel_precision = rel_tp / (rel_tp + rel_fp) if (rel_tp + rel_fp) else 0
    rel_recall = rel_tp / (rel_tp + rel_fn) if (rel_tp + rel_fn) else 0
    rel_f1 = 2 * rel_precision * rel_recall / (rel_precision + rel_recall) if (rel_precision + rel_recall) else 0

    # --- CHUNK STATS ---
    chunk_stats = defaultdict(lambda: {"tp": 0, "fp": 0})
    for rel in pred_data.get("relationships", []):
        src_id = rel["source_entity_id"].strip("[]")
        tgt_id = rel["target_entity_id"].strip("[]")
        source_name = pred_id_to_name.get(src_id, src_id)
        target_name = pred_id_to_name.get(tgt_id, tgt_id)
        edge = (canon(source_name), rel["relationship_type"].lower(), canon(target_name))
        chunk_id = rel.get("chunk_id", "unknown")
        if edge in tp_edges:
            chunk_stats[chunk_id]["tp"] += 1
        else:
            chunk_stats[chunk_id]["fp"] += 1

    # --- REPORT METRICS ---
    console.print(Panel(f"Evaluation Report: [bold cyan]{pred_file.name}[/bold cyan]", expand=False))

    summary_table = Table()
    summary_table.add_column("Metric")
    summary_table.add_column("Score", justify="right")
    summary_table.add_row("Entity Precision", f"{entity_precision:.2%}")
    summary_table.add_row("Entity Recall", f"{entity_recall:.2%}")
    summary_table.add_row("Entity F1", f"{entity_f1:.2%}")
    summary_table.add_row("---", "---")
    summary_table.add_row("Relationship Precision", f"{rel_precision:.2%}")
    summary_table.add_row("Relationship Recall", f"{rel_recall:.2%}")
    summary_table.add_row("Relationship F1", f"{rel_f1:.2%}")
    console.print(summary_table)

    console.print(f"\n[green]Entity TP:[/green] {entity_tp}  [yellow]FP:[/yellow] {entity_fp}  [red]FN:[/red] {entity_fn}")
    console.print(f"[green]Relationship TP:[/green] {rel_tp}  [yellow]FP:[/yellow] {rel_fp}  [red]FN:[/red] {rel_fn}\n")

    # --- TP TABLE ---
    if tp_edges:
        tp_table = Table(title="True Positive Relationships")
        tp_table.add_column("Source", style="cyan")
        tp_table.add_column("Relationship", style="magenta")
        tp_table.add_column("Target", style="cyan")
        for s, r, t in tp_edges:
            tp_table.add_row(s, r, t)
        console.print(tp_table)

    # --- FP / FN DIFF TABLE (SIDE-BY-SIDE) ---

    def edge_to_row(edge):
        s, r, t = edge
        return (s, r, t)

    fp_list = sorted([edge_to_row(e) for e in fp_edges])
    fn_list = sorted([edge_to_row(e) for e in fn_edges])

    max_len = max(len(fp_list), len(fn_list))

    diff_table = Table(title="False Positives vs False Negatives (Aligned View)")

    diff_table.add_column("FP Source", style="red")
    diff_table.add_column("FP Relation", style="red")
    diff_table.add_column("FP Target", style="red")

    diff_table.add_column("│", justify="center")

    diff_table.add_column("FN Source", style="green")
    diff_table.add_column("FN Relation", style="green")
    diff_table.add_column("FN Target", style="green")

    for i in range(max_len):
        fp_row = fp_list[i] if i < len(fp_list) else ("", "", "")
        fn_row = fn_list[i] if i < len(fn_list) else ("", "", "")

        diff_table.add_row(
            fp_row[0], fp_row[1], fp_row[2],
            "│",
            fn_row[0], fn_row[1], fn_row[2],
        )

    console.print(diff_table)

    # --- CHUNK TABLE ---
    chunk_table = Table(title="Relationship Results By Chunk")
    chunk_table.add_column("Chunk")
    chunk_table.add_column("TP", justify="right")
    chunk_table.add_column("FP", justify="right")
    chunk_table.add_column("FP Rate", justify="right")
    for chunk_id in sorted(chunk_stats.keys()):
        tp = chunk_stats[chunk_id]["tp"]
        fp = chunk_stats[chunk_id]["fp"]
        fp_rate = fp / (tp + fp) if (tp + fp) else 0
        chunk_table.add_row(str(chunk_id), str(tp), str(fp), f"{fp_rate:.2%}")
    console.print(chunk_table)

    # --- SAVE METRICS ---
    report = {
        "run_file": pred_file.name,
        "predicted_entities": len(pred_entities),
        "true_positives": rel_tp,
        "false_positives": rel_fp,
        "false_negatives": rel_fn,
        "precision": rel_precision,
        "recall": rel_recall,
        "f1": rel_f1,
    }
    metrics_file = METRICS_DIR / f"{pred_file.stem}.json"
    with open(metrics_file, "w") as f:
        json.dump(report, f, indent=2)
    console.print(f"\n[green]Saved metrics:[/green] {metrics_file}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", type=str, default="test")
    parser.add_argument("--run", type=str, default=None, help="Specific run file to test. Defaults to latest.")
    args = parser.parse_args()

    run_path = Path(args.run) if args.run else get_latest_run()
    truth_path = Path("data") / (args.file + ".gt.json")

    evaluate_run(run_path, truth_path)