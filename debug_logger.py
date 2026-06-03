# debug_logger.py
import logging
from pathlib import Path
import json
from datetime import datetime

# Configure a separate file-based logger for observability
LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)

logger = logging.getLogger("DebugLogger")
logger.setLevel(logging.DEBUG)

# File handler
fh = logging.FileHandler(LOG_DIR / f"debug_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
fh.setLevel(logging.DEBUG)
formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
fh.setFormatter(formatter)
logger.addHandler(fh)

# Avoid console spam
logger.propagate = False


# --- HELPER FUNCTIONS --- #

def log_prompt(prompt_type: str, prompt_text: str, chunk_id: int = None):
    """Log prompts sent to the LLM."""
    entry = {
        "type": prompt_type,
        "chunk_id": chunk_id,
        "prompt": prompt_text
    }
    logger.debug(json.dumps(entry, ensure_ascii=False))


def log_response(prompt_type: str, response_data: dict, chunk_id: int = None):
    """Log responses received from the LLM."""
    entry = {
        "type": f"{prompt_type}_response",
        "chunk_id": chunk_id,
        "response": response_data
    }
    logger.debug(json.dumps(entry, ensure_ascii=False))


def log_hallucinated_entity(entity):
    """Log hallucinated / filtered entities."""
    entry = {
        "type": "hallucinated_entity",
        "entity": entity.model_dump() if hasattr(entity, "model_dump") else dict(entity)
    }
    logger.debug(json.dumps(entry, ensure_ascii=False))


def log_relationship_check(chunk_id: int, rel, status: str, notes=None):
    """Log relationship validation and errors."""
    entry = {
        "type": "relationship_check",
        "chunk_id": chunk_id,
        "relationship": rel.model_dump() if hasattr(rel, "model_dump") else dict(rel),
        "status": status,  # 'valid', 'missing', 'false_positive', 'partial'
        "notes": notes
    }
    logger.debug(json.dumps(entry, ensure_ascii=False))