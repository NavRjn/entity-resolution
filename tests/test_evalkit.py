"""evalkit: metrics verified against hand-computed values; loaders against tiny inline fixtures. Offline, no LLM."""
import ast
import json
import re
from pathlib import Path

import pytest

from conftest import REPO
from evalkit.loaders import Card, load_dataset
from evalkit.loaders.conll import decode_spans
from evalkit.matching import MatchConfig, align
from evalkit.metrics.clustering import cluster_metrics
from evalkit.metrics.entities import alias_recall_counts, entity_counts
from evalkit.metrics.intrinsic import intrinsic
from evalkit.metrics.provenance import provenance_counts
from evalkit.metrics.relations import relation_counts
from evalkit.metrics.stats import bootstrap_prf
from evalkit.evaluate import evaluate, headline
from evalkit.schema import Coverage, GoldDocument, GoldEntity, GoldRelation, Mention, PredEntity, PredRelation, Prediction


def G(id_, name, typ="company", aliases=()):
    return GoldEntity(id=id_, name=name, type=typ, aliases=list(aliases))


def P(id_, name, typ="company", aliases=(), quotes=()):
    return PredEntity(id=id_, name=name, type=typ, aliases=list(aliases), quotes=list(quotes))


def doc(entities, relations=(), text="", **cov):
    return GoldDocument(doc_id="d", text=text, entities=entities, relations=list(relations), coverage=Coverage(**cov))


# --------------------------------------------------------------------------- loaders

def test_decode_spans_handles_iob1_and_iob2():
    assert decode_spans(["I-ORG", "I-ORG", "O", "I-PER"]) == [("ORG", 0, 1), ("PER", 3, 3)]            # IOB1
    assert decode_spans(["B-ORG", "I-ORG", "B-ORG", "O"]) == [("ORG", 0, 1), ("ORG", 2, 2)]            # IOB2, adjacent
    assert decode_spans(["I-ORG", "B-ORG"]) == [("ORG", 0, 0), ("ORG", 1, 1)]                          # IOB1 adjacent
    assert decode_spans(["I-ORG", "I-PER"]) == [("ORG", 0, 0), ("PER", 1, 1)]                          # type change splits


def test_conll_loader_offsets_types_and_doc_boundaries(tmp_path):
    f = tmp_path / "x.conll"
    f.write_text("-DOCSTART- O\n\nAcme I-ORG\nCorp I-ORG\nsigned O\n.\tO\n\nJohn I-PER\nSmith I-PER\n\n"
                 "-DOCSTART- O\n\nAcme I-ORG\n\n", encoding="utf-8")
    card = Card({"name": "t", "loader": "conll", "type_map": {"ORG": "company", "PER": "person"}})
    docs = list(load_dataset(card, f))
    assert len(docs) == 2
    d0 = docs[0]
    assert {(e.name, e.type) for e in d0.entities} == {("Acme Corp", "company"), ("John Smith", "person")}
    m = next(e for e in d0.entities if e.name == "Acme Corp").mentions[0]
    assert d0.text[m.start:m.end] == "Acme Corp"                      # offsets point into the rebuilt text


def test_card_type_map_drops_unmapped_labels(tmp_path):
    f = tmp_path / "x.conll"
    f.write_text("Paris I-LOC\nAcme I-ORG\n", encoding="utf-8")
    docs = list(load_dataset(Card({"name": "t", "loader": "conll", "type_map": {"ORG": "company"}}), f))
    assert [e.name for e in docs[0].entities] == ["Acme"]


def test_legacy_gt_pairs_names_to_ids():
    card = Card({"name": "synthetic", "loader": "legacy_gt", "options": {"text": "test-synthetic.txt"}})
    with pytest.warns(UserWarning, match="International Diagnostics Consortium"):
        d = next(iter(load_dataset(card, REPO / "data" / "test.gt.json")))
    assert len(d.relations) == 34 and len(d.entities) == 50          # 49 listed + 1 implied by a relation (GT defect)
    listed = [e for e in d.entities if e.name not in d.meta["implicit_entities"]]
    assert all(e.name in d.text for e in listed), "gold must be paired with the text it was written for"


# --------------------------------------------------------------------------- entities

