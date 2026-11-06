"""CoNLL-style token/tag files (E-NER, German LER, CoNLL-2002/2003 derivatives).

Handles IOB1 (E-NER: 'I-' may start an entity) and IOB2 transparently: a B- tag, or an I- tag whose label
differs from the open entity, starts a new entity.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterator

from ..schema import GoldDocument
from .base import Card, build_text, group_mentions, register


def decode_spans(tags: list[str]) -> list[tuple[str, int, int]]:
    """tags -> [(label, first_tok, last_tok_inclusive)] tolerant of IOB1/IOB2."""
    spans: list[tuple[str, int, int]] = []
    cur = None
    for i, tag in enumerate(tags):
        if tag == "O" or not tag:
            if cur:
                spans.append(tuple(cur))
                cur = None
            continue
        prefix, _, label = tag.partition("-")
        if cur and prefix != "B" and cur[0] == label:
            cur[2] = i
        else:
            if cur:
                spans.append(tuple(cur))
            cur = [label, i, i]
    if cur:
        spans.append(tuple(cur))
    return spans


def _read_sentences(path: Path, sep: str | None, marker: str) -> Iterator[tuple[bool, list[str], list[str]]]:
    """yield (starts_new_doc, tokens, tags) per sentence."""
    toks: list[str] = []
    tags: list[str] = []
    new_doc = False
    with path.open(encoding="utf-8") as f:
        for raw in f:
            line = raw.rstrip("\r\n")
            if line.startswith(marker):
                if toks:
                    yield new_doc, toks, tags
                    toks, tags = [], []
                new_doc = True
                continue
            if not line.strip():
                if toks:
                    yield new_doc, toks, tags
                    toks, tags, new_doc = [], [], False
                continue
            tok, _, tag = line.rpartition(sep or " ")
            toks.append(tok.strip() or line.strip())
            tags.append(tag.strip())
    if toks:
        yield new_doc, toks, tags


@register("conll")
def load_conll(path: Path, opt: dict, card: Card) -> Iterator[GoldDocument]:
    per_doc = int(opt.get("sentences_per_doc", 40))      # used when the file has no document markers
    marker = opt.get("doc_marker", "-DOCSTART-")
    max_docs = opt.get("max_docs")
    state = {"sents": [], "tags": [], "n": 0}

    def flush() -> GoldDocument | None:
        sents, tags_all = state["sents"], state["tags"]
        if not sents:
            return None
        doc_id = f"{card.name}-{state['n']:04d}"
        text, offs = build_text(sents)
        ments = []
        for si, tg in enumerate(tags_all):
            for label, a, b in decode_spans(tg):
                typ = card.map_type(label)
                if typ is None:
                    continue
                s, e = offs[si][a][0], offs[si][b][1]
                ments.append((text[s:e], typ, s, e))
        state["sents"], state["tags"] = [], []
        state["n"] += 1
        return GoldDocument(doc_id=doc_id, text=text, entities=group_mentions(ments, doc_id))

    seen_marker = False
    for new_doc, toks, tags in _read_sentences(path, opt.get("sep"), marker):
        seen_marker |= new_doc
        boundary = new_doc if seen_marker else len(state["sents"]) >= per_doc
        if boundary and state["sents"]:
            doc = flush()
            if doc:
                yield doc
            if max_docs and state["n"] >= max_docs:
                return
        state["sents"].append(toks)
        state["tags"].append(tags)
    doc = flush()
    if doc:
        yield doc
