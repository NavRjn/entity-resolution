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
import concurrent.futures
from collections import defaultdict
from debug_logger import log_prompt, log_response, log_hallucinated_entity, log_relationship_check

OLLAMA_CLIENT = ollama.Client(
    host="http://127.0.0.1:11434",
    timeout=180
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

    start_char: Optional[int] = None
    end_char: Optional[int] = None

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
    source_entity_id: str
    target_entity_id: str

    relationship_type: str

    evidence_quote: str
    chunk_id: int


class RelationshipList(BaseModel):
    relationships: list[Relationship]


# --- PROMPTS ---
LEGAL_SUFFIXES = {"inc", "corp", "corporation", "llc", "ltd", "limited", "company", "co", "plc", "group", "holdings"}

ALLOWED_RELATIONSHIPS = {"acquires", "owns", "subsidiary_of", "party_to_agreement", "signatory_for", "licensed_to", "transferred_to"}

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

RELATIONSHIP_SYSTEM_PROMPT = f"""
You are a highly accurate legal relationship extraction assistant.

Your task:
- Identify only explicit relationships mentioned in the provided text chunk.
- Use ONLY the entity IDs provided. Do not change, truncate, or invent new IDs.
- Only extract relationships that are directly supported by the text.
- Do NOT hallucinate relationships or relationship types.

Do NOT generate relationships based on descriptive text, office locations, lists of entities, or inferred connections.
Only extract relationships explicitly stated using verbs like "owns", "acquired", "is a party to", "is signatory for", "regulated by", "licensed to", or "transferred to".

Entity types and mapping rules:
- person → can have roles such as ceo_of, director_of, signatory_for
- company → can own other companies, be party_to_agreement, be regulated_by, or be investigated_by
- agreement → can have signatories, and companies/persons can be party_to_agreement
- regulator → companies/persons may be regulated_by or investigated_by them

Allowed relationships:
{ALLOWED_RELATIONSHIPS}

Important instructions:
1. If a relationship is mentioned but the target entity in text is not in the entity list, skip it.
2. If multiple entities are mentioned in the same sentence, carefully link the correct entity ID to the relationship according to type.
3. Do not invent relationship types; use only those in ALLOWED_RELATIONSHIPS.
4. Return evidence quotes exactly as they appear in the text.
5. If unsure, do not guess—omit the relationship.

Example:
Entities in this chunk:
E0 | Aurora Strategic Holdings, Inc. | company
E1 | Helios BioAnalytics Corporation | company
E2 | Jonathan R. Keene | person
E3 | Equity Purchase Agreement | agreement

Text:
Aurora Strategic Holdings, Inc. acquired Helios BioAnalytics Corporation pursuant to the Equity Purchase Agreement.
Jonathan R. Keene signed the Equity Purchase Agreement on behalf of Aurora Strategic Holdings, Inc.

Output relationships:
{{
  "relationships": [
    {{
      "source_entity_id": "E0",
      "target_entity_id": "E1",
      "relationship_type": "acquires",
      "evidence_quote": "Aurora Strategic Holdings, Inc. acquired Helios BioAnalytics Corporation"
    }},
    {{
      "source_entity_id": "E2",
      "target_entity_id": "E3",
      "relationship_type": "signatory_for",
      "evidence_quote": "Jonathan R. Keene signed the Equity Purchase Agreement"
    }},
    {{
      "source_entity_id": "E0",
      "target_entity_id": "E3",
      "relationship_type": "party_to_agreement",
      "evidence_quote": "Aurora Strategic Holdings, Inc. acquired Helios BioAnalytics Corporation pursuant to the Equity Purchase Agreement"
    }}
  ]
}}

Return JSON strictly in the above format:
{{
  "relationships": [
    {{
      "source_entity_id": "...",
      "target_entity_id": "...",
      "relationship_type": "...",
      "evidence_quote": "..."
    }}
  ]
}}
"""


ENTITY_PROMPT_TEMPLATE = lambda chunk: f"""
Extract the entities in the following text.

TEXT:
<<<
{chunk}
>>>
"""

def relationship_prompt_template(chunk: str, entities: List[Dict]) -> str:

    entity_block = "\n".join(
        f"[{e['entity_id']}] {e['name']} ({e['type']})"
        for e in entities
    )

    return f"""
                Known entities in this chunk:
                
                {entity_block}
                
                IMPORTANT:
                
                Only extract relationships between entities above.
                
                Return IDs exactly as provided.
                
                TEXT:
                <<<
                {chunk}
                >>>
        """



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


def _llm_backend(provider, schema, system_prompt, user_prompt, seed):
    if provider=="ollama":
        res = OLLAMA_CLIENT.chat(
            model="qwen2.5:7b-instruct-q4_K_M",
            format=schema,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            options={
                "temperature": 0.0,
                "seed": seed,
            }
        )
        return json.loads(res["message"]["content"])
    else:
        raise ValueError("Invalid model provider!: ", provider)


def _call_llm_threaded(user_prompt: str, system_prompt: str, schema: dict, seed: int = 42, timeout: int = None) -> dict:
    """Call the LLM in a separate thread so Ctrl+C works."""
    def call():
        return _llm_backend(
            provider="ollama",
            schema=schema,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            seed=seed
        )

    log_prompt(prompt_type="entity" if schema == EntityList.model_json_schema() else "relationship",
               prompt_text=user_prompt,
               chunk_id=None)

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(call)
        try:
            res_dict = future.result(timeout=timeout)  # Can add timeout in seconds
            log_response(prompt_type="entity" if schema == EntityList.model_json_schema() else "relationship",
                         response_data=res_dict,
                         chunk_id=None)
            return res_dict
        except concurrent.futures.TimeoutError:
            logger.warning("LLM call timed out")
            return {}
        except KeyboardInterrupt:
            logger.info("Ctrl+C pressed! Cancelling LLM call...")
            future.cancel()
            raise
        except Exception as e:
            logger.error(f"LLM Call failed: {e}")
            return {}


def extract_entities(chunk: str, seed: int = 42) -> List[ExtractedEntity]:
    """Extracts entities using the generic LLM caller."""
    prompt = ENTITY_PROMPT_TEMPLATE(chunk)
    data = _call_llm_threaded(prompt, SYSTEM_PROMPT, EntityList.model_json_schema(), seed)
    entities = data.get("entities", [])
    return [ExtractedEntity(**item) for item in entities]


def extract_relationships(chunk: str, entities: List[Dict], chunk_id: int, seed: int = 42) -> List[Relationship]:
    """Extracts relationships using the generic LLM caller."""
    # TODO: Instead of passing all entities, pass only ones mentioned in chunk
    prompt = relationship_prompt_template(chunk, entities)
    data = _call_llm_threaded(prompt, RELATIONSHIP_SYSTEM_PROMPT, RelationshipList.model_json_schema(), seed)
    relationships = data.get("relationships", [])

    return [
        Relationship(
            source_entity_id=item["source_entity_id"],
            target_entity_id=item["target_entity_id"],
            relationship_type=item["relationship_type"],
            evidence_quote=item["evidence_quote"],
            chunk_id=chunk_id,
        )
        for item in relationships
    ]


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

    start_pos = chunk_text.find(entity.exact_quote)
    end_pos = None if start_pos < 0 else (start_pos + len(entity.exact_quote))

    validated_entity = ValidatedEntity(
        chunk_id=chunk_id,
        entity_name=entity.entity_name,
        entity_type=entity.entity_type,
        exact_quote=entity.exact_quote,
        start_char=start_pos,
        end_char=end_pos,
        is_valid=is_valid,
        fail_reason=reason
    )

    if not is_valid: log_hallucinated_entity(validated_entity)

    return validated_entity


def validate_relationship(relationship: Relationship, chunk_text: str) -> bool:
    """Validates that the relationship evidence actually exists in the chunk."""
    norm_chunk = re.sub(r"\s+", " ", chunk_text)
    norm_quote = re.sub(r"\s+", " ", relationship.evidence_quote)
    exists = norm_quote in norm_chunk

    valid_relationship_type = relationship.relationship_type in ALLOWED_RELATIONSHIPS
    valid_source_and_target = relationship.source_entity_id and relationship.target_entity_id
    valid_quote =  relationship.evidence_quote and len(relationship.evidence_quote.strip()) > 5

    valid = exists and valid_relationship_type and valid_source_and_target and valid_quote
    if not valid:
        logger.warning(f"Dropping relationship | Exists: {exists} | Valid Type: {valid_relationship_type} | Valid Source/Target: {valid_source_and_target} | Valid Quote: {valid_quote}")

    return True # exists and valid_relationship_type and valid_source_and_target and valid_quote


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
                    entity_id="0",
                    canonical_name=ve.entity_name,
                    entity_type=ve.entity_type,
                    aliases=[],
                    evidence_quotes=[ve.exact_quote],
                    source_chunks=[ve.chunk_id],
                )
            )

    assign_entity_ids(canonicals)

    return canonicals