def test_entity_prf_hand_computed():
    g = doc([G("g1", "Acme Corp"), G("g2", "Bolt LLC"), G("g3", "Carol Diaz", "person"), G("g4", "Delta AG")])
    p = Prediction(doc_id="d", entities=[
        P("p1", "Acme Corporation"),                 # core-name match -> TP
        P("p2", "Bolt LLC", "person"),               # right name, wrong type
        P("p3", "Carol Diaz", "person"),             # TP
        P("p4", "Echo Inc"),                         # FP
    ])
    al = align(g.entities, p.entities)
    strict, _ = entity_counts(g, p, al, strict=True)
    lenient, _ = entity_counts(g, p, al, strict=False)
    assert (strict.tp, strict.fp, strict.fn) == (2, 2, 2)        # Bolt counts as both FP and FN
    assert (lenient.tp, lenient.fp, lenient.fn) == (3, 1, 1)
    assert lenient.precision == pytest.approx(0.75) and lenient.recall == pytest.approx(0.75)
    assert lenient.f1 == pytest.approx(0.75)


def test_alignment_is_one_to_one_and_order_independent():
    g = [G("g1", "Acme Corp"), G("g2", "Acme Corp Holdings")]
    p1 = [P("p1", "Acme Corp"), P("p2", "Acme Corp Holdings")]
    for preds in (p1, list(reversed(p1))):
        al = align(g, preds)
        assert len(al.pairs) == 2
        assert {(g[i].name, preds[j].name) for i, j, _ in al.pairs} == {("Acme Corp", "Acme Corp"), ("Acme Corp Holdings", "Acme Corp Holdings")}


def test_partial_gold_makes_precision_undefined_not_zero():
    g = doc([G("g1", "Acme Corp")], exhaustive_entity_types=[])
    p = Prediction(doc_id="d", entities=[P("p1", "Acme Corp"), P("p2", "Somebody Else", "person")])
    c, _ = entity_counts(g, p, align(g.entities, p.entities), strict=False)
    assert c.recall == 1.0 and c.precision is None and c.f1 is None


def test_out_of_scope_predicted_types_are_not_false_positives():
    g = doc([G("g1", "Acme Corp")], exhaustive_entity_types=["company"])
    p = Prediction(doc_id="d", entities=[P("p1", "Acme Corp"), P("p2", "Munich", "other"), P("p3", "Zeta Ltd")])
    c, _ = entity_counts(g, p, align(g.entities, p.entities), strict=False)
    assert (c.tp, c.fp) == (1, 1)               # Zeta counts, Munich (type 'other', unlabelled) does not


def test_alias_recall():
    g = doc([G("g1", "Aurora Strategic Holdings, Inc.", aliases=["Aurora", "ASH"])])
    p = Prediction(doc_id="d", entities=[P("p1", "Aurora Strategic Holdings", aliases=["Aurora"])])
    cov, tot = alias_recall_counts(g, p, align(g.entities, p.entities))
    assert (cov, tot) == (1, 2)


# --------------------------------------------------------------------------- relations

def _rel_fixture():
    g = doc([G("a", "Acme"), G("b", "Bolt"), G("c", "Cora", "person"), G("d", "Delta")],
            [GoldRelation(source="a", type="controls", target="b"), GoldRelation(source="c", type="represents", target="a"),
             GoldRelation(source="d", type="controls", target="a")])
    p = Prediction(doc_id="d", entities=[P("1", "Acme"), P("2", "Bolt"), P("3", "Cora", "person")],   # Delta never found
                   relations=[PredRelation(source="1", type="controls", target="2"),          # exact
                              PredRelation(source="3", type="related_to", target="1"),        # wrong type
                              PredRelation(source="2", type="controls", target="1")])         # reversed
    return g, p


def test_relation_levels_and_conditional():
    g, p = _rel_fixture()
    al = align(g.entities, p.entities)
    e2e = relation_counts(g, p, al)
    assert (e2e["strict"].tp, e2e["strict"].fp, e2e["strict"].fn) == (1, 2, 2)
    # reversed b->a collapses onto the correct a-b controls pair, so undirected sees 2 distinct preds, 1 correct
    assert (e2e["undirected"].tp, e2e["undirected"].fp, e2e["undirected"].fn) == (1, 1, 2)
    assert e2e["untyped"].tp == 2           # wrong-type (c->a) now counts
    assert e2e["pair"].tp == 2
    cond = relation_counts(g, p, al, conditional=True)
    assert cond["strict"].fn == 1           # d->a dropped: Delta was never found, that is an entity error
    assert cond["strict"].recall == pytest.approx(0.5)


# --------------------------------------------------------------------------- coreference

