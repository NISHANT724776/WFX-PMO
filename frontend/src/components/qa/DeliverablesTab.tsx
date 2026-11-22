"use client";

import { useCallback, useEffect, useState } from "react";
import RecordsTab from "@/components/delivery/RecordsTab";
import { Kpi } from "@/components/dash/parts";
import { Empty, ErrorBox } from "@/components/ui";
import { api } from "@/lib/api";
import { today } from "@/lib/plan";
import { BY_SLUG } from "@/lib/records";

type Block = { total: number; by_status: Record<string, number>; overdue: number; due_in_14_days: number; closed: number; done_pct: number | null; reports_count?: number };
type Summary = { available: boolean; formula: string; integrations: Block; reports: Block };
const KINDS = ["integration-items", "report-items"] as const;

/** Integrations (the register) and reports + prints (the inventory): owner, status, target and revised dates, what is late. */
export default function DeliverablesTab({ projectId, onChanged }: { projectId: string; onChanged: () => void }) {
  const [sum, setSum] = useState<Summary | null>(null);
  const [sub, setSub] = useState<(typeof KINDS)[number]>("integration-items");
  const [preset, setPreset] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => {
    try { setError(null); setSum(await api<Summary>(`/projects/${projectId}/deliverables/summary?as_of=${today()}`)); } catch (e) { setError(e instanceof Error ? e.message : "Failed to load"); }
  }, [projectId]);
  useEffect(() => { void load(); }, [load]);
  const changed = () => { void load(); onChanged(); };
  const b = sum?.[sub === "integration-items" ? "integrations" : "reports"];

  return (
    <div>
      <div className="mb-3"><h2 className="text-xl font-semibold text-blue-950">Reports, prints and integrations</h2>
        <p className="text-xs text-slate-500">Each item has an owner, a status and a target date. The target is the baseline: it moves only through a dated revision with a reason (Revise in the item), so slippage is always measured against the original. Late items appear on the Delays dashboard and the week plan.</p></div>
      <ErrorBox message={error} />
      {sum && (sum.available ? (
        <div className="mb-3 grid grid-cols-3 gap-2 sm:grid-cols-6">
          <Kpi value={sum.integrations.total} label="Integrations" onClick={() => { setSub("integration-items"); setPreset({}); }} active={sub === "integration-items"} />
          <Kpi value={sum.integrations.overdue} label="Integrations overdue" color={sum.integrations.overdue ? "#dc2626" : "#16a34a"} sub={sum.integrations.done_pct === null ? undefined : `${sum.integrations.done_pct}% done`} />
          <Kpi value={sum.integrations.due_in_14_days} label="Integrations due in 14 days" color="#b45309" />
          <Kpi value={sum.reports.total} label="Reports + prints" sub={sum.reports.reports_count ? `${sum.reports.reports_count} in the inventory` : undefined} onClick={() => { setSub("report-items"); setPreset({}); }} active={sub === "report-items"} />
          <Kpi value={sum.reports.overdue} label="Reports overdue" color={sum.reports.overdue ? "#dc2626" : "#16a34a"} sub={sum.reports.done_pct === null ? undefined : `${sum.reports.done_pct}% done`} />
          <Kpi value={sum.reports.due_in_14_days} label="Reports due in 14 days" color="#b45309" />
        </div>
      ) : <div className="mb-3"><Empty>No integrations or reports yet. Add them below, or import the integration register / reports inventory sheet under Smart Import.</Empty></div>)}
      <div className="mb-3 inline-flex max-w-full overflow-x-auto rounded-lg bg-slate-100 p-0.5">
        {KINDS.map((k) => (
          <button key={k} onClick={() => { setSub(k); setPreset({}); }} className={`px-3 py-1 transition-colors duration-150 whitespace-nowrap text-sm ${sub === k ? "rounded-md bg-white font-medium text-blue-950 shadow-sm" : "rounded-md text-slate-600 hover:text-slate-900"}`}>
            {BY_SLUG[k].label} <span className={sub === k ? "text-slate-400" : "text-slate-400"}>{sum ? (k === "integration-items" ? sum.integrations.total : sum.reports.total) : ""}</span>
          </button>
        ))}
      </div>
      {b && b.total > 0 && <p className="mb-2 text-xs text-slate-500">{Object.entries(b.by_status).filter(([, n]) => n).map(([k, n]) => `${n} ${k.replace(/_/g, " ")}`).join(" · ")}</p>}
      <RecordsTab key={sub} projectId={projectId} cfg={BY_SLUG[sub]} preset={preset} onChanged={changed} />
    </div>
  );
}
