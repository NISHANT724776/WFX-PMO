"""Excel export of the week plan, from the same payload as the screen and the PowerPoint."""
import io

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

TAGS = {"due": "Due", "starts": "Starts", "planned": "Planned", "carry_over": "Overdue carry-over"}


def week_plan(p: dict) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Week plan"
    w = p["week"]
    ws.append([f"{p['project']['name']}: {w['label']} plan"])
    ws.append([f"{w['start']} to {w['end']} (weeks run Monday to Sunday) · report date {p['as_of']}"])
    ws["A1"].font = Font(bold=True, size=13)
    ws.append([])
    head = ["#", "Workstream", "Activity", "Detail", "Owner", "Responsibility", "Type", "Due / target", "Days late", "Status", "% complete"]
    ws.append(head)
    for c in ws[4]:
        c.font, c.fill = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="1E3A8A")
    for g in p["groups"]:
        for c in g["cards"]:
            ws.append([c["seq"], g["name"], c["title"], c["description"], c["owner"], c["responsibility"], TAGS.get(c["tag"], c["tag"]), c["due"], c["days_late"] or None,
                       {"planned": "Planned", "in_progress": "In progress", "done": "Done"}.get(c.get("plan_status") or "", None), c.get("percent_complete")])
    for row in ws.iter_rows(min_row=5):
        for c in row:
            if isinstance(c.value, str) and c.value[:1] in ("=", "+", "-", "@"):
                c.data_type = "s"  # typed text never runs as a formula
    for i, width in enumerate([5, 22, 52, 46, 20, 18, 18, 13, 10, 12, 11], 1):
        ws.column_dimensions[get_column_letter(i)].width = width
    for row in ws.iter_rows(min_row=5):
        row[2].alignment = row[3].alignment = Alignment(wrap_text=True, vertical="top")
    ws.freeze_panes = "A5"
    ws.append([])
    ws.append([f"{p['total_cards']} activities. " + (p.get("notes") or [""])[0]])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
