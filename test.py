from lxml.html.builder import OUTPUT

from run import evaluate_extraction
from pathlib import Path
from datetime import datetime
import re
import json

from typing import Any, Dict

def pretty_print_metrics(metrics: Dict[str, Any], title: str = "Test Metrics") -> None:
    def is_list(v):
        return isinstance(v, list)

    # split metrics
    scalars = {k: v for k, v in metrics.items() if not is_list(v)}
    lists = {k: v for k, v in metrics.items() if is_list(v)}

    line = "=" * 60
    print(line)
    print(f"{title}")
    print(line)

    # print scalar metrics (sorted for stability)
    if scalars:
        print("\nScalar Metrics:")
        for k in sorted(scalars):
            v = scalars[k]
            if isinstance(v, float):
                print(f"  {k:<30} : {v:.4f}")
            else:
                print(f"  {k:<30} : {v}")

    # print list metrics
    if lists:
        print("\nList Metrics:")
        for k in sorted(lists):
            v = lists[k]
            print(f"\n  {k} ({len(v)} items):")
            for item in v:
                print(f"    - {item}")

    print(line)


def get_last(path: Path) -> Path | None:
    """
    Return the most recent file matching YYYYMMDD_HHMMSS.json
    in the given directory. Returns None if no match.
    """

    pattern = re.compile(r"(\d{8}_\d{6})\.json$")

    candidates = []

    for file in path.iterdir():
        if not file.is_file():
            continue

        match = pattern.match(file.name)
        if not match:
            continue

        try:
            ts = datetime.strptime(match.group(1), "%Y%m%d_%H%M%S")
            candidates.append((ts, file))
        except ValueError:
            continue

    if not candidates:
        return None

    # sort by timestamp, return latest
    return max(candidates, key=lambda x: x[0])[1]

DATA_DIR = Path('data')
OUTPUT_DIR = Path('outputs')
METRICS_DIR = Path('metrics')

if __name__ == "__main__":
    run_name = None
    run_path = run_name or get_last(OUTPUT_DIR)
    run_name = run_path.name.split(".")[0]

    with open(DATA_DIR / "test-gt.json") as f:
        truth = json.load(f)
        truth = [e for e in truth if e["entity_type"] != "location"]
    with open(run_path) as f:
        pred = json.load(f)

    print("RUN: ", run_name)
    print("TRUTH: ", [e.get("entity_name") for e in truth])
    print("PRED: ", [e.get("canonical_name") for e in pred])

    result = evaluate_extraction(pred, truth)
    with open(METRICS_DIR / run_name, "w") as f:
        json.dump(result, f, indent=2)
    pretty_print_metrics(result)