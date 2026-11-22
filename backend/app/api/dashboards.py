"""Dashboard data (JSON) and PowerPoint export. All numbers come from app.modules.dashboards.metrics."""
import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.core.audit import write_audit
from app.core.deps import ensure_project_access, get_db, require
from app.models import Product, Project, User
from app.modules.dashboards import export_pptx, export_reports, export_xlsx, metrics, reports, trackers

router = APIRouter()
PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"


def _snap(db: Session, user: User, project_id: uuid.UUID, as_of: date | None) -> metrics.Snapshot:
    ensure_project_access(db, user, project_id)
    p = db.get(Project, project_id)
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    return metrics.load(db, p, as_of or date.today())


def _build(db: Session, user: User, project_id: uuid.UUID, kind: str, as_of: date | None, product_id: uuid.UUID | None, period: str) -> dict:
    snap = _snap(db, user, project_id, as_of)
    if kind == "overall":
        return metrics.overall(snap)
    if kind == "product":
        if product_id is None or product_id not in snap.products:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Product not found")
        return metrics.product_view(snap, product_id)
    if kind == "next_week":
        return metrics.next_week(snap, period)
    if kind == "delays":
        return metrics.delays(snap)
    raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown dashboard")


@router.get("/{project_id}/dashboards/overall")
def overall(project_id: uuid.UUID, as_of: date | None = None, db: Session = Depends(get_db), user: User = Depends(require("projects:read"))):
    return _build(db, user, project_id, "overall", as_of, None, "")


@router.get("/{project_id}/dashboards/product/{product_id}")
def product(project_id: uuid.UUID, product_id: uuid.UUID, as_of: date | None = None, db: Session = Depends(get_db), user: User = Depends(require("projects:read"))):
    return _build(db, user, project_id, "product", as_of, product_id, "")


@router.get("/{project_id}/dashboards/next-week")
def next_week(project_id: uuid.UUID, as_of: date | None = None, period: str = Query("next_week", pattern="^(this_week|next_week|next_month)$"),
              db: Session = Depends(get_db), user: User = Depends(require("projects:read"))):
    return _build(db, user, project_id, "next_week", as_of, None, period)


SORTS = {"current": "current_finish", "original": "original_finish", "days_late": "days_late", "title": "title", "owner": "owner", "phase": "phase", "product": "product"}


@router.get("/{project_id}/dashboards/drilldown/{metric}")
def drilldown(project_id: uuid.UUID, metric: str, as_of: date | None = None, product_id: uuid.UUID | None = None, phase_id: uuid.UUID | None = None,
              owner: str | None = None, q: str | None = None, sort: str = Query("days_late", pattern="^(current|original|days_late|title|owner|phase|product)$"),
              direction: str = Query("desc", pattern="^(asc|desc)$"), page: int = Query(1, ge=1), size: int = Query(25, ge=1, le=100),
              db: Session = Depends(get_db), user: User = Depends(require("projects:read"))):
    """The records behind a KPI tile. Same predicate as the tile (metrics.ACTIVITY_METRICS), so the list length always equals the number shown."""
    if metric == "phases":
        snap = _snap(db, user, project_id, as_of)
        rows = metrics.overall(snap)["rows"]
        return {"metric": "phases", "label": "Phases", "rule": "Plan phases and tracker-milestone groups with their calculated state", "total": len(rows), "page": 1, "size": len(rows),
                "as_of": snap.as_of.isoformat(), "items": [{k: r[k] for k in ("label", "area", "state", "pct", "start", "end", "items", "done", "late_items")} for r in rows]}
    if metric not in metrics.ACTIVITY_METRICS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown KPI")
    snap = _snap(db, user, project_id, as_of)
    if product_id is not None and product_id not in snap.products:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Product not found")
    rows = metrics.drilldown_rows(snap, metric, product_id)
    grand = len(rows)
    if phase_id:
        rows = [r for r in rows if r["phase_id"] == phase_id]
    if owner:
        rows = [r for r in rows if owner.lower() in f"{r['owner'] or ''} {r['responsible'] or ''}".lower()]
    if q:
        rows = [r for r in rows if q.lower() in r["title"].lower()]
    key = SORTS[sort]
    present = [r for r in rows if r[key] is not None]
    missing = [r for r in rows if r[key] is None]
    present.sort(key=lambda r: (str(r[key]).lower() if isinstance(r[key], str) else r[key]), reverse=direction == "desc")
    rows = present + missing  # rows without a value always sort last
    label, rule, _ = metrics.ACTIVITY_METRICS[metric]
    return {"metric": metric, "label": label, "rule": rule, "total": len(rows), "unfiltered_total": grand, "page": page, "size": size, "as_of": snap.as_of.isoformat(),
            "grace_days": snap.grace, "items": jsonable_encoder(rows[(page - 1) * size : page * size])}


