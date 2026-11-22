"""Structure detection and column profiling. Pure functions over SheetGrid."""
import hashlib
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from app.modules.excel_intel.reader import SheetGrid

# Marks "no value here". Treated as blank, no warning.
BLANK_MARKERS = {"", "-", "–", "—", "n/a", "na", "nil", "null", "none"}
# Marks "value not known yet". Treated as blank in a date column, but reported as a warning.
UNKNOWN_MARKERS = {"tba", "tbd", "to be decided", "to be announced", "pending"}
DATE_FORMATS_DAYFIRST = ["%d-%b-%y", "%d-%b-%Y", "%d %b %Y", "%d %b %y", "%d/%m/%Y", "%d/%m/%y", "%d-%m-%Y", "%d.%m.%Y"]
DATE_FORMATS_MONTHFIRST = ["%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y"]
ISO_FORMATS = ["%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"]
HEADER_SCAN_ROWS = 25


def text(v: Any) -> str:
    return "" if v is None else str(v).strip()


def is_blank(v: Any) -> bool:
    return v is None or (isinstance(v, str) and v.strip().lower() in BLANK_MARKERS)


def is_unknown_marker(v: Any) -> bool:
    return isinstance(v, str) and v.strip().lower() in UNKNOWN_MARKERS


def parse_date(v: Any, dayfirst: bool = True) -> date | None:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if not isinstance(v, str):
        return None
    s = v.strip()
    formats = ISO_FORMATS + (DATE_FORMATS_DAYFIRST + DATE_FORMATS_MONTHFIRST if dayfirst else DATE_FORMATS_MONTHFIRST + DATE_FORMATS_DAYFIRST)
    for f in formats:
        try:
            return datetime.strptime(s, f).date()
        except ValueError:
            continue
    return None


def norm_header(s: str) -> str:
    """Lower-case alphanumerics only; trailing digits removed ('Planned Date2' -> 'planned date')."""
    s = re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()
    return re.sub(r"(?<=[a-z])\d+$", "", s).strip()


def col_letter(i: int) -> str:
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


@dataclass
class ColumnInfo:
    index: int
    letter: str
    header: str
    group_label: str | None
    inferred_type: str
    profile: dict[str, Any]


@dataclass
class SheetProfile:
    header_row: int  # 1-based
    header_candidates: list[dict[str, Any]]
    group_row: int | None  # 1-based
    data_start: int  # 1-based
    data_end: int  # 1-based
    section_rows: dict[int, str]  # 1-based row -> text
    columns: list[ColumnInfo]
    stats: dict[str, Any] = field(default_factory=dict)
    data_rows: list[int] = field(default_factory=list)  # 0-based row indexes of data rows


def _nonblank(row: list[Any]) -> list[int]:
    return [i for i, v in enumerate(row) if not is_blank(v)]


def detect_header_candidates(grid: SheetGrid) -> list[dict[str, Any]]:
    """Scores the first rows as header candidates. Title rows, link rows and one-cell rows score ~0."""
    cands = []
    limit = min(grid.n_rows, HEADER_SCAN_ROWS)
    for i in range(limit):
        row = grid.rows[i]
        idx = _nonblank(row)
        if len(idx) < 2:
            continue
        vals = [row[j] for j in idx]
        str_ratio = sum(isinstance(v, str) for v in vals) / len(vals)
        uniq = len({text(v).lower() for v in vals}) / len(vals)
        nxt = [r for r in grid.rows[i + 1 : i + 6] if _nonblank(r)]
        support = 0.0
        if nxt:
            support = min(1.0, (sum(len(_nonblank(r)) for r in nxt) / len(nxt)) / max(1, 0.5 * len(idx)))
            # a header row is followed by rows with non-text content (dates/numbers) or differently typed cells
            next_vals = [v for r in nxt for v in r if not is_blank(v)]
            non_text = sum(not isinstance(v, str) for v in next_vals) / max(1, len(next_vals))
            support *= 0.7 + 0.3 * min(1.0, non_text * 2 + (0.3 if len(nxt) >= 3 else 0))
        score = len(idx) * str_ratio * uniq * support
        if score > 0:
            cands.append({"row": i + 1, "score": round(score, 2), "preview": [text(v)[:30] for v in vals[:8]]})
    cands.sort(key=lambda c: -c["score"])
    return cands[:4]


