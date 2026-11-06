"""MLOps layer over Langfuse. One place, used by the legacy pipeline, the docling engine, the API and evalkit.

What it gives every run, regardless of backend:
    * one trace per run, session_id = run_id, tagged with backend/dataset, versioned with the git sha
    * a span per pipeline stage (and wall-time per stage in ops.json)
    * every litellm.completion (docling-graph's LLM calls) as a generation with tokens, cost, latency, errors
    * outputs/<run_id>/ops.json: stage latencies, tokens, USD cost, trace id, status/error (machine readable,
      so evalkit can join quality metrics with cost and latency without calling Langfuse)
    * evaluation scores written back onto the run's trace (record_scores) and onto the evaluation session

Design rules: observability must never break or slow a run (every Langfuse call is guarded and degrades to a
no-op when keys are missing, LANGFUSE_ENABLED=0, or the SDK is stubbed), and document text is NOT sent to
Langfuse by the instrumentation added here unless OBS_CAPTURE_CONTENT=1 (client documents are sensitive;
the legacy langfuse.openai wrapper in run.py still captures prompts as before).
"""
from __future__ import annotations

import contextvars
import functools
import json
import os
import subprocess
import sys
import threading
import time
from contextlib import ExitStack, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Optional

_current: contextvars.ContextVar[Optional["RunOps"]] = contextvars.ContextVar("run_ops", default=None)
_last: Optional["RunOps"] = None          # fallback for worker threads that lost the contextvar
_client_cache: dict = {}
_git_cache: dict = {}


# ----------------------------------------------------------------------------- client

def enabled() -> bool:
    return (os.getenv("LANGFUSE_ENABLED", "1") != "0"
            and bool(os.getenv("LANGFUSE_PUBLIC_KEY")) and bool(os.getenv("LANGFUSE_SECRET_KEY")))


def client():
    """The Langfuse client, or None when disabled/unavailable. Never raises."""
    if not enabled():
        return None
    try:
        import langfuse
        return langfuse.get_client()       # resolved at call time so test stubs work
    except Exception:
        return None


def capture_content() -> bool:
    """Only governs generations created by instrument_litellm(); see redact_enabled() for the global switch."""
    return os.getenv("OBS_CAPTURE_CONTENT", "0") == "1"


def redact_enabled() -> bool:
    return os.getenv("OBS_REDACT_CONTENT", "0") == "1"


def _mask(data: Any) -> Any:
    """Langfuse `mask` hook: keep structure, numbers and sizes; drop every string's content."""
    if isinstance(data, str):
        return f"[redacted {len(data)} chars]"
    if isinstance(data, dict):
        return {k: _mask(v) for k, v in data.items()}
    if isinstance(data, (list, tuple)):
        return [_mask(v) for v in data]
    return data


def _init_masked_client() -> None:
    """OBS_REDACT_CONTENT=1: register the Langfuse singleton with a mask BEFORE run.py calls get_client().

    Needed because langfuse.openai (imported by run.py, hence by the docling engine) captures full prompts,
    i.e. document excerpts, for every OpenAI call. With the mask only sizes leave the machine.
    """
    if redact_enabled() and enabled():
        try:
            from langfuse import Langfuse
            Langfuse(mask=_mask)
        except Exception:
            pass


def _auto_traced(model: str) -> bool:
    """True when langfuse.openai already records this call (a second generation would double-count cost)."""
    m = str(model).lower().removeprefix("openai/")
    return "langfuse.openai" in sys.modules and m.startswith(("gpt-", "o1", "o3", "o4", "chatgpt"))


def git_info() -> dict:
    if not _git_cache:
        def run(*a):
            return subprocess.check_output(["git", *a], cwd=Path(__file__).parent, text=True,
                                           stderr=subprocess.DEVNULL, timeout=5).strip()
        try:
            _git_cache.update(sha=run("rev-parse", "--short", "HEAD"), branch=run("rev-parse", "--abbrev-ref", "HEAD"),
                              dirty=bool(run("status", "--porcelain", "--untracked-files=no")))
        except Exception:
            _git_cache.update(sha="unknown", branch="unknown", dirty=False)
    return dict(_git_cache)


# ----------------------------------------------------------------------------- run state

