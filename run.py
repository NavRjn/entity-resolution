# %%
import argparse
import json
import string
import logging
from pathlib import Path
from typing import List, Dict, Optional
import datetime
import re
from uuid import uuid4
import fitz  # PyMuPDF
import ollama
# from bs4 import BeautifulSoup
from pydantic import BaseModel, Field
from rapidfuzz import fuzz
from rich.console import Console
from rich.table import Table
from rich.logging import RichHandler

OLLAMA_CLIENT = ollama.Client(
    host="http://127.0.0.1:11434"
)

# --- CONFIG & OBSERVABILITY ---
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    datefmt="[%X]",
    handlers=[RichHandler(rich_tracebacks=True)]
)
logger = logging.getLogger("EntityResolution")
console = Console()


# --- SCHEMAS ---
class ExtractedEntity(BaseModel):
    entity_name: str
    entity_type: str
    exact_quote: str  # Enforcing provenance


class EntityList(BaseModel):
    entities: list[ExtractedEntity]


class ValidatedEntity(BaseModel):
    chunk_id: int
    entity_name: str
    entity_type: str
    exact_quote: str
    is_valid: bool
    fail_reason: Optional[str] = None


class CanonicalEntity(BaseModel):
    entity_id: str

    canonical_name: str
    entity_type: str

    aliases: list[str] = Field(default_factory=list)
    evidence_quotes: list[str] = Field(default_factory=list)
    source_chunks: list[int] = Field(default_factory=list)


class Relationship(BaseModel):
    source_entity: str
    target_entity: str

    relationship_type: str

    evidence_quote: str
    chunk_id: int


class RelationshipList(BaseModel):
    relationships: list[Relationship]


# --- PROMPTS ---
SYSTEM_PROMPT = """
You are an expert legal entity extraction system.
Extract all corporate, legal, and personal entities from the text.

Do NOT extract locations (cities, countries).
Do NOT extract dates.
Do NOT extract monetary values or clause references.

Agreements:
- Transitional Manufacturing and Support Agreement
- Retention and Transition Bonus Agreements

Products:
- AegisPoint(TM)
- SentinelGrid Analytics
- OmniPath Clinical Exchange
- SAP Horizon Enterprise Suite

Schema:
[
  {
    "entity_name": "Standardized Name (e.g. Acme Corp)",
    "entity_type": "company|person|organization|agreement|product|other",
    "exact_quote": "The exact string from the text proving this exists."
  }
]
Return ONLY valid JSON.
"""

RELATIONSHIP_SYSTEM_PROMPT = """
You are an expert legal relationship extraction system.

Identify explicit relationships between entities.

Allowed relationships:

- party_to_agreement
- acquired_by
- owns
- subsidiary_of
- signatory_for
- licensed_to
- transferred_to

Only extract relationships directly supported by the text.

Return JSON:

{
  "relationships": [
    {
      "source_entity": "...",
      "target_entity": "...",
      "relationship_type": "...",
      "evidence_quote": "..."
    }
  ]
}
"""

ENTITY_PROMPT_TEMPLATE = lambda chunk: f"""
Extract the entities in the following text.

TEXT:
<<<
{chunk}
>>>
"""

RELATIONSHIP_PROMPT_TEMPLATE = lambda chunk: f"""
TEXT:
<<<
{chunk}
>>>
"""

LEGAL_SUFFIXES = {"inc", "corp", "corporation", "llc", "ltd", "limited", "company", "co", "plc", "group", "holdings"}


# --- PIPELINE COMPONENTS ---

def extract_text(path: Path) -> str:
    """Ingest document into raw text string."""
    logger.info(f"Ingesting file: {path}")
    text = []
    if path.suffix == ".pdf":
        with fitz.open(path) as doc:
            for page in doc:
                text.append(page.get_text())
    elif path.suffix == ".txt":
        with open(path, "r", encoding="utf-8") as f:
            text.append(f.read())
    else:
        raise ValueError(f"Unsupported file type: {path.suffix}")
    return "\n".join(text)


