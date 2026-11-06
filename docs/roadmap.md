# Pilot roadmap: Party & Role Register for claims/legal teams

Written 2026-11-04. Solo developer + Claude Code, ~10 h/week. **Pilot-ready: 2026-12-16.** A demo must be possible at any point from **2026-11-18** (week 2) with a growing feature set.

Everything labelled *assumption* is unverified and must be checked in the first analyst conversation. Nothing here is a measured result unless marked "measured".

---

## 1. Problem, sharpened

**Recommended job to replace: building the *party & role register* for a claim/dispute file.**
A table of every person, company, agreement and authority in the file, with aliases and former names, role/relationship (who controls, represents, is party to what), and a citation to the source passage for every row.

Why this job and not chronology or obligation extraction:
- It is what the tool already does (entities, aliases, relationships, citations).
- It is a table, so it maps directly to the spreadsheet analysts already live in.
- Every row is checkable against a quote, so trust can be built row by row.
- Errors are costly in a way buyers recognise: a missed alias means a missed conflict, a missed subrogation target or a wrong coverage position.

**Who hurts:** claims/coverage counsel, subrogation and recovery analysts, SIU, conflict-check/compliance staff, paralegals building "dramatis personae" lists.

### Cost model (all inputs are assumptions to validate)

| Input | Assumption | Source of truth to replace it |
|---|---|---|
| Fully loaded analyst/paralegal cost | 80-150 EUR/h in-house; 200-450 EUR/h outside counsel | Ask the pilot partner |
| Careful read + party extraction speed | 15-30 pages/h (dense legal text, note-taking, reconciling aliases) | Time two analysts on the pilot corpus |
| Typical file | 300-1,500 pages across 10-60 documents | Ask for a representative file |
| Manual effort per file | 15-60 analyst-hours for the register alone | Stopwatch study |
| Cost per file, manual | roughly 1.5k-9k EUR | derived |
| LLM cost per file | single-digit EUR per pass at current API prices (~0.25-1M input tokens) | measure from Langfuse |
| Target with tool | analyst reviews and corrects: 20-30% of manual time at equal or better recall | pilot measurement |

**Value claim to prove in the pilot:** not "the AI is accurate", but *"time to a reviewed, cited register drops from X h to Y h, and recall of aliases/roles does not drop."* The headline pilot metric is therefore **analyst minutes per file (with tool vs. without)** plus **recall of the reviewed register against a second analyst's independent register.**

---

## 2. Current state (measured 2026-11-04)

What I ran: FastAPI + Vite dev servers, `/runs`, `/runs/<id>`, `/api/runs/<id>/graph`, `test.py`.

