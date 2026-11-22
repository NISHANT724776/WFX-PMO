export type RefKind = "products" | "departments" | "locations" | "scenarios";
export type FieldKind = "text" | "area" | "date" | "select" | "ref" | "number";
export type FormField = { key: string; label: string; kind: FieldKind; options?: string[]; wide?: boolean; ref?: RefKind; createOnly?: boolean };
export type Column = { key: string; label: string; date?: boolean; wide?: boolean; ref?: RefKind };
export type KindConfig = {
  slug: string;
  label: string;
  singular: string;
  typeName: string; // used by links
  columns: Column[];
  filters: { key: string; label: string; ref?: RefKind }[];
  fields: FormField[];
  required: string[];
  statusEntity?: string; // a "Status" select backed by the status dictionary
  statusField?: string; // the record field that shows the current status label (default status_raw)
  revisionLabel?: string; // the record has a baseline date that is changed through revisions
  titleKey: string;
};

const t = (key: string, label: string, wide = false): FormField => ({ key, label, kind: "text", wide });
const a = (key: string, label: string): FormField => ({ key, label, kind: "area", wide: true });
const d = (key: string, label: string): FormField => ({ key, label, kind: "date" });
const r = (key: string, label: string, ref: RefKind): FormField => ({ key, label, kind: "ref", ref });
const n = (key: string, label: string): FormField => ({ key, label, kind: "number" });

