"""Applies an approved mapping to a sheet: parse, normalise, validate, key. Deterministic; never drops a row silently.

Every problem becomes an Issue. `rejects=True` means that source row is excluded from the import (but still listed).
"""
import hashlib
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from difflib import SequenceMatcher
from typing import Any

from app.modules.excel_intel.catalog import MODE_CATEGORY, EntityDef, categorize_status, uat_result
from app.modules.excel_intel.profiler import (
    ColumnInfo,
    SheetProfile,
    is_blank,
    is_unknown_marker,
    parse_date,
    text,
)
from app.modules.excel_intel.reader import SheetGrid


@dataclass
class Issue:
    severity: str  # error | warning | info
    code: str
    message: str
    row: int | None = None
    header: str | None = None
    field: str | None = None
    raw: str | None = None
    rejects: bool = False


@dataclass
class NormRow:
    source_row: int
    values: dict[str, Any]
    raw: dict[str, str]
    raw_values: dict[str, str]  # original text of cells that could not be parsed
    match_key: str = ""


@dataclass
class SheetResult:
    rows: list[NormRow] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)
    empty_rows: int = 0
    section_rows: int = 0

    @property
    def rejected_rows(self) -> set[int]:
        return {i.row for i in self.issues if i.rejects and i.row is not None}

    @property
    def blocking(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == "error" and i.row is None]


EXCLUDE = "__exclude__"  # product_map value: skip this product column group
HINT_ENTITIES = {"dependency_item", "delivery_schedule", "tech_tracker"}  # "Completed" typed in a date column means closed here
DELIVERY = ("delivery_schedule", "tech_tracker")
ID_ENTITIES = {"delivery_schedule", "tech_tracker", "helpdesk_ops_brd"}
PARENT_RE = re.compile(r"^\s*(\d{4,9})\s*[:\-]")  # "440679 : Party Configuration" -> parent ticket 440679


def norm(s: Any) -> str:
    return re.sub(r"\s+", " ", text(s)).lower()


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


def col_key(c: ColumnInfo) -> str:
    return f"{c.group_label}/{c.header}" if c.group_label else c.header


def _excel_serial(v: Any) -> date | None:
    if isinstance(v, (int, float)) and not isinstance(v, bool) and 20000 < v < 80000:
        return (datetime(1899, 12, 30) + timedelta(days=float(v))).date()
    return None


def parse_value(ftype: str, v: Any, fkey: str, header: str, row: int, issues: list[Issue], raw_values: dict, cfg: dict) -> Any:
    """Returns the parsed value (or None). Appends an Issue for anything suspicious."""
    if is_blank(v):
        return None
    if ftype == "date":
        d = parse_date(v, cfg.get("date_dayfirst", True)) or _excel_serial(v)
        if d is not None:
            return d
        raw_values[fkey] = text(v)
        if is_unknown_marker(v):
            issues.append(Issue("warning", "unknown_date", f"Date not yet known ('{text(v)}'); stored empty, original text kept", row, header, fkey, text(v)))
        else:
            issues.append(Issue("warning", "invalid_date", f"'{text(v)}' is not a valid date; stored empty, original text kept", row, header, fkey, text(v)))
        return None
    if ftype == "number":
        try:
            return int(round(float(str(v).replace(",", ""))))
        except ValueError:
            raw_values[fkey] = text(v)
            issues.append(Issue("warning", "invalid_number", f"'{text(v)}' is not a number", row, header, fkey, text(v)))
            return None
    if ftype == "status":
        return text(v)
    if ftype == "mode":
        m = MODE_CATEGORY.get(norm(v))
        if m is None:
            raw_values[fkey] = text(v)
            issues.append(Issue("warning", "unknown_mode", f"'{text(v)}' is not Onsite/Online/Remote", row, header, fkey, text(v)))
        return m
    if ftype == "id" and isinstance(v, float) and v.is_integer():
        return str(int(v))
    return re.sub(r"[ \t]+", " ", text(v)) if isinstance(v, str) else text(v)


