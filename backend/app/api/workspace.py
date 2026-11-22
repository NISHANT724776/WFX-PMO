"""Comments and attachments on any managed record, and the actions that move a Needs-Attention action item along."""
import re
import uuid
from datetime import date, timedelta

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.lifecycle import MANAGED, load, spec_for
from app.api.plan import project_or_404
from app.api.records import _out, monday_of
from app.config import get_settings
from app.core.audit import row_to_dict, write_audit
from app.core.deps import get_db, require
from app.core.storage import get_storage
from app.db.base import utcnow
from app.models import User
from app.models.workspace import ActionItem, Attachment, Comment, WeekPlanItem

router = APIRouter()

# deliberately short: documents, spreadsheets, decks, images, plain text and archives. No executables or scripts.
ALLOWED_EXT = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".csv", ".ppt", ".pptx", ".txt", ".png", ".jpg", ".jpeg", ".gif", ".zip", ".msg", ".eml"}


def _target(db: Session, user: User, project_id: uuid.UUID, entity_type: str, entity_id: uuid.UUID):
    project_or_404(db, user, project_id)
    return load(db, spec_for(entity_type), project_id, entity_id)


def _comment_out(c: Comment) -> dict:
    return jsonable_encoder({"id": c.id, "entity_type": c.entity_type, "entity_id": c.entity_id, "body": c.body, "author_email": c.author_email, "created_at": c.created_at})


def _attachment_out(a: Attachment) -> dict:
    return jsonable_encoder({"id": a.id, "entity_type": a.entity_type, "entity_id": a.entity_id, "filename": a.filename, "content_type": a.content_type,
                             "size_bytes": a.size_bytes, "note": a.note, "uploaded_by_email": a.uploaded_by_email, "created_at": a.created_at})


# ------------------------------------------------------------------ comments
class CommentIn(BaseModel):
    entity_type: str
    entity_id: uuid.UUID
    body: str = Field(min_length=1, max_length=4000)


@router.get("/{project_id}/comments")
def list_comments(project_id: uuid.UUID, entity_type: str, entity_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require("comments:read"))):
    _target(db, user, project_id, entity_type, entity_id)
    rows = db.scalars(select(Comment).where(Comment.project_id == project_id, Comment.entity_type == entity_type, Comment.entity_id == entity_id)
                      .order_by(Comment.created_at, Comment.id)).all()
    return [_comment_out(c) for c in rows]


@router.post("/{project_id}/comments", status_code=status.HTTP_201_CREATED)
def add_comment(project_id: uuid.UUID, body: CommentIn, db: Session = Depends(get_db), user: User = Depends(require("comments:write"))):
    _target(db, user, project_id, body.entity_type, body.entity_id)
    text = body.body.strip()
    if not text:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Comment is empty")
    c = Comment(project_id=project_id, entity_type=body.entity_type, entity_id=body.entity_id, body=text, author_id=user.id, author_email=user.email)
    db.add(c)
    db.flush()
    write_audit(db, user, "comment", body.entity_type, body.entity_id, after={"comment_id": str(c.id), "body": text[:200]})
    db.commit()
    return _comment_out(c)


@router.delete("/{project_id}/comments/{cid}", status_code=status.HTTP_204_NO_CONTENT)
def delete_comment(project_id: uuid.UUID, cid: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require("comments:write"))):
    project_or_404(db, user, project_id)
    c = db.get(Comment, cid)
    if c is None or c.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Comment not found")
    if c.author_id != user.id and "projects:write" not in user.permission_codes:  # your own comment, or an editor of the project
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the author or a project editor can remove a comment")
    write_audit(db, user, "comment_delete", c.entity_type, c.entity_id, before=row_to_dict(c))
    db.delete(c)
    db.commit()


# ------------------------------------------------------------------ attachments
def _clean_name(name: str) -> str:
    name = re.sub(r"[\\/\x00-\x1f]", "_", (name or "file").split("/")[-1].split("\\")[-1]).strip().strip(".")
    return (name or "file")[:200]


