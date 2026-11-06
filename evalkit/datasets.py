"""Dataset registry: cards -> fetch -> prepare -> load.

Layout on disk (all under eval_data/, git-ignored):
    eval_data/<name>/raw/          downloaded files, untouched
    eval_data/<name>/fetch.lock.json   url + sha256 + bytes per downloaded file (pin / detect upstream change)
    eval_data/<name>/prepared/gold.jsonl      one GoldDocument per line (source-agnostic gold)
    eval_data/<name>/prepared/docs/<id>.txt   plain text the pipeline can ingest (and <id>.pdf when the source is a PDF)

Any dataset not in evalkit/cards/ can be used by passing --card path/to/card.yaml.
"""
from __future__ import annotations

import fnmatch
import hashlib
import json
import random
import shutil
import urllib.request
import zipfile
from pathlib import Path

import yaml

from .loaders import Card, load_dataset
from .schema import GoldDocument

ROOT = Path(__file__).resolve().parent.parent
CARD_DIR = Path(__file__).resolve().parent / "cards"
DATA_DIR = ROOT / "eval_data"


def list_cards() -> dict[str, Card]:
    return {c.name: c for c in (Card(yaml.safe_load(p.read_text(encoding="utf-8"))) for p in sorted(CARD_DIR.glob("*.yaml")))}


def get_card(name_or_path: str) -> Card:
    p = Path(name_or_path)
    if p.suffix in (".yaml", ".yml") and p.exists():
        return Card(yaml.safe_load(p.read_text(encoding="utf-8")))
    cards = list_cards()
    if name_or_path not in cards:
        raise KeyError(f"unknown dataset {name_or_path!r}; known: {sorted(cards)}")
    return cards[name_or_path]


def dataset_dir(card: Card) -> Path:
    return DATA_DIR / card.name


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _safe_join(base: Path, member: str) -> Path:
    target = (base / member).resolve()
    if base.resolve() not in target.parents and target != base.resolve():
        raise ValueError(f"unsafe path in archive: {member}")
    return target


def fetch(card: Card, force: bool = False) -> Path:
    """Download the card's sources into raw/. Untrusted data: stored only, never executed."""
    raw = dataset_dir(card) / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    lock: dict = {}
    for src in card.raw.get("sources", []):
        url, dest = src["url"], src.get("dest")
        if src.get("manual"):
            print(f"[manual] {card.name}: download {url} into {raw} ({src.get('note', '')})")
            continue
        if src.get("zip"):
            tmp = raw / "_download.zip"
            urllib.request.urlretrieve(url, tmp)
            with zipfile.ZipFile(tmp) as z:
                for m in z.namelist():
                    if m.endswith("/") or not any(fnmatch.fnmatch(m, g) for g in src.get("include", ["*"])):
                        continue
                    rel = m.split("/", src.get("strip", 0))[-1] if src.get("strip") else m
                    out = _safe_join(raw, rel)
                    out.parent.mkdir(parents=True, exist_ok=True)
                    with z.open(m) as fin, out.open("wb") as fout:
                        shutil.copyfileobj(fin, fout)
            lock[url] = {"sha256": _sha256(tmp), "bytes": tmp.stat().st_size}
            tmp.unlink()
        else:
            out = _safe_join(raw, dest or url.rsplit("/", 1)[-1])
            out.parent.mkdir(parents=True, exist_ok=True)
            if force or not out.exists():
                urllib.request.urlretrieve(url, out)
            lock[url] = {"sha256": _sha256(out), "bytes": out.stat().st_size}
    (dataset_dir(card) / "fetch.lock.json").write_text(json.dumps(lock, indent=2), encoding="utf-8")
    return raw


def _truncate(doc: GoldDocument, max_chars: int) -> GoldDocument:
    """Cut the text; drop mentions beyond the cut; drop entities that lose all offset-bearing mentions."""
    if len(doc.text) <= max_chars:
        return doc
    doc.text = doc.text[:max_chars]
    keep = []
    for e in doc.entities:
        had_offsets = any(m.start is not None for m in e.mentions)
        e.mentions = [m for m in e.mentions if m.start is None or (m.end or 0) <= max_chars]
        if e.mentions or not had_offsets:
            keep.append(e)
    ids = {e.id for e in keep}
    doc.entities = keep
    doc.relations = [r for r in doc.relations if r.source in ids and r.target in ids]
    doc.meta["truncated_to"] = max_chars
    return doc


def prepare(card: Card, limit: int | None = None, seed: int = 0, max_chars: int | None = None,
            min_entities: int = 1, raw_path: Path | None = None) -> Path:
    """Convert raw -> prepared gold + plain-text docs. Deterministic for a given (limit, seed)."""
    main = card.raw.get("main", "")
    src = raw_path or (ROOT / main[1:] if main.startswith("@") else dataset_dir(card) / "raw" / main)
    docs = [d for d in load_dataset(card, src)]
    if max_chars:
        docs = [_truncate(d, max_chars) for d in docs]
    docs = [d for d in docs if len(d.entities) >= min_entities and d.text.strip()]
    if limit and len(docs) > limit:
        docs = sorted(random.Random(seed).sample(docs, limit), key=lambda d: d.doc_id)
    out = dataset_dir(card) / "prepared"
    if out.exists():
        shutil.rmtree(out)
    (out / "docs").mkdir(parents=True)
    with (out / "gold.jsonl").open("w", encoding="utf-8") as f:
        for d in docs:
            f.write(d.model_dump_json() + "\n")
            (out / "docs" / f"{d.doc_id}.txt").write_text(d.text, encoding="utf-8")
            sf = d.meta.get("source_file")
            if sf and Path(sf).exists():
                shutil.copy(sf, out / "docs" / f"{d.doc_id}{Path(sf).suffix}")
    (out / "card.json").write_text(json.dumps({k: v for k, v in card.raw.items()}, indent=2, default=str), encoding="utf-8")
    return out


def load_prepared(name_or_path: str) -> tuple[list[GoldDocument], Path]:
    """Load prepared gold by dataset name, or from an arbitrary gold.jsonl / prepared directory."""
    p = Path(name_or_path)
    if p.is_file():
        gold = p
    elif (p / "gold.jsonl").exists():
        gold = p / "gold.jsonl"
    else:
        gold = DATA_DIR / name_or_path / "prepared" / "gold.jsonl"
    if not gold.exists():
        raise FileNotFoundError(f"{gold} not found; run: uv run python -m evalkit prepare {name_or_path}")
    docs = [GoldDocument.model_validate_json(l) for l in gold.read_text(encoding="utf-8").splitlines() if l.strip()]
    return docs, gold.parent


def dataset_fingerprint(docs: list[GoldDocument]) -> str:
    h = hashlib.sha256()
    for d in sorted(docs, key=lambda d: d.doc_id):
        h.update(d.model_dump_json().encode())
    return h.hexdigest()[:12]