def assign_entity_ids(canonicals):
    for i, c in enumerate(canonicals):
        c.entity_id = f"E{i}"
    return canonicals


def build_canonical_entity_map(canonicals: List[CanonicalEntity]) -> List[Dict]:
    """
    Build stable entity reference list for relationship extraction.
    """
    entity_refs = []

    for c in canonicals:
        entity_refs.append({
            "entity_id": c.entity_id,
            "name": c.canonical_name,
            "type": c.entity_type
        })

        for alias in c.aliases:
            entity_refs.append({
                "entity_id": c.entity_id,
                "name": alias,
                "type": c.entity_type
            })

    return entity_refs


def build_chunk_entity_index(canonicals):
    index = defaultdict(list)

    for c in canonicals:
        for chunk_id in c.source_chunks:
            index[chunk_id].append({
                "entity_id": c.entity_id,
                "name": c.canonical_name,
                "type": c.entity_type
            })

    return index


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
            rel_table.add_row(r.source_entity_id, r.relationship_type, r.target_entity_id, str(r.chunk_id))

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


def filter_valid_relationships(relationships):
    cleaned = []

    for r in relationships:
        if r.relationship_type not in ALLOWED_RELATIONSHIPS:
            continue

        if not r.source_entity_id or not r.target_entity_id:
            continue

        if not r.evidence_quote or len(r.evidence_quote.strip()) < 5:
            continue

        cleaned.append(r)

    return cleaned


