"""Manage-mode records: comments, attachments, and actionable items raised from risks and delays."""
import uuid
from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, JSON, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, TimestampMixin, utcnow
from app.models.canonical import ImportedMixin, LifecycleMixin


class Comment(IdMixin, Base):
    __tablename__ = "comments"
    __table_args__ = (Index("ix_comment_entity", "entity_type", "entity_id"),)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    entity_type: Mapped[str] = mapped_column(String(30))
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    body: Mapped[str] = mapped_column(Text)
    author_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    author_email: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Attachment(IdMixin, Base):
    """The file lives in storage under a generated name; the user's file name is only a label."""

    __tablename__ = "attachments"
    __table_args__ = (Index("ix_attachment_entity", "entity_type", "entity_id"),)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    entity_type: Mapped[str] = mapped_column(String(30))
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str | None] = mapped_column(String(120))
    size_bytes: Mapped[int] = mapped_column(Integer)
    storage_name: Mapped[str] = mapped_column(String(80))
    note: Mapped[str | None] = mapped_column(String(300))
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    uploaded_by_email: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ActionItem(LifecycleMixin, ImportedMixin, IdMixin, TimestampMixin, Base):
    """A risk or delay turned into something a named person must do by a date (Needs Attention).
    status: open | in_progress | escalated | resolved. Resolving needs a note; reopening needs a reason."""

    __tablename__ = "action_items"
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("products.id"))
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str | None] = mapped_column(Text)
    source_type: Mapped[str | None] = mapped_column(String(30))  # what raised it, e.g. work_item, delivery_item
    source_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    linked_work_item_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("work_items.id", ondelete="SET NULL"))
    priority: Mapped[str] = mapped_column(String(10), default="medium", server_default="medium")  # low | medium | high | critical
    owner_name: Mapped[str | None] = mapped_column(String(150))
    due_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(12), default="open", server_default="open")
    escalation_level: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    escalated_to: Mapped[str | None] = mapped_column(String(150))
    escalated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    escalation_reason: Mapped[str | None] = mapped_column(Text)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_by_email: Mapped[str | None] = mapped_column(String(255))
    resolution_note: Mapped[str | None] = mapped_column(Text)
    reopen_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_action: Mapped[str | None] = mapped_column(String(300))
    last_action_by: Mapped[str | None] = mapped_column(String(255))
    last_action_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class CoverageActivity(LifecycleMixin, ImportedMixin, IdMixin, TimestampMixin, Base):
    """One piece of work for a department at a location. Coverage % is never typed in: it is sum(completed) / sum(planned) over these rows."""

    __tablename__ = "coverage_activities"
    __table_args__ = (CheckConstraint("planned_count >= 0 AND completed_count >= 0 AND completed_count <= planned_count", name="counts_valid"),)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    department_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("departments.id"), index=True)
    location_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("locations.id"), index=True)
    product_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("products.id"))
    title: Mapped[str] = mapped_column(String(300))
    responsible_name: Mapped[str | None] = mapped_column(String(150))
    planned_count: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    completed_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    remarks: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class WeekPlanItem(LifecycleMixin, ImportedMixin, IdMixin, TimestampMixin, Base):
    """An activity somebody put on a week's plan (Monday-Sunday). Removing it from the plan archives it; moving it changes week_start and target_date together."""

    __tablename__ = "week_plan_items"
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    week_start: Mapped[date] = mapped_column(Date, index=True)  # always a Monday
    title: Mapped[str] = mapped_column(String(300))
    workstream: Mapped[str | None] = mapped_column(String(100))
    owner_name: Mapped[str | None] = mapped_column(String(150))
    product_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("products.id"))
    module: Mapped[str | None] = mapped_column(String(150))
    target_date: Mapped[date | None] = mapped_column(Date)
    percent_complete: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(12), default="planned", server_default="planned")  # planned | in_progress | done
    remarks: Mapped[str | None] = mapped_column(Text)
    source_type: Mapped[str | None] = mapped_column(String(30))  # the plan task / pending item / ... this activity came from, if any
    source_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class DashboardLayout(IdMixin, TimestampMixin, Base):
    """A saved arrangement of widgets. scope: personal (only its owner) | project (everyone with access to the project) | management (everyone).
    It stores only WHICH widgets, where, and their settings; every number is fetched live from the database when the dashboard is shown."""

    __tablename__ = "dashboard_layouts"
    __table_args__ = (Index("ix_layout_scope", "scope", "project_id", "owner_id"),)
    name: Mapped[str] = mapped_column(String(120))
    scope: Mapped[str] = mapped_column(String(12))
    owner_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))  # personal layouts
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)  # project layouts
    config: Mapped[dict] = mapped_column(JSON)
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")  # a save must name the version it started from
    created_by_email: Mapped[str | None] = mapped_column(String(255))
    updated_by_email: Mapped[str | None] = mapped_column(String(255))


class DashboardPref(Base):
    """The layout a user last chose for a project, so it is there on the next visit."""

    __tablename__ = "dashboard_prefs"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)
    layout_id: Mapped[str] = mapped_column(String(60))  # a layout id, or "template:<key>"