def _group_labels(grid: SheetGrid, header_idx: int) -> tuple[int | None, dict[int, str]]:
    """Group band = row above the header whose labels (merged or forward-filled) sit over repeating sub-header sets.

    Only groups whose sub-header set repeats (e.g. Planned/Actual under PLM, ERP, ...) count; a title merged over
    ordinary columns is not a group.
    """
    if header_idx < 1:
        return None, {}
    r = header_idx - 1
    above, header = grid.rows[r], grid.rows[header_idx]
    hdr_cols = sorted(_nonblank(header))
    spans = {c1: c2 for (r1, c1, r2, c2) in grid.merged if r1 == r and r2 == r and c2 > c1}
    labels: dict[int, str] = {}
    for c1, c2 in spans.items():
        for c in range(c1, c2 + 1):
            if c in hdr_cols:
                labels[c] = text(above[c1])
    in_span = {c for c1, c2 in spans.items() for c in range(c1, c2 + 1)}
    cur = None
    for c in hdr_cols:
        if c in in_span:
            cur = None
            continue
        if not is_blank(above[c]):
            cur = text(above[c])
        if cur is not None:
            labels[c] = cur
    if len(set(labels.values())) < 2:
        return None, {}
    groups: dict[str, list[int]] = {}
    for c, lab in labels.items():
        groups.setdefault(lab, []).append(c)
    sig = {lab: tuple(norm_header(text(header[c])) for c in sorted(cols)) for lab, cols in groups.items()}
    repeated = Counter(sig.values())
    keep = {lab for lab, sg in sig.items() if repeated[sg] >= 2}
    labels = {c: lab for c, lab in labels.items() if lab in keep}
    if len({*labels.values()}) < 2:
        return None, {}
    return header_idx, labels


def _looks_like_subheader(grid: SheetGrid, idx: int, above_idx: int) -> bool:
    """Row idx repeats a small vocabulary (Planned/Actual, ...) under labels in row above_idx."""
    if idx >= grid.n_rows:
        return False
    row = grid.rows[idx]
    nb = _nonblank(row)
    if len(nb) < 4 or not all(isinstance(row[c], str) for c in nb):
        return False
    counts = Counter(norm_header(text(row[c])) for c in nb)
    if len(counts) > 4 or min(counts.values()) < 2:
        return False
    above = grid.rows[above_idx]
    labelled = sum(1 for c in nb if not is_blank(above[c]))
    return labelled >= 2


def _infer(values: list[Any]) -> tuple[str, dict[str, Any]]:
    """Returns (type, extra). Types: empty, date, number, boolean, id, category, text."""
    vals = [v for v in values if not is_blank(v)]
    if not vals:
        return "empty", {}
    unknown = [v for v in vals if is_unknown_marker(v)]
    core = [v for v in vals if not is_unknown_marker(v)]
    if not core:
        return "text", {}
    n = len(core)
    n_date = sum(1 for v in core if parse_date(v) is not None)
    n_num = sum(1 for v in core if isinstance(v, (int, float)) and not isinstance(v, bool))
    n_bool = sum(isinstance(v, bool) for v in core)
    extra: dict[str, Any] = {}
    if n_date / n >= 0.6:
        bad = [text(v) for v in core if parse_date(v) is None] + [text(v) for v in unknown]
        extra["invalid_date_values"] = Counter(bad).most_common(10)
        return "date", extra
    if n_num / n >= 0.8:
        return "number", extra
    if n_bool == n:
        return "boolean", extra
    distinct = len({text(v).lower() for v in core})
    if n >= 8 and distinct <= 15 and distinct / n <= 0.5:
        return "category", extra
    if distinct / n >= 0.9 and all(len(text(v)) <= 40 for v in core) and any(re.search(r"\d", text(v)) for v in core):
        return "id", extra
    return "text", extra