def _similar_values(values: Counter, fkey: str, header: str) -> list[Issue]:
    """Near-duplicate category values (e.g. 'Fjord, US' vs 'Fjord, USA'). Reported, never merged."""
    out, seen = [], set()
    keys = [k for k in values if k]
    for i, a in enumerate(keys):
        for b in keys[i + 1 :]:
            if norm(a) == norm(b):
                continue
            if SequenceMatcher(None, norm(a), norm(b)).ratio() >= 0.88 and (a, b) not in seen:
                seen.add((a, b))
                out.append(Issue("warning", "similar_values", f"Values look like duplicates: '{a}' and '{b}' (kept as is)", None, header, fkey))
    return out[:10]


def _harmonise_case(rows: list[NormRow], fkey: str, header: str, issues: list[Issue]) -> None:
    """'Tegra'/'TEGRA' -> most frequent spelling. Recorded as an info issue; originals stay in the raw row."""
    spell: dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        v = r.values.get(fkey)
        if isinstance(v, str):
            spell[v.lower()][v] += 1
    changed = []
    for variants in spell.values():
        if len(variants) > 1:
            best = variants.most_common(1)[0][0]
            for v in variants:
                if v != best:
                    changed.append((v, best))
                    for r in rows:
                        if r.values.get(fkey) == v:
                            r.values[fkey] = best
    for v, best in changed:
        issues.append(Issue("info", "case_harmonised", f"'{v}' shown as '{best}' (same value, different capitalisation); original kept in source record", None, header, fkey))


