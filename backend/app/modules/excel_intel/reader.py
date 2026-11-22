"""Safe workbook reading: XLSX / XLS / CSV into plain in-memory grids. Never evaluates formulas or runs macros."""
import csv
import io
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

ALLOWED_EXT = {".xlsx", ".xls", ".csv"}
MAX_ROWS = 100_000
MAX_COLS = 200
MAX_UNCOMPRESSED = 300 * 1024 * 1024
MAX_RATIO = 200


class UnsafeFileError(ValueError):
    """The file is rejected before parsing (macro, zip bomb, wrong type, ...)."""


@dataclass
class SheetGrid:
    name: str
    rows: list[list[Any]]  # 0-based, every row padded to n_cols
    n_cols: int
    state: str = "visible"
    merged: list[tuple[int, int, int, int]] = field(default_factory=list)  # (r1, c1, r2, c2) 0-based inclusive
    hidden_cols: set[int] = field(default_factory=set)
    hidden_rows: set[int] = field(default_factory=set)  # 0-based
    formula_cells: set[tuple[int, int]] = field(default_factory=set)
    uncached_formulas: int = 0
    error_cells: dict[tuple[int, int], str] = field(default_factory=dict)
    truncated: bool = False

    @property
    def n_rows(self) -> int:
        return len(self.rows)


def check_upload(filename: str, data: bytes) -> str:
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXT:
        raise UnsafeFileError(f"Unsupported file type '{ext}'. Allowed: .xlsx, .xls, .csv")
    if ext == ".xlsx":
        if not zipfile.is_zipfile(io.BytesIO(data)):
            raise UnsafeFileError("File is not a valid .xlsx workbook")
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            infos = z.infolist()
            total = sum(i.file_size for i in infos)
            if total > MAX_UNCOMPRESSED or (len(data) and total / len(data) > MAX_RATIO):
                raise UnsafeFileError("Workbook expands to an unsafe size (possible zip bomb)")
            if any(i.filename.lower().endswith("vbaproject.bin") for i in infos):
                raise UnsafeFileError("Workbooks containing macros are not accepted")
    elif ext == ".xls" and not data.startswith(b"\xd0\xcf\x11\xe0"):
        raise UnsafeFileError("File is not a valid .xls workbook")
    return ext


def read_workbook(path: Path, ext: str) -> list[SheetGrid]:
    if ext == ".xlsx":
        return _read_xlsx(path)
    if ext == ".xls":
        return _read_xls(path)
    return [_read_csv(path)]


def _pad(rows: list[list[Any]], n_cols: int) -> list[list[Any]]:
    return [r + [None] * (n_cols - len(r)) for r in rows]


def _read_xlsx(path: Path) -> list[SheetGrid]:
    import openpyxl

    wb_v = openpyxl.load_workbook(path, data_only=True)  # cached values
    wb_f = openpyxl.load_workbook(path, data_only=False)  # formulas (read, never evaluated)
    out: list[SheetGrid] = []
    for ws in wb_v.worksheets:
        wf = wb_f[ws.title]
        n_cols = min(ws.max_column or 0, MAX_COLS)
        truncated = (ws.max_row or 0) > MAX_ROWS or (ws.max_column or 0) > MAX_COLS
        rows: list[list[Any]] = []
        errors: dict[tuple[int, int], str] = {}
        for r_i, row in enumerate(ws.iter_rows(min_row=1, max_row=min(ws.max_row or 0, MAX_ROWS), max_col=n_cols)):
            vals = []
            for c_i, cell in enumerate(row):
                if cell.data_type == "e":
                    errors[(r_i, c_i)] = str(cell.value)
                vals.append(cell.value)
            rows.append(vals)
        formulas: set[tuple[int, int]] = set()
        uncached = 0
        for r_i, row in enumerate(wf.iter_rows(min_row=1, max_row=min(wf.max_row or 0, MAX_ROWS), max_col=n_cols)):
            for c_i, cell in enumerate(row):
                if cell.data_type == "f":
                    formulas.add((r_i, c_i))
                    if r_i < len(rows) and rows[r_i][c_i] is None:
                        uncached += 1
        merged = [(m.min_row - 1, m.min_col - 1, m.max_row - 1, m.max_col - 1) for m in ws.merged_cells.ranges]
        hidden = {
            openpyxl.utils.column_index_from_string(k) - 1
            for k, d in ws.column_dimensions.items()
            if d.hidden
        }
        hidden_rows = {r - 1 for r, d in ws.row_dimensions.items() if d.hidden}
        out.append(
            SheetGrid(ws.title, _pad(rows, n_cols), n_cols, ws.sheet_state, merged, hidden, hidden_rows, formulas, uncached, errors, truncated)
        )
    return out


def _read_xls(path: Path) -> list[SheetGrid]:
    import xlrd

    book = xlrd.open_workbook(str(path), formatting_info=True)
    out = []
    for sh in book.sheets():
        n_cols = min(sh.ncols, MAX_COLS)
        rows = []
        errors: dict[tuple[int, int], str] = {}
        for r in range(min(sh.nrows, MAX_ROWS)):
            vals: list[Any] = []
            for c in range(n_cols):
                t, v = sh.cell_type(r, c), sh.cell_value(r, c)
                if t == xlrd.XL_CELL_DATE:
                    v = xlrd.xldate_as_datetime(v, book.datemode)
                elif t == xlrd.XL_CELL_ERROR:
                    errors[(r, c)] = xlrd.error_text_from_code.get(v, "#ERR")
                elif t in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK):
                    v = None
                vals.append(v)
            rows.append(vals)
        merged = [(r1, c1, r2 - 1, c2 - 1) for (r1, r2, c1, c2) in sh.merged_cells]
        out.append(SheetGrid(sh.name, rows, n_cols, "visible" if sh.visibility == 0 else "hidden", merged,
                             set(), set(), set(), 0, errors, sh.nrows > MAX_ROWS or sh.ncols > MAX_COLS))
    return out


def _read_csv(path: Path) -> SheetGrid:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "cp1252"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    rows: list[list[Any]] = []
    for i, r in enumerate(csv.reader(io.StringIO(text), dialect)):
        if i >= MAX_ROWS:
            break
        rows.append([c if c != "" else None for c in r[:MAX_COLS]])
    n_cols = max((len(r) for r in rows), default=0)
    return SheetGrid(path.stem, _pad(rows, n_cols), n_cols, truncated=len(rows) >= MAX_ROWS)


def to_date(v: Any) -> date | None:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    return None
