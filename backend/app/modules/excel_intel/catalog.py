"""Target entities and fields that uploaded columns can map to. Synonyms are (phrase, weight) pairs."""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class FieldDef:
    key: str
    label: str
    type: str  # text | long_text | date | number | status | mode | id | category
    required: bool = False
    synonyms: tuple[tuple[str, float], ...] = ()


def _s(*phrases: str | tuple[str, float]) -> tuple[tuple[str, float], ...]:
    return tuple((p, 1.0) if isinstance(p, str) else p for p in phrases)


@dataclass(frozen=True)
class EntityDef:
    key: str
    label: str
    fields: tuple[FieldDef, ...]
    layout: str = "table"  # table | matrix
    importable: bool = True

    def field(self, key: str) -> FieldDef | None:
        return next((f for f in self.fields if f.key == key), None)


PLAN_TASK = EntityDef(
    "plan_task", "Project plan task",
    (
        FieldDef("phase", "Phase", "text", True, _s("phase", "stage", "project stage", "workstream")),
        FieldDef("title", "Task / Activity", "long_text", True, _s("task activity", "task", "activity", "task name", "activity name", "work package", "milestone")),
        FieldDef("responsible_party", "Responsible party", "category", False, _s("responsible party", "responsibility", "party", ("owner team", 0.9), ("team", 0.7))),
        FieldDef("owner", "Owner (person)", "text", False, _s("resource name", "assigned to", "responsible person", "owner", "assignee", "resource", ("responsible", 0.8))),
        FieldDef("location", "Location", "category", False, _s("location", "site", "project site", "place")),
        FieldDef("planned_start", "Planned start", "date", False, _s("start date", "planned start", "planned start date", "start", "baseline start", "begin date")),
        FieldDef("planned_finish", "Planned finish", "date", False, _s("end date", "planned finish", "planned end", "finish date", "finish", "end", "target date", "due date", "target finish")),
        FieldDef("duration_days", "Duration (days)", "number", False, _s("duration days", "duration", "days", "effort days")),
        FieldDef("actual_start", "Actual start", "date", False, _s("actual start date", "actual start", "started on")),
        FieldDef("actual_finish", "Actual finish", "date", False, _s("actual end date", "actual end", "actual finish", "actual closure", "actual closure date", "completed on")),
        FieldDef("delivery_mode", "Onsite / Online", "mode", False, _s("onsite remote", "onsite online", "delivery mode", "mode", ("type", 0.8))),
        FieldDef("status", "Status", "status", False, _s("status", "task status", "current status")),
        FieldDef("dependencies", "Dependencies", "long_text", False, _s("dependencies", "dependency", "depends on", "predecessor")),
        FieldDef("resource_allocation", "Resource allocation", "text", False, _s("resource allocation", "allocation", "allocation percent")),
        FieldDef("remarks", "Remarks", "long_text", False, _s("remarks notes", "remarks", "notes", "comments", "comment")),
    ),
)

TRACKER_EVENT = EntityDef(
    "tracker_event", "Tracker event x product (matrix)",
    (
        FieldDef("event_name", "Event", "long_text", True, _s("events", "event", "milestone", "activity", "description")),
        FieldDef("responsibility", "Responsibility", "category", False, _s("responsibility", "responsible", "responsible party", "owner team")),
        FieldDef("spoc", "SPOC", "text", False, _s("spoc", "single point of contact", "contact", "owner", "assigned to")),
        FieldDef("planned_date", "Planned date (per product)", "date", False, _s("planned date", "planned", "plan date", "target date", "baseline date")),
        FieldDef("actual_date", "Actual date (per product)", "date", False, _s("actual date", "actual", "completed date", "done date")),
    ),
    layout="matrix",
)

