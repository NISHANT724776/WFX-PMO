"""Commit staged rows to canonical tables in ONE transaction, with provenance; rollback where safe."""
import itertools
import uuid
from collections import defaultdict
from datetime import date, datetime, timezone
from typing import Any

from fastapi.encoders import jsonable_encoder
from sqlalchemy import Date, inspect, select
from sqlalchemy.orm import Session

from app.core.audit import write_audit
from app.models import ImportBatch, ImportRowReference, Project, ProjectPhase, User
from app.models.canonical import CANONICAL, DateRevision, RequirementLink, WorkItem
from app.modules.excel_intel import service
from app.modules.excel_intel.catalog import AUTHORITY

MODES = ("create_only", "update")


class CommitError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


def _stamp(obj: Any) -> str:
    return obj.updated_at.replace(tzinfo=None).isoformat()


def to_model_values(entity: str, v: dict[str, Any]) -> dict[str, Any]:
    """Catalog field keys -> canonical column names. A status-type field X becomes X_raw (original text) + X_category."""
    skip = {"phase", "product_label", "owner", "location", "dependencies"} if entity in ("plan_task", "tracker_event") else set()
    out: dict[str, Any] = {}
    for k, val in v.items():
        if k.endswith("_category") or k in skip:
            continue
        if k + "_category" in v:
            out[k + "_raw"], out[k + "_category"] = val, v[k + "_category"]
        else:
            out[k] = val
    if entity == "plan_task":
        out.update(owner_name=v.get("owner"), location_label=v.get("location"), dependencies_text=v.get("dependencies"))
        if v.get("location_id"):
            out["location_id"] = uuid.UUID(v["location_id"])
        else:
            out.pop("location_id", None)
    if entity == "tracker_event":
        out["product_id"] = uuid.UUID(v["product_id"])
    return out


STAGE_ORDER = ("customer_release", "uat_release", "qa_release", "dev_completion")


def derive_delivery_target(obj: Any) -> None:
    """The delivery commitment is the first available stage date (customer UAT release, UAT release, QA release, dev completion).
    It is set once, as the baseline; later changes are approved revisions."""
    if obj.delivery_target_date is None:
        obj.delivery_target_date = next((getattr(obj, k) for k in STAGE_ORDER if getattr(obj, k) is not None), None)


def merge_delivery(obj: Any, entity: str, vals: dict[str, Any]) -> list[str]:
    """Second sheet for a ticket that already exists from the other sheet. Authoritative fields overwrite; all others only fill
    empty cells; where both sheets hold different values the existing one is kept and the disagreement is recorded."""
    auth = AUTHORITY[entity]
    notes = dict(obj.merge_notes or {})
    changed: list[str] = []
    for k, nv in vals.items():
        if k in ("sort_order", "sources", "merge_notes", "status_category", "helpdesk_status_category") or nv is None:
            continue
        if k == "specs_completed" and not nv:
            continue
        cur = getattr(obj, k, None)
        pair = [k] + ([k.replace("_raw", "_category")] if k.endswith("_raw") else [])
        if cur is None or k in auth:
            if cur != nv:
                for kk in pair:
                    if vals.get(kk) is not None or kk == k:
                        changed.append(kk)
                        setattr(obj, kk, vals.get(kk))
                if cur is not None:
                    notes[k] = {"kept": nv, "replaced": cur, "from": entity}
        elif cur != nv:
            notes[k] = {"kept": cur, "ignored": nv, "from": entity}
    obj.merge_notes = jsonable_encoder(notes) or None
    obj.sources = [*(obj.sources or []), entity]
    return changed


def _snapshot(obj: Any, keys: list[str]) -> dict:
    return jsonable_encoder({k: getattr(obj, k) for k in keys})


def apply_snapshot(obj: Any, snap: dict) -> None:
    cols = {c.key: c for c in inspect(obj).mapper.column_attrs}
    for k, val in snap.items():
        col = cols[k].columns[0]
        if val is not None and isinstance(col.type, Date):
            val = date.fromisoformat(val)
        elif val is not None and col.type.python_type is uuid.UUID:
            val = uuid.UUID(val)
        setattr(obj, k, val)