# ------------------------------------------------------------------ UAT, reports + prints, integrations trackers
class UatScenario(LifecycleMixin, ImportedMixin, IdMixin, TimestampMixin, Base):
    """One UAT test scenario and where it stands. result: not_run | in_progress | passed | failed | blocked | retest.
    result_raw keeps the wording of an imported sheet. The history of changes is in the audit log."""

    __tablename__ = "uat_scenarios"
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("products.id"))
    scenario_id: Mapped[str | None] = mapped_column(String(60))  # the number used in the customer's sheet; a reference, not a key
    title: Mapped[str] = mapped_column(Text)
    module: Mapped[str | None] = mapped_column(String(150))
    functionality: Mapped[str | None] = mapped_column(String(200))
    scenario_type: Mapped[str | None] = mapped_column(String(100))
    source_ref: Mapped[str | None] = mapped_column(String(200))  # where the scenario came from (a source ID or document)
    linked_cases: Mapped[str | None] = mapped_column(Text)  # linked test cases, as written in the sheet
    uat_role: Mapped[str | None] = mapped_column(String(100))  # the role that executes it on the customer side
    business_objective: Mapped[str | None] = mapped_column(Text)
    pre_condition: Mapped[str | None] = mapped_column(Text)
    test_data: Mapped[str | None] = mapped_column(Text)
    steps: Mapped[str | None] = mapped_column(Text)
    expected_result: Mapped[str | None] = mapped_column(Text)
    tester: Mapped[str | None] = mapped_column(String(150))
    cycle: Mapped[str | None] = mapped_column(String(60))
    planned_date: Mapped[date | None] = mapped_column(Date)
    executed_date: Mapped[date | None] = mapped_column(Date)
    result: Mapped[str] = mapped_column(String(15), default="not_run", server_default="not_run")
    result_raw: Mapped[str | None] = mapped_column(String(100))
    actual_result: Mapped[str | None] = mapped_column(Text)
    defect_ref: Mapped[str | None] = mapped_column(String(120))
    remarks: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class UatDefect(LifecycleMixin, ImportedMixin, IdMixin, TimestampMixin, Base):
    """A defect found in UAT. severity: low | medium | high | critical. status: open | in_fix | retest | closed | rejected."""

    __tablename__ = "uat_defects"
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    scenario_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("uat_scenarios.id", ondelete="SET NULL"), index=True)
    product_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("products.id"))
    defect_ref: Mapped[str | None] = mapped_column(String(60))
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String(10), default="medium", server_default="medium")
    status: Mapped[str] = mapped_column(String(10), default="open", server_default="open")
    raised_on: Mapped[date | None] = mapped_column(Date)
    raised_by: Mapped[str | None] = mapped_column(String(150))
    owner_name: Mapped[str | None] = mapped_column(String(150))
    target_date: Mapped[date | None] = mapped_column(Date)
    closed_on: Mapped[date | None] = mapped_column(Date)
    resolution: Mapped[str | None] = mapped_column(Text)
    remarks: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class _Deliverable:
    """What integrations and reports/prints share: an owner, a status, a baseline target date, revised dates only through approved revisions."""

    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("products.id"))
    owner_name: Mapped[str | None] = mapped_column(String(150))
    status_raw: Mapped[str | None] = mapped_column(String(100))
    status_category: Mapped[str | None] = mapped_column(String(20))
    target_date: Mapped[date | None] = mapped_column(Date)  # baseline
    revised_target_date: Mapped[date | None] = mapped_column(Date)  # latest approved revision
    actual_date: Mapped[date | None] = mapped_column(Date)
    uat_status: Mapped[str | None] = mapped_column(String(60))
    remarks: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class IntegrationItem(_Deliverable, LifecycleMixin, ImportedMixin, IdMixin, TimestampMixin, Base):
    __tablename__ = "integration_items"
    name: Mapped[str] = mapped_column(String(300))
    company: Mapped[str | None] = mapped_column(String(150))
    process: Mapped[str | None] = mapped_column(String(200))
    documented: Mapped[str | None] = mapped_column(String(60))
    wfx_status: Mapped[str | None] = mapped_column(String(100))
    partner: Mapped[str | None] = mapped_column(String(150))
    system: Mapped[str | None] = mapped_column(String(150))
    direction: Mapped[str | None] = mapped_column(String(20))  # inbound | outbound | bidirectional
    technology: Mapped[str | None] = mapped_column(String(100))
    message_type: Mapped[str | None] = mapped_column(String(150))
    business_domain: Mapped[str | None] = mapped_column(String(150))
    region: Mapped[str | None] = mapped_column(String(100))
    endpoint: Mapped[str | None] = mapped_column(Text)


class ReportItem(_Deliverable, LifecycleMixin, ImportedMixin, IdMixin, TimestampMixin, Base):
    __tablename__ = "report_items"
    name: Mapped[str] = mapped_column(String(300))
    report_type: Mapped[str | None] = mapped_column(String(40))  # report | print | form | dashboard | other
    module: Mapped[str | None] = mapped_column(String(150))
    folder: Mapped[str | None] = mapped_column(String(200))
    sub_folder: Mapped[str | None] = mapped_column(String(200))
    complexity: Mapped[str | None] = mapped_column(String(10))  # low | medium | high
    reports_count: Mapped[int | None] = mapped_column(Integer)


from app.models.canonical import CANONICAL  # noqa: E402

CANONICAL.update({"uat_scenario": UatScenario, "integration_item": IntegrationItem, "report_item": ReportItem})
