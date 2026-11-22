"""PowerPoint export built from the SAME payload the web dashboards use (no separate calculations)."""
import io
from datetime import date, timedelta
from typing import Any

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches, Pt

NAVY, BLUE, GREEN, AMBER, RED, GREY, LIGHT, INK = (RGBColor.from_string(c) for c in ("0B1F4B", "1E3A8A", "16A34A", "D97706", "DC2626", "94A3B8", "F1F5F9", "1E293B"))
WHITE = RGBColor(255, 255, 255)
STATE_COLOR = {"done": GREEN, "in_progress": AMBER, "overdue": RED, "upcoming": GREY}
GATE_COLOR = {"done": GREEN, "overdue": RED, "due": AMBER, "planned": GREY}
MONTHS = "JFMAMJJASOND"
ROWS_PER_SLIDE = 30


def _d(s: str | None) -> date | None:
    return date.fromisoformat(s) if s else None


def clip(s: Any, n: int) -> str:
    s = " ".join(str(s or "").split())
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def span(a: str, b: str) -> str:
    da, db = _d(a), _d(b)
    f = "%b %y" if da.year != db.year else "%b"
    return f"{da.strftime(f)} - {db.strftime(f)}"


def fmt(s: str | None) -> str:
    d = _d(s)
    return d.strftime("%d-%b-%y") if d else "–"


def prs_new() -> Presentation:
    p = Presentation()
    p.slide_width, p.slide_height = Inches(13.333), Inches(7.5)
    return p


def text(slide, x, y, w, h, s, size=10, bold=False, color=INK, align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.MIDDLE):
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = Inches(0.03)
    tf.margin_top = tf.margin_bottom = Inches(0.01)
    tf.vertical_anchor = anchor
    p = tf.paragraphs[0]
    p.alignment = align
    r = p.add_run()
    r.text = str(s)
    r.font.size, r.font.bold, r.font.color.rgb = Pt(size), bold, color
    return tb


def rect(slide, x, y, w, h, fill=None, line=None, shape=MSO_SHAPE.RECTANGLE):
    sh = slide.shapes.add_shape(shape, Inches(x), Inches(y), Inches(max(w, 0.01)), Inches(h))
    if fill is None:
        sh.fill.background()
    else:
        sh.fill.solid()
        sh.fill.fore_color.rgb = fill
    if line is None:
        sh.line.fill.background()
    else:
        sh.line.color.rgb = line
        sh.line.width = Pt(1)
    sh.shadow.inherit = False
    return sh


def header(slide, title: str, sub: str) -> None:
    text(slide, 0.35, 0.18, 8.0, 0.4, title, 20, True, NAVY)
    text(slide, 0.35, 0.58, 12.5, 0.3, sub, 10, False, GREY)


def kpi_strip(slide, items: list[tuple[str, str, RGBColor]], x=0.35, y=0.95, w=1.55) -> None:
    for i, (val, lab, col) in enumerate(items):
        xx = x + i * (w + 0.1)
        rect(slide, xx, y, w, 0.85, LIGHT, RGBColor(203, 213, 225))
        text(slide, xx, y + 0.04, w, 0.45, val, 20, True, col, PP_ALIGN.CENTER)
        text(slide, xx, y + 0.5, w, 0.32, lab, 8, False, GREY, PP_ALIGN.CENTER)


def footer(slide, p: dict, extra: str = "") -> None:
    m = p["meta"] if "meta" in p else p
    y = 7.08
    for i, (c, lab) in enumerate(((GREEN, "Completed"), (AMBER, "In progress (fill = % done)"), (RED, "Overdue / planned start passed"), (GREY, "Upcoming"))):
        rect(slide, 0.35 + i * 2.1, y + 0.08, 0.22, 0.12, c)
        text(slide, 0.6 + i * 2.1, y, 1.85, 0.28, lab, 8, False, GREY)
    text(slide, 0.35, y + 0.27, 12.6, 0.2, f"% = {m['formulas']['completion']} · Source: imported plan and trackers · Report date {fmt(m['as_of'])} · {extra}", 7, False, GREY)


