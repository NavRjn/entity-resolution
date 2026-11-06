"""AWS Textract/GroundTruth annotation files (aws-legal-entity-extraction insurance letters).

Gold is document-level: Entities[{Text, Type}] with no flat-text offsets (positions are Textract block
references), so mentions carry text only. The matching source PDF is kept in meta['source_file'] so the
real PDF/docling path can be evaluated, not only the reconstructed text.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterator

from ..schema import GoldDocument
from .base import Card, group_mentions, register


@register("textract")
def load_textract(path: Path, opt: dict, card: Card) -> Iterator[GoldDocument]:
    ann_dir = path / opt.get("annotations_dir", "annotations")
    src_dir = path / opt.get("source_dir", "source")
    files = sorted(ann_dir.glob("*-ann.json"), key=lambda p: int(re.search(r"Letter (\d+)", p.name).group(1)))
    for f in files[: opt.get("max_docs")]:
        d = json.loads(f.read_text(encoding="utf-8"))
        stem = re.sub(r"-\d+-[0-9a-f]+-ann\.json$", "", f.name)
        lines = [b["Text"] for b in d["Blocks"] if b["BlockType"] == "LINE"]
        ments = []
        for e in d.get("Entities", []):
            typ = card.map_type(e["Type"])
            if typ is not None:
                ments.append((e["Text"].strip(), typ, None, None))
        doc_id = f"{card.name}-{stem.replace(' ', '_')}"
        pdf = src_dir / f"{stem}.pdf"
        yield GoldDocument(doc_id=doc_id, text="\n".join(lines), entities=group_mentions(ments, doc_id),
                           meta={"source_file": str(pdf) if pdf.exists() else None})