APPROVAL_GATE = EntityDef(
    "approval_gate", "Sign-off / approval gate",
    (
        FieldDef("name", "Department / gate", "text", True, _s("department team", "department", "team", "description", "gate", "name", "scenario")),
        FieldDef("mapping_date", "Mapping date", "date", False, _s("mapping date")),
        FieldDef("planned_date", "Target date", "date", False, _s("target date", "planned date", "due date", "planned")),
        FieldDef("actual_date", "Actual date", "date", False, _s("actual date", "actual")),
        FieldDef("submission_date", "Submission date", "date", False, _s("submission date", "submitted on", "submitted on date")),
        FieldDef("signoff_date", "Sign-off date", "date", False, _s("sign off date", "signoff date", "signed off date", "approved on")),
        FieldDef("approval_status", "Approval status", "category", False, _s("approval status", "status", "approved", "state")),
        FieldDef("comments", "Comments", "long_text", False, _s("sign off status", "comments", "remarks", "notes", ("approval comments", 0.9))),
    ),
)

GAP_SPEC = EntityDef(
    "gap_specification", "Gap / specification",
    (
        FieldDef("serial_no", "Serial no.", "number", False, _s("s no", "sr no", "serial no", "serial number", "sno")),
        FieldDef("external_issue_id", "External issue ID", "id", False, _s("issue id", "external issue id", "issue", "ticket id", "helpdesk id", "issue number")),
        FieldDef("event", "Event", "category", False, _s("event", "phase", "stage")),
        FieldDef("team", "Team", "category", False, _s("team", "department")),
        FieldDef("product_name", "Product", "category", False, _s("product", "product name")),
        FieldDef("module", "Module", "category", False, _s("module", ("area", 0.8), "functional area")),
        FieldDef("development_scope", "Development scope", "category", False, _s("development scope", "scope", "sub module")),
        FieldDef("description", "Description", "long_text", True, _s("brief description", "description", "summary", "details", "requirement")),
        FieldDef("priority", "Priority", "category", False, _s("priority", "severity")),
        FieldDef("category", "Category", "category", False, _s("category", "type", "gap type")),
        FieldDef("wfx_solution", "Proposed WFX solution", "long_text", False, _s("wfx solution", "proposed wfx solution", "solution", "proposed solution")),
        FieldDef("spec_status", "Specification status", "category", False, _s("spec status", "specification status", ("current status", 0.9), "status")),
        FieldDef("remarks", "Remarks", "long_text", False, _s("remarks", "notes", "comments")),
        FieldDef("responsibility", "Responsibility", "category", False, _s("responsibility", "responsible", "owner", "assigned to")),
        FieldDef("target_date", "Specs target date", "date", False, _s("specs target date", "target date", "target", "due date")),
        FieldDef("actual_date", "Specs actual date", "date", False, _s("specs actual date", "actual date", "actual")),
        FieldDef("submission_date", "Specs submission date", "date", False, _s("specs submission date", "submission date", "submitted on date", "submitted on")),
        FieldDef("signoff_date", "Sign-off date", "date", False, _s("sign off date", "signoff date", "signed off date", "signed off")),
        FieldDef("approval_status", "Approval status", "category", False, _s("approval status", "approval")),
        FieldDef("received_date", "Received on", "date", False, _s("received on date", "received on", "received date")),
        FieldDef("created_date", "Created on", "date", False, _s("created on date", "created on", "created date")),
        FieldDef("proto_status", "Prototype status", "category", False, _s("proto created", "prototype", "proto status")),
        FieldDef("specs_created", "Specs created", "category", False, _s("specs created", "spec created")),
    ),
)

DEPENDENCY_ITEM = EntityDef(
    "dependency_item", "Pending item (customer / WFX / partner)",
    (
        FieldDef("description", "Description", "long_text", True, _s("components", "component", "description", "pending item", "item", "activity", "brief description")),
        FieldDef("pending_with", "Pending with", "category", True, _s("responsibility", "pending with", "pending on", "owner party", "responsible party")),
        FieldDef("owner_name", "Owner", "text", False, _s("responsibility wfx owner", "wfx owner", "owner", "assigned to", "responsible person", "spoc")),
        FieldDef("original_target_date", "Original target date", "date", False, _s("target date", "original target date", "target", "due date", "planned date")),
        FieldDef("revised_target_date", "Revised target date", "date", False, _s("revised target date", "revised target", "revised date", "new target date")),
        FieldDef("actual_closure_date", "Actual closure date", "date", False, _s("actual closure date", "actual closure", "closed on", "closure date", "actual date")),
        FieldDef("status", "Status", "status", False, _s("status", "current status")),
        FieldDef("remarks", "Remarks", "long_text", False, _s("meeting remarks", "remarks", "notes", "comments", "remark")),
    ),
)

