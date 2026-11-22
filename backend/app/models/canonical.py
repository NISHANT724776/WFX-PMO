"""Canonical project records created by imports (and, from Phase 3, by users). One row per business object."""
import uuid
from datetime import date

from datetime import datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, declared_attr, mapped_column

from app.db.base import Base, IdMixin, TimestampMixin, utcnow


class LifecycleMixin:
    """Archive (hidden from lists and dashboards, kept) and soft delete (trash, restorable). Nothing is removed until a purge."""

    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    archived_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)


class ImportedMixin:
    """match_key = business key used to recognise the same record on re-import (never the external ID alone)."""

    match_key: Mapped[str] = mapped_column(String(300), default="")
    raw_values: Mapped[dict | None] = mapped_column(JSON)  # original text of cells that could not be parsed

    @declared_attr
    def import_batch_id(cls) -> Mapped[uuid.UUID | None]:
        return mapped_column(ForeignKey("import_batches.id", ondelete="SET NULL"), index=True)


class ProjectPhase(IdMixin, TimestampMixin, Base):
    __tablename__ = "project_phases"
    __table_args__ = (UniqueConstraint("project_id", "name"),)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(300))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    import_batch_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("import_batches.id", ondelete="SET NULL"))


class WorkItem(LifecycleMixin, ImportedMixin, IdMixin, TimestampMixin, Base):
    """Plan task. Planned dates are the baseline; revisions arrive in Phase 3 (date_revisions)."""

    __tablename__ = "work_items"
    __table_args__ = (Index("ix_wi_project_match", "project_id", "match_key"),)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    phase_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("project_phases.id"))
    product_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("products.id"))  # NULL = applies to all products
    title: Mapped[str] = mapped_column(Text)
    responsible_party: Mapped[str | None] = mapped_column(String(100))
    owner_name: Mapped[str | None] = mapped_column(String(150))
    location_label: Mapped[str | None] = mapped_column(String(200))
    location_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("locations.id"))
    delivery_mode: Mapped[str | None] = mapped_column(String(10))  # onsite | online
    planned_start: Mapped[date | None] = mapped_column(Date)
    planned_finish: Mapped[date | None] = mapped_column(Date)
    duration_days: Mapped[int | None] = mapped_column(Integer)
    actual_start: Mapped[date | None] = mapped_column(Date)
    actual_finish: Mapped[date | None] = mapped_column(Date)
    status_raw: Mapped[str | None] = mapped_column(String(50))
    status_category: Mapped[str | None] = mapped_column(String(20))
    dependencies_text: Mapped[str | None] = mapped_column(Text)
    resource_allocation: Mapped[str | None] = mapped_column(String(100))
    remarks: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    kind: Mapped[str] = mapped_column(String(12), default="task", server_default="task")  # task | milestone
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("work_items.id", ondelete="SET NULL"), index=True)
    percent_complete: Mapped[int | None] = mapped_column(Integer)  # what the owner reports for THIS task (0-100); dashboards still count status
    # latest APPROVED revision (planned_* above stay the immutable baseline)
    revised_start: Mapped[date | None] = mapped_column(Date)
    revised_finish: Mapped[date | None] = mapped_column(Date)


