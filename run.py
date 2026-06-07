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
from openai import OpenAI
from dotenv import load_dotenv
import os

load_dotenv()

OLLAMA_CLIENT = ollama.Client(host="http://127.0.0.1:11434", timeout=180)
OPENAI_CLIENT = OpenAI(api_key=os.getenv("OPENAI_API_LEGALDEV"))

# --- CONFIG & OBSERVABILITY ---
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    datefmt="[%X]",
    handlers=[RichHandler(rich_tracebacks=True)]
)
logger = logging.getLogger("EntityResolution")
logger.setLevel(logging.DEBUG) # Comment this out to reduce log verbosity
console = Console()


from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

# --- SCHEMAS ---
class Citation(BaseModel):
    file_id: str
    chunk_id: int
    start_char: int
    end_char: int
    quote: str


class ExtractedEntity(BaseModel):
    entity_name: str
    entity_type: str
    exact_quote: str  # Enforcing provenance


class EntityList(BaseModel):
    entities: list[ExtractedEntity]


class ValidatedEntity(BaseModel):

    entity_name: str
    entity_type: str

    citation: Citation

    is_valid: bool
    fail_reason: Optional[str] = None


class CanonicalEntity(BaseModel):
    entity_id: str

    canonical_name: str
    entity_type: str

    aliases: list[str] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)


class Relationship(BaseModel):
    source_entity_id: str
    target_entity_id: str

    relationship_type: str

    citation: Citation


class RelationshipList(BaseModel):
    relationships: list[Relationship]


@dataclass
class RunContext:
    run_id: str
    file_id: str
    seed: int

    file_path: Optional[Path] = None
    output_dir: Optional[Path] = None

    text: str = ""

    chunks: List[str] = field(default_factory=list)

    validated_entities: List[ValidatedEntity] = field(default_factory=list)
    canonicals: List[CanonicalEntity] = field(default_factory=list)

    chunk_entity_index: dict = field(default_factory=dict)

    relationships: List[Relationship] = field(default_factory=list)

    hallucination_count: int = 0


# --- PROMPTS ---
LEGAL_SUFFIXES = {"inc", "corp", "corporation", "llc", "ltd", "limited", "company", "co", "plc", "group", "holdings"}

ALLOWED_ENTITIES = {"person", "company", "agreement", "asset", "other"}
ALLOWED_RELATIONSHIPS = {"controls", "participates_in", "represents", "transfers_to", "governs", "related_to"}
ENTITY_RELATIONSHIP_DIRECTION_RULES = {
    "controls": {
        "source": {"person", "company"},
        "target": {"person", "company", "asset", "claim"}
    },

    "participates_in": {
        "source": {"person", "company"},
        "target": {"agreement", "claim"}
    },

    "represents": {
        "source": {"person", "company"},
        "target": {"person", "company"}
    },

    "transfers_to": {
        "source": {"asset", "claim", "agreement"},
        "target": {"person", "company"}
    },

    "governs": {
        "source": {"agreement", "claim", "asset"},
        "target": {"person", "company", "asset"}
    },

    "related_to": {
        "source": "any",
        "target": "any"
    }
}

SYSTEM_PROMPT = f"""
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
  {{
    "entity_name": "Standardized Name (e.g. Acme Corp)",
    "entity_type": "{"|".join(ALLOWED_ENTITIES)}",
    "exact_quote": "The exact string from the text proving this exists."
  }}
]
Return ONLY valid JSON.
"""