def commit(db: Session, batch: ImportBatch, user: User, project_id: uuid.UUID, mode: str,
           confirm_rejected: bool, template_name: str | None) -> dict:
    db.info["lifecycle"] = "all"  # imports match against archived and trashed records too, so nothing is duplicated or missed
    if mode not in MODES:
        raise CommitError(422, f"mode must be one of {MODES}")
    if batch.status != "ready":
        raise CommitError(409, f"Batch is '{batch.status}', only a ready batch can be committed")
    project = db.get(Project, project_id)
    if project is None:
        raise CommitError(422, "Unknown project")
    dup = db.scalar(select(ImportBatch).where(
        ImportBatch.sha256 == batch.sha256, ImportBatch.project_id == project_id,
        ImportBatch.status == "committed", ImportBatch.id != batch.id))
    if dup is not None:
        raise CommitError(409, f"This exact file was already imported into this project (batch {dup.id}). Roll that import back first if you need to re-import it.")

    validation = service.run_validation(db, batch)  # fresh, never trust a stale result
    if not validation["can_commit"]:
        raise CommitError(409, "Blocking problems remain; open the Validation step and resolve them first")
    total_rejected = sum(s.get("rejected_rows", 0) for s in validation["sheets"] if not s.get("skipped"))
    if total_rejected and not confirm_rejected:
        raise CommitError(409, f"{total_rejected} source row(s) are rejected and will NOT be imported. Review the error report and confirm to continue.")

    grids = service.load_grids(batch)
    now = datetime.now(timezone.utc)
    summary: list[dict] = []
    seq = itertools.count(1)
    try:
        order = sorted((s for s in batch.sheets if s.enabled and s.entity), key=lambda s: (s.entity != "plan_task", s.position))
        for sheet in order:
            res, _profile = service.process(db, sheet, grids[sheet.name])
            rejected = res.rejected_rows
            model = CANONICAL[sheet.entity]
            keys = [r.match_key for r in res.rows if r.source_row not in rejected]
            existing = {o.match_key: o for o in db.scalars(select(model).where(model.project_id == project_id, model.match_key.in_(keys)))} if keys else {}
            phases = {p.name: p for p in db.scalars(select(ProjectPhase).where(ProjectPhase.project_id == project_id))} if sheet.entity == "plan_task" else {}
            counts = {"created": 0, "updated": 0, "skipped": 0, "rejected": len(rejected)}
            for r in res.rows:
                if r.source_row in rejected:
                    continue
                vals = to_model_values(sheet.entity, r.values)
                if sheet.entity == "plan_task":
                    pname = r.values.get("phase")
                    if pname:
                        if pname not in phases:
                            phases[pname] = ProjectPhase(project_id=project_id, name=pname, sort_order=len(phases) + 1, import_batch_id=batch.id)
                            db.add(phases[pname])
                            db.flush()
                        vals["phase_id"] = phases[pname].id
                vals = {k: v for k, v in vals.items() if hasattr(model, k)}
                obj = existing.get(r.match_key)
                if obj is not None and sheet.entity in AUTHORITY and sheet.entity not in (obj.sources or []):
                    # the other delivery sheet already created this ticket: merge field by field (never overwrite blindly)
                    keys_before = list(vals) + ["sources", "merge_notes", "delivery_target_date"]
                    before = _snapshot(obj, keys_before)
                    changed = merge_delivery(obj, sheet.entity, vals)
                    derive_delivery_target(obj)
                    db.flush()
                    counts["updated"] += 1
                    counts["merged"] = counts.get("merged", 0) + 1
                    db.add(ImportRowReference(seq=next(seq), batch_id=batch.id, sheet_id=sheet.id, source_row=r.source_row, entity_type=sheet.entity,
                                              entity_id=obj.id, action="updated", before=before, row_stamp=_stamp(obj), raw=r.raw))
                    continue
                if obj is not None and mode == "create_only":
                    counts["skipped"] += 1
                    db.add(ImportRowReference(seq=next(seq), batch_id=batch.id, sheet_id=sheet.id, source_row=r.source_row, entity_type=sheet.entity,
                                              entity_id=obj.id, action="skipped", raw=r.raw))
                    continue
                if obj is not None:  # update: write only what changed, remember the old values
                    # update never ERASES: an empty cell in the new file keeps the existing value (e.g. formulas saved without a cached result)
                    changed = [k for k, nv in vals.items() if k != "sort_order" and nv is not None and getattr(obj, k, None) != nv]
                    before = _snapshot(obj, changed + (["delivery_target_date"] if sheet.entity in AUTHORITY else []))
                    for k in changed:
                        setattr(obj, k, vals[k])
                    if sheet.entity in AUTHORITY:
                        derive_delivery_target(obj)
                    obj.raw_values = r.raw_values or None
                    db.flush()
                    action = "updated" if changed else "skipped"
                    counts["updated" if changed else "skipped"] += 1
                    db.add(ImportRowReference(seq=next(seq), batch_id=batch.id, sheet_id=sheet.id, source_row=r.source_row, entity_type=sheet.entity,
                                              entity_id=obj.id, action=action, before=before if changed else None,
                                              row_stamp=_stamp(obj), raw=r.raw))
                    continue
                obj = model(project_id=project_id, match_key=r.match_key, raw_values=r.raw_values or None, import_batch_id=batch.id,
                            **vals)
                if sheet.entity in AUTHORITY:
                    obj.sources = [sheet.entity]
                    derive_delivery_target(obj)
                db.add(obj)
                db.flush()
                counts["created"] += 1
                if sheet.entity == "dependency_item" and obj.revised_target_date and obj.revised_target_date != obj.original_target_date:
                    # the source's "Revised Target Date" becomes a first, approved entry in the revision history
                    db.add(DateRevision(project_id=project_id, entity_type="dependency_item", entity_id=obj.id, field="target_date",
                                        old_date=obj.original_target_date, new_date=obj.revised_target_date,
                                        reason=f"Imported from {batch.filename}", status="approved", requested_by=user.id,
                                        requested_by_email=user.email, decided_by=user.id, decided_by_email=user.email, decided_at=now))
                db.add(ImportRowReference(seq=next(seq), batch_id=batch.id, sheet_id=sheet.id, source_row=r.source_row, entity_type=sheet.entity,
                                          entity_id=obj.id, action="created", row_stamp=_stamp(obj), raw=r.raw))
            summary.append({"sheet": sheet.name, "entity": sheet.entity, **counts})
        batch.status, batch.project_id, batch.committed_at, batch.committed_by = "committed", project_id, now, user.id
        batch.commit_summary = {"mode": mode, "sheets": summary, "rejected_confirmed": bool(total_rejected)}
        if template_name:
            t = service.save_template(db, batch, template_name.strip(), user.id)
            batch.template_id = t.id
        write_audit(db, user, "import_commit", "import_batch", batch.id, after={"project_id": str(project_id), **batch.commit_summary})
        db.commit()
    except CommitError:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise
    return batch.commit_summary