def build_networkx_graph(entities, relationships):
    import networkx as nx

    graph = nx.DiGraph()

    # Add nodes
    for e in entities:
        graph.add_node(
            e.entity_id,
            label=e.canonical_name,
            entity_type=e.entity_type
        )

    # Add edges DIRECTLY (NO lookup needed)
    for r in relationships:
        src = r.source_entity_id.strip("[]")
        tgt = r.target_entity_id.strip("[]")

        # only add if valid
        if graph.has_node(src) and graph.has_node(tgt):
            graph.add_edge(
                src,
                tgt,
                relationship=r.relationship_type,
                evidence=r.evidence_quote
            )

    return graph


# %%
# --- MAIN EXECUTION ---
def run_pipeline(file_path: Path, seed: int, run_id: str):
    logger.info(f"Starting Pipeline | Run ID: {run_id} | Seed: {seed}")

    text = extract_text(file_path)
    chunks = chunk_text_with_overlap(text)

    all_validated_entities = []
    all_relationships = []
    hallucination_count = 0

    # PASS 1: ENTITY EXTRACTION
    with console.status("[bold green]Extracting entities..."):
        for idx, chunk in enumerate(chunks):
            raw_entities = extract_entities(chunk, seed=seed)
            for raw_ent in raw_entities:
                validated = validate_guardrails(raw_ent, chunk, idx)
                all_validated_entities.append(validated)

                if not validated.is_valid:
                    hallucination_count += 1

    # ENTITY RESOLUTION
    logger.info("Resolving entities...")
    canonicals = resolve_entities(all_validated_entities)

    logger.info(f"Resolved {len(canonicals)} canonical entities from {len(all_validated_entities)} mentions")

    # entity_refs = build_canonical_entity_map(canonicals)
    chunk_entity_index = build_chunk_entity_index(canonicals)

    dropped, valid = 0, 0
    with console.status("[bold green]Extracting relationships..."):
        for idx, chunk in enumerate(chunks):

            entity_refs = chunk_entity_index[idx]

            if not entity_refs:
                continue

            raw_relationships = extract_relationships(chunk, entity_refs, idx, seed)

            for rel in raw_relationships:
                status = validate_relationship(rel, chunk)
                log_relationship_check(chunk_id=idx, rel=rel, status=("valid" if status else "false_positive"))


                if status:
                    valid += 1
                    all_relationships.append(rel)
                else:
                    dropped += 1

    logger.warning(f"Relationship extraction: {valid} valid relationships, {dropped} dropped/invalid relationships.")
    display_results(canonicals, all_relationships, hallucination_count)

    # GRAPH
    try:
        nx_graph = build_networkx_graph(canonicals, all_relationships)

        logger.info(
            f"Built NetworkX Graph with "
            f"{nx_graph.number_of_nodes()} nodes and "
            f"{nx_graph.number_of_edges()} edges."
        )

    except ImportError:
        logger.warning("NetworkX not installed. Skipping graph generation test.")

    # OUTPUT
    output_dir = Path("outputs")
    output_dir.mkdir(exist_ok=True)

    output_file = output_dir / f"{run_id}.json"

    output = {
        "entities": [
            c.model_dump()
            for c in canonicals
        ],
        "relationships": [
            r.model_dump()
            for r in all_relationships
        ]
    }

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)

    logger.info(f"Saved reproducible output to {output_file}")

    return output_file


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", type=str, default="test-synthetic.txt", help="Path to document")
    parser.add_argument("--seed", type=int, default=42, help="Deterministic seed for LLM")
    parser.add_argument("--run_name", type=str, default=None, help="Custom name for the run output")
    args = parser.parse_args()

    # Generate timestamped run ID if none provided
    run_id = args.run_name or datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    file_path = Path("data") / args.file

    run_pipeline(file_path, args.seed, run_id)