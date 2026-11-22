"""Lays a Report out as Excel, PDF or PowerPoint. No calculation happens here."""
import io
from datetime import date, datetime
from typing import Any
from xml.sax.saxutils import escape

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from pptx.enum.text import PP_ALIGN
from pptx.util import Inches, Pt
from reportlab.graphics.shapes import Drawing, Line, Rect, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table as RLTable, TableStyle

from app.modules.dashboards import export_pptx as px
from app.modules.dashboards.reports import Report, Table

NAVY, BLUE, GREEN, AMBER, RED, GREY = "#0B1F4B", "#1E3A8A", "#16A34A", "#D97706", "#DC2626", "#94A3B8"
STATE = {"done": GREEN, "in_progress": AMBER, "overdue": RED, "upcoming": GREY}
CELLS = {"overdue": "Overdue", "done": "Done", "open": "Open", "due": "Due soon", "planned": "Planned", "approved": "Approved", "high": "High", "medium": "Medium"}


def show(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, (date, datetime)):
        return v.strftime("%d-%b-%y")
    if isinstance(v, bool):
        return "Yes" if v else "No"
    if isinstance(v, float):
        return f"{v:g}"
    return CELLS.get(v, str(v)) if isinstance(v, str) and v in CELLS else str(v)


_LATIN = {"→": "->", "●": "*", "…": "...", "≥": ">=", "≤": "<=", "★": "*", "–": "-", "—": "-", "‘": "'", "’": "'", "“": '"', "”": '"'}


def safe(s: str) -> str:
    """The built-in PDF fonts cover Western European text; swap the few symbols that fall outside it."""
    for k, v in _LATIN.items():
        s = s.replace(k, v)
    return s.encode("latin-1", "replace").decode("latin-1")


# ------------------------------------------------------------------ Excel
def as_text(cell) -> None:
    """Text typed by a person (a task title, a remark) must never run as a spreadsheet formula when the file is opened."""
    if isinstance(cell.value, str) and cell.value[:1] in ("=", "+", "-", "@"):
        cell.data_type = "s"


def to_xlsx(r: Report) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Summary"
    ws["A1"], ws["A2"] = r.title, r.subtitle
    ws["A1"].font = Font(bold=True, size=14, color="0B1F4B")
    ws["A2"].font = Font(color="64748B")
    row = 4
    for label, value in r.kpis:
        ws.cell(row, 1, label).font = Font(bold=True)
        ws.cell(row, 2, value).alignment = Alignment(horizontal="left")
        row += 1
    row += 1
    ws.cell(row, 1, "About this report").font = Font(bold=True)
    for n in r.notes:
        row += 1
        ws.cell(row, 1, n).alignment = Alignment(wrap_text=True, vertical="top")
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=6)
        ws.row_dimensions[row].height = 30
    ws.column_dimensions["A"].width = 34
    ws.column_dimensions["B"].width = 26
    for t in r.tables:
        sh = wb.create_sheet(_sheet_name(wb, t.title))
        sh.append(t.columns)
        for c in sh[1]:
            c.font, c.fill, c.alignment = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="1E3A8A"), Alignment(wrap_text=True, vertical="center")
        for rr in t.rows:
            sh.append([CELLS.get(v, v) if isinstance(v, str) and v in CELLS else v for v in rr])
        for rr in sh.iter_rows(min_row=2):
            for c in rr:
                as_text(c)
        for i, col in enumerate(t.columns, 1):
            vals = [len(show(x[i - 1])) for x in t.rows[:200] if i - 1 < len(x)]
            sh.column_dimensions[get_column_letter(i)].width = min(60, max(10, len(col) + 2, *(vals or [0])))
        for rr in sh.iter_rows(min_row=2):
            for c in rr:
                if isinstance(c.value, (date, datetime)):
                    c.number_format = "dd-mmm-yy"
                c.alignment = Alignment(wrap_text=True, vertical="top")
        sh.freeze_panes = "A2"
        if t.rows:
            sh.auto_filter.ref = sh.dimensions
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _sheet_name(wb: Workbook, title: str) -> str:
    base = "".join(ch for ch in title if ch not in '[]:*?/\\')[:28] or "Sheet"
    name, n = base, 2
    while name in wb.sheetnames:
        name, n = f"{base[:25]} {n}", n + 1
    return name


