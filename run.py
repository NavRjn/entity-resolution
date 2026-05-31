# %%
import argparse
import json
import re
import string
import logging
from pathlib import Path
from typing import List, Dict, Optional

import fitz  # PyMuPDF
import ollama
from bs4 import BeautifulSoup
from pydantic import BaseModel
from rapidfuzz import fuzz
from rich.console import Console
from rich.table import Table
from rich.logging import RichHandler

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
    canonical_name: str
    entity_type: str
    aliases: list[str] = []
    evidence_quotes: list[str] = []
    source_chunks: list[int] = []


# --- PROMPTS ---
SYSTEM_PROMPT = """
You are an expert legal entity extraction system.
Extract all corporate and personal entities from the text.
For every entity, you MUST extract the exact, verbatim text snippet where it was found in the 'exact_quote' field.

Schema:
[
  {
    "entity_name": "Standardized Name (e.g. Acme Corp)",
    "entity_type": "company|person|organization|location",
    "exact_quote": "The exact string from the text proving this entity exists."
  }
]

Return ONLY valid JSON. No markdown, no prose.
"""

PROMPT_TEMPLATE = lambda chunk: f"""
Extract the entities in the following text.

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


def call_llm(chunk: str, seed: int = 42) -> List[ExtractedEntity]:
    """Calls Ollama and enforces JSON schema."""
    client = ollama.Client(host="http://127.0.0.1:11434")
    prompt = PROMPT_TEMPLATE(chunk)

    try:
        res = client.chat(
            model="qwen2.5:7b-instruct-q4_K_M",
            format=EntityList.model_json_schema(),  # Ensure JSON mode
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt}
            ],
            options={"temperature": 0.0, "seed": seed}
        )
        data = json.loads(res["message"]["content"])["entities"]
        # logger.debug(f"\nLLM returned {data}")
        return [ExtractedEntity(**item) for item in data]
    except Exception as e:
        logger.error(f"LLM Call failed: {str(e)}")
        return []


def validate_guardrails(entity: ExtractedEntity, chunk_text: str, chunk_id: int) -> ValidatedEntity:
    """The Zero-Hallucination Guardrail."""
    # Normalize spaces for robust checking, but retain characters
    norm_chunk = re.sub(r'\s+', ' ', chunk_text)
    norm_quote = re.sub(r'\s+', ' ', entity.exact_quote)

    is_valid = norm_quote in norm_chunk
    reason = None if is_valid else f"Hallucination: Quote not found in chunk."

    return ValidatedEntity(
        chunk_id=chunk_id,
        entity_name=entity.entity_name,
        entity_type=entity.entity_type,
        exact_quote=entity.exact_quote,
        is_valid=is_valid,
        fail_reason=reason
    )


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
            canonicals.append(CanonicalEntity(
                canonical_name=ve.entity_name,
                entity_type=ve.entity_type,
                aliases=[],
                evidence_quotes=[ve.exact_quote],
                source_chunks=[ve.chunk_id]
            ))

    return canonicals


def display_results(canonicals: List[CanonicalEntity], dropped: int):
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
    if dropped > 0:
        logger.warning(f"Guardrails blocked {dropped} hallucinated/invalid entities.")


# --- MAIN EXECUTION ---

def run_pipeline(file_path: str):
    logger.info("Starting Entity Resolution Pipeline...")
    logger.debug(f"Using schema: {EntityList.model_json_schema()}")

    # 1. Ingest
    text = extract_text(Path(file_path))

    # 2. Chunk
    chunks = chunk_text_with_overlap(text, max_chars=1000)

    all_validated_entities = []
    hallucination_count = 0

    # 3 & 4. Extract and Validate
    with console.status("[bold green]Processing chunks with LLM...") as status:
        for idx, chunk in enumerate(chunks):
            logger.debug(f"Processing chunk {idx + 1}/{len(chunks)}")
            raw_entities = call_llm(chunk)

            for raw_ent in raw_entities:
                validated = validate_guardrails(raw_ent, chunk, idx)
                all_validated_entities.append(validated)

                if not validated.is_valid:
                    hallucination_count += 1
                    logger.warning(f"Dropped Entity '{raw_ent.entity_name}': {validated.fail_reason}")

    # 5. Resolve
    logger.info("Resolving and grouping entities...")
    canonicals = resolve_entities(all_validated_entities)

    # 6. Output
    display_results(canonicals, hallucination_count)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", type=str, required=True, help="Path to document")
    args = parser.parse_args()

    run_pipeline(args.file)