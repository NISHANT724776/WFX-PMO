"""Cross-sheet relationship and key detection. Suggestions only: the user confirms or rejects each one."""
import re
from typing import Any

from app.modules.excel_intel.profiler import ColumnInfo, is_blank, norm_header, text

ID_HINT = re.compile(r"\b(id|no|number|code|ref|reference|serial|sr)\b")
MAX_VALUES = 5000


def column_values(rows: list[list[Any]], data_rows: list[int], idx: int) -> set[str]:
    out = set()
    for r in data_rows[:MAX_VALUES]:
        v = rows[r][idx]
        if not is_blank(v):
            out.add(str(int(v)) if isinstance(v, float) and v.is_integer() else text(v).lower())
    return out


def detect(sheets: list[dict[str, Any]]) -> dict[str, Any]:
    """sheets: [{id, name, columns: [ColumnInfo], values: {col_index: set}, data_rows: int}]"""
    keys, nonunique, candidates = [], [], []
    for sh in sheets:
        for c in sh["columns"]:
            nb = c.profile["non_blank"]
            idish = bool(ID_HINT.search(norm_header(c.header))) or c.inferred_type == "id"
            if not idish or nb < 5 or c.inferred_type in ("date", "empty"):
                continue
            if c.profile["unique"] == nb:
                keys.append({"sheet": sh["name"], "column": c.header, "kind": "primary_key_candidate", "unique": nb})
            elif c.profile["unique"] / nb > 0.5:
                nonunique.append({"sheet": sh["name"], "column": c.header, "kind": "repeated_reference",
                                  "rows": nb, "distinct": c.profile["unique"],
                                  "note": "Values repeat across rows, so this is a reference, not a unique key"})
    for i, a in enumerate(sheets):
        for b in sheets[i + 1 :]:
            for ca in a["columns"]:
                va = a["values"].get(ca.index)
                if not va or len(va) < 5 or ca.inferred_type in ("date", "empty", "category"):
                    continue
                for cb in b["columns"]:
                    vb = b["values"].get(cb.index)
                    if not vb or len(vb) < 5 or cb.inferred_type != ca.inferred_type:
                        continue
                    common = va & vb
                    overlap = len(common) / min(len(va), len(vb))
                    if len(common) >= 5 and overlap >= 0.6:
                        hs = 1.0 if norm_header(ca.header) == norm_header(cb.header) else 0.0
                        candidates.append({
                            "sheet_a": a["name"], "column_a": ca.header, "sheet_b": b["name"], "column_b": cb.header,
                            "overlap": round(overlap, 2), "common_values": len(common),
                            "confidence": round(min(1.0, overlap * 0.7 + hs * 0.3), 2),
                            "samples": sorted(common)[:4], "decision": None,
                        })
    candidates.sort(key=lambda x: -x["confidence"])
    return {"candidates": candidates[:25], "keys": keys, "repeated_references": nonunique}
