import { API_BASE, ApiError, tokenStore } from "./api";

export type Batch = {
  id: string;
  filename: string;
  size_bytes: number;
  status: "uploaded" | "analyzing" | "ready" | "failed" | "committed" | "rolled_back";
  error: string | null;
  uploaded_by: string | null;
  uploaded_at: string;
  project_id: string | null;
  committed_at: string | null;
  commit_summary: { mode: string; sheets: CommitSheet[] } | null;
  template: string | null;
  duplicate_of?: string | null;
  sheets?: SheetSummary[];
  validation?: ValidationSheet[] | null;
};

export type CommitSheet = { sheet: string; entity: string; created: number; updated: number; skipped: number; rejected: number };

export type SheetSummary = {
  id: string;
  name: string;
  state: string;
  classification: string;
  classification_label: string;
  class_confidence: number;
  entity: string | null;
  enabled: boolean;
  rows: number;
  columns: number;
  template: string | null;
  not_yet: string | null;
  unconfirmed: number;
};

export type ColumnMapping = {
  target_field: string | null;
  score: number;
  level: "high" | "medium" | "low" | "none" | "manual";
  status: "suggested" | "confirmed" | "ignored" | "unmapped";
  source: string;
  alternatives: [string, number][] | null;
};

export type SheetColumn = {
  id: string;
  index: number;
  letter: string;
  header: string;
  group_label: string | null;
  inferred_type: string;
  profile: { samples?: string[]; non_blank: number; unique: number; hidden?: boolean; invalid_date_values?: [string, number][] };
  mapping: ColumnMapping | null;
};

export type SheetDetail = {
  status_values: { field: string; header: string; value: string; count: number; category: string | null; chosen: boolean }[];
  pending_with_values: { value: string; count: number; category: string | null }[];
  id: string;
  name: string;
  classification_label: string;
  class_confidence: number;
  entity: string | null;
  enabled: boolean;
  config: { header_row?: number; product_map?: Record<string, string | null>; product_suggested?: Record<string, boolean> };
  profile: {
    header_row: number;
    header_candidates: { row: number; score: number; preview: string[] }[];
    stats: { data_rows: number; hidden_columns: string[]; section_rows: number; formula_cells: number; duplicate_rows: number };
    section_rows: { count: number; examples: string[] };
    template: string | null;
    not_yet: string | null;
  };
  entities: { key: string; label: string }[];
  fields: { key: string; label: string; type: string; required: boolean }[];
  layout: string | null;
  columns: SheetColumn[];
};

export type ValidationSheet = {
  sheet_id: string;
  name: string;
  skipped: boolean;
  reason?: string;
  entity?: string;
  source_rows?: number;
  records?: number;
  importable?: number;
  rejected_rows?: number;
  empty_rows?: number;
  section_rows?: number;
  errors?: number;
  warnings?: number;
  infos?: number;
  blocking?: { code: string; message: string }[];
};

export type Issue = {
  id: string;
  sheet: string | null;
  row: number | null;
  column: string | null;
  field: string | null;
  severity: "error" | "warning" | "info";
  code: string;
  message: string;
  raw_value: string | null;
  rejects_row: boolean;
};

export type Suggestion = { key: string; label: string; reference: string; available: boolean; sources: string[]; missing: Record<string, string[]>; note: string | null };

export async function uploadWorkbook(file: File): Promise<Batch> {
  const form = new FormData();
  form.append("file", file);
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/api/v1/imports`, {
      method: "POST",
      headers: { Authorization: `Bearer ${tokenStore.get() ?? ""}` },
      body: form,
    });
  } catch {
    throw new ApiError(0, "Cannot reach the server. Is the API running?");
  }
  const data = await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(res.status, typeof data?.detail === "string" ? data.detail : `Upload failed (${res.status})`);
  return data as Batch;
}

export async function downloadErrorReport(batchId: string, filename: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/v1/imports/${batchId}/errors.csv`, {
    headers: { Authorization: `Bearer ${tokenStore.get() ?? ""}` },
  });
  if (!res.ok) throw new ApiError(res.status, "Could not download the error report");
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = `${filename.replace(/\.[^.]+$/, "")}-error-report.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

export const fmtSize = (n: number) => (n > 1048576 ? `${(n / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`);
