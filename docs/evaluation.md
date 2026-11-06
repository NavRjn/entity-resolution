# Evaluation and observability

Everything here is offline and free unless a command says it calls an LLM. Code: `evalkit/` (metrics, datasets), `observability.py` (Langfuse). Tests: `tests/test_evalkit.py`, `tests/test_observability.py`.

```sh
uv run python -m evalkit datasets                         # cards: licence, what the labels give / lack
uv run python -m evalkit fetch ler                        # download raw files (sha256 pinned in eval_data/<name>/fetch.lock.json)
uv run python -m evalkit prepare ler --limit 30           # -> eval_data/ler/prepared/{gold.jsonl, docs/*.txt}
uv run python -m evalkit run ler --backend docling --limit 5 --yes      # PAID: runs the pipeline per doc, then scores
uv run python -m evalkit score --gold data/zero.gt.json --run 20261031_134601   # score an EXISTING run, no pipeline
uv run python -m evalkit history                          # trend of headline numbers
uv run python -m evalkit compare <evalA> <evalB>          # headline diff of two reports
uv run python -m evalkit gate <eval> --baseline <eval> --max-drop 0.03   # exit 1 on regression (CI)
uv run python test.py --file test                         # old entry point, now a shim over evalkit
```

## Design in one picture

```
raw labels (CoNLL, DocRED JSON, SQuAD/CUAD, Textract, legacy .gt.json, your own)
   │  card.yaml: loader + type_map + relation_map + coverage      ← the only per-dataset code is a YAML file
   ▼
GoldDocument  (text, entities+aliases+mentions, relations, Coverage)        evalkit/schema.py
   │                                                   pipeline output.json / any prediction JSON
   │                                                              │  evalkit/predictions.py
   ▼                                                              ▼
              matching.align  (Hungarian, order independent)
                         │
   entities · relations · coreference · provenance · structure · bootstrap CI        evalkit/metrics/
                         ▼
        report.json / report.md / metrics/history.csv / Langfuse scores
```

**Adding a dataset** = a card in `evalkit/cards/` (or any path via `--card`). **Adding a format** = one `@register("name")` function in `evalkit/loaders/`. Scoring labels that never touched the pipeline: `score --card my.yaml --gold-path labels.conll --gold x --run RUN`, or give a `gold.jsonl` / `*.gt.json`.

### The idea that makes the numbers honest: `Coverage`
Public datasets rarely label everything. A card therefore declares what was labelled:

| field | meaning | effect |
|---|---|---|
| `exhaustive_entity_types` | types labelled completely (`null` = all, `[]` = none) | predicted entities of other types are not false positives; `[]` ⇒ **precision/F1 reported as n/a, read recall** |
| `exhaustive_relations` | relations labelled completely | false → relation precision n/a |
| `has_coref` | aliases/clusters are real (not "same text = same entity") | false → coreference metrics skipped |
| `has_types` | gold has entity types | false → only lenient scores are meaningful |

## Metrics

| group | metrics | notes |
|---|---|---|
| Entity | P/R/F1 **strict** (name+type) and **lenient** (name), micro + macro over docs, per type, typing accuracy + confusion, alias recall | name match: normalised → legal-form-stripped → fuzzy ≥0.90, over name+aliases, 1:1 assignment |
| Relation | **strict** (s,type,t), **undirected**, **untyped**, **pair**; each *end-to-end* and *conditional* (only relations whose endpoints were found) | conditional separates relation quality from entity-finding quality |
| Alias / coref | pairwise, B³, MUC, CEAF-e, CoNLL average, at *name level* | needs no offsets; None when gold has nothing to merge |
| Provenance | verbatim-quote rate, placeholder-quote rate, valid-offset rate, unsupported-entity rate (hallucination *proxy*), gold-grounded citation rate | most are label-free |
| Structure (label-free) | duplicate entities, same name with conflicting types, orphans, dangling/self/duplicate edges, ontology direction-rule violations | the defect classes already seen in this project |
| Uncertainty | 95% bootstrap CI over documents | `bootstrap_prf`; `stability()` for repeated runs |
| Ops | latency per stage, LLM calls, tokens, USD | from `ops.json` written by `observability.py` |

