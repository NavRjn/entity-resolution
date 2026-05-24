#%%
from argparse import Namespace
from pathlib import Path
import fitz # PyMuPDF
import ollama
from bs4 import BeautifulSoup
from pydantic import BaseModel, RootModel
from tqdm import tqdm
import json
import string, re
from typing import List, Dict
import datetime
from rapidfuzz import fuzz

DATA_DIR = Path('data')
OUTPUT_DIR = Path('outputs')

CHUNK_SIZE = 1500
SEED = 42
OVERLAP = 0
DEBUG = False

test_data = DATA_DIR / "test-synthetic.txt"

SYSTEM_PROMPT = """
    Return ONLY a JSON array.
    
    Schema:
    [
      {
        "entity_name": string,
        "entity_type": string,
        "evidence": string
      }
    ]
    
    No prose.
    No explanations.
    No markdown.
    No analysis.
    No summaries.
    No extra text.
    
    If no entities exist:
    []
    """

PROMPT_TEMPLATE = lambda chunk: """
    Extract the identities in the following.
    
    TEXT:
    <<<
    """+chunk+"\n\t>>>"


LEGAL_SUFFIXES = {
    "inc", "corp", "corporation", "llc",
    "ltd", "limited", "company", "co",
    "plc", "group", "holdings"
}


class Entity(BaseModel):
    entity_name: str
    entity_type: str
    evidence: str


class CanonicalEntity(BaseModel):
    canonical_name: str
    entity_type: str
    aliases: list[str] = []
    evidence: list[str] = []


class Schema(RootModel[list[CanonicalEntity]]):
    pass


def normalize_text(s: str) -> str:
    """
    Normalize text for robust comparison:
    - lowercase
    - remove punctuation
    - collapse whitespace
    """
    if s is None:
        return ""

    s = s.lower()
    s = s.strip()

    # remove punctuation
    s = s.translate(str.maketrans("", "", string.punctuation))

    # collapse whitespace
    s = re.sub(r"\s+", " ", s)

    return s

def extract_text(path):
    text = []

    if path.suffix == ".pdf":
        # extract pdf
        doc = fitz.open(path)
        for page in doc:
            text.append(page.get_text())
        doc.close()
    elif path.suffix == ".txt":
        with open(path, "r") as f:
            text.append(f.read())

    else:
        raise ValueError(f"Unsupported file type: {path}")


    return "\n".join(text)

def clean_html(html):
    soup = BeautifulSoup(html, "lxml")

    # remove scripts/styles
    for tag in soup(["script", "style"]):
        tag.decompose()

    text_from_soup = soup.get_text(separator=" ")

    # collapse whitespace
    text_collapsed = " ".join(text_from_soup.split())

    return text_collapsed

def chunk_text(text, size=CHUNK_SIZE):
    text_len = len(text)
    chunks = [text[i:min(i+size+OVERLAP, text_len-1)] for i in range(0, text_len, size)]
    print(f"From {len(text)}: extracted {len(chunks)} chunks with size ~{len(chunks[0])}")
    return chunks

def smart_chunk(text, max_len=CHUNK_SIZE):
    sentences = re.split(r'(?<=[.!?])\s+', text)

    chunks = []
    current = ""

    for s in sentences:
        if len(current) + len(s) > max_len:
            chunks.append(current)
            current = s
        else:
            current += " " + s

    if current:
        chunks.append(current)

    print(f"From {len(text)}: extracted {len(chunks)} chunks with size ~{len(chunks[0])}")
    return chunks

def extract_entities(chunk, seed=SEED, stream=DEBUG):
    prompt = PROMPT_TEMPLATE(chunk)
    # print("PROMPT: \n", prompt, "\n", "*"*20)

    client = ollama.Client(host="http://127.0.0.1:11434")

    options = {
        "temperature":0,
        "seed": seed,
        # "stop":["\n\n"]
    }

    res = client.chat(
        model="qwen2.5:7b-instruct-q4_K_M",
        format=Schema.model_json_schema(),
        messages=[{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt}],
        stream=stream,
        options=options,
    )

    return res if DEBUG else res["message"]["content"]

def process_chunks(chunks, seed=SEED):
    canonical_entities = []

    for chunk in tqdm(chunks):

        try:
            entities = json.loads(extract_entities(chunk, seed=seed))
        except Exception as e:
            print("FAILED:", e)
            continue

        for entity in entities:
            merge_entity(entity, canonical_entities)

        print(f"Canonical entities: {len(canonical_entities)}")

    return canonical_entities

def get_entity_name(item):
    if type(item) == dict:
        name = item.get("entity_name") or item.get("canonical_name")
        if not name:
            print(f"name: {name} is None. in {item}")
            return ""
        return name
    elif type(item) == CanonicalEntity:
        return item.canonical_name
    else:
        print(item, "of type ", type(item), " is unknown; returning nothing")
        return ""

