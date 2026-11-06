"""Name and type normalisation shared by matching and loaders."""
import re
import unicodedata

# Legal-form tokens stripped for *lenient* name matching only (never for display).
LEGAL_FORMS = {
    "inc", "incorporated", "corp", "corporation", "llc", "llp", "lp", "ltd", "limited", "plc", "co", "company",
    "gmbh", "ag", "kg", "ug", "se", "sa", "nv", "bv", "ou", "ulc", "spc", "pte", "pty", "srl", "spa", "ab", "as",
    "oy", "ohg", "mbh", "ev", "the", "und", "and", "of",
}

ONTOLOGY_TYPES = {"person", "company", "agreement", "asset", "other"}

# Free-form labels (pipeline casing, legacy GT, NER tag sets) -> ontology.
DEFAULT_TYPE_MAP = {
    "person": "person", "per": "person", "people": "person", "individual": "person",
    "company": "company", "organization": "company", "organisation": "company", "org": "company",
    "business": "company", "corporation": "company", "subsidiary": "company", "firm": "company",
    "agreement": "agreement", "contract": "agreement",
    "asset": "asset",
    "other": "other", "misc": "other", "miscellaneous": "other",
}


def fold(text: str) -> str:
    """NFKC + casefold. Umlauts/accents are kept on purpose (German names)."""
    return unicodedata.normalize("NFKC", str(text or "")).casefold()


def norm_name(text: str) -> str:
    """Strict key: casefolded alphanumerics only ('Aurora, Inc.' == 'aurora inc')."""
    return re.sub(r"[\W_]+", "", fold(text))


def core_tokens(text: str) -> list[str]:
    """Lenient key: parentheticals and legal-form tokens removed, token list."""
    t = re.sub(r"\(.*?\)", " ", fold(text))
    toks = [w for w in re.split(r"[\W_]+", t) if w]
    core = [w for w in toks if w not in LEGAL_FORMS]
    return core or toks


def core_name(text: str) -> str:
    return " ".join(core_tokens(text))


def norm_type(label: str, type_map: dict | None = None) -> str:
    key = fold(label).strip()
    if type_map and key in type_map:
        return type_map[key]
    return DEFAULT_TYPE_MAP.get(key, "other")


def norm_rel(label: str) -> str:
    return re.sub(r"[\s\-]+", "_", fold(label).strip())