class TrackerEvent(ImportedMixin, IdMixin, TimestampMixin, Base):
    """One event for one product (unpivoted from the wide Master Sheet)."""

    __tablename__ = "tracker_events"
    __table_args__ = (Index("ix_te_project_match", "project_id", "match_key"),)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id"))
    event_name: Mapped[str] = mapped_column(String(300))
    responsibility: Mapped[str | None] = mapped_column(String(100))
    spoc: Mapped[str | None] = mapped_column(String(150))
    planned_date: Mapped[date | None] = mapped_column(Date)
    actual_date: Mapped[date | None] = mapped_column(Date)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class ApprovalGate(LifecycleMixin, ImportedMixin, IdMixin, TimestampMixin, Base):
    __tablename__ = "approval_gates"
    __table_args__ = (Index("ix_ag_project_match", "project_id", "match_key"),)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("products.id"))
    gate_type: Mapped[str] = mapped_column(String(60))  # from the source sheet, e.g. blue_printing_signoff, e2e
    name: Mapped[str] = mapped_column(String(300))
    mapping_date: Mapped[date | None] = mapped_column(Date)
    planned_date: Mapped[date | None] = mapped_column(Date)
    actual_date: Mapped[date | None] = mapped_column(Date)
    submission_date: Mapped[date | None] = mapped_column(Date)
    signoff_date: Mapped[date | None] = mapped_column(Date)
    approval_status: Mapped[str | None] = mapped_column(String(100))  # the status label (configurable: Status Configuration, entity approval_gate)
    approval_category: Mapped[str | None] = mapped_column(String(20))  # not_started | in_progress | done | blocked | cancelled; empty on imported gates
    approver_name: Mapped[str | None] = mapped_column(String(150))
    comments: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class GapSpecification(LifecycleMixin, ImportedMixin, IdMixin, TimestampMixin, Base):
    """external_issue_id is a reference, not a key: one issue can have several specification rows."""

    __tablename__ = "gap_specifications"
    __table_args__ = (Index("ix_gs_project_match", "project_id", "match_key"), Index("ix_gs_issue", "external_issue_id"))
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    serial_no: Mapped[int | None] = mapped_column(Integer)
    external_issue_id: Mapped[str | None] = mapped_column(String(60))
    event: Mapped[str | None] = mapped_column(String(100))
    team: Mapped[str | None] = mapped_column(String(100))
    product_name: Mapped[str | None] = mapped_column(String(100))
    module: Mapped[str | None] = mapped_column(String(150))
    development_scope: Mapped[str | None] = mapped_column(String(150))
    description: Mapped[str] = mapped_column(Text)
    priority: Mapped[str | None] = mapped_column(String(30))
    category: Mapped[str | None] = mapped_column(String(100))
    wfx_solution: Mapped[str | None] = mapped_column(Text)
    spec_status: Mapped[str | None] = mapped_column(String(100))
    remarks: Mapped[str | None] = mapped_column(Text)
    responsibility: Mapped[str | None] = mapped_column(String(100))
    target_date: Mapped[date | None] = mapped_column(Date)
    actual_date: Mapped[date | None] = mapped_column(Date)
    submission_date: Mapped[date | None] = mapped_column(Date)
    signoff_date: Mapped[date | None] = mapped_column(Date)
    approval_status: Mapped[str | None] = mapped_column(String(100))
    received_date: Mapped[date | None] = mapped_column(Date)
    created_date: Mapped[date | None] = mapped_column(Date)
    proto_status: Mapped[str | None] = mapped_column(String(100))
    specs_created: Mapped[str | None] = mapped_column(String(100))
    revised_target_date: Mapped[date | None] = mapped_column(Date)  # latest APPROVED revision of target_date
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class DateRevision(IdMixin, Base):
    """Append-only history of date changes. The baseline date is never overwritten."""

    __tablename__ = "date_revisions"
    __table_args__ = (Index("ix_dr_entity", "entity_type", "entity_id"),)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    entity_type: Mapped[str] = mapped_column(String(30))  # work_item | dependency_item
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    field: Mapped[str] = mapped_column(String(30))  # planned_start | planned_finish | target_date
    old_date: Mapped[date | None] = mapped_column(Date)  # effective date at the time of the request
    new_date: Mapped[date] = mapped_column(Date)
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(10), default="proposed")  # proposed | approved | rejected
    requested_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    requested_by_email: Mapped[str | None] = mapped_column(String(255))
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    decided_by_email: Mapped[str | None] = mapped_column(String(255))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WorkItemDependency(IdMixin, Base):
    __tablename__ = "work_item_dependencies"
    __table_args__ = (UniqueConstraint("predecessor_id", "successor_id"),)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    predecessor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("work_items.id", ondelete="CASCADE"), index=True)
    successor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("work_items.id", ondelete="CASCADE"), index=True)
    dep_type: Mapped[str] = mapped_column(String(2), default="FS")
    lag_days: Mapped[int] = mapped_column(Integer, default=0)


