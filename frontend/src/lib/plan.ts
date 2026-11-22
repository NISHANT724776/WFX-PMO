export type WorkItem = {
  id: string;
  title: string;
  kind: "task" | "milestone";
  phase_id: string | null;
  phase_name: string | null;
  parent_id: string | null;
  product_id: string | null;
  responsible_party: string | null;
  owner_name: string | null;
  location_label: string | null;
  delivery_mode: "onsite" | "online" | null;
  planned_start: string | null;
  planned_finish: string | null;
  revised_start: string | null;
  revised_finish: string | null;
  effective_start: string | null;
  effective_finish: string | null;
  actual_start: string | null;
  actual_finish: string | null;
  status_raw: string | null;
  status_category: string | null;
  dependencies_text: string | null;
  remarks: string | null;
  resource_allocation: string | null;
  is_overdue: boolean;
  is_start_delayed: boolean;
  is_closed: boolean;
  days_late: number;
  slippage_days: number;
  percent_complete: number | null;
  percent_mismatch?: boolean;
  is_critical_milestone?: boolean;
  blocked_by_late?: boolean;
  has_pending_revision?: boolean;
};

export type PlanLink = { id: string; predecessor_id: string; successor_id: string; type: string; lag_days: number; slack_days: number | null; violated: boolean; critical: boolean };

export type Revision = {
  id: string;
  field: string;
  old_date: string | null;
  new_date: string;
  reason: string;
  status: "proposed" | "approved" | "rejected";
  requested_by_email: string | null;
  requested_at: string;
  decided_by_email: string | null;
  decided_at: string | null;
};

export type WorkItemDetail = WorkItem & {
  predecessors: { id: string; work_item_id: string; title: string }[];
  successors: { id: string; work_item_id: string; title: string }[];
  revisions: Revision[];
};

export type PendingItem = {
  id: string;
  pending_with: "customer" | "wfx" | "external" | "internal";
  description: string;
  owner_name: string | null;
  category: string | null;
  product_id: string | null;
  original_target_date: string | null;
  revised_target_date: string | null;
  effective_target_date: string | null;
  actual_closure_date: string | null;
  status_raw: string | null;
  status_category: string | null;
  remarks: string | null;
  is_overdue: boolean;
  is_closed: boolean;
  days_late: number;
  slippage_days: number;
  revisions?: Revision[];
};

export type Status = { code: string; label: string; category: string; entity_type: string; color?: string | null };

export const PENDING_LABEL: Record<string, string> = { customer: "Customer", wfx: "WFX", external: "External partner", internal: "Internal team" };

export const COLORS = { done: "#16a34a", in_progress: "#d97706", overdue: "#dc2626", idle: "#94a3b8", blocked: "#7c3aed" };

export function barColor(w: Pick<WorkItem, "status_category" | "is_overdue" | "is_closed">): string {
  if (w.is_overdue) return COLORS.overdue;
  if (w.status_category === "done" || w.is_closed) return COLORS.done;
  if (w.status_category === "in_progress") return COLORS.in_progress;
  if (w.status_category === "blocked") return COLORS.blocked;
  return COLORS.idle;
}

export const DAY = 86400000;
export const toDate = (s: string | null): Date | null => (s ? new Date(`${s}T00:00:00Z`) : null);
export const iso = (d: Date): string => d.toISOString().slice(0, 10);
export const daysBetween = (a: Date, b: Date): number => Math.round((b.getTime() - a.getTime()) / DAY);
export const fmt = (s: string | null): string => (s ? new Date(`${s}T00:00:00Z`).toLocaleDateString(undefined, { day: "2-digit", month: "short", year: "2-digit", timeZone: "UTC" }) : "–");
export const today = (): string => new Date().toISOString().slice(0, 10);
