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


def get_latest_run() -> Path:
    files = list(OUTPUT_DIR.glob("*.json"))
    if not files:
        raise FileNotFoundError("No run files found in outputs/")
    return max(files, key=lambda f: f.stat().st_mtime)


def evaluate_run(pred_file: Path, truth_file: Path):
    with open(truth_file) as f:
        truth_data = json.load(f)
    with open(pred_file) as f:
        pred_data_raw = json.load(f)["entities"]

    # Filter out locations if you only care about orgs/people (based on your old script)
    truth =  [e for e in truth_data if e.get("entity_type") != "location"]
    # Filter out locations if you only care about orgs/people (based on your old script)
    pred_data =  [e for e in pred_data_raw if e.get("entity_type") != "location"]

    matched_truth = set()
    matched_preds = set()

    # Evaluation Logic: Check if ground truth exists in Canonical Names OR Aliases
    for t_idx, t_ent in enumerate(truth):
        t_norm = normalize(t_ent["entity_name"])

        for p_idx, p_ent in enumerate(pred_data):
            if p_idx in matched_preds: continue

            # Check canonical name and all aliases
            candidates = [p_ent["canonical_name"]] + p_ent.get("aliases", [])

            for candidate in candidates:
                if fuzz.ratio(t_norm, normalize(candidate)) > 90:
                    matched_truth.add(t_idx)
                    matched_preds.add(p_idx)
                    break

            if t_idx in matched_truth:
                break

    # Calculate Metrics
    tp = len(matched_truth)
    fn = len(truth) - tp
    fp = len(pred_data) - len(matched_preds)

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0
    f1 = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0

    # Display Metrics
    console.print(Panel(f"Evaluation Report: [bold cyan]{pred_file.name}[/bold cyan]", expand=False))

    metrics_table = Table(show_header=True, header_style="bold magenta")
    metrics_table.add_column("Metric")
    metrics_table.add_column("Score", justify="right")

    metrics_table.add_row("Ground Truth Entities", str(len(truth)))
    metrics_table.add_row("Predicted Entities", str(len(pred_data)))
    metrics_table.add_row("True Positives (Matched)", f"[green]{tp}[/green]")
    metrics_table.add_row("False Positives (Extra)", f"[yellow]{fp}[/yellow]")
    metrics_table.add_row("False Negatives (Missed)", f"[red]{fn}[/red]")
    metrics_table.add_row("---", "---")
    metrics_table.add_row("Precision", f"{precision:.2%}")
    metrics_table.add_row("Recall", f"{recall:.2%}")
    metrics_table.add_row("F1 Score", f"[bold green]{f1:.2%}[/bold green]")

    console.print(metrics_table)

    # Display Missed Entities
    if fn > 0:
        missed_table = Table(title="Missed Ground Truth Entities (False Negatives)", style="red")
        missed_table.add_column("Entity Name")
        missed_table.add_column("Type")
        for i, t_ent in enumerate(truth):
            if i not in matched_truth:
                missed_table.add_row(t_ent.get("entity_name", "N/A"), t_ent.get("entity_type", "N/A"))
        console.print(missed_table)

    # Display Over-extracted Entities
    if fp > 0:
        extra_table = Table(title="Extra Predicted Entities (False Positives)", style="yellow")
        extra_table.add_column("Canonical Name")
        extra_table.add_column("Type")
        for i, p_ent in enumerate(pred_data):
            if i not in matched_preds:
                extra_table.add_row(p_ent.get("canonical_name", "N/A"), p_ent.get("entity_type", "N/A"))
        console.print(extra_table)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--truth", type=str, default="data/test-gt.json")
    parser.add_argument("--run", type=str, default=None, help="Specific run file to test. Defaults to latest.")
    args = parser.parse_args()

    run_path = Path(args.run) if args.run else get_latest_run()
    truth_path = Path(args.truth)

    evaluate_run(run_path, truth_path)