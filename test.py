import argparse
import json
import re
from pathlib import Path
from rapidfuzz import fuzz
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

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

    #
    # ENTITIES
    truth_entities = truth_data["entities"]
    pred_entities = pred_data["entities"]

    matched_truth = set()
    matched_preds = set()

    for t_idx, t_ent in enumerate(truth_entities):
        t_norm = normalize(t_ent["entity_name"])

        for p_idx, p_ent in enumerate(pred_entities):
            if p_idx in matched_preds: continue

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

    #
    # RELATIONSHIPS
    #
    pred_id_to_name = {ent["entity_id"]: ent["canonical_name"] for ent in pred_entities}

    # Truth edges: use canonical form
    truth_edges = set(
        (canon(rel["source"]), rel["relationship"].lower(), canon(rel["target"]))
        for rel in truth_data.get("relationships", [])
    )

    # Predicted edges: use canonical form
    pred_edges = set()
    for rel in pred_data.get("relationships", []):
        src_id = rel["source_entity_id"].strip("[]")
        tgt_id = rel["target_entity_id"].strip("[]")
        source_name = pred_id_to_name.get(src_id)
        target_name = pred_id_to_name.get(tgt_id)
        if not source_name or not target_name:
            continue
        pred_edges.add((
            canon(source_name),
            rel["relationship_type"].lower(),
            canon(target_name)
        ))

    rel_tp = len(truth_edges & pred_edges)
    rel_fp = len(pred_edges - truth_edges)
    rel_fn = len(truth_edges - pred_edges)

    rel_precision = rel_tp / (rel_tp + rel_fp) if (rel_tp + rel_fp) else 0
    rel_recall = rel_tp / (rel_tp + rel_fn) if (rel_tp + rel_fn) else 0
    rel_f1 = 2 * rel_precision * rel_recall / (rel_precision + rel_recall) if (rel_precision + rel_recall) else 0

    #
    # REPORT
    #
    console.print(Panel(f"Evaluation Report: [bold cyan]{pred_file.name}[/bold cyan]", expand=False))

    table = Table()
    table.add_column("Metric")
    table.add_column("Score", justify="right")
    table.add_row("Entity Precision", f"{entity_precision:.2%}")
    table.add_row("Entity Recall", f"{entity_recall:.2%}")
    table.add_row("Entity F1", f"{entity_f1:.2%}")
    table.add_row("---", "---")
    table.add_row("Relationship Precision", f"{rel_precision:.2%}")
    table.add_row("Relationship Recall", f"{rel_recall:.2%}")
    table.add_row("Relationship F1", f"{rel_f1:.2%}")

    console.print(table)
    console.print()
    console.print(
        f"[green]Entity TP:[/green] {entity_tp}  "
        f"[yellow]FP:[/yellow] {entity_fp}  "
        f"[red]FN:[/red] {entity_fn}"
    )
    console.print(
        f"[green]Relationship TP:[/green] {rel_tp}  "
        f"[yellow]FP:[/yellow] {rel_fp}  "
        f"[red]FN:[/red] {rel_fn}"
    )

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
    parser.add_argument("--file", type=str, default="data/test.gt.json")
    parser.add_argument("--run", type=str, default=None, help="Specific run file to test. Defaults to latest.")
    args = parser.parse_args()

    run_path = Path(args.run) if args.run else get_latest_run()
    truth_path = Path("data") / (args.file + ".gt.json")

    evaluate_run(run_path, truth_path)