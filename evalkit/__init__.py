"""Source-agnostic evaluation for the entity-resolution pipeline.

Layers (each only depends on the ones above it):
    schema      canonical gold/prediction data model
    normalize   name + type normalisation
    loaders/    dataset formats -> schema.GoldDocument (CoNLL, DocRED, SQuAD/CUAD, Textract, native)
    predictions pipeline output -> schema.Prediction
    matching    gold<->pred entity alignment
    metrics/    entity, clustering, relation, provenance, intrinsic, stats
    evaluate    orchestration -> Report
"""