# ------------------------------------------------------------------ PDF
def _gantt(rows: list[dict], as_of: str, width: float) -> Drawing:
    label_w, row_h, head = 175.0, 11.0, 24.0
    starts = [date.fromisoformat(x["start"]) for x in rows if x["start"]]
    ends = [date.fromisoformat(x["end"]) for x in rows if x["end"]]
    d = Drawing(width, head + row_h * len(rows) + 4)
    if not starts:
        d.add(String(0, 4, "No dated items to draw.", fontSize=8))
        return d
    today = date.fromisoformat(as_of)
    lo, hi = min(starts + [today]), max(ends + [today])
    lo = date(lo.year, lo.month, 1)
    hi = date(hi.year + (hi.month == 12), (hi.month % 12) + 1, 1)
    bw, total = width - label_w - 4, (hi - lo).days
    xs = lambda dt: label_w + (dt - lo).days / total * bw  # noqa: E731
    H = d.height
    m = lo
    while m < hi:
        nxt = date(m.year + (m.month == 12), (m.month % 12) + 1, 1)
        if m.month in (1, 4, 7, 10) or m == lo:
            qend = m
            for _ in range(3):
                qend = date(qend.year + (qend.month == 12), (qend.month % 12) + 1, 1)
                if qend >= hi or qend.month in (1, 4, 7, 10):
                    break
            d.add(Rect(xs(m), H - 11, xs(min(qend, hi)) - xs(m), 10, fillColor=colors.HexColor(NAVY), strokeColor=colors.white, strokeWidth=0.3))
            d.add(String(xs(m) + 2, H - 9, f"Q{(m.month - 1) // 3 + 1} {m.year}", fontSize=6, fillColor=colors.white))
        d.add(String((xs(m) + xs(nxt)) / 2, H - 21, "JFMAMJJASOND"[m.month - 1], fontSize=6, fillColor=colors.HexColor("#64748B"), textAnchor="middle"))
        d.add(Line(xs(m), 0, xs(m), H - 12, strokeColor=colors.HexColor("#E2E8F0"), strokeWidth=0.3))
        m = nxt
    for i, r in enumerate(rows):
        y = H - head - (i + 1) * row_h
        name = f"{r['label']} ({r['area']})" if r.get("kind") == "events" else r["label"]  # tracker rows are per product
        d.add(String(0, y + 3, safe(name)[:46], fontSize=6.5, fillColor=colors.HexColor("#1E293B")))
        if r["start"] and r["end"]:
            s, e = xs(date.fromisoformat(r["start"])), max(xs(date.fromisoformat(r["end"])), xs(date.fromisoformat(r["start"])) + 2)
            col = colors.HexColor(STATE[r["state"]])
            d.add(Rect(s, y + 2, e - s, row_h - 5, fillColor=colors.Color(col.red, col.green, col.blue, alpha=0.3), strokeColor=col, strokeWidth=0.4))
            if r["pct"]:
                d.add(Rect(s, y + 2, (e - s) * min(r["pct"], 100) / 100, row_h - 5, fillColor=col, strokeColor=None))
    d.add(Line(xs(today), 0, xs(today), H - 12, strokeColor=colors.HexColor(RED), strokeWidth=1))
    return d