@router.get("/{project_id}/attachments")
def list_attachments(project_id: uuid.UUID, entity_type: str, entity_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require("comments:read"))):
    _target(db, user, project_id, entity_type, entity_id)
    rows = db.scalars(select(Attachment).where(Attachment.project_id == project_id, Attachment.entity_type == entity_type, Attachment.entity_id == entity_id)
                      .order_by(Attachment.created_at, Attachment.id)).all()
    return [_attachment_out(a) for a in rows]


@router.post("/{project_id}/attachments", status_code=status.HTTP_201_CREATED)
async def upload_attachment(project_id: uuid.UUID, entity_type: str = Form(...), entity_id: uuid.UUID = Form(...), note: str | None = Form(None),
                            file: UploadFile = File(...), db: Session = Depends(get_db), user: User = Depends(require("comments:write"))):
    _target(db, user, project_id, entity_type, entity_id)
    filename = _clean_name(file.filename or "")
    ext = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""
    if ext not in ALLOWED_EXT:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"File type '{ext or 'none'}' is not allowed. Allowed: {', '.join(sorted(ALLOWED_EXT))}")
    limit = get_settings().max_upload_mb * 1024 * 1024
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, f"File is larger than {get_settings().max_upload_mb} MB")
    if not data:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "File is empty")
    name = get_storage().save(data, ext)
    a = Attachment(project_id=project_id, entity_type=entity_type, entity_id=entity_id, filename=filename, content_type=file.content_type,
                   size_bytes=len(data), storage_name=name, note=(note or "").strip()[:300] or None, uploaded_by=user.id, uploaded_by_email=user.email)
    db.add(a)
    db.flush()
    write_audit(db, user, "attach", entity_type, entity_id, after={"attachment_id": str(a.id), "filename": filename, "size_bytes": len(data)})
    db.commit()
    return _attachment_out(a)


@router.get("/{project_id}/attachments/{aid}/download")
def download_attachment(project_id: uuid.UUID, aid: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require("comments:read"))):
    project_or_404(db, user, project_id)
    a = db.get(Attachment, aid)
    if a is None or a.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Attachment not found")
    path = get_storage().path(a.storage_name)
    if not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "The stored file is missing")
    # always a download, never rendered in the browser
    return FileResponse(path, media_type="application/octet-stream", filename=a.filename, headers={"X-Content-Type-Options": "nosniff"})


@router.delete("/{project_id}/attachments/{aid}", status_code=status.HTTP_204_NO_CONTENT)
def delete_attachment(project_id: uuid.UUID, aid: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require("comments:write"))):
    project_or_404(db, user, project_id)
    a = db.get(Attachment, aid)
    if a is None or a.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Attachment not found")
    if a.uploaded_by != user.id and "projects:write" not in user.permission_codes:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the uploader or a project editor can remove an attachment")
    write_audit(db, user, "detach", a.entity_type, a.entity_id, before=row_to_dict(a))
    get_storage().delete(a.storage_name)
    db.delete(a)
    db.commit()


# ------------------------------------------------------------------ action items: escalate / resolve / reopen
class Reason(BaseModel):
    reason: str = Field(min_length=3, max_length=2000)
    to: str | None = Field(None, max_length=150)  # escalate only: who it goes to


def _action(db: Session, user: User, project_id: uuid.UUID, rid: uuid.UUID) -> ActionItem:
    project_or_404(db, user, project_id)
    o = db.get(ActionItem, rid)
    if o is None or o.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Action not found")
    return o


def _finish(db: Session, user: User, project_id: uuid.UUID, o: ActionItem, verb: str, before: dict, action: str) -> dict:
    o.last_action, o.last_action_by, o.last_action_at = verb, user.email, utcnow()
    write_audit(db, user, action, "action_item", o.id, before=before, after=row_to_dict(o))
    db.commit()
    return _out(MANAGED["action_item"], o, date.today(), project_or_404(db, user, project_id).delay_grace_days or 0)