RELATIONSHIP_SYSTEM_PROMPT = f"""
You are a highly accurate legal relationship extraction assistant.

Task:
- Extract only **explicit relationships** mentioned in the text.
- Use only the entity IDs provided; do not invent, truncate, or modify them.
- Only relationships explicitly supported by the text should be extracted.
- Do NOT hallucinate relationships, relationship types, or entity connections.

Allowed relationships:
{ALLOWED_RELATIONSHIPS}

Follow the following rules for each relationship:
{ENTITY_RELATIONSHIP_DIRECTION_RULES}

Instructions:
1. If a relationship’s target entity is not listed, skip it.
2. For multiple entities in the same sentence, carefully assign the correct IDs to relationships.
3. Do not invent new relationship types; use only allowed ones.
4. Return the exact text evidence for each relationship.
5. If unsure, omit the relationship rather than guessing.
6. **Direction matters:** the relationships are designed such that the source is always the actor, acting on the target. Do not flip them.
7. IMPORTANT: If you are sure two entities are related, but not how. DO NOT REVERT TO related_to. Instead, omit it entirely.
Use related_to ONLY when the text explicitly states a non-specific relationship using words such as ‘related to’, ‘associated with’, ‘affiliated with’. Otherwise omit. 
8. Do not infer relationships from: co-occurrence, same paragraph, shared document section. A relationship must be directly inferable without external reasoning
9. If entity is a regulator AND action verb present → always attempt extraction
10. controls can ONLY be extracted if explicit ownership/control language exists (e.g. owns, parent of, subsidiary of, acquired, wholly owned).
Participation in agreements or transactions does NOT imply control.

Example:
Entities:
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
      "relationship_type": "controls",
      "evidence_quote": "Aurora Strategic Holdings, Inc. acquired Helios BioAnalytics Corporation"
    }},
    {{
      "source_entity_id": "E2",
      "target_entity_id": "E3",
      "relationship_type": "participates_in",
      "evidence_quote": "Jonathan R. Keene signed the Equity Purchase Agreement"
    }},
    {{
      "source_entity_id": "E0",
      "target_entity_id": "E3",
      "relationship_type": "participates_in",
      "evidence_quote": "Aurora Strategic Holdings, Inc. acquired Helios BioAnalytics Corporation pursuant to the Equity Purchase Agreement"
    }},
    {{
      "source_entity_id": "E2",
      "target_entity_id": "E0",
      "relationship_type": "related_to",
      "evidence_quote": "Jonathan R. Keene signed the Equity Purchase Agreement on behalf of Aurora Strategic Holdings, Inc"
    }}
  ]
}}

Here on the E2->related_to->E0 relationship, we do not know the relationship, but we know that Jonathan R. Keene
is sufficiently related to Aurora Strategic Holdings enough to sign for them.

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
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]

    if provider=="ollama":
        res = OLLAMA_CLIENT.chat(
            model="qwen2.5:7b-instruct-q4_K_M",
            format=schema,
            messages=messages,
            options={
                "temperature": 0.0,
                "seed": seed,
            }
        )
        return json.loads(res["message"]["content"])
    elif provider=="openai":
        response = OPENAI_CLIENT.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            temperature=0,
            seed=seed,

            # IMPORTANT: enforce JSON mode
            response_format={"type": "json_object"}
        )

        content = response.choices[0].message.content
        return json.loads(content)
    else:
        raise ValueError("Invalid model provider!: ", provider)


def _call_llm_threaded(user_prompt: str, system_prompt: str, schema: dict, seed: int = 42, timeout: int = None) -> dict:
    """Call the LLM in a separate thread so Ctrl+C works."""
    def call():
        return _llm_backend(
            provider="openai",
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


def extract_relationships(chunk: str, entities: List[Dict], chunk_id: int, file_id: str, seed: int = 42) -> List[Relationship]:
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
            citation=Citation(
                file_id=file_id,
                chunk_id=chunk_id,
                start_char=-1, # TODO: Fill them properly later
                end_char=-1,
                quote=item["evidence_quote"]
            )
        )
        for item in relationships
    ]


def validate_guardrails(entity: ExtractedEntity, chunk_text: str, chunk_id: int, file_id: str) -> ValidatedEntity:
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
    end_pos = -1 if start_pos < 0 else (start_pos + len(entity.exact_quote))

    citation = Citation(file_id=file_id, chunk_id=int(chunk_id), start_char=int(start_pos), end_char=int(end_pos), quote=entity.exact_quote)

    validated_entity = ValidatedEntity(
        entity_name=entity.entity_name,
        entity_type=entity.entity_type,
        is_valid=is_valid,
        fail_reason=reason,
        citation=citation
    )

    if not is_valid: log_hallucinated_entity(validated_entity)

    return validated_entity


def validate_relationship(relationship: Relationship, chunk_text: str) -> bool:
    """Validates that the relationship evidence actually exists in the chunk."""
    norm_chunk = re.sub(r"\s+", " ", chunk_text)
    norm_quote = re.sub(r"\s+", " ", relationship.citation.quote)
    exists = norm_quote in norm_chunk

    valid_relationship_type = relationship.relationship_type in ALLOWED_RELATIONSHIPS
    valid_source_and_target = relationship.source_entity_id and relationship.target_entity_id
    valid_quote =  relationship.citation.quote and len(relationship.citation.quote.strip()) > 5

    valid = exists and valid_relationship_type and valid_source_and_target and valid_quote
    if not valid:
        logger.warning(f"Dropping relationship | Exists: {exists} | Valid Type: {valid_relationship_type} | Valid Source/Target: {valid_source_and_target} | Valid Quote: {valid_quote}")
        if not exists: logger.debug(f"{norm_quote} not found in chunk: {norm_chunk}")

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
                    if ve.citation not in c.citations:
                        c.citations.append(ve.citation)
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
                    citations=[ve.citation],
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
        for citation in c.citations:
            chunk_id = citation.chunk_id
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
        chunks_str = ", ".join(map(str, [cit.chunk_id for cit in c.citations])) if c.citations else "None"
        table.add_row(c.canonical_name, c.entity_type, aliases_str, chunks_str)

    console.print(table)

    if relationships:
        rel_table = Table(title="Extracted Relationships")
        rel_table.add_column("Source", style="cyan")
        rel_table.add_column("Relationship", style="magenta")
        rel_table.add_column("Target", style="cyan")
        rel_table.add_column("Chunk", style="yellow", justify="right")

        for r in relationships:
            rel_table.add_row(r.source_entity_id, r.relationship_type, r.target_entity_id, str(r.citation.chunk_id))

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
                evidence=r.citation.quote
            )

    return graph


def get_run_dir(run_id: str) -> Path:
    run_dir = Path("outputs") / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def get_latest_run_id() -> str:
    outputs_dir = Path("outputs")
    runs = [p for p in outputs_dir.iterdir() if p.is_dir()]
    if not runs:
        raise ValueError("No previous runs found in outputs/")
    return sorted(runs, key=lambda p: p.stat().st_mtime)[-1].name


def save_manifest(run_dir: Path, source_file: str, seed: int):
    manifest = {
        "run_id": run_dir.name,
        "created_at": datetime.datetime.now().isoformat(),
        "source_file": source_file,
        "seed": seed,
        "chunk_max_chars": 2000,
        "chunk_overlap_chars": 200,
    }

    with open(run_dir / "manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)


def load_manifest(run_dir: Path):
    with open(run_dir / "manifest.json", "r", encoding="utf-8") as f:
        return json.load(f)


def save_chunks(run_dir: Path, chunks: List[str]):
    with open(run_dir / "chunks.json", "w", encoding="utf-8") as f:
        json.dump({"chunks": chunks}, f, indent=2)


def load_chunks(run_dir: Path) -> List[str]:
    with open(run_dir / "chunks.json", "r", encoding="utf-8") as f:
        return json.load(f)["chunks"]


def save_entities_artifact(run_dir: Path, validated_entities, canonicals, chunk_entity_index):
    payload = {
        "validated_entities": [v.model_dump() for v in validated_entities],
        "canonical_entities": [c.model_dump() for c in canonicals],
        "chunk_entity_index": dict(chunk_entity_index)
    }

    with open(run_dir / "entities.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def load_entities_artifact(run_dir: Path):
    with open(run_dir / "entities.json", "r", encoding="utf-8") as f:
        return json.load(f)


def save_output(run_dir: Path, canonicals, relationships):
    payload = {
        "entities": [c.model_dump() if hasattr(c, "model_dump") else c for c in canonicals],
        "relationships": [r.model_dump() if hasattr(r, "model_dump") else r for r in relationships]
    }

    with open(run_dir / "output.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    logger.info(f"Saved output to {run_dir / 'output.json'}")


def rebuild_canonicals(canonical_entities_json):
    return [CanonicalEntity(**c) for c in canonical_entities_json]


# %%
# --- MAIN EXECUTION ---
FILE_ID = "0000"


class EntityResolutionPipeline:
    def run_entities(self, ctx: RunContext) -> RunContext:
        ctx.text = extract_text(ctx.file_path)
        ctx.chunks = chunk_text_with_overlap(ctx.text)

        with console.status("[bold green]Extracting entities..."):
            for idx, chunk in enumerate(ctx.chunks):
                raw_entities = extract_entities(chunk, seed=ctx.seed)

                for raw_ent in raw_entities:
                    validated = validate_guardrails(raw_ent, chunk, idx, ctx.file_id)
                    ctx.validated_entities.append(validated)

                    if not validated.is_valid:
                        ctx.hallucination_count += 1

        logger.info("Resolving entities...")
        ctx.canonicals = resolve_entities(ctx.validated_entities)

        logger.info(f"Resolved {len(ctx.canonicals)} canonical entities from {len(ctx.validated_entities)} mentions")

        ctx.chunk_entity_index = build_chunk_entity_index(ctx.canonicals)
        run_dir = get_run_dir(ctx.run_id)

        save_manifest(run_dir, str(ctx.file_path), ctx.seed)
        save_chunks(run_dir, ctx.chunks)
        save_entities_artifact(run_dir, ctx.validated_entities, ctx.canonicals, ctx.chunk_entity_index)

        return ctx

    def run_relationships(self, ctx: RunContext):

        all_relationships = []

        dropped = 0
        valid = 0

        logger.warning(f"Starting relationship extraction with {len(ctx.canonicals)} entities and {len(ctx.chunks)} chunks.")
        with console.status("[bold green]Extracting relationships..."):
            for idx, chunk in enumerate(ctx.chunks):
                entity_refs = ctx.chunk_entity_index.get(str(idx), ctx.chunk_entity_index.get(idx, []))
                if not entity_refs:
                    continue

                raw_relationships = extract_relationships(chunk, entity_refs, idx, ctx.file_id, ctx.seed)

                for rel in raw_relationships:
                    status = validate_relationship(rel, chunk)
                    log_relationship_check(chunk_id=idx, rel=rel, status=("valid" if status else "false_positive"))
                    if status:
                        valid += 1
                        all_relationships.append(rel)
                    else:
                        dropped += 1

        ctx.relationships = all_relationships
        logger.warning(f"Relationship extraction: {valid} valid relationships, {dropped} dropped.")

        return ctx

    def run_full(self, ctx: RunContext):

        self.run_entities(ctx)
        self.run_relationships(ctx)

        display_results(ctx.canonicals, ctx.relationships, ctx.hallucination_count)

        try:
            nx_graph = build_networkx_graph(ctx.canonicals, ctx.relationships)
            logger.info(f"Built NetworkX Graph with {nx_graph.number_of_nodes()} nodes and {nx_graph.number_of_edges()} edges.")
        except ImportError:
            logger.warning("NetworkX not installed.")

        save_output(ctx.output_dir, ctx.canonicals, ctx.relationships)
        return ctx

    def run_relationships_only(self, run_id: str):

        run_dir = get_run_dir(run_id)
        manifest = load_manifest(run_dir)
        chunks = load_chunks(run_dir)
        entities = load_entities_artifact(run_dir)

        ctx = RunContext(run_id=run_id, file_id=FILE_ID, seed=manifest["seed"])
        ctx.output_dir = run_dir
        ctx.chunks = chunks
        ctx.canonicals = rebuild_canonicals(entities["canonical_entities"])
        ctx.chunk_entity_index = entities["chunk_entity_index"]

        self.run_relationships(ctx)

        save_output(run_dir, ctx.canonicals, ctx.relationships)

        return ctx


if __name__ == "__main__":

    parser = argparse.ArgumentParser()

    parser.add_argument("--file", type=str)
    parser.add_argument("--run", type=str)
    parser.add_argument("--last", action="store_true")
    parser.add_argument("--only", choices=["entities", "relationship", "all"], default="all")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    sources = sum([args.file is not None, args.run is not None, args.last])

    if sources != 1:
        parser.error("Specify exactly one of --file, --run, or --last")
    if args.last:
        args.run = get_latest_run_id()

    pipeline = EntityResolutionPipeline()

    if args.only == "relationship":
        if not args.run:
            parser.error("--only relationship requires --run or --last")
        pipeline.run_relationships_only(args.run)

    else:
        if not args.file:
            parser.error("--file required")
        run_id = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        file_path = Path("data") / args.file

        ctx = RunContext(
            run_id=run_id,
            file_id=FILE_ID,
            seed=args.seed,
            file_path=file_path,
            output_dir=get_run_dir(run_id)
        )

        if args.only == "entities":
            pipeline.run_entities(ctx)
        else:
            pipeline.run_full(ctx)