class RunOps:
    """Thread-safe accumulator for one run's operational numbers."""

    def __init__(self, run_id: str, backend: str, meta: dict | None = None):
        self.run_id, self.backend, self.meta = run_id, backend, meta or {}
        self.started = time.perf_counter()
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.stages: dict[str, float] = {}
        self.llm = {"calls": 0, "errors": 0, "prompt_tokens": 0, "completion_tokens": 0, "cost_usd": 0.0,
                    "llm_seconds": 0.0, "by_model": {}}
        self.trace_id: Optional[str] = None
        self.status, self.error = "running", None
        self._lock = threading.Lock()

    def add_stage(self, name: str, seconds: float) -> None:
        with self._lock:
            self.stages[name] = self.stages.get(name, 0.0) + seconds

    def add_llm(self, model: str, prompt: int, completion: int, cost: float, seconds: float, error: bool) -> None:
        with self._lock:
            l = self.llm
            l["calls"] += 1
            l["errors"] += int(error)
            l["prompt_tokens"] += prompt
            l["completion_tokens"] += completion
            l["cost_usd"] += cost
            l["llm_seconds"] += seconds
            m = l["by_model"].setdefault(str(model), {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "cost_usd": 0.0})
            m["calls"] += 1
            m["prompt_tokens"] += prompt
            m["completion_tokens"] += completion
            m["cost_usd"] += cost

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id, "backend": self.backend, "status": self.status, "error": self.error,
            "started_at": self.started_at, "latency_s": round(time.perf_counter() - self.started, 3),
            "stages_s": {k: round(v, 3) for k, v in self.stages.items()},
            "llm": {**self.llm, "cost_usd": round(self.llm["cost_usd"], 6), "llm_seconds": round(self.llm["llm_seconds"], 3)},
            "trace_id": self.trace_id, "git": git_info(), "meta": self.meta,
        }

    def write(self, output_dir: Path | None) -> None:
        if output_dir:
            try:
                Path(output_dir).mkdir(parents=True, exist_ok=True)
                (Path(output_dir) / "ops.json").write_text(json.dumps(self.to_dict(), indent=2, default=str), encoding="utf-8")
            except Exception:
                pass


_eval: contextvars.ContextVar[Optional[dict]] = contextvars.ContextVar("eval_ctx", default=None)


@contextmanager
def eval_context(eval_id: str, dataset: str) -> Iterator[None]:
    """Runs started inside share one Langfuse session (= the evaluation) and are tagged 'eval' + dataset."""
    token = _eval.set({"eval_id": eval_id, "dataset": dataset})
    try:
        yield
    finally:
        _eval.reset(token)


def current_ops() -> Optional[RunOps]:
    return _current.get() or _last


def _enter(stack: ExitStack, factory) -> Any:
    """Enter a context manager built by `factory`, swallowing observability failures."""
    try:
        return stack.enter_context(factory())
    except Exception:
        return None


def _meta_str(d: dict | None) -> dict[str, str]:
    return {str(k): str(v)[:190] for k, v in (d or {}).items() if v is not None}


@contextmanager
def run_trace(run_id: str, *, backend: str, output_dir: Path | None = None, name: str = "entity_resolution_run",
              metadata: dict | None = None, tags: list[str] | None = None, session_id: str | None = None,
              input: Any = None) -> Iterator[RunOps]:
    """Wrap one end-to-end run. Re-raises failures after recording them (status=failed + error in ops.json)."""
    global _last
    g = git_info()
    ev = _eval.get()
    if ev:
        session_id, tags = session_id or ev["eval_id"], [*(tags or []), "eval", ev["dataset"]]
    meta = {"backend": backend, "git_sha": g["sha"], "git_dirty": g["dirty"], **(ev or {}), **(metadata or {})}
    ops = RunOps(run_id, backend, meta)
    token = _current.set(ops)
    prev_last, _last = _last, ops
    cl = client()
    root = None
    try:
        with ExitStack() as stack:
            if cl:
                try:
                    from langfuse import propagate_attributes
                    _enter(stack, lambda: propagate_attributes(
                        session_id=session_id or run_id, trace_name=name, version=g["sha"],
                        tags=[backend, *(tags or [])], metadata=_meta_str(meta)))
                except Exception:
                    pass
                root = _enter(stack, lambda: cl.start_as_current_observation(
                    as_type="span", name=name, input=input, metadata=meta))
                try:
                    ops.trace_id = cl.get_current_trace_id()
                except Exception:
                    pass
            try:
                yield ops
                ops.status = "completed"
            except BaseException as e:
                ops.status, ops.error = "failed", f"{type(e).__name__}: {e}"[:500]
                raise
            finally:
                try:
                    if cl and root is not None:
                        root.update(output={"status": ops.status, **ops.to_dict()["llm"]},
                                    level="ERROR" if ops.status == "failed" else "DEFAULT",
                                    status_message=ops.error)
                except Exception:
                    pass
    finally:
        ops.write(output_dir)
        _current.reset(token)
        _last = prev_last
        if cl:
            try:
                cl.flush()
            except Exception:
                pass


@contextmanager
def stage(name: str, **meta: Any) -> Iterator[None]:
    """Time a pipeline stage and (when enabled) emit it as a span under the current run trace."""
    ops = current_ops()
    cl = client() if ops else None
    t0 = time.perf_counter()
    with ExitStack() as stack:
        if cl:
            _enter(stack, lambda: cl.start_as_current_observation(as_type="span", name=name, metadata=meta or None))
        try:
            yield
        finally:
            if ops:
                ops.add_stage(name, time.perf_counter() - t0)


# ----------------------------------------------------------------------------- litellm (docling-graph's LLM calls)