def chunk_text_with_overlap(text: str, max_chars: int = 2000, overlap_chars: int = 200) -> List[str]:
    """
    Sentence-aware chunking with overlap for maximum recall.
    (Approximates tokens via chars to keep it lean without heavy tokenizers yet).
    """
    sentences = re.split(r'(?<=[.!?])\s+', text)
    chunks = []
    current_chunk = ""

    for sentence in sentences:
        if len(current_chunk) + len(sentence) < max_chars:
            current_chunk += sentence + " "
        else:
            chunks.append(current_chunk.strip())
            # Start next chunk with overlap from the end of the previous
            overlap_text = current_chunk[-overlap_chars:] if len(current_chunk) > overlap_chars else current_chunk
            # snap overlap to the nearest sentence boundary safely
            overlap_sentences = re.split(r'(?<=[.!?])\s+', overlap_text)
            current_chunk = " ".join(overlap_sentences[1:]) + " " + sentence + " "

    if current_chunk:
        chunks.append(current_chunk.strip())

    logger.info(f"Generated {len(chunks)} chunks with overlap.")
    return chunks


def _call_llm(user_prompt: str, system_prompt: str, schema: dict, seed: int = 42) -> dict:
    """Generic LLM caller used by both entity and relationship extraction."""
    try:
        res = OLLAMA_CLIENT.chat(
            model="qwen2.5:7b-instruct-q4_K_M",
            format=schema,  # Ensure JSON mode
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            options={
                "temperature": 0.0,
                "seed": seed,
                # "num_ctx": 1024,  # <-- Speeds up prompt processing
                # "num_predict": 256  # <-- Speeds up generation (fail fast)
            }
        )
        return json.loads(res["message"]["content"])
    except Exception as e:
        logger.error(f"LLM Call failed: {str(e)}")
        return {}


def extract_entities(chunk: str, seed: int = 42) -> List[ExtractedEntity]:
    """Extracts entities using the generic LLM caller."""
    prompt = ENTITY_PROMPT_TEMPLATE(chunk)
    data = _call_llm(prompt, SYSTEM_PROMPT, EntityList.model_json_schema(), seed)
    entities = data.get("entities", [])
    return [ExtractedEntity(**item) for item in entities]


def extract_relationships(chunk: str, chunk_id: int, seed: int = 42) -> List[Relationship]:
    """Extracts relationships using the generic LLM caller."""
    prompt = RELATIONSHIP_PROMPT_TEMPLATE(chunk)
    data = _call_llm(prompt, RELATIONSHIP_SYSTEM_PROMPT, RelationshipList.model_json_schema(), seed)
    relationships = data.get("relationships", [])
    return [
        Relationship(
            source_entity=item["source_entity"],
            target_entity=item["target_entity"],
            relationship_type=item["relationship_type"],
            evidence_quote=item["evidence_quote"],
            chunk_id=chunk_id
        )
        for item in relationships]


def validate_guardrails(entity: ExtractedEntity, chunk_text: str, chunk_id: int) -> ValidatedEntity:
    """The Zero-Hallucination Guardrail."""
    # Normalize spaces for robust checking, but retain characters
    norm_chunk = re.sub(r'\s+', ' ', chunk_text)
    norm_quote = re.sub(r'\s+', ' ', entity.exact_quote)

    is_valid = norm_quote in norm_chunk
    reason = None if is_valid else f"Hallucination: Quote not found in chunk."

    if is_junk_entity(entity.entity_name):
        is_valid = False
        reason = "Matched junk regex filter"
    if is_empty_after_normalization(entity.entity_name):
        is_valid = False
        reason = "Entity collapsed after normalization"

    return ValidatedEntity(
        chunk_id=chunk_id,
        entity_name=entity.entity_name,
        entity_type=entity.entity_type,
        exact_quote=entity.exact_quote,
        is_valid=is_valid,
        fail_reason=reason
    )


def validate_relationship(relationship: Relationship, chunk_text: str) -> bool:
    """Validates that the relationship evidence actually exists in the chunk."""
    norm_chunk = re.sub(r"\s+", " ", chunk_text)
    norm_quote = re.sub(r"\s+", " ", relationship.evidence_quote)

    return norm_quote in norm_chunk