What they do **not** measure: correctness of merges beyond names, relation evidence quality, calibration, and anything on documents unlike the dataset. Always quote the dataset with the number.

## Datasets (verified = I downloaded it and ran `prepare`)

| card | what | labels | licence | verified | link |
|---|---|---|---|---|---|
| `ler` | German federal court decisions, 19 classes (mapped: person, company, agreement) | human, expert | CC-BY-4.0 | yes | [GitHub](https://github.com/elenanereiss/Legal-Entity-Recognition) · [paper](https://arxiv.org/abs/2003.13016) · [HF](https://huggingface.co/datasets/elenanereiss/german-ler) |
| `e_ner` | 52 SEC EDGAR filings, PER/ORG | human | **CC-BY-NC-SA-4.0 (non-commercial)** | yes | [GitHub](https://github.com/terenceau2/E-NER-Dataset) · [paper](https://arxiv.org/abs/2212.09306) |
| `cuad_parties` | 510 commercial contracts, signing parties with offsets | human, attorney-reviewed | CC-BY-4.0 | yes | [GitHub](https://github.com/TheAtticusProject/cuad) · [paper](https://arxiv.org/abs/2103.06268) · [HF](https://huggingface.co/datasets/theatticusproject/cuad-qa) |
| `insurance_letters` | life-insurance demand letters (real PDFs) with role entities | human-labelled, **synthetic letters** | MIT-0 | yes | [GitHub](https://github.com/aws-samples/aws-legal-entity-extraction) · [blog](https://aws.amazon.com/blogs/machine-learning/extract-entities-from-insurance-documents-using-amazon-comprehend-named-entity-recognition/) |
| `re_docred` | Wikipedia; coreference clusters + relations (only ownership relations mapped → `controls`) | human + human re-annotation | MIT | yes | [GitHub](https://github.com/tonytan48/Re-DocRED) · [paper](https://arxiv.org/abs/2205.12696) |
| `synthetic_legacy` | in-repo `data/test.gt.json` | LLM-written | internal | yes | `data/` |

Candidates found but **not integrated** (not verified by download): REFinD (SEC relation extraction, 29K instances, JPMorgan; distributed through Codalab, manual download) [site](https://refind-re.github.io), InLegalNER (Indian judgments; gated on Hugging Face) [HF](https://huggingface.co/datasets/opennyaiorg/InLegalNER), LegalNERo (Romanian), MAPA (EUR-Lex, small), ContractNER on HF. Original DocRED is on Google Drive (not scriptable); Re-DocRED is the maintained, scriptable superset.

**Honest limits of public data for this product.** There is no public human-labelled corpus with *this* ontology's relations (`controls`, `participates_in`, `represents`, ...) on legal/insurance text. Public data gives you entity recall/precision (LER, E-NER), party recall on real contracts (CUAD, recall only), alias/coreference (Re-DocRED, not legal), and a PDF ingestion path (insurance letters, synthetic). Relation quality on legal text still needs your own labels; the `score` command exists so analyst corrections can become gold later.

Practical: E-NER filings average ~40k characters each, CUAD contracts far more; use `prepare --max-chars` before any paid `run`. `run` prints a token estimate and refuses without `--yes`.

## Findings from building this (existing-data defects)
- `data/test.gt.json` was written for `data/test-synthetic.txt`; `data/test.txt` is an unrelated 1.8 MB SEC HTML filing (1 of 49 gold names occurs in it). The `synthetic_legacy` card and the legacy loader now pick the right text.
- `data/test.gt.json` has a relation endpoint ("International Diagnostics Consortium") missing from its entity list. The old scorer accepted this silently; the loader now adds it as an implicit entity and warns.
- `data/zero*.gt.json` use free-form relation labels (`owns`, `ceo_of`, `subsidiary_of`), so strict relation scores are 0 by construction; read the `untyped`/`pair` rows or add a `relation_map`.
- The old `test.py` took the first fuzzy hit above 90 (order dependent), reported only relation metrics in its saved JSON, and crashed on Windows consoles.
- First honest measurement of the docling backend (run `20261031_134601` vs `data/zero.gt.json`, 5 gold entities): entity R 100%, P 71% (two entities duplicated as both Company and Person), **100% placeholder citation quotes**. One tiny document: a pipeline sanity check, not a benchmark.

## Observability (`observability.py`)
Per run, for both backends: one Langfuse trace, `session_id = run_id`, tagged backend (+ `eval`, dataset during `evalkit run`), versioned with the git sha; a span per stage; every `litellm.completion` (docling-graph's calls) as a generation with model, tokens, cost, latency, errors; and `outputs/<run_id>/ops.json` (stage seconds, tokens, USD, trace id, status/error). Evaluation write-back: `eval/*` scores on each run's trace and on the evaluation session, so quality, cost and latency sit on the same trace.

- Never breaks a run: no keys, `LANGFUSE_ENABLED=0`, an SDK error or a stub all degrade to no-ops.
- **Privacy (corrected after a live check):** `run.py` imports `langfuse.openai`, which patches the OpenAI SDK process-wide. Because `engine/api.py` imports `run.py`, **every docling OpenAI call is captured with its full prompt, i.e. document excerpts, and sent to Langfuse cloud**. That predates `observability.py`. Set `OBS_REDACT_CONTENT=1` to register the Langfuse client with a mask that replaces every string in every span/generation with `[redacted N chars]` (tokens, cost, timings and scores are unaffected). Default is off so legacy debugging behaviour is unchanged. `OBS_CAPTURE_CONTENT=1` only affects generations created by `instrument_litellm()`, which now skips OpenAI models (already traced above) to avoid double-counting cost.
- Not covered: Ollama calls (no wrapper), prompt-version linking for the docling path (it uses its own prompts, not Langfuse prompts).
- Scores use deterministic ids (`<trace-or-session>:eval/<metric>`), so re-scoring updates instead of duplicating.
- Verified live once: a mock-LLM trace arrived with nested spans, a generation (gpt-4o, 10/20 tokens, $0.000225) and a score; I deleted that test trace.

> **Update 2026-11-06:** the crash in `ler-0025` was the converter bug, now fixed (`engine/api.py` anchors citations from docling-graph's `provenance.json`). Re-converting the stored artifacts (`evalkit reconvert`, free) and re-scoring moved entity F1 from 22.5% to **30.4%** (CI 14.7-42.9%, P 30.8% / R 30.0%), placeholder quotes from 100% to 1.9%, and 51/51 located citations slice exactly their quote from `document.txt`. The first run's number was depressed by the converter, not only by the model.

## First measured run: `ler`, docling backend, 5 documents (2026-11-05)
Estimated $0.06-0.21; **measured $0.58** (4 completed + 1 failed run). Dataset: LER (German court decisions), gpt-4o via docling-graph. 5 tiny documents: treat every number as a sketch, the CI is [4%, 39%].

| | |
|---|---|
| Entity P / R / F1 (lenient = strict) | 25.8% / 20.0% / 22.5% (TP 8, FP 23, FN 32) |
| Best case after explicit label/ontology filters | P 62.5% / R 26.3% / F1 37.0% (`all_filters_combined`) |
| Person+company only | P 66.7% / R 18.2% |
| Typing accuracy on matched entities | 100% |
| Relations extracted | 0 (LER has no relation gold; orphan-entity rate 100%) |
| Placeholder citation quotes | 100%, yet 88.6% of nodes have a verbatim anchor in docling-graph's `provenance.json` |
| Cost | $0.116/doc, 8.8 LLM calls/doc, 19.9 prompt tokens per document token; 1 crashed run wasted $0.127 |

What the diagnostics say (see `report.md`, "Why entities were missed or invented"):
1. **Precision loss is mostly the `Agreement` class.** 20 of 23 extra predictions are typed `agreement` (court decisions, procedures, activities such as "Revisionsverfahren", "Urteil des FG"). 24 of 44 extracted nodes were agreements. A type-definition/prompt problem in `engine/template.py`, independent of the dataset.
2. **Recall is low even on easy types:** plain person/company names (e.g. "Koch", "Mosbacher", "DPMA", "Staatsanwaltschaft München I") are simply absent (10 of 32 misses).
3. **Part of the miss is the dataset:** 7 clause/statute references (`§ 24 Abs. 4 ...`), 3 anonymised placeholders ("B", "K."). Even after removing them and ignoring non-person/company predictions, F1 only reaches 37%.
4. **Cost overshoot is structural:** 20x prompt overhead (schema + instructions repeated per chunk, plus gleaning and consolidation passes). A straight-line projection to a 300-page matter gives ~$13 and ~59 min sequential, against the roadmap gates of EUR 5 and 5 min. Linear extrapolation from short documents; verify on a long one.
5. **A crash after paying:** `ler-0025` failed in `save_compatible_files` (`prov.get("chunks")[0]` on a node whose provenance is `{"status": "unresolved"}`), after the LLM work was done. Same family as known issue #3.

## English vs German (2026-11-06)
Question: how much of the poor German result is language? Same backend (docling-graph, gpt-4o), 5-8 documents per set, scored with the same lenient entity matching. Cost of the two new runs: $0.58 + $0.42 (estimates $0.35-0.82 and $0.09-0.20; the second was low, see "Cost model").

| | LER (German judgments) | E-NER (English SEC filings) | Re-DocRED (English Wikipedia) |
|---|---|---|---|
| documents / chars / gold entities | 5 / 40,058 / 40 | 5 / 40,000 / 77 | 8 / 9,611 / 65 |
| entity precision | 30.8% | 81.8% | 81.1% |
| entity recall | 30.0% | 35.1% | 46.2% |
| entity F1 (95% CI) | 30.4% [14.7, 42.9] | 49.1% [23.8, 57.0] | 58.8% [48.2, 70.7] |
| F1 after label/ontology filters ("ceiling") | 34.5% | 49.5% | 58.6% |
| extra predictions by type | **agreement 22**, company 3, person 2 | company 6 | person 5, company 2 |
| typing accuracy on matched entities | 100% | 100% | 77% |
| relationships extracted | 0 | 13 (2 of 5 docs) | **0 (of 26 gold)** |
| cost per document / LLM calls per document | $0.116 / 8.8 | $0.116 / 9.2 | $0.052 / 6.0 |

Reading it:
1. **Precision is where German collapses, and it is one thing: `Agreement`.** 22 of the 27 extra predictions in German are court decisions, procedures and clause references typed as agreements ("Beschluss vom 11. 2. 2015", "Revisionsverfahren"). Neither English set produces a single agreement false positive. Consistent with an English-shaped `Agreement` meeting German legal text, but also with the content itself: judgments talk about decisions, SEC filings do not. LER is also shuffled unrelated sentences, so it is not a coherent document. Language and domain cannot be separated with these data.
2. **Recall is not a language problem.** 30% / 35% / 46%. In English filings the misses are short names ("SEC", "Tay", "TCP": 6.5% recall for 3-10 character names) and entities mentioned several times (13% recall for 2-3 mentions, 17% for 4+); long names are found 75% of the time.
3. **Relationships are not a language problem.** On Re-DocRED the model found all entities of "Originally by Ximian, it was later acquired by Novell, and is now developed by Microsoft" and filled none of the relation fields; docling-graph's raw `edges.csv` holds only the document->entity `MENTIONS_*` links, so the converter is not dropping anything. 0 of 26 gold relations, 0 predicted. The 13 relationships on E-NER filings are mostly `related_to`. This needs its own investigation (template edge fields, dense-mode phase 2, prompt), independent of language.
4. **Cost does not depend on language** at equal size ($0.116 per 8k-character document in both), but has a fixed per-document part (see below).
5. **Not controlled yet:** a clean language test needs the same content in two languages, for example the LER sentences machine-translated to English (translation cost small, but alignment with gold spans needs care), or an English set of court decisions (InLegalNER is gated; an EUR-Lex or ECHR set could be added as a card). Until then, quote German and English numbers separately. See `docs/roadmap.md` section 9 for the language-agnostic ontology decision.

### Cost model (refit 2026-11-06)
Three paid runs fit `cost per document = $0.041 + $0.0094 per 1k characters` (gpt-4o, docling backend): 8k-char documents $0.116, 1.2k-char documents $0.052. The fixed part is the schema and instruction prompts sent per document (6-9 LLM calls even for one paragraph), so many short documents cost more than their length suggests. `evalkit run` now prints this estimate (+-30%). A single 300-page (900k character) document would extrapolate to about $8.50, unverified and much lower than the earlier straight-line figure of $13-39; chunking, gleaning and consolidation may not scale linearly.