def rollback(db: Session, batch: ImportBatch, user: User) -> dict:
    db.info["lifecycle"] = "all"  # imports match against archived and trashed records too, so nothing is duplicated or missed
    if batch.status != "committed":
        raise CommitError(409, "Only a committed import can be rolled back")
    refs = list(db.scalars(select(ImportRowReference).where(ImportRowReference.batch_id == batch.id, ImportRowReference.action.in_(("created", "updated")))
                           .order_by(ImportRowReference.seq.desc())))  # newest write first
    stamps: dict[tuple[str, uuid.UUID], set[str | None]] = defaultdict(set)
    for ref in refs:
        stamps[(CANONICAL[ref.entity_type].__tablename__, ref.entity_id)].add(ref.row_stamp)  # every write this batch made to the record
    conflicts, objs = set(), {}
    for ref in refs:
        model = CANONICAL[ref.entity_type]
        obj = db.get(model, ref.entity_id)
        if obj is None:
            continue
        objs[ref.id] = obj
        if _stamp(obj) not in stamps[(model.__tablename__, ref.entity_id)]:
            conflicts.add(ref.entity_id)  # changed by someone after the import
    if conflicts:
        raise CommitError(409, f"{len(conflicts)} imported record(s) were edited after the import, so rollback is not safe. Nothing was changed.")
    deleted = restored = 0
    gone: set[uuid.UUID] = set()
    for ref in refs:
        obj = objs.get(ref.id)
        if obj is None:
            continue
        if ref.action == "created":
            db.delete(obj)
            gone.add(ref.entity_id)
            deleted += 1
        else:
            apply_snapshot(obj, ref.before or {})
            restored += 1
    if gone:  # nothing may point at records that no longer exist
        db.query(DateRevision).filter(DateRevision.entity_id.in_(gone)).delete(synchronize_session=False)
        db.query(RequirementLink).filter((RequirementLink.source_id.in_(gone)) | (RequirementLink.target_id.in_(gone))).delete(synchronize_session=False)
    db.flush()
    for ph in db.scalars(select(ProjectPhase).where(ProjectPhase.import_batch_id == batch.id)):
        if db.scalar(select(WorkItem.id).where(WorkItem.phase_id == ph.id).limit(1)) is None:
            db.delete(ph)
    batch.status, batch.rolled_back_at = "rolled_back", datetime.now(timezone.utc)
    write_audit(db, user, "import_rollback", "import_batch", batch.id, after={"deleted": deleted, "restored": restored})
    db.commit()
    return {"deleted": deleted, "restored": restored}
