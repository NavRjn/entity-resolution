# Deployment options: cloud API, client cloud, on-prem

Written 2026-11-04. Prices, model names and GPU sizing below are from my own knowledge and are **not verified against current vendor pages**; check them before quoting anything to a client. Quality figures for open-weight models on this task are **unmeasured**: the eval harness in `docs/roadmap.md` must produce them.

## What the software needs

- An LLM with structured/JSON output, a context of >= 32k tokens and decent German. Calls: chunked extraction (many, parallel), plus adjudication of ambiguous merges.
- CPU only for everything else (docling parsing, rapidfuzz, FastAPI, SQLite/files). A GPU is only needed if the LLM is local.
- Today `engine/api.py` hard-codes OpenAI `gpt-4o`, while `config.yaml` has a provider switch (OpenAI or Ollama `qwen3:8b`) used by the legacy pipeline only. **Work item:** route the docling engine through the same config so the provider/base URL/model are settings. Any OpenAI-compatible endpoint (vLLM, Azure OpenAI, Ollama, LiteLLM) then works without code changes.

## Options

| # | Option | Who provides compute and licence | Data leaves client? | Effort for me | Expected quality | Typical use |
|---|---|---|---|---|---|---|
| A | **Cloud API, my account** (zero-retention terms, EU region where offered) | Me (usage billed to me or passed through) | Yes, to the provider | Lowest | Best | Demo on synthetic data; pilot on approved non-sensitive docs |
| B | **Client's own cloud tenant** (Azure OpenAI, AWS Bedrock, Google Vertex in their subscription and region) | Client | Stays inside their cloud agreement | Low: point the base URL and credentials at their endpoint | Same class as A | Enterprises that already have an approved AI service; the most likely realistic path for insurers |
| C | **Client on-prem GPU server** running an open-weight model via vLLM (OpenAI-compatible) | Client provides GPU + OS access; open-weight licences are mostly permissive but must be checked per model | No | Medium: container, model download, tuning, re-run evals | Lower than A/B, must be measured | Strict no-cloud policies |
| D | **I bring hardware** (workstation/laptop with a 24-48 GB GPU, or a rented dedicated EU GPU server) | Me, charged to the client as an engagement fee | A: no (on-site). Rented server: yes, to a third-party host, needs approval | Medium-high, plus security review of my device | Same as C at smaller model sizes | Short on-site pilot where the client cannot provision anything |
| E | **Air-gapped bundle** (container images + model weights on encrypted drive) | Client machine | No | High | As C | Later phase, not a pilot |

## Sizing hints for C/D (rough; verify)

| Model class | Weights memory | Hardware that usually runs it | Notes |
|---|---|---|---|
| ~8B (e.g. Qwen3-8B, already configured) | ~5-16 GB | One 16-24 GB GPU | Fast; extraction quality and German likely too weak for the 0.85 entity target; fine for smoke tests |
| ~24-32B (e.g. Mistral Small class, Qwen 32B class) | ~16-35 GB quantised | One 24-48 GB GPU (RTX 4090/5090 24-32 GB tight, L40S/RTX 6000 Ada 48 GB comfortable) | The realistic sweet spot for on-prem |
| ~70B class | ~40-80 GB quantised | One 80 GB or two 48 GB GPUs | Best open quality; slower; costly hardware |

Rules of thumb: expect a **quality drop of unknown size** versus a frontier API model; expect throughput of tens of tokens/second per stream on one GPU, so latency for 20 documents will be several times the cloud number. Plan to evaluate 1-2 candidate models on the German and English eval sets before promising anything.

## Compliance points to raise early (especially for German clients)
- Data processing agreement (Auftragsverarbeitungsvertrag) with every sub-processor in the chain; model providers are sub-processors.
- EU data residency / data-zone deployment for Azure OpenAI or Bedrock, and the provider's data-retention and abuse-monitoring settings (zero data retention usually requires an explicit approval step).
- Transfers outside the EU and the client's position on US providers.
- Professional secrecy (§203 StGB for lawyers) and the insurer's own supervisory expectations (VAIT/DORA for IT and outsourcing) may require contractual and technical measures even for B.
- Logging: do not write document text into logs or tracing (Langfuse) when running on client data; make this a configuration switch.

## Recommended path
1. **Now to the pilot:** A with synthetic data only. Never show or send client text through my personal API key.
2. **Pilot proposal to the client:** offer B first (their cloud tenant, their approved models), fall back to C if they refuse any cloud use, and keep D for an on-site, time-boxed engagement only.
3. **Do not build E** until a client pays for it.

## What to ask the client
1. Is there an approved generative-AI service (Azure OpenAI, Bedrock, Vertex, an internal gateway)? In which region?
2. If none: can they provision a GPU VM or server with an agreed OS image? Which GPU class?
3. Who signs off on a processing agreement, and how long does that take?
4. Is the pilot corpus allowed to leave their network at all, even encrypted?

## Work items that follow from this
- [ ] Provider/base URL/model and API key in config for the docling engine (needed in all options).
- [ ] A `LLM_BASE_URL` override so an OpenAI-compatible server works unchanged.
- [ ] "No content in logs/traces" switch.
- [ ] Eval runs per model recorded in `metrics/history.csv`, so the cloud-vs-local quality gap is a number, not a guess.
- [ ] One-command container start; documented hardware and software prerequisites.