@router.get("/{project_id}/dashboards/coverage")
def coverage(project_id: uuid.UUID, product_id: uuid.UUID | None = None, db: Session = Depends(get_db), user: User = Depends(require("projects:read"))):
    """Department x location coverage, calculated from the coverage activities (never typed in)."""
    ensure_project_access(db, user, project_id)
    p = db.get(Project, project_id)
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    return metrics.coverage(db, p, product_id)


@router.get("/{project_id}/uat/summary")
def uat_summary(project_id: uuid.UUID, as_of: date | None = None, product_id: uuid.UUID | None = None, db: Session = Depends(get_db), user: User = Depends(require("projects:read"))):
    ensure_project_access(db, user, project_id)
    return trackers.uat_summary(db, db.get(Project, project_id), as_of or date.today(), product_id)


@router.get("/{project_id}/deliverables/summary")
def deliverables_summary(project_id: uuid.UUID, as_of: date | None = None, product_id: uuid.UUID | None = None, db: Session = Depends(get_db), user: User = Depends(require("projects:read"))):
    ensure_project_access(db, user, project_id)
    return trackers.deliverables_summary(db, db.get(Project, project_id), as_of or date.today(), product_id)


@router.get("/{project_id}/dashboards/delays")
def delays(project_id: uuid.UUID, as_of: date | None = None, db: Session = Depends(get_db), user: User = Depends(require("projects:read"))):
    return _build(db, user, project_id, "delays", as_of, None, "")


@router.get("/{project_id}/dashboard-exports/{kind}")
def export(project_id: uuid.UUID, kind: str, as_of: date | None = None, product_id: uuid.UUID | None = None,
           period: str = Query("next_week", pattern="^(this_week|next_week|next_month)$"), fmt: str = Query("pptx", alias="format", pattern="^(pptx|xlsx)$"),
           db: Session = Depends(get_db), user: User = Depends(require("projects:read", "dashboards:export"))):
    kind = kind.replace("-", "_")
    if kind not in ("overall", "product", "next_week", "delays"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown dashboard")
    if fmt == "xlsx" and kind != "next_week":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Excel export is available for the week plan")
    payload = _build(db, user, project_id, kind, as_of, product_id, period)
    if fmt == "xlsx":
        data = export_xlsx.week_plan(payload)
        write_audit(db, user, "export", "dashboard", project_id, after={"kind": kind, "format": "xlsx", "as_of": payload["as_of"], "bytes": len(data)})
        db.commit()
        return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": f'attachment; filename="{payload["project"]["code"]}-{kind}-{payload["as_of"]}.xlsx"'})
    data = export_pptx.build(kind, payload)
    write_audit(db, user, "export", "dashboard", project_id, after={"kind": kind, "as_of": payload["as_of"], "bytes": len(data)})
    db.commit()
    name = f"{payload['project']['code']}-{kind}-{payload['as_of']}.pptx"
    return Response(data, media_type=PPTX, headers={"Content-Disposition": f'attachment; filename="{name}"'})


# ------------------------------------------------------------------ the eight management reports (Excel, PDF, PowerPoint)
EXPORT_TYPES = {"xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", export_reports.to_xlsx), "pdf": ("application/pdf", export_reports.to_pdf),
                "pptx": (PPTX, export_reports.to_pptx)}


@router.get("/{project_id}/exports")
def export_catalogue(project_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require("projects:read"))):
    ensure_project_access(db, user, project_id)
    return reports.catalogue()


@router.get("/{project_id}/exports/{report}")
def export_report(project_id: uuid.UUID, report: str, fmt: str = Query("pdf", alias="format", pattern="^(xlsx|pdf|pptx)$"), as_of: date | None = None, product_id: uuid.UUID | None = None,
                  period: str = Query("next_week", pattern="^(this_week|next_week|next_month)$"),
                  db: Session = Depends(get_db), user: User = Depends(require("projects:read", "dashboards:export"))):
    """One report in one format, built from the same numbers as the dashboards. Every export is written to the audit log."""
    ensure_project_access(db, user, project_id)
    p = db.get(Project, project_id)
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    r = reports.build(db, p, report.replace("-", "_"), as_of or date.today(), product_id, period)
    ctype, render = EXPORT_TYPES[fmt]
    data = render(r)
    write_audit(db, user, "export", "report", project_id, after={"report": r.key, "format": fmt, "as_of": r.as_of, "bytes": len(data)})
    db.commit()
    return Response(data, media_type=ctype, headers={"Content-Disposition": f'attachment; filename="{r.project["code"]}-{r.key}-{r.as_of}.{fmt}"'})