- Pipeline output of the saved docling run `20261031_134601`: 7 entities, 7 raw edges, all graph edges have **empty `evidence`**, every citation quote is a placeholder like `#/texts/0` with offsets 0/0, aliases are `[""]`.
- Graph API returns the same real-world company twice with different types (`Northbridge Risk Holdings` as both Company and Person; `Harbor Re Analytics` likewise). This is an entity-typing/dedup defect, not a cosmetic issue.
- UI: Run Detail says **"Companies 0 / Other 0" while listing a Company** (the type casing bug, known issue #2). Nav bar is unstyled links. Runs list shows status "unknown" for every run. Failed runs show as "pending" forever.
- Eval: `test.py` crashes on Windows consoles (`UnicodeEncodeError`, needs `PYTHONUTF8=1`). The 0% F1 I got on that run is **not a valid baseline**: the run's source file is gone and `test.gt.json` is for the Aurora document. **There is currently no trustworthy F1 number for the docling backend.** Establishing one is task 1.
- Ground truth: `data/test.gt.json` (49 entities, 34 relationships) plus three 5-entity toy sets. No German data. No alias or cross-document GT.
- 8 known bugs are already pinned by xfail tests in `docs/tests/known-issues.md`; #1-#4 and #7 directly hurt the demo.
- Two backends coexist (legacy `run.py` and docling-graph via `engine/`). The API only uses docling.

**Biggest strategic risk:** the docling path currently drops provenance (placeholder citations). An analyst product without real citations is not usable. That, not graph visuals, is the first thing to fix.

---

## 3. Product specification (pilot v1)

**One-sentence product:** upload a claim file, get a reviewed, cited party & role register in a spreadsheet in minutes instead of hours.

### Must have (pilot gate)
1. **Ingest:** PDF, DOCX, TXT, 5-20 documents per "matter"; German and English.
2. **Register table (the home screen):** one row per resolved entity: canonical name, type, aliases/former names, role summary, documents in which it appears, mention count, confidence, review status.
3. **Evidence panel:** click a row, see every supporting quote with document and page, highlighted in the source text. Citations must be verbatim and offset-verified.
4. **Relationships table:** source, relation, target, quote, document/page, confidence. Same filters as register.
5. **Review actions:** accept, reject, rename, merge two entities, split one, edit role. Every action stored (audit trail) and fed back as labelled data.
6. **Export:** XLSX (register, relationships, evidence sheets, with the matter metadata and run settings on a cover sheet) and CSV. Re-import of the edited sheet is out of scope for the pilot.
7. **Observability:** per-run page with latency per stage, tokens, cost in EUR, citation-validity rate, entity/relationship counts; plus an eval dashboard from the ground-truth sets.
8. **Failure visibility:** runs have explicit status (queued/running/failed/completed) with error text.

### Should have
- Cross-document resolution with merge suggestions the analyst can accept in one click.
- "Show me what changed" between two runs of the same matter.
- Batch progress (per document).

### Explicitly out of scope for the pilot
Graph-visualisation polish, multi-tenant auth/SSO, fine-tuning, local-model parity, a generic ontology editor, real-time collaboration, MUI/shadcn consolidation (fix only what is visibly broken), arbitrary relationship types.

---

## 4. Metrics and targets

Define these precisely so that "0.75 F1" means something. All are computed by one eval harness (Section 6) and logged per run.

| Metric | What it measures | Pilot gate | Stretch |
|---|---|---|---|
| **Entity F1 (resolved)** | Resolved entity matches a GT entity by canonical name or any GT alias | **>= 0.85** | 0.92 |
| **Alias/coref pairwise F1** (or B-cubed) | Are mentions grouped into the right real-world entity, across documents | **>= 0.80** | 0.90 |
| **Relationship F1 (strict)** | (source, type, target) triple matches GT | **>= 0.65** | 0.75 |
| **Relationship F1 (lenient)** | Triple matches ignoring direction/type subtype | >= 0.75 | 0.85 |
| **Citation validity** | Quote appears verbatim in the cited source span | **>= 99%** | 100% |
| **Hallucination rate** | Output entities with no GT support after human check of a sample | <= 3% | <= 1% |
| **Latency** | 20 documents / ~300 pages, end to end | **<= 5 min** | <= 2 min |
| **Cost** | Per 300-page matter on cloud API | <= 5 EUR | <= 2 EUR |
| **Analyst time** | Review-to-final-register vs. manual | **<= 30% of manual** | 15% |

Notes:
- 0.75 strict relationship F1 on first contact with a new corpus is ambitious; relationship extraction is the weakest part of most LLM pipelines. Entity-level and alias-level quality are what analysts feel first, so those carry the gates. Report strict and lenient relationship F1 separately.
- Report precision and recall separately. For conflict-check use cases **recall matters more than precision** (a false positive costs a click, a miss costs a case). Make the review UI cheap for false positives.
- F1 on synthetic data overstates real-world quality. State the dataset in every number quoted to the pilot partner.

---

## 5. Implementable methods (from my own knowledge; not verified by web research this session)

Ordered by expected ROI for this codebase:

1. **Verbatim quote anchoring.** Make the LLM return the quote; locate it in the source with exact then fuzzy match (rapidfuzz `partial_ratio` alignment) to produce real char offsets and page numbers; drop or flag anything that cannot be located. Fixes placeholder citations and hallucinations in one step.
2. **Defined-term / alias pass.** Legal text defines aliases explicitly (`("Aurora")`, `formerly known as`, `hereinafter`, German `(nachfolgend "...")`, `vormals`, `ehemals`). A regex+LLM pass over these patterns yields high-precision alias edges before any fuzzy matching.
3. **Blocking + pairwise LLM adjudication.** Block candidates by normalised name tokens (strip legal suffixes Inc., LLC, GmbH, AG, UG, Ltd.) with rapidfuzz; send only ambiguous pairs, with their quotes, to a cheap model for same/different/unsure. Cache decisions.
4. **Type-constrained extraction and schema validation.** Strict structured output, closed type set, reject duplicates of the same canonical name with different types (the Company/Person duplicate seen in the graph).
5. **Role-aware relationships.** Extract relationships only between already resolved entity IDs, with the ontology's direction rules enforced (fix known issue #7 so `validate_relationship` actually rejects).
6. **Parallel chunk extraction** with a concurrency limit and prompt caching of the static instruction prefix. This is the main latency lever.
7. **Model routing.** Strong model for extraction and adjudication of unsure pairs; cheap model for easy tasks. Decide by measured F1/cost tradeoff on the eval set, not by assumption.
8. **Confidence from agreement.** Run extraction twice with different chunk boundaries/seeds; entities seen in both get high confidence, singletons get flagged for review. Cheaper than a separate judge model and directly usable in the UI.

Not worth it now: fine-tuning, graph neural nets, embedding-only clustering, a vector database.

---

## 6. Evaluation and data plan

**Dataset v1 (target 12 documents, built by 2026-11-17):**
- 5 English claim/dispute-style documents (existing Aurora memo + 4 new).
- 4 German documents (GmbH/AG/KG structures, Geschäftsführer, Vorstand, Versicherungsnehmer, Haftpflichtversicherer, Gutachter, Anwalt).
- 3 multi-document "matters" (3-5 documents each) with the same entities under different aliases across documents, former names, abbreviations and one deliberate near-collision (two different companies with similar names).

**Method:** ground-truth first, text second. Generate the entity/relationship GT with explicit alias lists, then have an LLM write documents that must use those aliases and relationships; then **hand-verify the GT against the text** (spot-check a third, mechanically check every GT quote exists). `data/generation-prompt.md` is a starting point but lacks aliases, German, multi-doc and adversarial cases.

**Realism check:** add 2-3 public documents (court opinions, SEC 8-K/credit agreements for English; Bundesanzeiger/Handelsregister-style public text or German court decisions for German) with a small hand-labelled GT. Anything unfamiliar to the model is a better test than something it wrote.

**Harness:**
- Fix `test.py` Windows encoding; make it write `metrics.json` into the run directory and a one-line summary to `metrics/history.csv` (run id, git sha, model, dataset, P/R/F1 per metric, latency, tokens, cost).
- `check.py --eval` runs all datasets (cached LLM calls where possible) and fails if F1 regresses by more than 0.03.
- Langfuse is already initialised in `run.py`; ensure the docling path also reports latency/tokens/cost per stage.
- Keep the analyst's review actions as a second ground-truth source (corrections = labels).

---

## 7. Dated roadmap

Weeks start on Wednesdays to match today's date. ~10 h/week. Each week ends with a demo-able increment.

### Week 1: 2026-11-04 -> 11-10 · "Trust the numbers"
- [ ] Pick a single backend for the pilot (recommend docling path + own post-processing; keep legacy code only for reference). Decision recorded in this file.
- [ ] Fix known issues #1-#4, #7 (aliases, entity type casing, empty chunk list, missing output error, relationship validation). Turn xfails green.
- [ ] Explicit run status (`status.json` with state and error text); list view shows it.
- [ ] Fix `test.py` Windows encoding; compute entity, relationship and alias metrics; write `metrics.json`.
- [ ] **Baseline:** run the pipeline on `test-synthetic` and the zero sets, record the first honest F1/latency/cost numbers in `metrics/history.csv`. (Costs a few cents to ~1 EUR of API credits; I will confirm before running.)
- Exit: one table of measured baseline numbers; no crashing run silently "pending".

### Week 2: 11-11 -> 11-17 · "Dataset and citations"
- [ ] Dataset v1 (12 docs, see Section 6) with GT and a GT validator script.
- [ ] Quote anchoring (method 1): real offsets and page, citation-validity metric.
- [ ] `check.py --eval` with regression threshold.
- **Demo checkpoint A (usable 11-18): the 2-week demo.** Upload a document, see entities and relationships with real quotes and measured F1 on screen, show Langfuse trace. Honest message: "quality gates tracked, here is where we are."

### Week 3: 11-18 -> 11-24 · "Quality"
- [ ] Defined-term/alias pass (method 2), including German patterns.
- [ ] Blocking + adjudication for cross-document merges (method 3).
- [ ] Entity typing/duplicate rejection (method 4).
- [ ] Iterate on prompts against the eval set. Target: entity F1 >= 0.80 on EN, alias F1 >= 0.75.
- Exit: metrics table moved from baseline; changes tied to numbers in `metrics/history.csv`.

### Week 4: 11-25 -> 12-01 · "The analyst's table"
- [ ] Register table as the home screen (sort/filter/search, review status, confidence).
- [ ] Evidence panel with highlighted source text.
- [ ] Accept / reject / rename / merge / split with audit log.
- [ ] XLSX export (register, relationships, evidence, cover sheet) via `openpyxl`.
- [ ] Unstyled nav and "Companies 0" style defects fixed; desktop and mobile checked in the browser.
- **Demo checkpoint B (usable 12-02): the 3-4-week demo.** Upload, wait minutes, review in a table, export to Excel, show F1 and cost per run.

### Week 5: 12-02 -> 12-08 · "German, speed, cost"
- [ ] German evaluation pass; fix whatever the 4 German docs expose (suffixes, umlauts, compounds, German defined terms).
- [ ] Parallel chunk extraction with concurrency cap; prompt caching; model routing experiment (method 6-7). Target: 20 docs <= 5 min, <= 5 EUR.
- [ ] Confidence from two-pass agreement (method 8) shown in the table.
- [ ] Cost/latency per stage on the run page.
- Exit: gates for latency/cost met or the shortfall documented with a plan.

### Week 6: 12-09 -> 12-15 · "Pilot hardening"
- [ ] Remove `/debug`; configurable data directory; no document content in logs; simple shared-secret login for the API.
- [ ] One-command start (docker compose or a single `uv run` script); fresh-machine rehearsal.
- [ ] Deployment pack per `docs/deployment-options.md` (provider switch via config, EU-region option).
- [ ] Pilot protocol: consent and data-handling one-pager, success metrics, stopwatch protocol for analyst time, feedback form.
- [ ] Full rehearsal on the 12 eval documents plus any approved real documents.
- **2026-12-16: pilot-ready.** Go/no-go against the gates in Section 4.

### Buffer
There is deliberately no slack week. If one slips, cut in this order: confidence from two-pass agreement, "what changed between runs", cross-document merge suggestions UI, German polish beyond the eval set. Never cut quote anchoring, the eval harness or the XLSX export.

---

## 8. Demo tiers (pick by lead time)

| Lead time | What you can show | Risk to disclose |
|---|---|---|
| **2 weeks (11-18)** | Upload, extraction, real quotes, live F1 on synthetic set, cost/latency trace | UI is basic; no review actions; English only |
| **3 weeks (11-25)** | + alias/defined-term resolution, cross-doc merges, improved F1 table | Table UI still partial |
| **4 weeks (12-02)** | + register table, evidence panel, review actions, XLSX export | German only lightly tested |
| **6 weeks (12-16)** | Full pilot build, German, speed/cost gates | none beyond measured gaps |

---

## 9. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Synthetic-data F1 flatters the system | Add public real documents; report dataset with every number; use analyst corrections as labels in the pilot |
| docling-graph dependency is a local editable path (`../docling-graph`) and hard-codes gpt-4o | Pin the checkout; move model/provider to config (needed for on-prem anyway); keep an escape hatch to the legacy pipeline |
| German quality unknown | Build German eval first (week 2); if gates are missed, pilot in English and offer German as phase 2 |
| Relationship F1 stuck below 0.65 | Lead with the register (entity/alias), position relationships as "suggested, reviewed by analyst" |
| Client data cannot go to a cloud API | See `docs/deployment-options.md`; the demo uses synthetic data only |
| Solo bandwidth (10 h/week) | Fixed cut order above; Claude Code handles boilerplate; no new infrastructure |
| Analysts do not trust it | Citations on every row, one-click source view, reject is cheap, export is plain Excel |

---

## 10. Open questions to resolve with the pilot partner
1. Which file types and page counts are typical? Scanned PDFs (OCR needed) or digital?
2. What does the analyst's current register look like (columns, templates)? Match it in the export.
3. Which roles/relationships do they care about beyond the six in the ontology?
4. What data-handling approval is needed (DPA/AVV, EU residency, ZDR)?
5. Who can give 2-3 hours for a stopwatch comparison on one real (approved) file?

---

## 9. Open architectural decision: a language-agnostic ontology (added 2026-11-06)

**Decision recorded: the ontology must eventually be language-agnostic. Today it is English-only, and the pilot requires German (section 3, "German and English").**

What "English-only" means in this code base today:
- `engine/template.py` and `ENTITY_RELATIONSHIP_DIRECTION_RULES` in `run.py` define entity classes (`Person`, `Company`, `Agreement`, `Asset`, `OtherEntity`) and relation names (`controls`, `participates_in`, `represents`, `transfers_to`, `governs`, `related_to`) as English words, and the field descriptions that steer the LLM are English prose. docling-graph sends that schema to the model for every chunk.
- Class boundaries are drawn around English legal concepts. "Agreement" has no clean German counterpart split: *Vertrag* (contract), *Beschluss* / *Urteil* (decision, judgment), *Bescheid*, *Satzung*, *Tarifvertrag* are different things, and the first measured German run typed court decisions and procedures as `Agreement` (22 of 27 extra predictions, `docs/evaluation.md`).
- Company legal forms (GmbH, AG, KG, UG, e.V.), roles (*Geschaeftsfuehrer*, *Vorstand*, *Prokurist*, *Versicherungsnehmer*) and defined-term patterns (`nachfolgend`, `vormals`) have no place in an English-worded schema.
- Evaluation labels are mapped to the ontology per dataset (`type_map` / `relation_map` in `evalkit/cards/`), which is already language-neutral on the label side; the pipeline side is not.

What a language-agnostic design needs (not yet designed, not scheduled):
1. **Canonical concept IDs separate from words.** A concept (`legal_person`, `natural_person`, `contract`, `judicial_decision`, `ownership_control`, ...) has a stable ID, and per-language labels, definitions, examples and prompts attach to it. Output, storage, the UI and the evaluation labels use IDs; only prompts and display use language text.
2. **Classes that do not lean on one legal system.** At least a separate class for decisions/proceedings/legislation instead of stretching `Agreement`; relations defined by what they mean (control, party-to, represents), not by English verb phrases.
3. **Per-language prompt and definition packs** selected by detected document language, with mixed-language documents (German contract with English terms) handled per chunk.
4. **Per-language evaluation sets** with the same concept IDs, so a score for German and for English are comparable (the `evalkit` cards already work this way: one `type_map` per dataset).

What the first experiments do and do not show (details in `docs/evaluation.md`, "English vs German"):
- Precision fell from about 82% (English SEC filings) to 31% (German court decisions), almost entirely through `Agreement`-typed extras. That is consistent with an English-shaped ontology meeting German legal text, **but it is confounded** with domain (judgments discuss decisions and procedures), so it is not proof that language is the cause.
- The missing relationships are **not** a German problem: the same pipeline extracted **zero** relationships on eight short English paragraphs that state ownership outright. That is a relationship-extraction problem to fix first and separately.
- Recall was similar across languages (30% German, 35% English filings), so language does not explain it.

Until this is designed: do not tune the `Agreement` definition to German or add German-only special cases in the template. Fix the type definition in a way that survives the redesign (a decisions/proceedings class), and measure English and German separately every time.

**Update 2026-11-06 (relationships):** the missing relationships are a template defect, not a language effect: relation fields nested as `Union` in every entity class give docling-graph a 28-path catalog and are never filled. A separate relation pass (`engine/relations.py`) reaches 78% precision / 50% recall on English ownership relations for about 2% of the extraction cost; see `docs/evaluation.md`, "Relationship extraction investigation". Language neutrality of that pass was confirmed on German text, so section 9 concerns the *entity classes and prompts*, not relation extraction as such.