def evaluate_extraction(pred_json: list[dict], truth_json: list[dict]) -> Dict:
    """
    Compare LLM output vs ground truth entities.
    Returns multiple evaluation metrics.
    """
    print("* "*20)
    print("EVAL: starting Evaluation")
    print(f"predicted {len(pred_json)} entities")
    print(f"Actual {len(truth_json)} entities")


    # Normalize inputs into sets of tuples
    def to_set(data):
        return set(
            (
                normalize_text(get_entity_name(item)),
                normalize_text(item.get("entity_type", "")),
            )
            for item in data
        )

    def names_only(data):
        return set(
            normalize_text(get_entity_name(item))
            for item in data
        )

    pred_set = to_set(pred_json)
    truth_set = to_set(truth_json)

    pred_names = names_only(pred_json)
    truth_names = names_only(truth_json)

    # ---- MATCHING ----
    matched = pred_set & truth_set
    matched_names = pred_names & truth_names

    # ---- METRICS ----

    # 1. Recall (entity_name level)
    recall_name = len(matched_names) / len(truth_names) if truth_names else 0

    # 2. Precision (entity_name level)
    precision_name = len(matched_names) / len(pred_names) if pred_names else 0

    # 3. F1 (entity_name level)
    if precision_name + recall_name > 0:
        f1_name = 2 * precision_name * recall_name / (precision_name + recall_name)
    else:
        f1_name = 0

    # 4. Strict match (name + type)
    strict_recall = len(matched) / len(truth_set) if truth_set else 0
    strict_precision = len(matched) / len(pred_set) if pred_set else 0

    if strict_precision + strict_recall > 0:
        strict_f1 = 2 * strict_precision * strict_recall / (strict_precision + strict_recall)
    else:
        strict_f1 = 0

    # 5. Extra / missing analysis
    missing = truth_names - pred_names
    extra = pred_names - truth_names

    return {
        "recall_entity_name": recall_name,
        "precision_entity_name": precision_name,
        "f1_entity_name": f1_name,

        "strict_recall_name+type": strict_recall,
        "strict_precision_name+type": strict_precision,
        "strict_f1_name+type": strict_f1,

        "num_truth": len(truth_names),
        "num_pred": len(pred_names),
        "num_matched_names": len(matched_names),

        "missing_entities": list(missing),
        "extra_entities": list(extra),
    }

def normalize_entity_name(name: str) -> str:
    name = normalize_text(name)

    words = name.split()

    words = [w for w in words if w not in LEGAL_SUFFIXES]

    return " ".join(words)

def is_same_entity(a: str, b: str, threshold=90):
    a_norm = normalize_entity_name(a)
    b_norm = normalize_entity_name(b)

    if a_norm == b_norm:
        return True

    score = fuzz.token_sort_ratio(a_norm, b_norm)

    return score >= threshold

def merge_entity(entity: dict, canonicals: list[CanonicalEntity]):
    name = get_entity_name(entity)
    ent_type = entity["entity_type"]
    evidence = entity["evidence"]

    for c in canonicals:

        # optional:
        # only compare same/similar types
        if c.entity_type != ent_type:
            continue

        candidates = [c.canonical_name] + c.aliases

        for candidate in candidates:

            if is_same_entity(name, candidate):

                # add alias
                if name not in c.aliases and name != c.canonical_name:
                    c.aliases.append(name)

                # add evidence
                if evidence not in c.evidence:
                    c.evidence.append(evidence)

                return

    # no match found → new canonical
    canonicals.append(
        CanonicalEntity(
            canonical_name=name,
            entity_type=ent_type,
            aliases=[],
            evidence=evidence
        )
    )

def setup_args() -> Namespace:
    import argparse

    parser = argparse.ArgumentParser(description="LLM Entity Extraction")

    parser.add_argument("--data_path", type=str, default=str(test_data), help="Path to input data (pdf or txt)")
    parser.add_argument("--run", type=str, default=None, help="Override name of output")
    parser.add_argument("--chunk_size", type=int, default=CHUNK_SIZE, help="Chunk size for text splitting")
    parser.add_argument("--overlap", type=int, default=OVERLAP, help="Overlap size for chunking")
    parser.add_argument("--seed", type=int, default=SEED, help="Random seed for reproducibility")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode with streaming output")

    args = parser.parse_args()

    return args


            
if __name__ == "__main__":
    args = setup_args()
    run_id = datetime.datetime.now().strftime("%Y%m%d_%H%M%S") if args.run is None else args.run
    #%%

    text = extract_text(Path(args.data_path))
    cleaned_text = clean_html(text)
    chunks = smart_chunk(cleaned_text, args.chunk_size) # chunk_text(cleaned_text)
    #%%

    entities = process_chunks(chunks, seed=args.seed)
    entities_to_dump = [e.model_dump() for e in entities]
    with open(OUTPUT_DIR / f"{run_id}.json", "w") as f:
        json.dump(entities_to_dump, f, indent=2)
    print(entities)

    #%%

    with open(DATA_DIR / "test-gt.json", "r") as f:
        gt_json = json.load(f)


    print("\n\nDone.")