def process_sheet(
    grid: SheetGrid,
    profile: SheetProfile,
    columns: list[ColumnInfo],
    effective: dict[int, str],  # column index -> target field (approved mappings only)
    entity: EntityDef,
    cfg: dict,
    ctx: dict,  # product_map {label: product_id}, location_lookup {norm: id}, gate_type, unconfirmed: int
) -> SheetResult:
    res = SheetResult(section_rows=len(profile.section_rows))
    by_idx = {c.index: c for c in columns}
    mapped = {i: f for i, f in effective.items() if i in by_idx}
    fdefs = {f.key: f for f in entity.fields}

    # --- sheet-level (blocking) checks
    if ctx.get("unconfirmed"):
        res.issues.append(Issue("error", "unconfirmed_mapping", f"{ctx['unconfirmed']} medium-confidence mapping(s) need your confirmation before import"))
    mapped_fields = set(mapped.values())
    for f in entity.fields:
        if f.required and f.key not in mapped_fields:
            res.issues.append(Issue("error", "required_unmapped", f"Required field '{f.label}' is not mapped to any column", field=f.key))
    if grid.truncated:
        res.issues.append(Issue("warning", "truncated", "Sheet exceeds the size limit; only the first rows were read"))
    if profile.stats.get("uncached_formulas"):
        res.issues.append(Issue("warning", "formula_not_cached", f"{profile.stats['uncached_formulas']} formula cell(s) have no stored result (file not recalculated in Excel); they read as empty"))
    hidden = [by_idx[i].letter for i in mapped if by_idx[i].profile.get("hidden")]
    if hidden:
        res.issues.append(Issue("info", "hidden_columns", f"Mapped column(s) {', '.join(hidden)} are hidden in the workbook; imported anyway"))
    if profile.stats.get("duplicate_rows"):
        res.issues.append(Issue("info", "duplicate_rows", f"{profile.stats['duplicate_rows']} row(s) are exact duplicates of an earlier row (kept; match key makes them distinct)"))

    matrix_groups: dict[str, dict[str, int]] = {}
    if entity.layout == "matrix":
        for i, f in mapped.items():
            c = by_idx[i]
            if c.group_label and f in ("planned_date", "actual_date"):
                matrix_groups.setdefault(c.group_label, {})[f] = i
        pmap = ctx.get("product_map", {})
        for label in matrix_groups:
            if not pmap.get(label):
                res.issues.append(Issue("error", "product_unresolved", f"Product column group '{label}' is not linked to a product (choose a product, create one, or exclude the group)", header=label))
        if not matrix_groups:
            res.issues.append(Issue("error", "no_product_groups", "No product date columns were mapped"))

    id_cols = {i: f for i, f in mapped.items() if not (entity.layout == "matrix" and by_idx[i].group_label)}
    cat_values: dict[str, Counter] = defaultdict(Counter)
    value_maps = cfg.get("value_maps", {})
    sec_list = sorted(profile.section_rows.items())  # (1-based row, title): the group a row was listed under
    # who a pending item is waiting on: 'WFX' is known; anything else (the customer's own name, a partner) the user must classify
    pw_map = {"wfx": "wfx", **{norm(k): v for k, v in cfg.get("pending_with_map", {}).items() if v}}
    pw_unresolved: set[str] = set()
    unknown_status: Counter = Counter()
    seq = 0

    for r in profile.data_rows:
        excel_row = r + 1
        row = grid.rows[r]
        issues_before = len(res.issues)
        raw = {col_key(c): text(row[c.index])[:300] for c in columns if not is_blank(row[c.index])}
        raw_values: dict[str, str] = {}
        values: dict[str, Any] = {}
        for i, fkey in id_cols.items():
            c, fd = by_idx[i], fdefs[fkey]
            if (r, i) in grid.error_cells:
                # an Excel error (#REF!, #DIV/0!...) in a REQUIRED field rejects the row; in an optional field it is
                # a warning and the row is kept with that value empty
                err = grid.error_cells[(r, i)]
                res.issues.append(Issue("error" if fd.required else "warning", "formula_error",
                                        f"Cell contains an Excel error ({err})" + ("" if fd.required else "; value stored empty, row kept"),
                                        excel_row, c.header, fkey, err, rejects=fd.required))
                values[fkey] = None
                continue
            if fkey in ("original_target_date", "spec_target_date") and entity.key in HINT_ENTITIES and norm(row[i]) in ("completed", "closed", "done"):
                values["_closed_hint"] = True  # "Completed" written in a date column means closed, not a bad date
                raw_values[fkey] = text(row[i])
                values[fkey] = None
                continue
            val = parse_value(fd.type, row[i], fkey, c.header, excel_row, res.issues, raw_values, cfg)
            if fkey == "pending_with" and val is not None:
                classified = pw_map.get(norm(val))
                if classified == "ignore":  # the user chose to exclude rows with this value (e.g. a repeated header row)
                    res.issues.append(Issue("info", "skipped_by_choice", f"Row skipped because '{text(val)}' was set to be excluded", excel_row, c.header, fkey, text(val), rejects=True))
                    classified = None
                    values["_pw_unresolved"] = True  # suppress the required-value error for this row
                elif classified is None:
                    pw_unresolved.add(text(val))
                    values["_pw_unresolved"] = True
                val = classified
            if fd.type == "status" and val is not None:
                vm = value_maps.get(fkey, {})
                cat = vm.get(norm(val)) or categorize_status(text(val))
                if cat is None:
                    unknown_status[(fkey, c.header, str(val))] += 1  # reported once per distinct value, below
                values[fkey + "_category"] = cat
            if fkey == "external_id" and entity.key in ID_ENTITIES and isinstance(val, str) and not re.fullmatch(r"\d{3,9}", val):
                res.issues.append(Issue("warning", "odd_id", f"'{val}' does not look like a ticket number; kept as written", excel_row, c.header, fkey, val))
            values[fkey] = val
            if fd.type == "category" and isinstance(val, str):
                cat_values[fkey][val] += 1
        # drop rows with nothing mapped
        if all(v is None for k, v in values.items() if not k.endswith("_category")) and entity.layout != "matrix":
            res.empty_rows += 1
            continue
        if entity.key == "integration_item" and values.get("name") is None:  # registers often have no 'name' column: name it from the partner and the message or system
            values["name"] = " - ".join(str(x) for x in (values.get("partner"), values.get("message_type") or values.get("system")) if x) or None
        if entity.key == "report_item" and values.get("name") is None:  # an inventory of folders: the sub folder (or folder) is the name
            values["name"] = values.get("sub_folder") or values.get("folder")
        if entity.key in ("integration_item", "report_item") and values.get("name") is None:
            res.issues.append(Issue("error", "missing_required", "This row has nothing to name it from (no name, partner, message, folder or sub folder)", excel_row, None, "name", rejects=True))
        for f in entity.fields:
            if f.key == "pending_with" and values.get("_pw_unresolved"):
                continue  # reported once as a blocking issue below
            if f.required and f.key in mapped_fields and values.get(f.key) is None:
                res.issues.append(Issue("error", "missing_required", f"Required value '{f.label}' is empty", excel_row, None, f.key, rejects=True))
        for a, b in (("planned_start", "planned_finish"), ("actual_start", "actual_finish")):
            if values.get(a) and values.get(b) and values[b] < values[a]:
                res.issues.append(Issue("warning", "date_order", f"{b.replace('_', ' ')} is before {a.replace('_', ' ')}", excel_row, None, b))
        if entity.layout == "matrix":
            if values.get("event_name") is None:
                if all(is_blank(v) for v in row):
                    res.empty_rows += 1
                    continue
            produced = False
            for label, pair in matrix_groups.items():
                pid = ctx.get("product_map", {}).get(label)
                if not pid or pid == EXCLUDE:
                    continue
                gv: dict[str, Any] = {}
                for fkey, ci in pair.items():
                    c = by_idx[ci]
                    if (r, ci) in grid.error_cells:
                        res.issues.append(Issue("error", "formula_error", f"Cell contains an Excel error ({grid.error_cells[(r, ci)]})", excel_row, col_key(c), fkey, grid.error_cells[(r, ci)], rejects=True))
                        continue
                    gv[fkey] = parse_value("date", row[ci], fkey, col_key(c), excel_row, res.issues, raw_values, cfg)
                if gv.get("planned_date") is None and gv.get("actual_date") is None:
                    continue  # this event does not apply to this product
                seq += 1
                nrow = NormRow(excel_row, {**values, "product_label": label, "product_id": pid, **gv, "sort_order": seq}, raw, dict(raw_values))
                nrow.match_key = f"{pid}|{norm(values.get('event_name'))}"
                res.rows.append(nrow)
                produced = True
            if not produced and not values.get("event_name"):
                res.empty_rows += 1
            continue
        if entity.key == "dependency_item":
            hint = values.pop("_closed_hint", False)
            values.pop("_pw_unresolved", None)
            values["category"] = next((t for rr, t in reversed(sec_list) if rr <= excel_row), None)
            if values.get("status") is None:  # no status column: closed = has a closure date or was written as 'Completed'
                closed = bool(values.get("actual_closure_date")) or hint
                values["status"], values["status_category"] = ("Closed", "done") if closed else ("Open", "not_started")
        if entity.key in DELIVERY:
            values["specs_completed"] = bool(values.pop("_closed_hint", False))  # "Completed" under the specs target date: the specs are done, NOT the delivery
            values.pop("_pw_unresolved", None)
            m = PARENT_RE.match(values.get("description") or "")
            if m and m.group(1) != values.get("external_id"):
                values["parent_external_id"] = m.group(1)
        if entity.key == "uat_scenario":
            raw_result = (str(values.get("result")) if values.get("result") is not None else "").strip()
            mapped = uat_result(raw_result)
            values["result_raw"] = raw_result or None
            values["result"] = mapped or "not_run"
            if mapped is None:
                unknown_status[("result", "Result / status", raw_result)] += 1
        if entity.key == "helpdesk_ops_brd":
            values["kind"] = "ops_brd"
        elif entity.key == "ops_open_point":
            values["kind"] = "open_point"
        seq += 1
        values["sort_order"] = seq
        nrow = NormRow(excel_row, values, raw, raw_values)
        # business key for re-import matching (never the external issue ID alone)
        if entity.key == "plan_task":
            nrow.match_key = f"{norm(values.get('phase'))}|{norm(values.get('title'))}|{values.get('planned_start') or ''}"
            loc = values.get("location")
            if loc:
                values["location_id"] = ctx.get("location_lookup", {}).get(norm(loc))
        elif entity.key == "approval_gate":
            values["gate_type"] = ctx.get("gate_type", "gate")
            nrow.match_key = f"{values['gate_type']}|{norm(values.get('name'))}"
        elif entity.key == "gap_specification":
            nrow.match_key = f"{norm(values.get('external_issue_id'))}|{hashlib.sha1(norm(values.get('description')).encode()).hexdigest()[:12]}"
        elif entity.key == "dependency_item":
            nrow.match_key = f"{norm(values.get('category'))}|{norm(values.get('description'))}"
        elif entity.key in DELIVERY:
            nrow.match_key = f"{norm(values.get('external_id'))}"  # same ticket in both sheets; repeats get #2, #3 by order
        elif entity.key == "brd_requirement":
            nrow.match_key = f"{norm(values.get('sr_no'))}|{hashlib.sha1(norm(values.get('description')).encode()).hexdigest()[:10]}"
        elif entity.key == "helpdesk_ops_brd":
            nrow.match_key = f"ops_brd|{norm(values.get('external_id'))}"
        elif entity.key == "ops_open_point":
            nrow.match_key = f"open_point|{norm(values.get('sr_no'))}|{hashlib.sha1(norm(values.get('description')).encode()).hexdigest()[:10]}"
        elif entity.key == "discussion_item":
            nrow.match_key = f"{norm(values.get('sr_no'))}|{hashlib.sha1(norm(values.get('name')).encode()).hexdigest()[:10]}"
        elif entity.key == "scope_decision":
            nrow.match_key = hashlib.sha1(norm(values.get("customer_feedback")).encode()).hexdigest()[:16]
        elif entity.key == "uat_scenario":
            nrow.match_key = f"{norm(values.get('scenario_id'))}|{hashlib.sha1(norm(values.get('title')).encode()).hexdigest()[:10]}"
        elif entity.key == "integration_item":
            nrow.match_key = f"{norm(values.get('name'))}|{norm(values.get('partner'))}|{norm(values.get('direction'))}"
        elif entity.key == "report_item":
            nrow.match_key = f"{norm(values.get('folder'))}|{norm(values.get('sub_folder'))}|{norm(values.get('name'))}"
        res.rows.append(nrow)

    for (fkey, header, value), n in unknown_status.items():
        if fkey == "result":
            res.issues.append(Issue("warning", "unknown_status", f"UAT result '{value}' appears in {n} row(s) and is not one of Passed, Failed, Blocked, Retest, In progress, Not run; those scenarios are imported as Not run (the original wording is kept). Correct them in the UAT tab.", None, header, fkey, value))
            continue
        res.issues.append(Issue("warning", "unknown_status", f"Status '{value}' appears in {n} row(s) and is not classified; its category is left empty. Classify it under Status values.", None, header, fkey, value))
    if pw_unresolved:
        res.issues.append(Issue("error", "pending_with_unresolved", "Say who these values mean (Customer, WFX, External partner or Internal team): " + ", ".join(sorted(pw_unresolved)[:8]), field="pending_with"))
    if grid.hidden_rows:
        n_hidden = len([r for r in profile.data_rows if r in grid.hidden_rows])
        if n_hidden:
            res.issues.append(Issue("info", "hidden_rows", f"{n_hidden} data row(s) are hidden in the workbook (filtered or collapsed); imported anyway"))

    # --- cross-row checks
    for fkey, cnt in cat_values.items():
        header = next((by_idx[i].header for i, f in id_cols.items() if f == fkey), fkey)
        _harmonise_case(res.rows, fkey, header, res.issues)
        res.issues.extend(_similar_values(cnt, fkey, header))
    if entity.key == "plan_task":
        labels = Counter(r.values.get("location") for r in res.rows if r.values.get("location"))
        unlinked = sorted(k for k in labels if not ctx.get("location_lookup", {}).get(norm(k)))
        if unlinked:
            res.issues.append(Issue("info", "location_unlinked", f"{len(unlinked)} location label(s) are not in the Location master and were stored as text: {', '.join(unlinked[:8])}", field="location"))
    if entity.key == "plan_task" and profile.section_rows:
        used = {norm(r.values.get("phase")) for r in res.rows}
        orphans = [t for t in dict.fromkeys(profile.section_rows.values()) if norm(t) not in used]
        if orphans:
            res.issues.append(Issue("info", "section_phase_mismatch", f"{len(orphans)} section title row(s) do not match any task's Phase value (phases come from the Phase column): {'; '.join(o[:50] for o in orphans[:6])}", field="phase"))
    seen: Counter = Counter()
    dups = 0
    for r in res.rows:
        seen[r.match_key] += 1
        if seen[r.match_key] > 1:
            dups += 1
            r.match_key = f"{r.match_key}#{seen[r.match_key]}"
    if dups:
        sev_msg = "repeated external IDs are expected" if entity.key == "gap_specification" else "rows share the same business key"
        res.issues.append(Issue("info", "duplicate_keys", f"{dups} row(s) share a business key with an earlier row ({sev_msg}); each is imported as its own record"))
    return res