export const KINDS: KindConfig[] = [
  {
    slug: "delivery-items", label: "Delivery items", singular: "delivery item", typeName: "delivery_item", titleKey: "description", statusEntity: "delivery_item", revisionLabel: "Delivery date",
    columns: [{ key: "external_id", label: "ID" }, { key: "stream", label: "Stream" }, { key: "module", label: "Module" }, { key: "description", label: "Description", wide: true }, { key: "status_raw", label: "Status" },
      { key: "helpdesk_status_raw", label: "Helpdesk" }, { key: "tech_owner", label: "Tech owner" }, { key: "effective_target_date", label: "Delivery date", date: true }],
    filters: [{ key: "stream", label: "Stream" }, { key: "status_category", label: "Status category" }, { key: "helpdesk_status_category", label: "Helpdesk category" }, { key: "priority", label: "Priority" }, { key: "module", label: "Module" }, { key: "tech_owner", label: "Tech owner" }],
    required: ["description"],
    fields: [a("description", "Description"), t("external_id", "Delivery / helpdesk ID"), t("stream", "Stream"), t("module", "Module"), t("priority", "Priority"), t("functional_owner", "Functional owner"), t("product_owner", "Product owner"),
      t("tech_owner", "Technical owner"), t("qa_owner", "QA owner"), t("specs_responsibility", "Specs responsibility"), t("testing_responsibility", "Testing responsibility"), t("customer_discussion_status", "Customer discussion status"),
      t("functional_specs_status", "Functional specs status"), d("spec_closure_date", "Customer spec closure (planned)"), d("spec_closure_actual", "Customer spec closure (actual)"), d("dev_initiation", "Dev initiation"),
      d("dev_completion", "Handover to QA"), d("qa_release", "QA release"), d("uat_release", "Release to UAT server"), d("customer_release", "Customer UAT release"), d("customer_uat_closure", "Customer UAT closure"),
      d("actual_completion", "Actual completion"), a("dev_remarks", "Dev remarks"), a("meeting_remarks", "Meeting remarks"), a("pd_remarks", "PD remarks"), a("remarks", "Remarks")],
  },
  {
    slug: "requirements", label: "Requirements (BRD)", singular: "requirement", typeName: "brd_requirement", titleKey: "description", revisionLabel: "Target date",
    columns: [{ key: "sr_no", label: "Sr" }, { key: "brd_serial", label: "BRD serial" }, { key: "description", label: "Requirement", wide: true }, { key: "module", label: "Module" }, { key: "brd_status", label: "BRD status" },
      { key: "covered_in_proto", label: "In prototype" }, { key: "responsibility", label: "Responsibility" }, { key: "effective_target_date", label: "Target", date: true }],
    filters: [{ key: "module", label: "Module" }, { key: "brd_status", label: "BRD status" }, { key: "covered_in_proto", label: "In prototype" }, { key: "responsibility", label: "Responsibility" }],
    required: ["description"],
    fields: [a("description", "Requirement"), t("brd_serial", "BRD serial"), t("sr_no", "Source serial no."), t("module", "Module"), t("brd_status", "BRD status"), t("development_phase", "Development phase"),
      t("covered_in_proto", "Covered in prototype"), t("responsibility", "Responsibility"), t("req_type", "Type"), a("remarks", "Remarks")],
  },
  {
    slug: "helpdesk-items", label: "Helpdesk & operations", singular: "helpdesk item", typeName: "helpdesk_item", titleKey: "description", statusEntity: "helpdesk_item",
    columns: [{ key: "kind", label: "Kind" }, { key: "external_id", label: "Helpdesk ID" }, { key: "category", label: "Category" }, { key: "description", label: "Description", wide: true }, { key: "status_raw", label: "Status" },
      { key: "responsibility", label: "Responsibility" }, { key: "target_date", label: "Target", date: true }],
    filters: [{ key: "kind", label: "Kind" }, { key: "category", label: "Category" }, { key: "status_category", label: "Status category" }, { key: "responsibility", label: "Responsibility" }],
    required: ["description"],
    fields: [a("description", "Description"), t("external_id", "Helpdesk ID"), t("category", "Category"), t("responsibility", "Responsibility"), d("target_date", "Target closure date"),
      t("request_from", "Request from"), t("division", "Division"), d("request_date", "Request date"), a("remarks", "Remarks")],
  },
  {
    slug: "gap-specifications", label: "Gaps & specifications", singular: "gap specification", typeName: "gap_specification", titleKey: "description", revisionLabel: "Specs target date",
    columns: [{ key: "external_issue_id", label: "Issue ID" }, { key: "event", label: "Event" }, { key: "module", label: "Module" }, { key: "description", label: "Description", wide: true }, { key: "priority", label: "Priority" },
      { key: "spec_status", label: "Spec status" }, { key: "responsibility", label: "Responsibility" }, { key: "effective_target_date", label: "Target", date: true }, { key: "approval_status", label: "Approval" }],
    filters: [{ key: "event", label: "Event" }, { key: "team", label: "Team" }, { key: "module", label: "Module" }, { key: "priority", label: "Priority" }, { key: "spec_status", label: "Spec status" }, { key: "responsibility", label: "Responsibility" }, { key: "approval_status", label: "Approval" }],
    required: ["description"],
    fields: [a("description", "Description"), t("external_issue_id", "External issue ID"), t("event", "Event"), t("team", "Team"), t("module", "Module"), t("development_scope", "Development scope"), t("priority", "Priority"),
      t("category", "Category"), a("wfx_solution", "Proposed WFX solution"), t("spec_status", "Specification status"), t("responsibility", "Responsibility"), d("actual_date", "Specs actual date"),
      d("submission_date", "Submission date"), d("signoff_date", "Sign-off date"), t("approval_status", "Approval status"), a("remarks", "Remarks")],
  },
  {
    slug: "discussions", label: "Open discussions", singular: "discussion", typeName: "discussion_item", titleKey: "name",
    columns: [{ key: "name", label: "Topic", wide: true }, { key: "item_type", label: "Type" }, { key: "module", label: "Module" }, { key: "concern", label: "Concern", wide: true }, { key: "responsibility", label: "Responsibility" },
      { key: "target_date", label: "Target", date: true }, { key: "status", label: "Status" }],
    filters: [{ key: "item_type", label: "Type" }, { key: "module", label: "Module" }, { key: "status", label: "Status" }, { key: "responsibility", label: "Responsibility" }],
    required: ["name"],
    fields: [a("name", "Topic"), a("concern", "Concern"), t("module", "Module"), t("item_type", "Type"), t("responsibility", "Responsibility"), d("target_date", "Target date"),
      { key: "status", label: "Status", kind: "select", options: ["open", "decided", "closed"] }, a("final_decision", "Final decision"), a("meeting_remarks", "Meeting remarks"), a("remarks", "Remarks")],
  },
  {
    slug: "scope-decisions", label: "Out of scope", singular: "scope request", typeName: "scope_decision", titleKey: "customer_feedback",
    columns: [{ key: "customer_feedback", label: "Customer feedback", wide: true }, { key: "original_scope", label: "Scope as agreed", wide: true }, { key: "new_requirement", label: "New requirement" },
      { key: "approval_status", label: "Decision" }, { key: "decision_owner", label: "Decided by" }, { key: "decision_date", label: "Date", date: true }],
    filters: [{ key: "approval_status", label: "Decision" }, { key: "decision_owner", label: "Decided by" }],
    required: ["customer_feedback"],
    fields: [a("customer_feedback", "Customer feedback"), a("original_scope", "Scope as agreed (BRD)"), a("new_requirement", "New requirement"), a("reason", "Reason"),
      { key: "approval_status", label: "Decision", kind: "select", options: ["pending", "approved", "rejected"] }, t("decision_owner", "Decision owner"), d("decision_date", "Decision date"), a("remarks", "Remarks")],
  },
  {
    slug: "action-items", label: "Actions", singular: "action", typeName: "action_item", titleKey: "title",
    columns: [{ key: "title", label: "Action", wide: true }, { key: "owner_name", label: "Owner" }, { key: "priority", label: "Priority" }, { key: "due_date", label: "Due", date: true },
      { key: "status", label: "Status" }, { key: "last_action", label: "Latest action", wide: true }],
    filters: [{ key: "status", label: "Status" }, { key: "priority", label: "Priority" }, { key: "owner_name", label: "Owner" }],
    required: ["title"],
    fields: [a("title", "Action"), a("description", "Description"), t("owner_name", "Owner"), { key: "priority", label: "Priority", kind: "select", options: ["low", "medium", "high", "critical"] }, d("due_date", "Due date"),
      { key: "status", label: "Status", kind: "select", options: ["open", "in_progress"] }],
  },
  {
    slug: "approval-gates", label: "Sign-off gates", singular: "sign-off gate", typeName: "approval_gate", titleKey: "name", statusEntity: "approval_gate", statusField: "approval_status",
    columns: [{ key: "gate_type", label: "Set" }, { key: "name", label: "Gate", wide: true }, { key: "product_id", label: "Product", ref: "products" }, { key: "approver_name", label: "Approver" },
      { key: "planned_date", label: "Planned", date: true }, { key: "submission_date", label: "Submitted", date: true }, { key: "signoff_date", label: "Approved", date: true }, { key: "approval_status", label: "Status" }],
    filters: [{ key: "gate_type", label: "Set" }, { key: "approval_status", label: "Status" }, { key: "approver_name", label: "Approver" }],
    required: ["name"],
    fields: [a("name", "Gate"), t("gate_type", "Set (e.g. blueprint sign-off)"), r("product_id", "Product", "products"), t("approver_name", "Approver"), d("planned_date", "Planned date"),
      d("submission_date", "Submission date"), d("signoff_date", "Approval date"), a("comments", "Comments (needed when rejected)")],
  },
  {
    slug: "coverage-activities", label: "Coverage activities", singular: "coverage activity", typeName: "coverage_activity", titleKey: "title",
    columns: [{ key: "title", label: "Activity", wide: true }, { key: "department_id", label: "Department", ref: "departments" }, { key: "location_id", label: "Location", ref: "locations" },
      { key: "product_id", label: "Product", ref: "products" }, { key: "responsible_name", label: "Responsible" }, { key: "planned_count", label: "Planned" }, { key: "completed_count", label: "Completed" }, { key: "pct", label: "%" }],
    filters: [{ key: "department_id", label: "Department", ref: "departments" }, { key: "location_id", label: "Location", ref: "locations" }, { key: "responsible_name", label: "Responsible" }],
    required: ["title", "department_id", "location_id"],
    fields: [a("title", "Activity"), r("department_id", "Department", "departments"), r("location_id", "Location", "locations"), r("product_id", "Product", "products"), t("responsible_name", "Responsible person"),
      n("planned_count", "Planned (count)"), n("completed_count", "Completed (count)"), a("remarks", "Remarks")],
  },
  {
    slug: "week-plan-items", label: "Week plan activities", singular: "planned activity", typeName: "week_plan_item", titleKey: "title",
    columns: [{ key: "week_start", label: "Week of", date: true }, { key: "title", label: "Activity", wide: true }, { key: "workstream", label: "Workstream" }, { key: "owner_name", label: "Owner" },
      { key: "module", label: "Module" }, { key: "target_date", label: "Target", date: true }, { key: "percent_complete", label: "%" }, { key: "status", label: "Status" }],
    filters: [{ key: "workstream", label: "Workstream" }, { key: "owner_name", label: "Owner" }, { key: "status", label: "Status" }, { key: "module", label: "Module" }],
    required: ["title"],
    fields: [a("title", "Activity"), t("workstream", "Workstream"), t("owner_name", "Owner"), r("product_id", "Product", "products"), t("module", "Module"), d("week_start", "Week starts (a Monday)"), d("target_date", "Target date"),
      n("percent_complete", "% complete (0-100)"), { key: "status", label: "Status", kind: "select", options: ["planned", "in_progress", "done"] }, a("remarks", "Remarks")],
  },
  {
    slug: "uat-scenarios", label: "UAT scenarios", singular: "UAT scenario", typeName: "uat_scenario", titleKey: "title",
    columns: [{ key: "scenario_id", label: "ID" }, { key: "title", label: "Scenario", wide: true }, { key: "module", label: "Module" }, { key: "cycle", label: "Cycle" }, { key: "tester", label: "Tester" },
      { key: "planned_date", label: "Planned", date: true }, { key: "executed_date", label: "Executed", date: true }, { key: "result", label: "Result" }, { key: "defect_ref", label: "Defect" }],
    filters: [{ key: "result", label: "Result" }, { key: "module", label: "Module" }, { key: "cycle", label: "Cycle" }, { key: "tester", label: "Tester" }],
    required: ["title"],
    fields: [a("title", "Scenario"), t("scenario_id", "Scenario ID"), t("module", "Module"), t("cycle", "UAT cycle"), r("product_id", "Product", "products"), t("tester", "Tester"), d("planned_date", "Planned date"), d("executed_date", "Executed on"),
      { key: "result", label: "Result", kind: "select", options: ["not_run", "in_progress", "passed", "failed", "blocked", "retest"] }, a("actual_result", "Actual result (needed when failed)"), t("defect_ref", "Defect reference"),
      a("business_objective", "Business objective"), a("pre_condition", "Pre-condition"), a("test_data", "Test data"), a("steps", "Steps"), a("expected_result", "Expected result"), a("remarks", "Remarks")],
  },
  {
    slug: "uat-defects", label: "UAT defects", singular: "defect", typeName: "uat_defect", titleKey: "title",
    columns: [{ key: "defect_ref", label: "Ref" }, { key: "title", label: "Defect", wide: true }, { key: "scenario_id", label: "Scenario", ref: "scenarios" }, { key: "severity", label: "Severity" }, { key: "status", label: "Status" },
      { key: "owner_name", label: "Owner" }, { key: "raised_on", label: "Raised", date: true }, { key: "target_date", label: "Target", date: true }, { key: "closed_on", label: "Closed", date: true }],
    filters: [{ key: "status", label: "Status" }, { key: "severity", label: "Severity" }, { key: "owner_name", label: "Owner" }],
    required: ["title"],
    fields: [a("title", "Defect"), t("defect_ref", "Defect reference"), r("scenario_id", "Scenario", "scenarios"), r("product_id", "Product", "products"), { key: "severity", label: "Severity", kind: "select", options: ["low", "medium", "high", "critical"] },
      { key: "status", label: "Status", kind: "select", options: ["open", "in_fix", "retest", "closed", "rejected"] }, t("raised_by", "Raised by"), t("owner_name", "Owner"), d("raised_on", "Raised on"), d("target_date", "Target date"),
      d("closed_on", "Closed on (needed to close)"), a("resolution", "Resolution (needed to close or reject)"), a("description", "Description"), a("remarks", "Remarks")],
  },
  {
    slug: "integration-items", label: "Integrations", singular: "integration", typeName: "integration_item", titleKey: "name", statusEntity: "integration_item", revisionLabel: "Target date",
    columns: [{ key: "name", label: "Integration", wide: true }, { key: "partner", label: "Partner" }, { key: "direction", label: "Direction" }, { key: "technology", label: "Technology" }, { key: "region", label: "Region" },
      { key: "owner_name", label: "Owner" }, { key: "status_raw", label: "Status" }, { key: "effective_target_date", label: "Target", date: true }, { key: "uat_status", label: "UAT" }],
    filters: [{ key: "status_category", label: "Status category" }, { key: "direction", label: "Direction" }, { key: "technology", label: "Technology" }, { key: "partner", label: "Partner" }, { key: "region", label: "Region" }, { key: "owner_name", label: "Owner" }],
    required: ["name"],
    fields: [a("name", "Integration"), t("partner", "Partner"), t("system", "System"), { key: "direction", label: "Direction", kind: "select", options: ["inbound", "outbound", "bidirectional"] }, t("technology", "Technology (API, SFTP, EDI…)"),
      t("message_type", "Message / object"), t("business_domain", "Business domain"), t("region", "Region"), r("product_id", "Product", "products"), t("owner_name", "Owner"), { ...d("target_date", "Target date (baseline)"), createOnly: true },
      d("actual_date", "Actual date"), t("uat_status", "UAT status"), a("endpoint", "Endpoint"), a("remarks", "Remarks")],
  },
  {
    slug: "report-items", label: "Reports + prints", singular: "report or print", typeName: "report_item", titleKey: "name", statusEntity: "report_item", revisionLabel: "Target date",
    columns: [{ key: "name", label: "Report / print", wide: true }, { key: "report_type", label: "Type" }, { key: "module", label: "Module" }, { key: "folder", label: "Folder" }, { key: "sub_folder", label: "Sub folder" },
      { key: "reports_count", label: "Count" }, { key: "complexity", label: "Complexity" }, { key: "owner_name", label: "Owner" }, { key: "status_raw", label: "Status" }, { key: "effective_target_date", label: "Target", date: true }, { key: "uat_status", label: "UAT" }],
    filters: [{ key: "status_category", label: "Status category" }, { key: "report_type", label: "Type" }, { key: "module", label: "Module" }, { key: "folder", label: "Folder" }, { key: "complexity", label: "Complexity" }, { key: "owner_name", label: "Owner" }],
    required: ["name"],
    fields: [a("name", "Report / print"), t("report_type", "Type (report, print, form…)"), t("module", "Module"), t("folder", "Folder"), t("sub_folder", "Sub folder"), n("reports_count", "Reports count"),
      { key: "complexity", label: "Complexity", kind: "select", options: ["low", "medium", "high"] }, r("product_id", "Product", "products"), t("owner_name", "Owner"), { ...d("target_date", "Target date (baseline)"), createOnly: true },
      d("actual_date", "Actual date"), t("uat_status", "UAT status"), a("remarks", "Remarks")],
  },
];