def test_cluster_perfect_and_overmerge():
    g = doc([G("g1", "Acme Corp", aliases=["Acme"]), G("g2", "Bolt LLC", aliases=["Bolt"])])
    perfect = Prediction(doc_id="d", entities=[P("1", "Acme Corp", aliases=["Acme"]), P("2", "Bolt LLC", aliases=["Bolt"])])
    r = cluster_metrics(g, perfect, align(g.entities, perfect.entities))
    assert r["pairwise"]["f1"] == r["b3"]["f1"] == r["muc"]["f1"] == r["ceafe"]["f1"] == r["conll_f1"] == 1.0

    merged = Prediction(doc_id="d", entities=[P("1", "Acme Corp", aliases=["Acme", "Bolt LLC", "Bolt"])])
    r = cluster_metrics(g, merged, align(g.entities, merged.entities))
    assert r["pairwise"]["recall"] == 1.0 and r["pairwise"]["precision"] == pytest.approx(2 / 6)
    assert r["b3"]["precision"] == pytest.approx(0.5) and r["b3"]["recall"] == 1.0


def test_cluster_undermerge_hurts_recall_only():
    g = doc([G("g1", "Acme Corp", aliases=["Acme"])])
    split = Prediction(doc_id="d", entities=[P("1", "Acme Corp"), P("2", "Acme")])
    r = cluster_metrics(g, split, align(g.entities, split.entities))
    assert r["pairwise"]["recall"] == 0.0 and r["b3"]["recall"] == pytest.approx(0.5)


def test_cluster_metrics_none_when_nothing_to_resolve():
    g = doc([G("g1", "Acme Corp"), G("g2", "Bolt")])
    p = Prediction(doc_id="d", entities=[P("1", "Acme Corp")])
    assert cluster_metrics(g, p, align(g.entities, p.entities)) is None


# --------------------------------------------------------------------------- provenance + intrinsic

def test_provenance_placeholder_verbatim_and_unsupported():
    text = "Acme Corp. signed the   Master Agreement with Bolt LLC."
    p = Prediction(doc_id="d", entities=[
        P("1", "Acme Corp", quotes=["Acme Corp. signed the Master Agreement", "#/texts/0"]),   # verbatim (whitespace-normalised) + placeholder
        P("2", "Totally Invented Ltd", quotes=["Totally Invented Ltd paid"]),                    # not in text at all
    ])
    c = provenance_counts(text, p).rates()
    assert c["quote_verbatim_rate"] == pytest.approx(1 / 3)
    assert c["placeholder_quote_rate"] == pytest.approx(1 / 3)
    assert c["unsupported_entity_rate"] == pytest.approx(0.5)


def test_grounding_uses_gold_offsets():
    text = "Acme Corp. signed. Later Acme Corp. paid."
    g = GoldDocument(doc_id="d", text=text, entities=[GoldEntity(id="g", name="Acme Corp", type="company",
                     mentions=[Mention(text="Acme Corp", start=0, end=9)])])
    hit = Prediction(doc_id="d", entities=[PredEntity(id="p", name="Acme Corp", quotes=["Acme Corp. signed"])])
    miss = Prediction(doc_id="d", entities=[PredEntity(id="p", name="Acme Corp", quotes=["Later Acme Corp. paid"])])
    for pred, expected in ((hit, 1.0), (miss, 0.0)):
        # 'Acme Corp. signed' also occurs only at offset 0; 'Later Acme...' does not overlap the gold mention
        assert provenance_counts(text, pred, g, align(g.entities, pred.entities)).rates()["grounding_rate"] == expected


def test_intrinsic_flags_the_known_defect_classes():
    p = Prediction(doc_id="d", entities=[
        P("c1", "Northbridge Risk Holdings", "company"), P("c2", "Northbridge Risk Holdings", "person"),   # type conflict + duplicate
        P("a1", "Master Agreement", "agreement"), P("x", "Lonely", "company")],
        relations=[PredRelation(source="a1", type="controls", target="c1"),        # agreement cannot control: rule violation
                   PredRelation(source="c1", type="participates_in", target="a1"),
                   PredRelation(source="c1", type="owns", target="ghost")])       # unknown type + dangling
    r = intrinsic(p)
    assert r["duplicate_entity_groups"] == 1 and r["type_conflict_names"] == 1
    assert r["direction_violation_rate"] == pytest.approx(1 / 3)
    assert r["dangling_relation_rate"] == pytest.approx(1 / 3)
    assert r["unknown_relation_type_rate"] == pytest.approx(1 / 3)
    assert r["orphan_entity_rate"] == pytest.approx(2 / 4)       # c2 and x touch no relation