def timeline(slide, rows: list[dict], x: float, y: float, w: float, as_of: str, label_w: float = 2.7, status_w: float = 1.0, row_h: float = 0.168) -> None:
    starts = [_d(r["start"]) for r in rows if r["start"]]
    ends = [_d(r["end"]) for r in rows if r["end"]]
    if not starts:
        text(slide, x, y, w, 0.3, "No dated items to draw.", 10, False, GREY)
        return
    lo, hi = min(starts + [_d(as_of)]), max(ends + [_d(as_of)])
    lo = date(lo.year, lo.month, 1)
    hi = date(hi.year + (hi.month == 12), (hi.month % 12) + 1, 1)
    bar_w = w - label_w - status_w
    total = (hi - lo).days
    px = lambda d: x + label_w + (d - lo).days / total * bar_w  # noqa: E731
    text(slide, x, y, label_w, 0.22, "Phase", 8, True, NAVY)
    text(slide, x + w - status_w, y, status_w, 0.22, "Status", 8, True, NAVY, PP_ALIGN.CENTER)
    d = lo
    while d < hi:
        nxt = date(d.year + (d.month == 12), (d.month % 12) + 1, 1)
        x0, x1 = px(d), px(nxt)
        if d.month in (1, 4, 7, 10) or d == lo:
            qend = d
            for _ in range(3):
                qend = date(qend.year + (qend.month == 12), (qend.month % 12) + 1, 1)
                if qend >= hi or qend.month in (1, 4, 7, 10):
                    break
            q = rect(slide, x0, y - 0.02, min(px(min(qend, hi)), x + label_w + bar_w) - x0, 0.15, NAVY)
            if x + label_w + bar_w - x0 >= 0.5:  # no room for the label at the right edge: leave the band unlabeled
                text(slide, x0, y - 0.03, min(1.0, x + label_w + bar_w - x0), 0.17, f"Q{(d.month - 1) // 3 + 1} {d.year}", 7, True, WHITE)
        text(slide, x0, y + 0.13, x1 - x0, 0.14, MONTHS[d.month - 1], 7, False, GREY, PP_ALIGN.CENTER)
        d = nxt
    top = y + 0.3
    last_area = None
    for i, r in enumerate(rows):
        ry = top + i * row_h
        if r["area"] != last_area:
            text(slide, x, ry, 0.7, row_h, r["area"] if r["area"] != "Project-wide" else "ALL", 6, True, BLUE)
            last_area = r["area"]
        text(slide, x + 0.7, ry, label_w - 0.7, row_h, clip(r["label"], int((label_w - 0.7) * 17)), 7, False, INK)
        col = STATE_COLOR[r["state"]]
        if r["start"] and r["end"]:
            b0, b1 = px(_d(r["start"])), max(px(_d(r["end"])) , px(_d(r["start"])) + 0.05)
            rect(slide, b0, ry + 0.035, b1 - b0, row_h - 0.07, LIGHT if r["state"] == "in_progress" else col, col)
            if r["state"] == "in_progress":
                rect(slide, b0, ry + 0.035, (b1 - b0) * r["pct"] / 100, row_h - 0.07, AMBER)
            if b1 - b0 > 0.55:
                text(slide, b0, ry, b1 - b0, row_h, span(r["start"], r["end"]), 6, False, WHITE if r["state"] in ("done", "overdue", "upcoming") else INK, PP_ALIGN.CENTER)
        for st in r["stars"]:
            if st["date"]:
                text(slide, px(_d(st["date"])) - 0.08, ry - 0.01, 0.16, row_h, "★", 8, True, NAVY, PP_ALIGN.CENTER)
        label = "100% Done" if r["state"] == "done" else "Planned" if r["state"] == "upcoming" else f"{r['pct']}% · {'Overdue' if r['state'] == 'overdue' else 'In-Progress'}"
        text(slide, x + w - status_w, ry, status_w, row_h, label, 7, r["state"] == "overdue", RED if r["state"] == "overdue" else INK, PP_ALIGN.CENTER)
    tx = px(_d(as_of))
    ln = rect(slide, tx - 0.01, top - 0.05, 0.02, len(rows) * row_h + 0.05, RED)
    text(slide, tx - 0.3, top + len(rows) * row_h, 0.6, 0.16, "Today", 7, True, RED, PP_ALIGN.CENTER)


def overall_slides(p: dict) -> Presentation:
    prs = prs_new()
    rows = p["rows"]
    chunks = [rows[i : i + ROWS_PER_SLIDE] for i in range(0, max(1, len(rows)), ROWS_PER_SLIDE)] or [[]]
    for n, chunk in enumerate(chunks):
        s = prs.slides.add_slide(prs.slide_layouts[6])
        header(s, f"{p['project']['customer'] or p['project']['name']}  ·  Project Status" + (f" ({n + 1}/{len(chunks)})" if len(chunks) > 1 else ""),
               f"{p['project']['name']}  ·  Status as of {fmt(p['as_of'])}")
        k = p["kpis"]
        ov = k["overall"]
        kpi_strip(s, [(f"{ov['pct_display']}%" if ov["pct_display"] is not None else "n/a", "OVERALL", NAVY), (str(k["completed"]["value"]), "COMPLETED", GREEN),
                      (str(k["in_progress"]["value"]), "IN PROGRESS", AMBER), (str(k["overdue"]["value"]), "OVERDUE PHASES", RED), (str(k["upcoming"]["value"]), "UPCOMING", GREY)], x=5.0, y=0.12, w=1.5)
        timeline(s, chunk, 0.35, 1.05, 12.6, p["as_of"])
        footer(s, p)
    return prs


