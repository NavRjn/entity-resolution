"""Gold <-> prediction entity alignment.

One-to-one maximum-weight assignment (Hungarian) over name similarity, so the result does not depend on
iteration order (the old test.py took the first fuzzy hit above 90). Alignment is type-agnostic, with a
small bonus for equal types so ties resolve sensibly; strict vs lenient typing is decided by the metrics.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from rapidfuzz import fuzz
from scipy.optimize import linear_sum_assignment

from .normalize import core_name, norm_name
from .schema import GoldEntity, PredEntity

TYPE_BONUS = 0.01


@dataclass
class MatchConfig:
    fuzzy_threshold: float = 0.90      # min similarity of legal-form-stripped names
    use_aliases: bool = True           # compare all surface forms, not only canonical names
    allow_fuzzy: bool = True


def name_sim(a: str, b: str, cfg: MatchConfig) -> float:
    if norm_name(a) == norm_name(b):
        return 1.0
    ca, cb = core_name(a), core_name(b)
    if ca and ca == cb:
        return 0.97
    if cfg.allow_fuzzy and ca and cb:
        r = fuzz.ratio(ca, cb) / 100
        return r if r >= cfg.fuzzy_threshold else 0.0
    return 0.0


def entity_sim(g: GoldEntity, p: PredEntity, cfg: MatchConfig) -> float:
    gf = g.surface_forms() if cfg.use_aliases else [g.name]
    pf = [p.name, *p.aliases] if cfg.use_aliases else [p.name]
    best = max((name_sim(a, b, cfg) for a in gf for b in pf), default=0.0)
    if best and g.type == p.type:
        best += TYPE_BONUS
    return best


@dataclass
class Alignment:
    pairs: list[tuple[int, int, float]] = field(default_factory=list)   # (gold_idx, pred_idx, score)
    gold_to_pred: dict[int, int] = field(default_factory=dict)
    pred_to_gold: dict[int, int] = field(default_factory=dict)


def align(gold: list[GoldEntity], pred: list[PredEntity], cfg: MatchConfig | None = None) -> Alignment:
    cfg = cfg or MatchConfig()
    out = Alignment()
    if not gold or not pred:
        return out
    m = np.zeros((len(gold), len(pred)))
    for i, g in enumerate(gold):
        for j, p in enumerate(pred):
            m[i, j] = entity_sim(g, p, cfg)
    rows, cols = linear_sum_assignment(-m)
    for i, j in zip(rows, cols):
        if m[i, j] > 0:
            out.pairs.append((int(i), int(j), float(m[i, j])))
            out.gold_to_pred[int(i)] = int(j)
            out.pred_to_gold[int(j)] = int(i)
    return out