def normalize_entity_name(name: str) -> str:
    s = name.lower().strip()
    s = re.sub(r"[\.\-\s]+", " ", s)
    s = s.translate(str.maketrans("", "", string.punctuation))
    words = [w for w in s.split() if w not in LEGAL_SUFFIXES]
    return " ".join(words)


def resolve_entities(validated_entities: List[ValidatedEntity]) -> List[CanonicalEntity]:
    """Merges entities using fuzzy logic."""
    canonicals: List[CanonicalEntity] = []

    for ve in validated_entities:
        if not ve.is_valid:
            continue

        norm_name = normalize_entity_name(ve.entity_name)
        matched = False

        for c in canonicals:
            # Check canonical name and aliases
            candidates = [normalize_entity_name(c.canonical_name)] + [normalize_entity_name(a) for a in c.aliases]

            if is_acronym(ve.entity_name, c.canonical_name):
                c.aliases.append(ve.entity_name)
                matched = True

            for candidate in candidates:
                if fuzz.token_sort_ratio(norm_name, candidate) > 90:  # Keep high for strictness
                    if ve.entity_name not in c.aliases and ve.entity_name != c.canonical_name:
                        c.aliases.append(ve.entity_name)
                    if ve.exact_quote not in c.evidence_quotes:
                        c.evidence_quotes.append(ve.exact_quote)
                    if ve.chunk_id not in c.source_chunks:
                        c.source_chunks.append(ve.chunk_id)
                    matched = True
                    break
            if matched:
                break

        if not matched:
            canonicals.append(
                CanonicalEntity(
                    entity_id=str(uuid4()),
                    canonical_name=ve.entity_name,
                    entity_type=ve.entity_type,
                    aliases=[],
                    evidence_quotes=[ve.exact_quote],
                    source_chunks=[ve.chunk_id],
                )
            )

    return canonicals


def display_results(canonicals: List[CanonicalEntity], relationships: List[Relationship], dropped: int):
    """CLI rendering of the relationship table."""
    table = Table(title="Resolved Entities Table")
    table.add_column("Canonical Name", style="cyan", no_wrap=True)
    table.add_column("Type", style="magenta")
    table.add_column("Aliases Found", style="green")
    table.add_column("Source Chunks", justify="right", style="yellow")

    for c in canonicals:
        aliases_str = ", ".join(c.aliases) if c.aliases else "None"
        chunks_str = ", ".join(map(str, c.source_chunks))
        table.add_row(c.canonical_name, c.entity_type, aliases_str, chunks_str)

    console.print(table)

    if relationships:
        rel_table = Table(title="Extracted Relationships")
        rel_table.add_column("Source", style="cyan")
        rel_table.add_column("Relationship", style="magenta")
        rel_table.add_column("Target", style="cyan")
        rel_table.add_column("Chunk", style="yellow", justify="right")

        for r in relationships:
            rel_table.add_row(r.source_entity, r.relationship_type, r.target_entity, str(r.chunk_id))

        console.print(rel_table)

    if dropped > 0:
        logger.warning(f"Guardrails blocked {dropped} hallucinated/invalid entities.")


def is_junk_entity(name: str) -> bool:
    # 1. Drop if it's purely a currency or number
    if re.search(r'^(USD|\$|€|£)?\s*[\d\,\.]+$', name.strip()):
        return True
    # 2. Drop if it's a contract clause reference
    if re.search(r'^(Section|Article|Clause)\s+\d+', name, re.IGNORECASE):
        return True
    # 3. Drop generic plurals
    if name.lower().endswith(('personnel', 'employees', 'staff', 'shareholders')):
        return True
    # 4. Drop if it's JUST a legal suffix (like "Ltd.")
    normalized = normalize_entity_name(name)

    if normalized == "":
        return True
    return False