_DELIVERY_COMMON = (
    FieldDef("external_id", "Delivery / helpdesk ID", "id", True, _s("id", "helpdesk id", "ticket id", "delivery id", "tracker id")),
    FieldDef("stream", "Stream", "category", False, _s("stream")),
    FieldDef("module", "Module", "category", False, _s("module")),
    FieldDef("description", "Description", "long_text", True, _s("description", "brief description")),
    FieldDef("priority", "Priority", "category", False, _s("priority")),
    FieldDef("helpdesk_status", "WFX helpdesk status", "status", False, _s("wfx helpdesk status", "helpdesk status")),
    FieldDef("status", "Delivery status", "status", False, _s("status", "delivery status")),
    FieldDef("functional_owner", "Functional owner", "text", False, _s("functional owner")),
    FieldDef("customer_discussion_status", "Customer discussion status", "category", False, _s("customer discussion status", "customer disucssion status")),
    FieldDef("spec_closure_date", "Customer spec closure (planned)", "date", False, _s("customer spec closure date", "customer spec closure date planned", "spec closure date")),
    FieldDef("dev_initiation", "Dev initiation", "date", False, _s("dev initiation date", "development initiation date")),
    FieldDef("dev_completion", "Handover to QA (dev completion)", "date", False, _s("handover to qa date dev completion date", "handover to qa date", "handover to qa", "dev completion date")),
    FieldDef("qa_release", "QA release", "date", False, _s("qa release date positive flow", "qa release date")),
    FieldDef("uat_release", "Release to UAT server", "date", False, _s("internal release to uat server positive flow", "relase to customer uat server release", "release to customer uat server release", "release to uat server")),
    FieldDef("dev_remarks", "Dev remarks", "long_text", False, _s("dev remarks", "development remarks")),
)

DELIVERY_SCHEDULE = EntityDef(
    "delivery_schedule", "Delivery schedule (delivery item)",
    _DELIVERY_COMMON + (
        FieldDef("customer_release", "Customer UAT release", "date", False, _s("customer release date on customer uat", "customer release date")),
        FieldDef("specs_responsibility", "Specs responsibility", "text", False, _s("specs responsibility", "spec responsibility")),
        FieldDef("spec_target_date", "Specs target date", "date", False, _s("target date", "specs target date")),
        FieldDef("testing_responsibility", "Testing responsibility", "text", False, _s("testing responsibility")),
        FieldDef("remarks", "Remarks", "long_text", False, _s("remarks")),
        FieldDef("tracker_ref", "Tracker reference", "long_text", False, _s("shahi tracker ref", "tracker ref", "tracker reference")),
        FieldDef("helpdesk_description", "Helpdesk description", "long_text", False, _s("helpdesk description")),
    ),
)

TECH_TRACKER = EntityDef(
    "tech_tracker", "Technical development tracker (delivery item)",
    _DELIVERY_COMMON + (
        FieldDef("product_owner", "Product owner", "text", False, _s("product owner")),
        FieldDef("tech_owner", "Technical owner", "text", False, _s("tech owner", "technical owner")),
        FieldDef("qa_owner", "QA owner", "text", False, _s("qa owner")),
        FieldDef("functional_specs_status", "Functional specs status", "category", False, _s("functional specs status", "functional spec status")),
        FieldDef("spec_closure_actual", "Customer spec closure (actual)", "date", False, _s("customer spec closure date actual")),
        FieldDef("high_level_status", "Specs discussion: high level", "category", False, _s("specs discussion status high level")),
        FieldDef("high_level_date", "High level date", "date", False, _s("high level date")),
        FieldDef("detail_level_status", "Specs discussion: detailed", "category", False, _s("specs discussion status detailed level")),
        FieldDef("detail_level_date", "Detail level date", "date", False, _s("detail level date")),
        FieldDef("customer_uat_closure", "Customer UAT closure", "date", False, _s("customer uat closure")),
        FieldDef("meeting_remarks", "Meeting remarks", "long_text", False, _s("meeting remarks")),
        FieldDef("target_brd_closure", "Target BRD closure", "date", False, _s("target brd clsoure date", "target brd closure date")),
        FieldDef("pd_remarks", "PD remarks", "long_text", False, _s("pd remarks")),
    ),
)

