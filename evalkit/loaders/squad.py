"""SQuAD-style extractive-QA JSON (CUAD). One question label (e.g. 'Parties') becomes entity annotations.

The full contract text is `context`; answers carry `answer_start`, so mentions have real char offsets.
CUAD labels only the chosen clause type, so its card declares partial coverage (recall only).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator

from ..schema import GoldDocument
from .base import Card, group_mentions, register


@register("squad")
def load_squad(path: Path, opt: dict, card: Card) -> Iterator[GoldDocument]:
    label = opt.get("qa_label", "Parties")
    typ = opt.get("entity_type", "other")
    data = json.loads(path.read_text(encoding="utf-8"))["data"]
    n = 0
    for art in data:
        for para in art["paragraphs"]:
            ctx = para["context"]
            ments = []
            for qa in para["qas"]:
                if not qa["id"].endswith(f"__{label}"):
                    continue
                for a in qa.get("answers", []):
                    s = a["answer_start"]
                    ments.append((a["text"].strip(), typ, s, s + len(a["text"])))
            if not ments:
                continue
            doc_id = f"{card.name}-{n:04d}"
            yield GoldDocument(doc_id=doc_id, text=ctx, entities=group_mentions(ments, doc_id),
                               meta={"title": art.get("title")})
            n += 1
            if opt.get("max_docs") and n >= opt["max_docs"]:
                return