/** The record types of the Delivery tab. Gates, coverage and week-plan activities live on the dashboards. */
export const DELIVERY_KINDS = KINDS.filter((k) => !["approval-gates", "coverage-activities", "week-plan-items", "uat-scenarios", "uat-defects", "integration-items", "report-items"].includes(k.slug));

export const BY_SLUG = Object.fromEntries(KINDS.map((k) => [k.slug, k]));
export const BY_TYPE = Object.fromEntries(KINDS.map((k) => [k.typeName, k]));

export type Rec = Record<string, unknown> & {
  id: string; title: string; is_overdue?: boolean; is_start_delayed?: boolean; is_closed?: boolean; days_late?: number; slippage_days?: number; effective_target_date?: string | null;
  stages?: { key: string; label: string; date: string | null; state: "done" | "late" | "upcoming" | "none" }[];
  links?: { id: string; link_type: string; basis: string | null; kind: string; type: string; record_id: string; title: string }[];
  revisions?: { id: string; field: string; old_date: string | null; new_date: string; reason: string; status: "proposed" | "approved" | "rejected"; requested_by_email: string | null; requested_at: string; decided_by_email: string | null }[];
  merge_notes?: Record<string, { kept?: unknown; ignored?: unknown; replaced?: unknown; from: string }> | null;
  sources?: string[] | null;
};

export type Suggestion = { rule: string; source_type: string; source_id: string; target_type: string; target_id: string; link_type: string; basis: string; source_title: string; target_title: string; ambiguous: boolean };