def product_slide(p: dict) -> Presentation:
    prs = prs_new()
    s = prs.slides.add_slide(prs.slide_layouts[6])
    prod = p["product"]
    header(s, f"{prod['code']}  —  Coverage & Status", f"{prod['name']}  ·  {p['project']['customer'] or ''}  ·  Status as of {fmt(p['as_of'])}")
    k = p["kpis"]
    ov = k["overall"]
    ng = k["next_gate"]
    kpi_strip(s, [(f"{ov['pct_display']}%" if ov["pct_display"] is not None else "n/a", "Overall completion", NAVY), (f"{k['items']['done']} / {k['items']['total']}", "Plan tasks + tracker events done", BLUE),
                  (str(k["late"]["value"]), "Items overdue / start delayed", RED if k["late"]["value"] else GREEN), (fmt(ng["planned"]) if ng else "–", f"Next gate: {clip(ng['name'], 46)}" if ng else "Next gate: none upcoming", AMBER),
                  (fmt(k["go_live"]), "Go-Live", NAVY)], y=0.95, w=1.62)
    timeline(s, p["rows"][:22], 0.35, 2.0, 8.4, p["as_of"], label_w=2.6, status_w=0.95, row_h=0.2)
    gx = 8.95
    text(s, gx, 1.95, 4.0, 0.25, "Sign-Off Gate Tracker", 11, True, NAVY)
    for i, g in enumerate(p["gates"][:9]):
        gy = 2.22 + i * 0.36
        rect(s, gx, gy, 4.0, 0.33, LIGHT)
        text(s, gx + 0.05, gy, 2.7, 0.17, g["name"][:44], 7, True, INK)
        plan = f" (plan {_d(g['planned']).strftime('%d-%b')})" if g["actual"] and g["actual"] != g["planned"] else ""
        text(s, gx + 0.05, gy + 0.16, 2.8, 0.16, f"{fmt(g['actual'] or g['planned'])}{plan}", 7, False, GREY)
        chip = rect(s, gx + 3.1, gy + 0.06, 0.8, 0.21, GATE_COLOR[g["state"]], None, MSO_SHAPE.ROUNDED_RECTANGLE)
        text(s, gx + 3.1, gy + 0.06, 0.8, 0.21, {"done": "Done", "overdue": "Overdue", "due": "Due", "planned": "Planned"}[g["state"]], 7, True, WHITE, PP_ALIGN.CENTER)
    ay = 2.22 + min(len(p["gates"]), 9) * 0.36 + 0.1
    text(s, gx, ay, 4.0, 0.25, "Needs attention", 11, True, RED)
    for i, a in enumerate(p["needs_attention"][:6]):
        text(s, gx, ay + 0.27 + i * 0.3, 4.0, 0.3, "• " + a["text"][:120], 7, False, INK, anchor=MSO_ANCHOR.TOP)
    footer(s, p, p["notes"][0] if p.get("notes") else "")
    return prs


def week_slides(p: dict) -> Presentation:
    prs = prs_new()
    groups = p["groups"] or []
    pages = [groups[i : i + 4] for i in range(0, max(1, len(groups)), 4)] or [[]]
    for n, page in enumerate(pages):
        s = prs.slides.add_slide(prs.slide_layouts[6])
        w = p["week"]
        header(s, f"{p['week']['label']}  —  Plan", f"{p['project']['name']}  ·  {fmt(w['start'])} – {fmt(w['end'])}  ·  report date {fmt(p['as_of'])}")
        rect(s, 10.1, 0.2, 2.9, 0.45, NAVY, None, MSO_SHAPE.ROUNDED_RECTANGLE)
        text(s, 10.1, 0.2, 2.9, 0.45, f"{fmt(w['start'])} – {fmt(w['end'])}", 12, True, WHITE, PP_ALIGN.CENTER)
        colw = 3.05
        for gi, g in enumerate(page):
            gx = 0.35 + gi * (colw + 0.1)
            rect(s, gx, 1.0, colw, 0.38, BLUE)
            text(s, gx + 0.05, 1.0, colw - 0.1, 0.38, f"{g['name']}  ·  {g['count']} activit{'y' if g['count'] == 1 else 'ies'}", 10, True, WHITE)
            for ci, c in enumerate(g["cards"][:7]):
                cy = 1.45 + ci * 0.78
                rect(s, gx, cy, colw, 0.74, WHITE, RGBColor(203, 213, 225))
                rect(s, gx + 0.05, cy + 0.07, 0.3, 0.3, RED if c["tag"] == "carry_over" else NAVY, None, MSO_SHAPE.OVAL)
                text(s, gx + 0.05, cy + 0.07, 0.3, 0.3, f"{c['seq']:02d}", 8, True, WHITE, PP_ALIGN.CENTER)
                text(s, gx + 0.4, cy + 0.02, colw - 0.45, 0.26, clip(c["title"], 40), 8, True, INK)
                text(s, gx + 0.4, cy + 0.27, colw - 0.45, 0.2, clip(c["description"], 46), 7, False, GREY, anchor=MSO_ANCHOR.TOP)
                tag = {"due": "Due", "starts": "Starts", "planned": "Planned", "carry_over": f"OVERDUE {c['days_late']} d · was due"}[c["tag"]]
                text(s, gx + 0.4, cy + 0.5, colw - 0.45, 0.22, clip(f"{tag} {fmt(c['due'])} · {c['owner'] or c['responsibility'] or ''}", 52), 7, c["tag"] == "carry_over", RED if c["tag"] == "carry_over" else BLUE)
            if len(g["cards"]) > 7:
                text(s, gx, 1.45 + 7 * 0.78, colw, 0.2, f"+ {len(g['cards']) - 7} more in the web view", 7, False, GREY)
        if not groups:
            text(s, 0.35, 1.2, 12, 0.4, "Nothing is due in this period.", 12, False, GREY)
        footer(s, p, "Cards sorted by due date; overdue carry-overs are labelled")
    return prs


