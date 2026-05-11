from run import evaluate_extraction
from pathlib import Path
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

DATA_DIR = Path('data')
OUTPUT_DIR = Path('outputs')
METRICS_DIR = Path('metrics')

if __name__ == "__main__":
    run_name = "20260511_214655.json"
    with open(DATA_DIR / "test-gt.json") as f:
        truth = json.load(f)
        truth = [e for e in truth if e["entity_type"] != "location"]
    with open(OUTPUT_DIR / run_name) as f:
        pred = json.load(f)

    result = evaluate_extraction(pred, truth)
    with open(METRICS_DIR / run_name, "w") as f:
        json.dump(result, f, indent=2)
    pretty_print_metrics(result)