BRD_REQUIREMENT = EntityDef(
    "brd_requirement", "BRD requirement",
    (
        FieldDef("sr_no", "Source serial no.", "id", False, _s("sr no", "s no", "serial no", "sno")),
        FieldDef("brd_serial", "BRD serial", "id", False, _s("brd sr", "brd serial no", "brd serial", "brd sr no")),
        FieldDef("description", "Requirement (key pointer)", "long_text", True, _s("key pointers", "key pointer", "description", "requirement")),
        FieldDef("module", "Module", "category", False, _s("module")),
        FieldDef("brd_status", "BRD status", "category", False, _s("brd status")),
        FieldDef("development_phase", "Development phase", "category", False, _s("development phase")),
        FieldDef("covered_in_proto", "Covered in prototype", "category", False, _s("covered in proto", "covered in prototype")),
        FieldDef("responsibility", "Responsibility", "text", False, _s("responsibility", "responsible")),
        FieldDef("target_date", "Target date", "date", False, _s("target date", "target")),
        FieldDef("remarks", "Remarks", "long_text", False, _s("remarks")),
        FieldDef("req_type", "Type", "category", False, _s("type")),
    ),
)

HELPDESK_OPS_BRD = EntityDef(
    "helpdesk_ops_brd", "Helpdesk item (Operations BRD)",
    (
        FieldDef("sr_no", "Source serial no.", "id", False, _s("s no", "sr no", "sno")),
        FieldDef("category", "Category", "category", False, _s("category")),
        FieldDef("external_id", "Helpdesk ID", "id", True, _s("helpdesk id", "ticket id")),
        FieldDef("tracker_ref", "Tracker reference", "long_text", False, _s("shahi tracker ref", "tracker ref")),
        FieldDef("description", "Helpdesk description", "long_text", True, _s("helpdesk description", "description")),
        FieldDef("status", "BRD status", "status", False, _s("brd status", "status")),
        FieldDef("responsibility", "Responsibility (WFX)", "text", False, _s("brd responsibility wfx", "responsibility")),
        FieldDef("target_date", "Target closure date", "date", False, _s("target closure date", "target date")),
    ),
)

OPS_OPEN_POINT = EntityDef(
    "ops_open_point", "New / open operations point",
    (
        FieldDef("sr_no", "Source serial no.", "id", False, _s("s no", "sr no", "sno")),
        FieldDef("request_date", "Request date", "date", False, _s("request date")),
        FieldDef("request_from", "Request from", "text", False, _s("request from", "requested by")),
        FieldDef("division", "Division", "category", False, _s("division")),
        FieldDef("description", "Description", "long_text", True, _s("description")),
        FieldDef("status", "Status", "status", False, _s("status")),
    ),
)

DISCUSSION_ITEM = EntityDef(
    "discussion_item", "Open discussion item",
    (
        FieldDef("sr_no", "Source serial no.", "id", False, _s("sr no", "s no", "sno")),
        FieldDef("name", "Name / topic", "long_text", True, _s("name", "title", "topic")),
        FieldDef("brd_serial", "BRD serial", "id", False, _s("brd serial no", "brd serial", "brd sr")),
        FieldDef("tracker_sr_no", "Tracker serial", "id", False, _s("tracker sr no", "tracker serial no")),
        FieldDef("remarks", "Remarks", "long_text", False, _s("remarks")),
        FieldDef("item_type", "Type", "category", False, _s("type")),
        FieldDef("module", "Module", "category", False, _s("module")),
        FieldDef("concern", "Concern", "long_text", False, _s("concern")),
        FieldDef("functionality_status", "Functionality status", "category", False, _s("functionality status")),
        FieldDef("document_reference", "Document reference", "text", False, _s("document reference")),
        FieldDef("responsibility", "Responsibility", "text", False, _s("report responsibility", "responsibility")),
        FieldDef("target_date", "Target date", "date", False, _s("target date")),
    ),
)

