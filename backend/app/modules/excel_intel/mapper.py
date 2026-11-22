"""Semantic column mapping. score = 0.60 header similarity + 0.25 value pattern + 0.15 context, plus history/template."""
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from app.modules.excel_intel.catalog import MODE_CATEGORY, STATUS_CATEGORY, EntityDef, FieldDef
from app.modules.excel_intel.profiler import ColumnInfo, norm_header

W_HEADER, W_VALUE, W_CONTEXT = 0.60, 0.25, 0.15
HIGH, MEDIUM, LOW = 0.85, 0.65, 0.45
QUALIFIERS = ("actual", "revised")


def level(score: float) -> str:
    return "high" if score >= HIGH else "medium" if score >= MEDIUM else "low" if score >= LOW else "none"


def _has(tokens: set[str], q: str) -> bool:
    return any(t == q or SequenceMatcher(None, t, q).ratio() >= 0.8 for t in tokens)  # tolerates 'Actuat'


def header_similarity(header_norm: str, phrase_norm: str) -> float:
    if not header_norm or not phrase_norm:
        return 0.0
    if header_norm == phrase_norm:
        return 1.0
    h, p = set(header_norm.split()), set(phrase_norm.split())
    if p <= h:
        s = 0.65 + 0.30 * len(p) / len(h)
    elif h <= p:
        s = 0.55 + 0.30 * len(h) / len(p)
    else:
        jac = len(h & p) / len(h | p)
        ratio = SequenceMatcher(None, header_norm, phrase_norm).ratio()
        s = max(jac * 0.8, ratio * 0.7)
    for q in QUALIFIERS:  # "Actual Start" must not match plain "Start", and vice versa
        if _has(h, q) != _has(p, q):
            s *= 0.35
    return min(s, 1.0)


def _values_in(col: ColumnInfo, vocab: set[str]) -> bool:
    vals = col.profile.get("values")
    return bool(vals) and all(str(v).strip().lower() in vocab for v, _ in vals)


def value_score(f: FieldDef, col: ColumnInfo) -> float:
    t = col.inferred_type
    if t == "empty":
        return 0.5  # nothing to judge from (e.g. an unused actual-date column)
    if f.type == "date":
        return 1.0 if t == "date" else 0.15
    if f.type == "number":
        return 1.0 if t == "number" else 0.2
    if f.type == "status":
        return 1.0 if _values_in(col, set(STATUS_CATEGORY)) else 0.8 if t == "category" else 0.5
    if f.type == "mode":
        return 1.0 if _values_in(col, set(MODE_CATEGORY)) else 0.3
    if f.type == "id":
        return 1.0 if t in ("id", "number") else 0.6
    if f.type == "category":
        return 0.9 if t in ("category", "text") else 0.3 if t in ("date", "number") else 0.5
    return 0.8 if t in ("text", "category", "id") else 0.3  # text / long_text


@dataclass
class Suggestion:
    column_index: int
    header: str
    target_field: str | None
    score: float
    level: str
    source: str = "auto"  # auto | history | template
    alternatives: list[tuple[str, float]] = field(default_factory=list)


def score_pair(col: ColumnInfo, f: FieldDef, ctx: float) -> float:
    hn = norm_header(col.header)
    hs = max((header_similarity(hn, norm_header(p)) * w for p, w in f.synonyms), default=0.0)
    return W_HEADER * hs + W_VALUE * value_score(f, col) + W_CONTEXT * ctx


def suggest_mappings(
    columns: list[ColumnInfo],
    entity: EntityDef,
    context: float = 1.0,
    history: dict[str, str] | None = None,
    template: dict[str, str] | None = None,
) -> list[Suggestion]:
    """One field per column, one column per field (greedy by score). Matrix group columns share fields."""
    history, template = history or {}, template or {}
    matrix = entity.layout == "matrix"
    scored: list[tuple[float, int, str, str]] = []  # score, col idx, field key, source
    per_col: dict[int, list[tuple[str, float]]] = {}
    for col in columns:
        hn = norm_header(col.header)
        for f in entity.fields:
            s, src = score_pair(col, f, context), "auto"
            if history.get(hn) == f.key:
                s, src = min(1.0, s + 0.20), "history"
            if template.get(hn) == f.key:
                s, src = max(s, 0.97), "template"
            scored.append((s, col.index, f.key, src))
            per_col.setdefault(col.index, []).append((f.key, round(s, 3)))
    scored.sort(key=lambda x: -x[0])
    taken_cols: dict[int, tuple[str, float, str]] = {}
    used_fields: set[str] = set()
    for s, ci, fk, src in scored:
        if s < LOW or ci in taken_cols:
            continue
        col = next(c for c in columns if c.index == ci)
        # matrix: planned/actual fields repeat once per product group; identifiers are used once
        shared = matrix and fk in ("planned_date", "actual_date") and col.group_label
        if fk in used_fields and not shared:
            continue
        if matrix and fk in ("planned_date", "actual_date") and not col.group_label:
            continue
        if matrix and col.group_label and fk not in ("planned_date", "actual_date"):
            continue
        taken_cols[ci] = (fk, s, src)
        if not shared:
            used_fields.add(fk)
    out = []
    for col in columns:
        alts = sorted(per_col.get(col.index, []), key=lambda x: -x[1])[:3]
        if col.index in taken_cols:
            fk, s, src = taken_cols[col.index]
            out.append(Suggestion(col.index, col.header, fk, round(s, 3), level(s), src, alts))
        else:
            best = alts[0][1] if alts else 0.0
            out.append(Suggestion(col.index, col.header, None, best, "none", "auto", alts))
    return out
