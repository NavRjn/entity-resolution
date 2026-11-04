"""Single entry point for all checks.  Offline, free, never calls an LLM.

    uv run python check.py                 # backend tests + frontend lint + frontend build
    uv run python check.py --fast          # backend tests only
    uv run python check.py --preflight     # tests + local readiness report (keys, runs, servers)
    uv run python check.py --online        # also run the free network checks (OpenAI key, Langfuse prompts, Ollama)

Exit code is non-zero if any step FAILs.  Lint problems are reported as WARN (pre-existing style errors).
"""
import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FRONTEND = ROOT / "frontend"


def run_step(name, cmd, cwd, warn_only=False):
    print(f"\n=== {name} " + "=" * max(3, 60 - len(name)))
    start = time.time()
    try:
        code = subprocess.call(cmd, cwd=cwd)
    except FileNotFoundError as e:
        print(f"could not start: {e}")
        code = 127
    secs = time.time() - start
    status = "PASS" if code == 0 else ("WARN" if warn_only else "FAIL")
    return name, status, secs


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fast", action="store_true", help="backend tests only")
    ap.add_argument("--preflight", action="store_true", help="also run preflight.py (local readiness report)")
    ap.add_argument("--online", action="store_true", help="also run preflight.py --online (free network checks)")
    args = ap.parse_args()

    t0 = time.time()
    results = [run_step("backend tests (pytest)", [sys.executable, "-m", "pytest"], ROOT)]

    if not args.fast:
        npm = shutil.which("npm")
        if not npm or not (FRONTEND / "node_modules").exists():
            print("\n[skip] frontend checks: npm or frontend/node_modules missing (run `npm install` in frontend/)")
            results += [("frontend lint", "SKIP", 0.0), ("frontend build", "SKIP", 0.0)]
        else:
            results.append(run_step("frontend lint", [npm, "run", "lint"], FRONTEND, warn_only=True))
            results.append(run_step("frontend build", [npm, "run", "build"], FRONTEND))

    if args.preflight or args.online:
        cmd = [sys.executable, str(ROOT / "preflight.py")] + (["--online"] if args.online else [])
        results.append(run_step("preflight", cmd, ROOT))

    print("\n" + "=" * 66)
    for name, status, secs in results:
        print(f"{status:5} {name:32} {secs:6.1f}s")
    print(f"total {time.time() - t0:.1f}s")
    failed = [n for n, s, _ in results if s == "FAIL"]
    print("RESULT: " + ("FAILED -> " + ", ".join(failed) if failed else "OK (safe to run / demo)"))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