SCOPE_DECISION = EntityDef(
    "scope_decision", "Out-of-scope request",
    (
        FieldDef("customer_feedback", "Customer feedback", "long_text", True, _s("feedback", "customer feedback")),
        FieldDef("original_scope", "Scope as agreed (BRD)", "long_text", False, _s("scope as per brd", "original scope", "agreed scope")),
        FieldDef("new_requirement", "New requirement", "long_text", False, _s("requirement", "new requirement")),
    ),
)

UAT_SCENARIO = EntityDef(
    "uat_scenario", "UAT scenario",
    (
        FieldDef("scenario_id", "Scenario ID", "id", False, _s("scenario id", "test case id", "test case no", "tc id", "tc no", "scenario no", "scenario number", "s no", "sr no")),
        FieldDef("title", "Scenario", "long_text", True, _s(("scenario title", 1.3), "scenario", "test scenario", "scenario description", "scenario name", "test case", "description")),
        FieldDef("module", "Module", "category", False, _s("module", "functional area", "area")),
        FieldDef("functionality", "Functionality", "text", False, _s("functionality", "function", "feature")),
        FieldDef("scenario_type", "Scenario type", "category", False, _s("scenario type", "test type", "type")),
        FieldDef("source_ref", "Source", "text", False, _s("source id", "source", "source reference", "reference")),
        FieldDef("linked_cases", "Linked test cases", "long_text", False, _s("linked test cases", "linked cases", "test cases")),
        FieldDef("uat_role", "UAT role (executor)", "text", False, _s("uat role executor", "uat role", "executor", "role")),
        FieldDef("business_objective", "Business objective", "long_text", False, _s("business objective", "objective", "purpose")),
        FieldDef("pre_condition", "Pre-condition", "long_text", False, _s("pre condition", "precondition", "pre requisite", "prerequisite")),
        FieldDef("test_data", "Test data", "long_text", False, _s("test data", "data")),
        FieldDef("steps", "Steps", "long_text", False, _s("test steps", "steps", "procedure")),
        FieldDef("expected_result", "Expected result", "long_text", False, _s("expected result", "expected outcome", "expected")),
        FieldDef("tester", "Tester", "text", False, _s("tested by", "tester", "executed by", "assigned to")),
        FieldDef("cycle", "UAT cycle", "category", False, _s("uat cycle", "cycle", "round", "uat round")),
        FieldDef("planned_date", "Planned date", "date", False, _s("planned date", "test date", "target date", "plan date", "due date")),
        FieldDef("executed_date", "Executed on", "date", False, _s("executed on", "execution date", "tested on", "executed date", "actual date")),
        FieldDef("result", "Result / status", "category", False, _s("status pass fail", "test status", "uat status", "execution status", "result", "status", "pass fail")),
        FieldDef("actual_result", "Actual result", "long_text", False, _s("actual result", "actual outcome", "actual")),
        FieldDef("defect_ref", "Defect reference", "text", False, _s("defect id", "defect no", "bug id", "defect", "issue id")),
        FieldDef("remarks", "Remarks", "long_text", False, _s("remarks", "comments", "notes")),
    ),
)

INTEGRATION_ITEM = EntityDef(
    "integration_item", "Integration",
    (
        FieldDef("name", "Integration", "long_text", False, _s("integration", "interface", "interface name", "integration name", "name", "message format", "description")),
        FieldDef("company", "Company", "text", False, _s("company", "legal entity")),
        FieldDef("process", "Process", "text", False, _s("process", "business process")),
        FieldDef("partner", "Partner / system", "text", False, _s("partner system", "partner", "third party", "vendor", "customer system")),
        FieldDef("system", "System", "text", False, _s("system", "application", "erp system")),
        FieldDef("documented", "Documented", "category", False, _s("documented", "documentation")),
        FieldDef("wfx_status", "WFX status", "category", False, _s("wfx status", "wfx review status")),
        FieldDef("direction", "Direction", "category", False, _s("direction", "flow", "inbound outbound")),
        FieldDef("technology", "Technology", "category", False, _s("technology", "protocol", "method", "integration type", "mode")),
        FieldDef("message_type", "Message / object", "text", False, _s("message format", "message type", "message", "object", "document type")),
        FieldDef("business_domain", "Business domain", "category", False, _s("business domain", "domain")),
        FieldDef("region", "Region", "category", False, _s("region entity", "region", "country", "location")),
        FieldDef("endpoint", "Endpoint", "long_text", False, _s("system path url endpoing", "system path url endpoint", "endpoint", "url endpoint", "system path", "url", "path", "host")),
        FieldDef("owner_name", "Owner", "text", False, _s("owner", "responsible", "assigned to", "developer", "spoc")),
        FieldDef("status", "Status", "status", False, _s("status", "current status", "development status")),
        FieldDef("target_date", "Target date", "date", False, _s("specs target date", "target date", "planned date", "due date", "go live date", "target")),
        FieldDef("actual_date", "Actual date", "date", False, _s("specs actual date", "actual date", "completed on", "actual completion")),
        FieldDef("uat_status", "UAT status", "category", False, _s("uat status", "test status")),
        FieldDef("remarks", "Remarks", "long_text", False, _s("remarks", "comments", "notes")),
    ),
)