def test_ontology_copy_matches_run_py():
    src = (REPO / "run.py").read_text(encoding="utf-8")
    from evalkit.ontology import ALLOWED_RELATIONSHIPS, DIRECTION_RULES
    allowed = ast.literal_eval(re.search(r"^ALLOWED_RELATIONSHIPS = (\{.*?\})$", src, re.M).group(1))
    rules = ast.literal_eval(re.search(r"^ENTITY_RELATIONSHIP_DIRECTION_RULES = (\{.*?^\})", src, re.M | re.S).group(1))
    assert allowed == ALLOWED_RELATIONSHIPS and rules == DIRECTION_RULES


# --------------------------------------------------------------------------- stats + orchestration

def test_bootstrap_ci_contains_point_estimate_and_shrinks_with_data():
    from evalkit.metrics.prf import Counts, sum_counts
    docs = [Counts(8, 2, 2) for _ in range(40)]
    ci = bootstrap_prf(docs, n=300)["f1"]
    assert ci[0] <= sum_counts(docs).f1 <= ci[1] and ci[1] - ci[0] < 1e-9      # identical docs => zero-width CI
    mixed = [Counts(10, 0, 0), Counts(0, 5, 5)] * 5
    lo, hi = bootstrap_prf(mixed, n=300)["f1"]
    assert hi - lo > 0.05
    assert bootstrap_prf([Counts(1, 0, 0)]) is None


def test_evaluate_perfect_prediction_on_repo_ground_truth():
    card = Card({"name": "synthetic", "loader": "legacy_gt", "options": {"text": "test-synthetic.txt"}})
    g = next(iter(load_dataset(card, REPO / "data" / "test.gt.json")))
    ids = {e.id: f"P{i}" for i, e in enumerate(g.entities)}
    pred = Prediction(doc_id=g.doc_id,
                      entities=[PredEntity(id=ids[e.id], name=e.name, type=e.type, quotes=[e.name]) for e in g.entities],
                      relations=[PredRelation(source=ids[r.source], type=r.type, target=ids[r.target]) for r in g.relations])
    rep = evaluate([g], {g.doc_id: pred}, n_boot=50)
    h = headline(rep)
    assert h["entity_f1_strict"] == 1.0 and h["relation_f1_strict"] == 1.0 and h["typing_accuracy"] == 1.0
    assert h["quote_verbatim_rate"] == 1.0 and h["unsupported_entity_rate"] == 0.0


def test_missing_prediction_is_scored_as_all_missed():
    g = doc([G("g1", "Acme Corp")])
    rep = evaluate([g], {}, n_boot=10)
    assert rep["missing_predictions"] == ["d"] and rep["summary"]["entity_lenient"]["recall"] == 0.0


def test_score_existing_run_directory(workspace):
    """The post-hoc path: a normal run's output.json scored against labels that never touched the pipeline."""
    from evalkit.cli import score_and_report
    run = workspace / "outputs" / "r1"
    run.mkdir(parents=True)
    (run / "output.json").write_text(json.dumps({
        "entities": [{"entity_id": "E1", "canonical_name": "Acme Corp", "entity_type": "Company", "aliases": [None, ""], "citations": []},
                     {"entity_id": "E2", "canonical_name": "Bolt LLC", "entity_type": "Company", "aliases": [], "citations": []}],
        "relationships": [{"source_entity_id": "[E1]", "target_entity_id": "[E2]", "relationship_type": "controls",
                           "citation": {"quote": "q"}}]}), encoding="utf-8")
    g = doc([G("g1", "Acme Corp"), G("g2", "Bolt LLC"), G("g3", "Missed Inc")], [GoldRelation(source="g1", type="controls", target="g2")])
    rep = score_and_report([g], {"d": run}, "adhoc", "e1", out_dir=workspace / "eval_runs" / "e1",
                           langfuse=False, history=False, quiet=True)
    assert rep["headline"]["entity_recall"] == pytest.approx(2 / 3)
    assert rep["headline"]["relation_f1_strict"] == 1.0
    assert (workspace / "eval_runs" / "e1" / "report.md").exists()


# --------------------------------------------------------------------------- diagnostics

