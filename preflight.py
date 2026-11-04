"""Readiness report to run before a demo or a paid run.  Never prints secret values.

    uv run python preflight.py             # local only: keys present, deps, saved runs, local servers
    uv run python preflight.py --online    # + free network checks (no LLM tokens consumed):
                                           #   OpenAI GET /v1/models, Langfuse prompt fetch, Ollama /api/tags

FAIL = something that will break a run/demo.  WARN = worth knowing.  Exit code 1 only on FAIL.
"""
import argparse
import base64
import importlib
import json
import socket
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
results = []  # (status, label, detail)


def report(status, label, detail=""):
    results.append((status, label, detail))
    print(f"{status:4} {label}" + (f"  -- {detail}" if detail else ""))


def port_open(port, host="127.0.0.1"):
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        try:
            with socket.create_connection(("::1", port), timeout=1):
                return True
        except OSError:
            return False


def http_get(url, headers=None, timeout=10):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, json.loads(r.read().decode("utf-8") or "null")


# ---------------------------------------------------------------- local checks
def load_env():
    env_path = ROOT / ".env"
    if not env_path.exists():
        report("FAIL", ".env file", "missing (needs OPENAI_API_LEGALDEV, OPENAI_API_KEY, LANGFUSE_*)")
        return {}
    from dotenv import dotenv_values

    env = {k: v for k, v in dotenv_values(env_path).items() if v}
    for key, why in [
        ("OPENAI_API_KEY", "used by docling-graph (the /run endpoint)"),
        ("OPENAI_API_LEGALDEV", "used by legacy run.py"),
        ("LANGFUSE_PUBLIC_KEY", "run.py fetches prompts from Langfuse at import"),
        ("LANGFUSE_SECRET_KEY", "run.py fetches prompts from Langfuse at import"),
    ]:
        report("OK" if key in env else "FAIL", f".env {key}", "set" if key in env else f"missing -- {why}")
    if "LANGFUSE_BASE_URL" not in env and "LANGFUSE_HOST" not in env:
        report("WARN", ".env LANGFUSE_BASE_URL", "not set; Langfuse defaults to its cloud EU host")
    return env


def check_dependencies():
    if not (ROOT.parent / "docling-graph").is_dir():
        report("FAIL", "sibling ../docling-graph checkout", "missing (pyproject path dependency)")
    for mod in ("docling_graph", "fastapi", "uvicorn", "rapidfuzz", "networkx", "engine.template"):
        try:
            importlib.import_module(mod)
            report("OK", f"import {mod}")
        except Exception as e:
            report("FAIL", f"import {mod}", f"{type(e).__name__}: {e}")


def check_runs():
    outputs = ROOT / "outputs"
    run_dirs = sorted(p for p in outputs.iterdir() if p.is_dir()) if outputs.exists() else []
    if not run_dirs:
        report("WARN", "saved runs in outputs/", "none -- the Runs page will be empty")
        return
    bad, incomplete, ok = [], [], 0
    for d in run_dirs:
        out, manifest = d / "output.json", d / "manifest.json"
        if not out.exists():
            incomplete.append(d.name)
            continue
        try:
            data = json.loads(out.read_text(encoding="utf-8"))
            json.loads(manifest.read_text(encoding="utf-8"))
            problems = []
            for e in data["entities"]:
                if not {"entity_id", "canonical_name", "entity_type"} <= e.keys():
                    problems.append("entity missing keys")
                elif not all(isinstance(a, str) for a in e.get("aliases", [])):
                    problems.append("non-string alias (GET /graph would 500)")
            for r in data["relationships"]:
                if not {"source_entity_id", "target_entity_id", "relationship_type", "citation"} <= r.keys():
                    problems.append("relationship missing keys (old schema? GET /graph would 500)")
            if problems:
                bad.append(f"{d.name}: {sorted(set(problems))[0]}")
            else:
                ok += 1
        except Exception as e:
            bad.append(f"{d.name}: {type(e).__name__}: {e}")
    report("OK" if ok else "WARN", "saved runs loadable", f"{ok} of {len(run_dirs)}")
    for b in bad:
        report("WARN", "  broken run", b)
    if incomplete:
        report("WARN", "  runs without output.json (pending or failed)", ", ".join(incomplete[:5]) + (" ..." if len(incomplete) > 5 else ""))


def check_uploads():
    ups = ROOT / "uploads"
    files = [p for p in ups.iterdir() if p.is_file()] if ups.exists() else []
    report("OK" if files else "WARN", "uploads/", f"{len(files)} file(s)" if files else "empty")


def check_local_servers():
    report("OK" if port_open(8000) else "WARN", "API on :8000", "up" if port_open(8000) else "not running (uv run python -m uvicorn api.main:app --reload)")
    report("OK" if port_open(5173) else "WARN", "frontend on :5173", "up" if port_open(5173) else "not running (cd frontend && npm run dev)")


# ---------------------------------------------------------------- online (free) checks
def check_openai(env):
    for key in ("OPENAI_API_KEY", "OPENAI_API_LEGALDEV"):
        if key not in env:
            continue
        try:
            _, body = http_get("https://api.openai.com/v1/models", {"Authorization": f"Bearer {env[key]}"})
            ids = {m["id"] for m in body["data"]}
            report("OK" if "gpt-4o" in ids else "FAIL", f"OpenAI {key}", "valid, gpt-4o available" if "gpt-4o" in ids else "valid, but gpt-4o NOT visible")
        except urllib.error.HTTPError as e:
            report("FAIL", f"OpenAI {key}", f"HTTP {e.code} (invalid or revoked key?)")
        except Exception as e:
            report("FAIL", f"OpenAI {key}", f"{type(e).__name__}: {e}")


def check_langfuse(env):
    if "LANGFUSE_PUBLIC_KEY" not in env or "LANGFUSE_SECRET_KEY" not in env:
        return
    base = (env.get("LANGFUSE_BASE_URL") or env.get("LANGFUSE_HOST") or "https://cloud.langfuse.com").rstrip("/")
    token = base64.b64encode(f"{env['LANGFUSE_PUBLIC_KEY']}:{env['LANGFUSE_SECRET_KEY']}".encode()).decode()
    for prompt in ("entity-system", "relationship-system"):
        try:
            http_get(f"{base}/api/public/v2/prompts/{prompt}", {"Authorization": f"Basic {token}"})
            report("OK", f"Langfuse prompt '{prompt}'")
        except urllib.error.HTTPError as e:
            report("FAIL", f"Langfuse prompt '{prompt}'", f"HTTP {e.code} -- run.py will crash on import")
        except Exception as e:
            report("FAIL", f"Langfuse prompt '{prompt}'", f"{type(e).__name__}: {e}")


def check_ollama():
    try:
        _, body = http_get("http://127.0.0.1:11434/api/tags", timeout=3)
        report("OK", "Ollama on :11434", f"{len(body.get('models', []))} model(s)")
    except Exception:
        report("WARN", "Ollama on :11434", "not reachable (only needed for local-model runs)")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--online", action="store_true", help="run the free network checks too")
    args = ap.parse_args()

    print("--- local ---")
    env = load_env()
    check_dependencies()
    check_runs()
    check_uploads()
    check_local_servers()
    if args.online:
        print("--- online (free; no LLM tokens) ---")
        check_openai(env)
        check_langfuse(env)
        check_ollama()
    else:
        print("--- online checks skipped (use --online) ---")

    fails = [r for r in results if r[0] == "FAIL"]
    warns = [r for r in results if r[0] == "WARN"]
    print(f"\n{len(fails)} FAIL, {len(warns)} WARN")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