class DependencyItem(LifecycleMixin, ImportedMixin, IdMixin, TimestampMixin, Base):
    """Pending activity: pending with Customer / WFX / External partner / Internal team."""

    __tablename__ = "dependency_items"
    __table_args__ = (Index("ix_di_project_match", "project_id", "match_key"), Index("ix_di_with", "project_id", "pending_with"))
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("products.id"))
    category: Mapped[str | None] = mapped_column(String(200))  # e.g. the section it was listed under
    pending_with: Mapped[str] = mapped_column(String(10))  # customer | wfx | external | internal
    description: Mapped[str] = mapped_column(Text)
    owner_name: Mapped[str | None] = mapped_column(String(200))
    original_target_date: Mapped[date | None] = mapped_column(Date)  # baseline
    revised_target_date: Mapped[date | None] = mapped_column(Date)  # latest approved revision
    actual_closure_date: Mapped[date | None] = mapped_column(Date)
    status_raw: Mapped[str | None] = mapped_column(String(50))
    status_category: Mapped[str | None] = mapped_column(String(20))
    remarks: Mapped[str | None] = mapped_column(Text)
    linked_work_item_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("work_items.id", ondelete="SET NULL"))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class DeliveryItem(LifecycleMixin, ImportedMixin, IdMixin, TimestampMixin, Base):
    """One development/delivery ticket. external_id (helpdesk/tracker number) repeats, so it is a reference, not a key.
    Fed by two sheets (Delivery Schedule and Tech_Final); each is authoritative for its own fields (catalog.AUTHORITY)."""

    __tablename__ = "delivery_items"
    __table_args__ = (Index("ix_dlv_project_match", "project_id", "match_key"), Index("ix_dlv_ext", "project_id", "external_id"))
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("products.id"))
    external_id: Mapped[str | None] = mapped_column(String(60))
    parent_external_id: Mapped[str | None] = mapped_column(String(60))  # "440679 : Party Configuration" -> 440679
    stream: Mapped[str | None] = mapped_column(String(100))
    module: Mapped[str | None] = mapped_column(String(150))
    description: Mapped[str] = mapped_column(Text)
    priority: Mapped[str | None] = mapped_column(String(100))
    status_raw: Mapped[str | None] = mapped_column(String(150))
    status_category: Mapped[str | None] = mapped_column(String(20))
    helpdesk_status_raw: Mapped[str | None] = mapped_column(String(100))
    helpdesk_status_category: Mapped[str | None] = mapped_column(String(20))
    functional_owner: Mapped[str | None] = mapped_column(String(150))
    product_owner: Mapped[str | None] = mapped_column(String(150))
    tech_owner: Mapped[str | None] = mapped_column(String(150))
    qa_owner: Mapped[str | None] = mapped_column(String(150))
    specs_responsibility: Mapped[str | None] = mapped_column(String(150))
    testing_responsibility: Mapped[str | None] = mapped_column(String(150))
    functional_specs_status: Mapped[str | None] = mapped_column(String(100))
    customer_discussion_status: Mapped[str | None] = mapped_column(String(100))
    high_level_status: Mapped[str | None] = mapped_column(String(100))
    detail_level_status: Mapped[str | None] = mapped_column(String(100))
    high_level_date: Mapped[date | None] = mapped_column(Date)
    detail_level_date: Mapped[date | None] = mapped_column(Date)
    # lifecycle stage dates (planned unless stated)
    spec_closure_date: Mapped[date | None] = mapped_column(Date)
    spec_closure_actual: Mapped[date | None] = mapped_column(Date)
    dev_initiation: Mapped[date | None] = mapped_column(Date)
    dev_completion: Mapped[date | None] = mapped_column(Date)  # handover to QA
    qa_release: Mapped[date | None] = mapped_column(Date)
    uat_release: Mapped[date | None] = mapped_column(Date)  # release to UAT server
    customer_release: Mapped[date | None] = mapped_column(Date)  # release on the customer's UAT
    customer_uat_closure: Mapped[date | None] = mapped_column(Date)
    spec_target_date: Mapped[date | None] = mapped_column(Date)
    target_brd_closure: Mapped[date | None] = mapped_column(Date)
    # the delivery commitment: baseline derived once from the stage dates, then moved only by approved revisions
    delivery_target_date: Mapped[date | None] = mapped_column(Date)
    revised_target_date: Mapped[date | None] = mapped_column(Date)
    actual_completion: Mapped[date | None] = mapped_column(Date)
    specs_completed: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")  # the source wrote "Completed" as the SPECS target date (specs done; says nothing about delivery)
    dev_remarks: Mapped[str | None] = mapped_column(Text)
    meeting_remarks: Mapped[str | None] = mapped_column(Text)
    pd_remarks: Mapped[str | None] = mapped_column(Text)
    remarks: Mapped[str | None] = mapped_column(Text)
    tracker_ref: Mapped[str | None] = mapped_column(Text)
    helpdesk_description: Mapped[str | None] = mapped_column(Text)
    sources: Mapped[list | None] = mapped_column(JSON)  # sheets that contributed, e.g. ["delivery_schedule", "tech_tracker"]
    merge_notes: Mapped[dict | None] = mapped_column(JSON)  # fields where the two sources disagreed (kept vs ignored value)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class BrdRequirement(LifecycleMixin, ImportedMixin, IdMixin, TimestampMixin, Base):
    """Requirement (BRD point). brd_serial repeats and can be 'Not Received', so the source row number is kept separately."""

    __tablename__ = "brd_requirements"
    __table_args__ = (Index("ix_brd_project_match", "project_id", "match_key"), Index("ix_brd_serial", "project_id", "brd_serial"))
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    sr_no: Mapped[str | None] = mapped_column(String(30))
    brd_serial: Mapped[str | None] = mapped_column(String(60))
    description: Mapped[str] = mapped_column(Text)
    module: Mapped[str | None] = mapped_column(String(150))
    brd_status: Mapped[str | None] = mapped_column(String(150))
    development_phase: Mapped[str | None] = mapped_column(String(100))
    covered_in_proto: Mapped[str | None] = mapped_column(String(100))
    responsibility: Mapped[str | None] = mapped_column(String(150))
    target_date: Mapped[date | None] = mapped_column(Date)
    revised_target_date: Mapped[date | None] = mapped_column(Date)
    req_type: Mapped[str | None] = mapped_column(String(100))
    remarks: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class HelpdeskItem(LifecycleMixin, ImportedMixin, IdMixin, TimestampMixin, Base):
    """Helpdesk reference (Operations BRD) or an open operations point. One helpdesk requirement can have many delivery items."""

    __tablename__ = "helpdesk_items"
    __table_args__ = (Index("ix_hd_project_match", "project_id", "match_key"), Index("ix_hd_ext", "project_id", "external_id"))
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(20))  # ops_brd | open_point
    sr_no: Mapped[str | None] = mapped_column(String(30))
    external_id: Mapped[str | None] = mapped_column(String(60))
    category: Mapped[str | None] = mapped_column(String(100))
    tracker_ref: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text)
    status_raw: Mapped[str | None] = mapped_column(String(150))
    status_category: Mapped[str | None] = mapped_column(String(20))
    responsibility: Mapped[str | None] = mapped_column(String(150))
    target_date: Mapped[date | None] = mapped_column(Date)
    request_date: Mapped[date | None] = mapped_column(Date)
    request_from: Mapped[str | None] = mapped_column(String(150))
    division: Mapped[str | None] = mapped_column(String(100))
    remarks: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class DiscussionItem(LifecycleMixin, ImportedMixin, IdMixin, TimestampMixin, Base):
    __tablename__ = "discussion_items"
    __table_args__ = (Index("ix_dsc_project_match", "project_id", "match_key"),)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("products.id"))
    sr_no: Mapped[str | None] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(Text)
    brd_serial: Mapped[str | None] = mapped_column(String(60))
    tracker_sr_no: Mapped[str | None] = mapped_column(String(60))
    remarks: Mapped[str | None] = mapped_column(Text)
    item_type: Mapped[str | None] = mapped_column(String(100))
    module: Mapped[str | None] = mapped_column(String(150))
    concern: Mapped[str | None] = mapped_column(Text)
    functionality_status: Mapped[str | None] = mapped_column(String(150))
    document_reference: Mapped[str | None] = mapped_column(String(300))
    responsibility: Mapped[str | None] = mapped_column(String(150))
    target_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(10), default="open")  # open | decided | closed
    final_decision: Mapped[str | None] = mapped_column(Text)
    meeting_remarks: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class ScopeDecision(LifecycleMixin, ImportedMixin, IdMixin, TimestampMixin, Base):
    """Out-of-scope request: what was agreed, what the customer now asks, and the decision."""

    __tablename__ = "scope_decisions"
    __table_args__ = (Index("ix_sd_project_match", "project_id", "match_key"),)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    customer_feedback: Mapped[str] = mapped_column(Text)
    original_scope: Mapped[str | None] = mapped_column(Text)
    new_requirement: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    approval_status: Mapped[str] = mapped_column(String(12), default="pending")  # pending | approved | rejected
    decision_owner: Mapped[str | None] = mapped_column(String(150))
    decision_date: Mapped[date | None] = mapped_column(Date)
    remarks: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class RequirementLink(IdMixin, Base):
    """Many-to-many link between two project records (requirement <-> delivery item <-> helpdesk item ...)."""

    __tablename__ = "requirement_links"
    __table_args__ = (
        UniqueConstraint("source_type", "source_id", "target_type", "target_id"),
        Index("ix_rl_target", "target_type", "target_id"),
        Index("ix_rl_source", "source_type", "source_id"),
    )
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    source_type: Mapped[str] = mapped_column(String(30))
    source_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    target_type: Mapped[str] = mapped_column(String(30))
    target_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    link_type: Mapped[str] = mapped_column(String(20))  # same_ticket | parent_child | brd_discussion | related
    basis: Mapped[str | None] = mapped_column(String(300))  # the evidence, e.g. "helpdesk ID 389979 = delivery ID 389979"
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


CANONICAL = {
    "plan_task": WorkItem,
    "tracker_event": TrackerEvent,
    "approval_gate": ApprovalGate,
    "gap_specification": GapSpecification,
    "dependency_item": DependencyItem,
    "delivery_schedule": DeliveryItem,
    "tech_tracker": DeliveryItem,
    "brd_requirement": BrdRequirement,
    "helpdesk_ops_brd": HelpdeskItem,
    "ops_open_point": HelpdeskItem,
    "discussion_item": DiscussionItem,
    "scope_decision": ScopeDecision,
}