@router.post("/{project_id}/records/action-items/{rid}/escalate")
def escalate(project_id: uuid.UUID, rid: uuid.UUID, body: Reason, db: Session = Depends(get_db), user: User = Depends(require("projects:write"))):
    o = _action(db, user, project_id, rid)
    if o.status == "resolved":
        raise HTTPException(status.HTTP_409_CONFLICT, "A resolved action cannot be escalated; reopen it first")
    before = row_to_dict(o)
    o.status, o.escalation_level = "escalated", (o.escalation_level or 0) + 1
    o.escalated_to, o.escalated_at, o.escalation_reason = (body.to or o.escalated_to), utcnow(), body.reason.strip()
    return _finish(db, user, project_id, o, f"Escalated (level {o.escalation_level}): {body.reason.strip()}"[:300], before, "escalated")


@router.post("/{project_id}/records/action-items/{rid}/resolve")
def resolve(project_id: uuid.UUID, rid: uuid.UUID, body: Reason, db: Session = Depends(get_db), user: User = Depends(require("projects:write"))):
    o = _action(db, user, project_id, rid)
    if o.status == "resolved":
        raise HTTPException(status.HTTP_409_CONFLICT, "Already resolved")
    before = row_to_dict(o)
    o.status, o.resolved_at, o.resolved_by_email, o.resolution_note = "resolved", utcnow(), user.email, body.reason.strip()
    return _finish(db, user, project_id, o, f"Resolved: {body.reason.strip()}"[:300], before, "resolved")


@router.post("/{project_id}/records/action-items/{rid}/reopen")
def reopen(project_id: uuid.UUID, rid: uuid.UUID, body: Reason, db: Session = Depends(get_db), user: User = Depends(require("projects:write"))):
    o = _action(db, user, project_id, rid)
    if o.status != "resolved":
        raise HTTPException(status.HTTP_409_CONFLICT, "Only a resolved action can be reopened")
    before = row_to_dict(o)
    o.status, o.reopen_count = "open", (o.reopen_count or 0) + 1  # the earlier resolution stays in the audit log
    o.resolved_at, o.resolved_by_email, o.resolution_note = None, None, None
    return _finish(db, user, project_id, o, f"Reopened: {body.reason.strip()}"[:300], before, "reopened")


# ------------------------------------------------------------------ week plan: move an activity to another week
class MoveWeek(BaseModel):
    week_start: date | None = None  # the Monday of the new week
    weeks: int | None = Field(None, ge=-52, le=52)  # or: shift by this many weeks


@router.post("/{project_id}/records/week-plan-items/{rid}/move")
def move_week(project_id: uuid.UUID, rid: uuid.UUID, body: MoveWeek, db: Session = Depends(get_db), user: User = Depends(require("projects:write"))):
    """Moves the activity to another Monday-Sunday week. The target date moves with it, keeping its weekday."""
    project = project_or_404(db, user, project_id)
    o = db.get(WeekPlanItem, rid)
    if o is None or o.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Activity not found")
    if (body.week_start is None) == (body.weeks is None):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Send either week_start or weeks")
    new_start = body.week_start if body.week_start else o.week_start + timedelta(weeks=body.weeks)
    if new_start.weekday() != 0:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Weeks run Monday to Sunday: pick a Monday")
    if new_start == o.week_start:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "It is already in that week")
    before = row_to_dict(o)
    shift = new_start - o.week_start
    o.week_start = new_start
    if o.target_date:
        o.target_date = o.target_date + shift
    write_audit(db, user, "move_week", "week_plan_item", o.id, before=before, after=row_to_dict(o))
    db.commit()
    return _out(MANAGED["week_plan_item"], o, date.today(), project.delay_grace_days or 0)