def to_pdf(r: Report) -> bytes:
    buf = io.BytesIO()
    page = landscape(A4)
    doc = SimpleDocTemplate(buf, pagesize=page, leftMargin=12 * mm, rightMargin=12 * mm, topMargin=12 * mm, bottomMargin=14 * mm, title=safe(r.title), author="WFX PMO", pageCompression=0)
    ss = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=ss["Title"], fontName="Helvetica-Bold", fontSize=18, textColor=colors.HexColor(NAVY), alignment=0, spaceAfter=2)
    sub = ParagraphStyle("sub", parent=ss["Normal"], fontSize=9, textColor=colors.HexColor("#64748B"), spaceAfter=8)
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], fontName="Helvetica-Bold", fontSize=11, textColor=colors.HexColor(NAVY), spaceBefore=10, spaceAfter=4)
    small = ParagraphStyle("small", parent=ss["Normal"], fontSize=7, leading=8.6)
    note = ParagraphStyle("note", parent=ss["Normal"], fontSize=7.5, textColor=colors.HexColor("#475569"), leading=9.5)
    W = page[0] - 24 * mm
    story: list = [Paragraph(escape(safe(r.title)), h1), Paragraph(escape(safe(r.subtitle)), sub)]
    if r.kpis:
        n = len(r.kpis)
        cells = [[Paragraph(f'<font size="15" color="{NAVY}"><b>{escape(safe(v))}</b></font>', ParagraphStyle("k", alignment=1, leading=18)) for _, v in r.kpis],
                 [Paragraph(f'<font size="7" color="#64748B">{escape(safe(l))}</font>', ParagraphStyle("kl", alignment=1, leading=8)) for l, _ in r.kpis]]
        t = RLTable(cells, colWidths=[W / n] * n)
        t.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")), ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")), ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F1F5F9")),
                               ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4), ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
        story += [t, Spacer(1, 6)]
    if r.gantt:
        story.append(Paragraph("Timeline", h2))
        for i in range(0, len(r.gantt), 26):
            story += [_gantt(r.gantt[i : i + 26], r.as_of, W), Spacer(1, 4)]
        story.append(Paragraph('<font size="7" color="#64748B">Fill = % done. Green = done, amber = in progress, red = overdue, grey = upcoming. The red line is the report date.</font>', note))
    for tb in r.tables:
        if not tb.rows and tb.title not in ("Needs attention",):
            continue
        story.append(Paragraph(escape(safe(tb.title)) + f' <font size="8" color="#64748B">({len(tb.rows)})</font>', h2))
        story.append(_pdf_table(tb, W, small))
    story.append(Spacer(1, 8))
    for n in r.notes:
        story.append(Paragraph(escape(safe(n)), note))

    def foot(canvas, d):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(colors.HexColor("#64748B"))
        canvas.drawString(12 * mm, 8 * mm, safe(f"WFX PMO · {r.project['code']} · {r.title} · report date {date.fromisoformat(r.as_of).strftime('%d-%b-%Y')}"))
        canvas.drawRightString(page[0] - 12 * mm, 8 * mm, f"Page {d.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=foot, onLaterPages=foot)
    return buf.getvalue()


def _pdf_table(tb: Table, W: float, style: ParagraphStyle) -> RLTable:
    if not tb.rows:
        return RLTable([[Paragraph("Nothing to show.", style)]])
    n = len(tb.columns)
    weights = [max(len(c) + 4, min(40, max([len(c)] + [len(show(r[i])) for r in tb.rows[:60] if i < len(r)]))) for i, c in enumerate(tb.columns)]
    total = sum(weights)
    widths = [W * w / total for w in weights]
    head = ParagraphStyle("th", parent=style, textColor=colors.white, fontName="Helvetica-Bold")
    data = [[Paragraph(escape(safe(c)), head) for c in tb.columns]] + [[Paragraph(escape(safe(show(v))), style) for v in (row + [None] * n)[:n]] for row in tb.rows]
    t = RLTable(data, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(BLUE)), ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
                           ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#CBD5E1")), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                           ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3)]))
    return t


# ------------------------------------------------------------------ PowerPoint
MAX_PPT_ROWS = 150


def to_pptx(r: Report) -> bytes:
    """Reports that have a status-slide layout (overall, product, next week) use it as is; the others get table slides in the same style.
    The timeline report puts the phase bars first, then the task tables."""
    payload = r.payload and {**r.payload, "meta": r.payload}
    if r.pptx_kind == "overall":
        prs = px.overall_slides(payload)
        tables = [t for t in r.tables if r.key == "timeline" and t.title != "Phases"]
    elif r.pptx_kind == "product":
        prs = px.product_slide(payload)
        tables = []
    elif r.pptx_kind == "next_week":
        prs = px.week_slides(payload)
        tables = []
    else:
        prs = px.prs_new()
        tables = r.tables
    for t in tables:
        _table_slides(prs, r, t)
    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()


def _table_slides(prs, r: Report, t: Table) -> None:
    rows = t.rows[:MAX_PPT_ROWS]
    per = 13
    pages = [rows[i : i + per] for i in range(0, max(1, len(rows)), per)] or [[]]
    for n, chunk in enumerate(pages):
        s = prs.slides.add_slide(prs.slide_layouts[6])
        name = r.title if (t.title == r.title or len(r.tables) == 1) else f"{r.title}: {t.title}"
        px.header(s, name + (f" ({n + 1}/{len(pages)})" if len(pages) > 1 else ""), r.subtitle)
        if n == 0 and r.kpis:
            px.kpi_strip(s, [(v, l, px.NAVY) for l, v in r.kpis[:7]], y=0.95, w=min(1.75, 12.4 / max(1, len(r.kpis[:7])) - 0.1))
        top = 2.0 if (n == 0 and r.kpis) else 1.0
        if not chunk:
            px.text(s, 0.35, top, 12, 0.4, "Nothing to show.", 12, False, px.GREY)
        else:
            cols = len(t.columns)
            weights = [max(len(c) + 3, min(34, max([len(c)] + [len(show(x[i])) for x in rows[:40] if i < len(x)]))) for i, c in enumerate(t.columns)]
            tot = sum(weights)
            shape = s.shapes.add_table(len(chunk) + 1, cols, Inches(0.35), Inches(top), Inches(12.6), Inches(0.3 * (len(chunk) + 1)))
            tbl = shape.table
            for i, w in enumerate(weights):
                tbl.columns[i].width = Inches(12.6 * w / tot)
            for i, c in enumerate(t.columns):
                cell = tbl.cell(0, i)
                cell.text = px.clip(c, 28)
                cell.fill.solid()
                cell.fill.fore_color.rgb = px.BLUE
                para = cell.text_frame.paragraphs[0]
                para.runs[0].font.size, para.runs[0].font.bold, para.runs[0].font.color.rgb = Pt(8), True, px.WHITE
            for ri, row in enumerate(chunk, 1):
                for ci in range(cols):
                    cell = tbl.cell(ri, ci)
                    cell.text = px.clip(show(row[ci]) if ci < len(row) else "", 70)
                    cell.fill.solid()
                    cell.fill.fore_color.rgb = px.WHITE if ri % 2 else px.LIGHT
                    cell.text_frame.paragraphs[0].alignment = PP_ALIGN.LEFT
                    for run in cell.text_frame.paragraphs[0].runs:
                        run.font.size, run.font.color.rgb = Pt(7.5), px.INK
        extra = f"{len(t.rows) - MAX_PPT_ROWS} more rows are in the Excel export. " if len(t.rows) > MAX_PPT_ROWS and n == len(pages) - 1 else ""
        px.text(s, 0.35, 7.05, 12.6, 0.3, px.clip(extra + (r.notes[0] if r.notes else ""), 220) + f" · Report date {px.fmt(r.as_of)}", 7, False, px.GREY)
