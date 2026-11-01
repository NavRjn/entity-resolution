"""
This is the basic API entrypoint for all document processing requirements

"""
import json
from dataclasses import dataclass
from typing import Optional
from pathlib import Path
import sys
import csv
from .template import OntologyDocument
from dotenv import load_dotenv
load_dotenv()

from docling_graph import PipelineConfig, run_pipeline, PipelineContext
from run import Citation, CanonicalEntity, EntityList, Relationship, RelationshipList

@dataclass
class RunContext:
    # Input fields
    run_id: str
    file_id: str
    file_path: Path # TODO: add optional support
    output_dir: Path # TODO: add optional support

    # Output fields
    doc_ctx: Optional[PipelineContext] = None


def save_compatible_files(run_id: str, source_file: Path, output_dir: Path):
    """
    The function should read OUTPUTDIR/*/docling_graph/nodes.csv, edges.csv
    Should create new OUTPUTDIR/manifest.json and output.json
    :return:
    """

    graph_path = next(output_dir.glob("*/docling_graph"))
    metadata_path = next(output_dir.glob("*/metadata.json"))
    if not graph_path.exists():
        nodes = {}
        edges = {}
        metadata = {}
    else:
        print("Reading ", str(graph_path))
        with (graph_path/"nodes.csv").open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            nodes = list(reader)
        with (graph_path/"edges.csv").open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            edges = list(reader)
        with metadata_path.open("r", encoding="utf-8") as f:
            metadata =json.load(f)

    created_at = metadata.get("timestamp", "")

    manifest = {
        "run_id": str(run_id),
        "created_at": created_at,
        "source_file": str(source_file),
        "seed": 0,
        "chunk_max_chars": None,
        "chunk_overlap_chars": None
    }


    entities = [{
        "entity_id": node.get("id", "NA"),
        "canonical_name": node.get("name", "NA"),
        "entity_type": node.get("label", "NA"),
        "aliases": [node.get("merged_aliases")],
        "citations": [Citation(
            file_id=(prov := json.loads(node.get("__provenance__"))).get("document_id", "NA"), # use walrus operator to convert string to json on the fly
            chunk_id=prov.get("chunks")[0],
            start_char=0, end_char=0,
            quote=ref
        ).model_dump() for ref in json.loads(node.get("__provenance__")).get("refs", ["NA"])] # TODO: Improve compatibility
    } for node in nodes if node.get("label") != "OntologyDocument"]

    relationships = [{
        "source_entity_id": edge.get("source", "NA"),
        "target_entity_id": edge.get("target", "NA"),
        "relationship_type": edge.get("label", "NA"),
        "citation": Citation(
        file_id="NA", chunk_id=0, start_char=0, end_char=0, quote=""
    ).model_dump()
    } for edge in edges if "OntologyDocument" not in edge.get("source")]

    output = {"entities": entities, "relationships": relationships}

    with open(output_dir/"manifest.json", "w", encoding="utf-8") as f:
        print("Saving manifest.json at ", str(output_dir/"manifest.json"))
        json.dump(manifest, f, indent=2, ensure_ascii=False, default=str)

    with open(output_dir/"output.json", "w", encoding="utf-8") as f:
        print("Saving output.json at ", str(output_dir/"output.json"))
        json.dump(output, f, indent=2, ensure_ascii=False, default=str)



def run_full(ctx: RunContext) -> RunContext:

    run_id = ctx.run_id
    file_id = ctx.file_id
    file_path = ctx.file_path
    output_dir = ctx.output_dir

    print("Searching in Paths:...")
    for path in sys.path:
        print(path)

    cfg = PipelineConfig(
        source=str(file_path),
        template="engine.template.OntologyDocument",
        backend="llm",
        inference="remote",
        provider_override="openai",
        model_override="gpt-4o",
        dump_to_disk=True,
        output_dir=output_dir
    )

    doc_ctx = run_pipeline(cfg)
    ctx.doc_ctx = doc_ctx
    
    save_compatible_files(run_id, file_path, output_dir)
    return ctx