def profile_columns(grid: SheetGrid, header_idx: int, data_rows: list[int], group_map: dict[int, str]) -> list[ColumnInfo]:
    header = grid.rows[header_idx]
    above = grid.rows[header_idx - 1] if header_idx >= 1 and group_map else None
    cols: list[ColumnInfo] = []
    for c in range(grid.n_cols):
        h = text(header[c])
        if not h and above is not None and not is_blank(above[c]):
            h = text(above[c])  # two-level header: column title lives in the band row
        values = [grid.rows[r][c] for r in data_rows]
        if not h and all(is_blank(v) for v in values):
            continue
        t, extra = _infer(values)
        nb = [v for v in values if not is_blank(v)]
        distinct = Counter(text(v) for v in nb)
        prof: dict[str, Any] = {
            "non_blank": len(nb),
            "blank": len(values) - len(nb),
            "unique": len(distinct),
            "samples": [k for k, _ in distinct.most_common(5)],
            "hidden": c in grid.hidden_cols,
            "formula_cells": sum(1 for r in data_rows if (r, c) in grid.formula_cells),
            "error_cells": sum(1 for r in data_rows if (r, c) in grid.error_cells),
            "header_was_blank": not h,
            **extra,
        }
        if t in ("category", "text", "id") and len(distinct) <= 60:
            prof["values"] = distinct.most_common(60)
        if t in ("date", "number"):
            conv = [parse_date(v) if t == "date" else v for v in nb]
            conv = [x for x in conv if x is not None and not isinstance(x, str)]
            if conv:
                prof["min"], prof["max"] = str(min(conv)), str(max(conv))
        cols.append(ColumnInfo(c, col_letter(c), h or f"Column {col_letter(c)}", group_map.get(c), t, prof))
    return cols


def profile_sheet(grid: SheetGrid, header_row: int | None = None) -> SheetProfile:
    """header_row is 1-based; None = auto-detect (best candidate)."""
    cands = detect_header_candidates(grid)
    if header_row is None:
        header_row = cands[0]["row"] if cands else 1
        if _looks_like_subheader(grid, header_row, header_row - 1):  # titles above, Planned/Actual pairs below
            header_row += 1
    h_idx = max(0, min(header_row - 1, max(0, grid.n_rows - 1)))
    group_row, group_map = None, {}
    if grid.n_rows and h_idx >= 1:
        g, group_map = _group_labels(grid, h_idx)
        group_row = g  # 1-based number of the row above the header == h_idx (0-based index h_idx-1)
    # data rows: after header, skipping blank rows; section rows (one label spanning the row) are tracked separately
    n_hdr_cols = len(_nonblank(grid.rows[h_idx])) if grid.n_rows else 0
    section: dict[int, str] = {}
    data_rows: list[int] = []
    last = h_idx
    for r in range(h_idx + 1, grid.n_rows):
        row = grid.rows[r]
        nb = _nonblank(row)
        if not nb:
            continue
        last = r
        spans_wide = any(r1 == r and (c2 - c1 + 1) >= max(3, n_hdr_cols // 2) for (r1, c1, r2, c2) in grid.merged)
        if n_hdr_cols >= 4 and len(nb) == 1 and (spans_wide or nb[0] == 0):
            section[r + 1] = text(row[nb[0]])
            continue
        data_rows.append(r)
    cols = profile_columns(grid, h_idx, data_rows, group_map)
    # whole-row duplicates (informational)
    seen = Counter(hashlib.sha1(repr([text(v) for v in grid.rows[r]]).encode()).hexdigest() for r in data_rows)
    dup_rows = sum(c - 1 for c in seen.values() if c > 1)
    stats = {
        "data_rows": len(data_rows),
        "duplicate_rows": dup_rows,
        "section_rows": len(section),
        "formula_cells": len(grid.formula_cells),
        "uncached_formulas": grid.uncached_formulas,
        "error_cells": len(grid.error_cells),
        "hidden_columns": sorted(col_letter(c) for c in grid.hidden_cols),
        "merged_ranges": len(grid.merged),
        "truncated": grid.truncated,
    }
    return SheetProfile(
        header_row=h_idx + 1,
        header_candidates=cands,
        group_row=(h_idx if group_row is not None else None),
        data_start=h_idx + 2,
        data_end=last + 1,
        section_rows=section,
        columns=cols,
        stats=stats,
        data_rows=data_rows,
    )
