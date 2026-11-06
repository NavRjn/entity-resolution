from engine.aliases import defined_terms, key, resolve


def _e(eid, name, typ="company", aliases=(), n_cit=1):
    return {"entity_id": eid, "canonical_name": name, "entity_type": typ, "aliases": list(aliases),
            "citations": [{"file_id": "f", "chunk_id": 0, "start_char": i, "end_char": i + 3, "quote": "abc",
                           "match": "verbatim"} for i in range(n_cit)]}


def _rel(a, b, t="controls"):
    return {"source_entity_id": a, "target_entity_id": b, "relationship_type": t, "citation": {}}


def test_key_strips_legal_form_and_articles():
    assert key("The ABC GmbH & Co. KG") == "abc"
    assert key("Acme, Inc.") == "acme"
    assert key("Verein e.V.") == "verein"
    assert key("Co") == "co"            # never strip a name to nothing


def test_defined_terms_english_and_german():
    text = ('Aurora Holdings GmbH (nachfolgend "Aurora") und die Nordlicht AG (vormals Polar Handel GmbH) '
            'sowie Acme Inc. (hereinafter the “Company”) and Beta Corp. (hereinafter "Beta").')
    pairs = dict(defined_terms(text))
    assert pairs["Aurora Holdings GmbH"] == "Aurora"
    assert pairs["Nordlicht AG"] == "Polar Handel GmbH"
    assert pairs["Beta Corp."] == "Beta"
    assert "Acme Inc." not in pairs                 # "Company" is a generic term, not an alias


def test_defined_term_adds_alias_but_never_invents_entities():
    data = {"entities": [_e("1", "Aurora Holdings GmbH")], "relationships": []}
    stats = resolve(data, 'Aurora Holdings GmbH (nachfolgend "Aurora") signed. Unknown Corp. (hereinafter "UC").')
    assert data["entities"][0]["aliases"] == ["Aurora"]
    assert len(data["entities"]) == 1 and stats["aliases_added"] == 1


def test_defined_term_merges_existing_duplicate_and_rewires_relationships():
    data = {"entities": [_e("1", "Aurora Holdings GmbH", n_cit=2), _e("2", "Aurora"), _e("3", "Bob", "person")],
            "relationships": [_rel("2", "3"), _rel("1", "3")]}
    resolve(data, 'Aurora Holdings GmbH (nachfolgend "Aurora") employs Bob.')
    assert [e["entity_id"] for e in data["entities"]] == ["1", "3"]
    assert data["entities"][0]["aliases"] == ["Aurora"]
    assert len(data["relationships"]) == 1            # duplicate after rewiring collapsed


def test_legal_form_variants_merge_and_prefer_full_name():
    data = {"entities": [_e("1", "ABC"), _e("2", "ABC GmbH", n_cit=3)], "relationships": []}
    stats = resolve(data, "no definitions here")
    assert len(data["entities"]) == 1 and stats["merged_same_name"] == 1
    assert data["entities"][0]["canonical_name"] == "ABC GmbH" and data["entities"][0]["aliases"] == ["ABC"]


def test_same_name_person_and_company_merges_to_company_with_legal_form():
    data = {"entities": [_e("1", "Northbridge Risk Ltd", "company"), _e("2", "Northbridge Risk", "person")],
            "relationships": []}
    resolve(data, "x")
    assert len(data["entities"]) == 1 and data["entities"][0]["entity_type"] == "company"


def test_different_companies_stay_separate():
    data = {"entities": [_e("1", "Acme Insurance AG"), _e("2", "Acme Holdings AG")], "relationships": []}
    resolve(data, "x")
    assert len(data["entities"]) == 2