def is_acronym(short_name: str, long_name: str) -> bool:
    if len(short_name) < 2 or len(short_name) > 6:
        return False
    # Create acronym from long name (e.g. "Food and Drug Administration" -> "FADA" or "FDA")
    words = [w for w in long_name.split() if w.lower() not in ('and', 'of', 'the', 'for')]
    expected_acronym = "".join([w[0].upper() for w in words if w])
    return short_name.upper() == expected_acronym


def is_empty_after_normalization(name: str) -> bool:
    return normalize_entity_name(name).strip() == ""


def entity_name_in_quote(entity_name: str, quote: str) -> bool:
    return entity_name.lower() in quote.lower()


def looks_incomplete_person(name: str) -> bool:
    parts = name.strip().split()

    if len(parts) < 2:
        return True

    if len(parts[-1]) == 2 and parts[-1].endswith("."):
        return True

    return False


def build_networkx_graph(entities: List[CanonicalEntity], relationships: List[Relationship]):
    """Builds a NetworkX directed graph from entities and relationships."""
    import networkx as nx

    graph = nx.DiGraph()

    for entity in entities:
        graph.add_node(
            entity.entity_id,
            label=entity.canonical_name,
            entity_type=entity.entity_type
        )

    name_to_id = {
        e.canonical_name: e.entity_id
        for e in entities
    }
    # Also map aliases so relationships pointing to an alias still connect
    for e in entities:
        for alias in e.aliases:
            name_to_id[alias] = e.entity_id

    for rel in relationships:
        source_id = name_to_id.get(rel.source_entity)
        target_id = name_to_id.get(rel.target_entity)

        if source_id and target_id:
            graph.add_edge(
                source_id,
                target_id,
                relationship=rel.relationship_type,
                evidence=rel.evidence_quote
            )

    return graph


# --- MAIN EXECUTION ---

def run_pipeline(file_path: str, seed: int, run_id: str):
    logger.info(f"Starting Pipeline | Run ID: {run_id} | Seed: {seed}")

    text = extract_text(Path(file_path))
    chunks = chunk_text_with_overlap(text)

    all_validated_entities = []
    all_relationships = []
    hallucination_count = 0

    with console.status("[bold green]Processing chunks with LLM...") as status:
        for idx, chunk in enumerate(chunks):
            # 1. Extract Entities
            raw_entities = extract_entities(chunk, seed=seed)
            for raw_ent in raw_entities:
                validated = validate_guardrails(raw_ent, chunk, idx)
                all_validated_entities.append(validated)
                if not validated.is_valid:
                    hallucination_count += 1

            # 2. Extract Relationships
            raw_relationships = extract_relationships(chunk, idx, seed=seed)
            for rel in raw_relationships:
                if validate_relationship(rel, chunk):
                    all_relationships.append(rel)

    logger.info("Resolving and grouping entities...")
    canonicals = resolve_entities(all_validated_entities)

    display_results(canonicals, all_relationships, hallucination_count)

    # Ensure networkx graph builds properly
    try:
        nx_graph = build_networkx_graph(canonicals, all_relationships)
        logger.info(
            f"Built NetworkX Graph with {nx_graph.number_of_nodes()} nodes and {nx_graph.number_of_edges()} edges.")
    except ImportError:
        logger.warning("NetworkX not installed. Skipping graph generation test in memory.")

    # --- NEW: Reproducible JSON Output ---
    output_dir = Path("outputs")
    output_dir.mkdir(exist_ok=True)

    output_file = output_dir / f"{run_id}.json"

    # Save both entities and relationships
    output = {
        "entities": [c.model_dump() for c in canonicals],
        "relationships": [r.model_dump() for r in all_relationships]
    }

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)

    logger.info(f"Saved reproducible output to {output_file}")
    return output_file


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", type=str, default="data/test-synthetic.txt", help="Path to document")
    parser.add_argument("--seed", type=int, default=42, help="Deterministic seed for LLM")
    parser.add_argument("--run_name", type=str, default=None, help="Custom name for the run output")
    args = parser.parse_args()

    # Generate timestamped run ID if none provided
    run_id = args.run_name or datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    run_pipeline(args.file, args.seed, run_id)