def delay_slide(p: dict) -> Presentation:
    prs = prs_new()
    s = prs.slides.add_slide(prs.slide_layouts[6])
    header(s, "Delay Dashboard", f"{p['project']['name']}  ·  as of {fmt(p['as_of'])}  ·  grace {p['grace_days']} day(s)")
    kpi_strip(s, [(str(p["total"]), "Delayed items", RED if p["total"] else GREEN)] + [(str(x["count"]) if x["count"] is not None else "n/a", x["label"] + ("" if x["available"] else " (later)"), GREY if not x["available"] else NAVY) for x in p["sources"]], w=1.7)
    text(s, 0.35, 1.95, 4, 0.25, "Ageing (days late)", 10, True, NAVY)
    mx = max([a["count"] for a in p["ageing"]] + [1])
    for i, a in enumerate(p["ageing"]):
        rect(s, 1.3, 2.25 + i * 0.3, 3.0 * a["count"] / mx, 0.22, RED if i >= 3 else AMBER)
        text(s, 0.35, 2.25 + i * 0.3, 0.9, 0.22, a["bucket"] + " d", 8, False, INK)
        text(s, 1.35 + 3.0 * a["count"] / mx, 2.25 + i * 0.3, 0.6, 0.22, str(a["count"]), 8, True, INK)
    text(s, 5.0, 1.95, 3.5, 0.25, "By party", 10, True, NAVY)
    for i, b in enumerate(p["by_party"][:6]):
        text(s, 5.0, 2.25 + i * 0.3, 3.5, 0.25, f"{ {'wfx': 'WFX'}.get(b['party'], b['party'].title()) }: {b['count']}", 9, False, INK)
    text(s, 8.5, 1.95, 4.4, 0.25, "By product", 10, True, NAVY)
    for i, b in enumerate(p["by_product"][:6]):
        text(s, 8.5, 2.25 + i * 0.3, 4.4, 0.25, f"{b['name']}: {b['count']}", 9, False, INK)
    text(s, 0.35, 4.2, 12, 0.25, "Most delayed", 10, True, NAVY)
    for i, r in enumerate(p["rows"][:11]):
        y = 4.48 + i * 0.22
        text(s, 0.35, y, 5.8, 0.22, clip(r["title"], 96), 7, False, INK)
        text(s, 6.2, y, 1.6, 0.22, r["source"].replace("_", " "), 7, False, GREY)
        text(s, 7.8, y, 1.6, 0.22, clip(r["owner"], 26), 7, False, INK)
        text(s, 9.4, y, 1.4, 0.22, f"due {fmt(r['due'])}", 7, False, INK)
        text(s, 10.8, y, 1.0, 0.22, f"{r['days_late']} d late", 7, True, RED)
        if r["slippage"]:
            text(s, 11.8, y, 1.2, 0.22, f"+{r['slippage']} d vs plan", 7, False, AMBER)
    footer(s, p, "Slippage is measured against the baseline date; development delivery delays arrive with the delivery tracker")
    return prs


def build(kind: str, payload: dict) -> bytes:
    payload = {**payload, "meta": payload}  # footer() reads formulas/as_of from the payload itself
    prs = {"overall": overall_slides, "product": product_slide, "next_week": week_slides, "delays": delay_slide}[kind](payload)
    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()
