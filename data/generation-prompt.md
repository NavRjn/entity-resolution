# Synthetic Legal Relationship Benchmark Generator

## Step 1: Generate Entities

Create 5 entities. 

Allowed types:

* company
* person
* agreement
* product
* organization
* regulator
* subsidiary

Return JSON only.

Example:

[
{
"entity_name": "Aurora Strategic Holdings, Inc.",
"entity_type": "company"
}
]

---

## Step 2: Generate Relationship Ground Truth

Using ONLY the entities created above, generate between 5-10 relationships. 

Allowed relationship types:

* acquired
* owns
* subsidiary_of
* party_to_agreement
* signatory_for
* licensed_to
* transferred_to
* ceo_of
* director_of
* regulated_by
* investigated_by
* custodian_for
* trustee_for
* supplier_to
* contracted_with

Requirements:

* Every relationship must connect existing entities.
* No invented entities.
* No duplicate relationships.
* Relationships must be logically consistent.

Return JSON only.

Example:

{
"relationships": [
{
"source": "Aurora Strategic Holdings, Inc.",
"relationship": "acquired",
"target": "Helios BioAnalytics Corporation"
}
]
}

---

## Step 3: Generate Legal Memorandum

Generate a realistic insurance, reinsurance, compliance, acquisition, governance, or regulatory memorandum. With a strict character count of 1000 chars. 

Requirements:

* Every relationship must appear at least once in the text.
* Every entity must appear at least once.
* Use realistic legal language.
* Include distracting facts and unrelated narrative.
* Include aliases, abbreviations, and repeated references.
* Do NOT include a relationship table.
* The relationship graph must be recoverable only from the prose.

Output only the memorandum text.
