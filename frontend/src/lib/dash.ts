export type RowState = "done" | "in_progress" | "overdue" | "upcoming";
export type Ref = { type: string; id: string | null; title?: string; label?: string; area?: string };

export type DashRow = {
  label: string; area: string; state: RowState; pct: number; start: string | null; end: string | null; items: number; done: number; late_items: number;
  stars: { date: string | null; title: string; id: string; type: string }[]; refs: Ref[]; kind: "phase" | "events"; phase_id?: string | null; product_id?: string;
};

export type Meta = {
  kind: string;
  project: { id: string; code: string; name: string; customer: string | null; go_live: string | null };
  as_of: string; grace_days: number; generated_at: string;
  formulas: { completion: string; gates: string; phase_state: string };
  sources: Record<string, number>;
  available: boolean; notes: string[];
};

export type Completion = { total: number; done: number; in_progress: number; pct: number | null; pct_display: number | null; overdue: number; start_delayed: number; formula: string; numerator: number; denominator: number };
export type Counter = { value: number; label: string; refs: Ref[] };

export type Activities = { all: number; completed: number; in_progress: number; overdue: number; start_delayed: number; not_started: number; upcoming_milestones: number; phases: number };
export type Overall = Meta & { kpis: { overall: Completion; completed: Counter; in_progress: Counter; overdue: Counter; upcoming: Counter; activities: Activities }; rows: DashRow[] };

export type Gate = { type: string; id: string | null; name: string; planned: string | null; actual: string | null; state: "done" | "overdue" | "due" | "planned"; owner: string | null; responsibility: string | null };
export type ActionSummary = { id: string; title: string; owner: string | null; priority: string; status: string; due: string | null; overdue: boolean; last_action: string | null; last_action_by: string | null; last_action_at: string | null };
export type Attention = { severity: "high" | "medium"; kind: string; text: string; refs: Ref[]; days: number; action?: ActionSummary | null };
export type Approval = { id: string; set: string; name: string; planned: string | null; submission: string | null; signoff: string | null; status: string | null; state: string };

export type ProductDash = Meta & {
  product: { id: string; code: string; name: string };
  kpis: { overall: Completion; items: { done: number; total: number; label: string }; late: Counter; next_gate: Gate | null; go_live: string | null };
  rows: DashRow[]; gates: Gate[]; approvals: Approval[]; approval_summary: Record<string, { approved: number; total: number }>; needs_attention: Attention[];
};

export type Card = { seq: number; id?: string; title: string; description: string; owner: string | null; responsibility: string | null; due: string | null; tag: "due" | "starts" | "carry_over" | "planned"; days_late: number; source: { type: string; id: string | null; ids?: string[] };
  percent_complete?: number | null; plan_status?: "planned" | "in_progress" | "done"; week_start?: string; in_plan?: boolean };
export type WeekDash = Meta & { period: string; week: { start: string; end: string; label: string }; groups: { name: string; count: number; carry_over_hidden: number; cards: Card[] }[]; total_cards: number };

export type DelayRow = { source: string; id: string; title: string; product: string; owner: string | null; responsibility: string | null; party: string; due: string | null; baseline: string | null; days_late: number; slippage: number; kind: string };
export type DelaySource = { key: string; label: string; available: boolean; count: number | null; reason?: string; refs?: string[] };
export type DelayDash = Meta & {
  sources: DelaySource[]; total: number; rows: DelayRow[]; truncated: boolean; ageing: { bucket: string; count: number }[];
  by_product: { name: string; count: number }[]; by_party: { party: string; count: number }[]; by_owner: { name: string; count: number }[]; slippage: DelayRow[];
};

export const STATE_COLOR: Record<RowState, string> = { done: "#16a34a", in_progress: "#d97706", overdue: "#dc2626", upcoming: "#94a3b8" };
export const GATE_COLOR: Record<string, string> = { done: "#16a34a", overdue: "#dc2626", due: "#d97706", planned: "#94a3b8" };
export const GATE_LABEL: Record<string, string> = { done: "Done", overdue: "Overdue", due: "Due", planned: "Planned" };
export const statusText = (r: DashRow): string => (r.state === "done" ? "100% Done" : r.state === "upcoming" ? "Planned" : `${r.pct}% · ${r.state === "overdue" ? "Overdue" : "In-Progress"}`);
export const SOURCE_LABEL: Record<string, string> = { plan_task: "Project plan", tracker_event: "Tracker event", pending_item: "Pending item", gap_specification: "Gap spec", approval_gate: "Sign-off gate", delivery_item: "Development delivery", uat_scenario: "UAT scenario", uat_defect: "UAT defect", integration_item: "Integration", report_item: "Report / print" };