def instrument_litellm() -> bool:
    """Wrap litellm.completion so every call becomes a Langfuse generation + tokens/cost in RunOps. Idempotent."""
    try:
        import litellm
    except Exception:
        return False
    if getattr(litellm.completion, "_obs_wrapped", False):
        return True
    orig = litellm.completion

    @functools.wraps(orig)
    def wrapped(*args, **kwargs):
        ops = current_ops()
        if ops is None:
            return orig(*args, **kwargs)
        model = kwargs.get("model") or (args[0] if args else "unknown")
        cl = client()
        t0 = time.perf_counter()
        with ExitStack() as stack:
            gen = None
            if cl and not _auto_traced(str(model)):
                tc = None
                try:
                    if ops.trace_id and cl.get_current_trace_id() != ops.trace_id:
                        tc = {"trace_id": ops.trace_id}     # worker thread without OTel context: attach to the run's trace
                except Exception:
                    pass
                msgs = kwargs.get("messages") or []
                gen = _enter(stack, lambda: cl.start_as_current_observation(
                    as_type="generation", name="litellm.completion", model=str(model), trace_context=tc,
                    input=msgs if capture_content() else {"messages": len(msgs), "chars": sum(len(str(m.get("content", ""))) for m in msgs)},
                    model_parameters={k: v for k, v in kwargs.items() if k in ("temperature", "max_tokens", "seed") and isinstance(v, (int, float))} or None))
            try:
                resp = orig(*args, **kwargs)
            except BaseException as e:
                ops.add_llm(model, 0, 0, 0.0, time.perf_counter() - t0, error=True)
                try:
                    if gen:
                        gen.update(level="ERROR", status_message=f"{type(e).__name__}: {e}"[:300])
                except Exception:
                    pass
                raise
            if kwargs.get("stream"):
                ops.add_llm(model, 0, 0, 0.0, time.perf_counter() - t0, error=False)
                return resp
            usage = getattr(resp, "usage", None)
            pt = int(getattr(usage, "prompt_tokens", 0) or 0)
            ct = int(getattr(usage, "completion_tokens", 0) or 0)
            try:
                cost = float(litellm.completion_cost(completion_response=resp) or 0.0)
            except Exception:
                cost = 0.0
            ops.add_llm(model, pt, ct, cost, time.perf_counter() - t0, error=False)
            try:
                if gen:
                    out = {"usage_details": {"input": pt, "output": ct}}
                    if cost:
                        out["cost_details"] = {"total": cost}
                    if capture_content():
                        out["output"] = resp.choices[0].message.content
                    gen.update(**out)
            except Exception:
                pass
            return resp

    wrapped._obs_wrapped = True
    litellm.completion = wrapped
    return True


# ----------------------------------------------------------------------------- evaluation write-back

def record_scores(metrics: dict, *, trace_id: str | None = None, session_id: str | None = None,
                  comment: str | None = None, prefix: str = "eval/") -> int:
    """Attach numeric evaluation metrics as Langfuse scores to a trace and/or a session. Returns #scores sent."""
    cl = client()
    if not cl:
        return 0
    sent = 0
    for k, v in metrics.items():
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            continue
        try:
            kw = {"trace_id": trace_id} if trace_id else {"session_id": session_id}
            sid = f"{trace_id or session_id}:{prefix}{k}"[:120]          # deterministic => re-scoring updates, never duplicates
            cl.create_score(name=f"{prefix}{k}", value=float(v), data_type="NUMERIC", comment=comment, score_id=sid, **kw)
            sent += 1
        except Exception:
            pass
    try:
        cl.flush()
    except Exception:
        pass
    return sent


def eval_trace(name: str, session_id: str, metrics: dict, metadata: dict | None = None) -> str | None:
    """Create a standalone evaluation trace (for runs that predate ops.json) and score it. Returns trace id."""
    cl = client()
    if not cl:
        return None
    try:
        from langfuse import propagate_attributes
        with propagate_attributes(session_id=session_id, trace_name=name, tags=["evaluation"], metadata=_meta_str(metadata)):
            with cl.start_as_current_observation(as_type="span", name=name, metadata=metadata, output=metrics) as span:
                tid = cl.get_current_trace_id()
        record_scores(metrics, trace_id=tid, comment=(metadata or {}).get("dataset"))
        return tid
    except Exception:
        return None


def sync_dataset(name: str, items: list[dict], description: str = "") -> int:
    """Mirror gold documents into a Langfuse dataset (idempotent on item id). items: {id, input, expected_output, metadata}."""
    cl = client()
    if not cl:
        return 0
    try:
        cl.create_dataset(name=name, description=description)
    except Exception:
        pass                                   # already exists
    n = 0
    for it in items:
        try:
            cl.create_dataset_item(dataset_name=name, id=it["id"], input=it.get("input"),
                                   expected_output=it.get("expected_output"), metadata=it.get("metadata"))
            n += 1
        except Exception:
            pass
    return n


_init_masked_client()