REPORT_ITEM = EntityDef(
    "report_item", "Report / print",
    (
        FieldDef("name", "Report / print", "long_text", False, _s("report name", "report", "print name", "name", "form name", "description", "sub folder")),
        FieldDef("report_type", "Type", "category", False, _s("report type", "type", "category")),
        FieldDef("module", "Module", "category", False, _s("module", "functional area")),
        FieldDef("folder", "Folder", "category", False, _s("folder", "report folder")),
        FieldDef("sub_folder", "Sub folder", "category", False, _s("sub folder", "subfolder")),
        FieldDef("reports_count", "Reports count", "number", False, _s("reports count", "report count", "count", "no of reports")),
        FieldDef("complexity", "Complexity", "category", False, _s("complexity", "effort")),
        FieldDef("owner_name", "Owner", "text", False, _s("developer", "owner", "responsible", "assigned to")),
        FieldDef("status", "Status", "status", False, _s("status", "current status", "development status")),
        FieldDef("target_date", "Target date", "date", False, _s("target date", "planned date", "due date", "target")),
        FieldDef("actual_date", "Actual date", "date", False, _s("actual date", "completed on", "actual completion")),
        FieldDef("uat_status", "UAT status", "category", False, _s("uat status", "test status")),
        FieldDef("remarks", "Remarks", "long_text", False, _s("remarks", "comments", "notes")),
    ),
)

ENTITIES: dict[str, EntityDef] = {
    e.key: e for e in (PLAN_TASK, TRACKER_EVENT, APPROVAL_GATE, GAP_SPEC, DEPENDENCY_ITEM, DELIVERY_SCHEDULE, TECH_TRACKER,
                       BRD_REQUIREMENT, HELPDESK_OPS_BRD, OPS_OPEN_POINT, DISCUSSION_ITEM, SCOPE_DECISION, UAT_SCENARIO, INTEGRATION_ITEM, REPORT_ITEM)
}

# Delivery Schedule and Tech_Final both describe the same tickets. When a ticket already exists from the OTHER sheet, only the
# fields listed here are overwritten by this sheet; every other field is filled only if empty, and a disagreement is recorded.
# (Decision 3: Tech_Final is authoritative for owner/QA fields, Delivery Schedule for customer-facing dates.)
AUTHORITY: dict[str, frozenset[str]] = {
    "delivery_schedule": frozenset({"spec_closure_date", "dev_initiation", "dev_completion", "qa_release", "uat_release", "customer_release",
                                    "spec_target_date", "specs_responsibility", "testing_responsibility", "remarks", "tracker_ref", "helpdesk_description"}),
    "tech_tracker": frozenset({"functional_owner", "product_owner", "tech_owner", "qa_owner", "functional_specs_status", "spec_closure_actual",
                               "high_level_status", "high_level_date", "detail_level_status", "detail_level_date", "customer_uat_closure",
                               "dev_remarks", "meeting_remarks", "target_brd_closure", "pd_remarks"}),
}
STATUS_PREFIX_RULES = (("pending with", "blocked"), ("on hold", "blocked"), ("delivery closure received", "done"))