def test_error_taxonomy_hand_labelled():
    from evalkit.metrics.diagnostics import diagnose, sensitivity
    g = doc([G("1", "K.", "person"), G("2", "Markenstelle fuer Klasse 2", "company"), G("3", "§ 24 Abs. 4 Vertrag", "agreement"),
             G("4", "Koch", "person"), G("5", "Acme Corp")],
            text="K. Beschluss der Markenstelle fuer Klasse 2 § 24 Abs. 4 Vertrag Koch Acme Corp Urteil vom 3. Mai 2015 in der Sache Revision", exhaustive_entity_types=["person", "company", "agreement"])
    p = Prediction(doc_id="d", entities=[
        P("a", "Acme Corp"),                                            # TP
        P("b", "Beschluss der Markenstelle fuer Klasse 2", "agreement"),    # boundary variant of gold 2 (and why gold 2 is missed)
        P("c", "Planet Zorg", "person"),                                # unsupported (not in the text)
        P("d", "Urteil vom 3. Mai 2015 in der Sache", "agreement"),     # descriptive phrase
        P("e", "Revision", "agreement")])                               # plain extra
    d = diagnose(g, p, align(g.entities, p.entities))
    assert d["missed"] == {"anonymised_placeholder": 1, "boundary_mismatch": 1, "reference_like": 1, "absent": 1}
    assert d["extra"] == {"boundary_variant": 1, "unsupported": 1, "descriptive_phrase": 1, "plain_extra": 1}
    s = sensitivity(g, p, align(g.entities, p.entities))
    assert s["baseline"] == (1, 4, 4)
    assert s["all_filters_combined (ceiling)"] == (1, 1, 1)      # gold left: Acme (TP), Koch (FN); "...Klasse 2" has a digit => filtered; FP: Planet Zorg


def test_cli_rescoring_keeps_failed_documents_in_gold(workspace, monkeypatch):
    """A document that was attempted but crashed must count as all-missed, not vanish from the denominator."""
    import evalkit.cli as cli
    monkeypatch.setattr(cli, "EVAL_RUNS", workspace / "eval_runs")
    monkeypatch.setattr(cli, "HISTORY", workspace / "history.csv")
    ok, bad = workspace / "eval_runs" / "e" / "runs" / "d1", workspace / "eval_runs" / "e" / "runs" / "d2"
    ok.mkdir(parents=True); bad.mkdir(parents=True)
    (ok / "output.json").write_text(json.dumps({"entities": [{"entity_id": "1", "canonical_name": "Acme", "entity_type": "company"}], "relationships": []}), encoding="utf-8")
    (bad / "ops.json").write_text(json.dumps({"run_id": "d2", "status": "failed", "error": "boom", "latency_s": 1, "stages_s": {},
                                              "llm": {"calls": 2, "errors": 0, "prompt_tokens": 100, "completion_tokens": 10, "cost_usd": 0.5, "llm_seconds": 1, "by_model": {}}}), encoding="utf-8")
    g1, g2 = doc([G("a", "Acme")]), doc([G("b", "Bolt")])
    g1.doc_id, g2.doc_id = "d1", "d2"
    rep = cli.score_and_report([g1, g2], {"d1": ok}, "t", "e", ops_dirs=[ok, bad], langfuse=False, history=False, quiet=True)
    assert rep["missing_predictions"] == ["d2"] and rep["headline"]["entity_recall"] == 0.5
    assert rep["ops"]["wasted_usd_failed_runs"] == 0.5 and rep["headline"]["failed_runs"] == 1


def test_export_to_outputs_copies_ui_files_and_skips_failed_runs(tmp_path, monkeypatch):
    from evalkit import cli
    monkeypatch.setattr(cli, "OUTPUTS", tmp_path / "outputs")
    ok, failed = tmp_path / "runs" / "doc-1", tmp_path / "runs" / "doc-2"
    for d in (ok, failed):
        d.mkdir(parents=True)
    for f in ("manifest.json", "output.json", "document.txt", "ops.json"):
        (ok / f).write_text("{}", encoding="utf-8")
    (ok / "raw_artifact.csv").write_text("x", encoding="utf-8")          # docling internals stay in eval_runs/
    (failed / "ops.json").write_text("{}", encoding="utf-8")             # failed run: no output.json
    done = cli.export_to_outputs("EVAL", [ok, failed])
    assert done == [tmp_path / "outputs" / "EVAL__doc-1"]
    assert sorted(p.name for p in done[0].iterdir()) == ["document.txt", "manifest.json", "ops.json", "output.json"]