def categorize_status(value: str) -> str | None:
    """Status text -> category (done / in_progress / ...). Exact synonym first, then a few prefix rules; unknown stays None."""
    v = " ".join(value.lower().split())
    if v in STATUS_CATEGORY:
        return STATUS_CATEGORY[v]
    return next((cat for prefix, cat in STATUS_PREFIX_RULES if v.startswith(prefix)), None)

# Sheet classes. `entity` None = recognised and profiled, but import target is built in a later phase.
CLASS_ENTITY: dict[str, str | None] = {
    "project_plan": "plan_task",
    "milestone_matrix": "tracker_event",
    "approval_signoff": "approval_gate",
    "gap_tracker": "gap_specification",
    "uat_scenarios": "uat_scenario",
    "integration_register": "integration_item",
    "reports_inventory": "report_item",
    "delivery_schedule": "delivery_schedule",
    "tech_tracker": "tech_tracker",
    "brd": "brd_requirement",
    "helpdesk_brd": "helpdesk_ops_brd",
    "open_points": "ops_open_point",
    "discussion": "discussion_item",
    "scope": "scope_decision",
    "dependency_register": "dependency_item",
    "wbs": None,
    "lookup": None,
    "unknown": None,
}
CLASS_LABEL = {
    "project_plan": "Project plan", "milestone_matrix": "Milestone matrix (events x products)",
    "approval_signoff": "Sign-off / approval gates", "gap_tracker": "Gap / specification tracker",
    "uat_scenarios": "UAT scenarios", "integration_register": "Integration register",
    "reports_inventory": "Reports + prints inventory", "delivery_tracker": "Delivery tracker",
    "brd": "BRD / requirements", "dependency_register": "Pending items / dependencies", "wbs": "WBS",
    "lookup": "Lookup list", "unknown": "Unknown",
}
NOT_YET = {
    "wbs": "Phase 7",
}

STATUS_CATEGORY = {
    "done": "done", "complete": "done", "completed": "done", "closed": "done", "approved": "done", "signed off": "done",
    "in progress": "in_progress", "in-progress": "in_progress", "wip": "in_progress", "ongoing": "in_progress", "started": "in_progress",
    "not started": "not_started", "pending": "not_started", "planned": "not_started", "open": "not_started", "new": "not_started",
    "blocked": "blocked", "on hold": "blocked", "hold": "blocked",
    "cancelled": "cancelled", "canceled": "cancelled", "dropped": "cancelled",
    # delivery lifecycle wording (clear cases only; wording such as "Pending For Delivery" is left for the user to classify)
    "under development": "in_progress", "in qa": "in_progress", "qa complete": "in_progress", "deployed on test": "in_progress",
    "dev initiated": "in_progress", "development complete": "in_progress", "approved for release": "in_progress",
    "under impl. review": "in_progress", "under evaluation": "in_progress", "under discussion": "in_progress",
    "deployed on live": "done",
}
MODE_CATEGORY = {"onsite": "onsite", "on-site": "onsite", "on site": "onsite", "remote": "online", "online": "online", "offsite": "online"}


# UAT results: the customer's wording -> one of our six results. Unknown wording is never guessed: it is reported and the scenario stays "not run".
UAT_RESULTS = {
    "passed": "passed", "pass": "passed", "p": "passed", "ok": "passed", "success": "passed", "successful": "passed", "accepted": "passed", "signed off": "passed", "closed": "passed",
    "failed": "failed", "fail": "failed", "f": "failed", "ng": "failed", "rejected": "failed", "not ok": "failed",
    "blocked": "blocked", "on hold": "blocked", "hold": "blocked", "cannot test": "blocked",
    "retest": "retest", "re test": "retest", "re-test": "retest", "to be retested": "retest", "retest required": "retest", "fixed": "retest",
    "in progress": "in_progress", "in-progress": "in_progress", "wip": "in_progress", "testing": "in_progress", "started": "in_progress", "ongoing": "in_progress", "partially passed": "in_progress",
    "not run": "not_run", "not started": "not_run", "pending": "not_run", "yet to start": "not_run", "open": "not_run", "new": "not_run", "planned": "not_run", "": "not_run",
}


def uat_result(value: str | None) -> str | None:
    return UAT_RESULTS.get(" ".join((value or "").lower().split()))
