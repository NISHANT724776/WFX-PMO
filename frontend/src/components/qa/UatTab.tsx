"use client";

import { useCallback, useEffect, useState } from "react";
import RecordsTab from "@/components/delivery/RecordsTab";
import { Kpi } from "@/components/dash/parts";
import { Empty, ErrorBox } from "@/components/ui";
import { api } from "@/lib/api";
import { today } from "@/lib/plan";
import { BY_SLUG } from "@/lib/records";

type Group = { name: string; total: number; passed: number; failed: number; blocked: number; retest: number; in_progress: number; not_run: number; pass_rate: number | null };
type Summary = {
  available: boolean; formula: string;
  scenarios: { total: number; by_result: Record<string, number>; pass_rate: number | null; executed_pct: number | null; to_do: number; overdue: number; by_module: Group[]; by_cycle: Group[] };
  defects: { total: number; open: number; closed: number; open_by_severity: Record<string, number>; overdue: number; oldest_open_days: number | null };
};
const RESULTS: [string, string, string][] = [["passed", "Passed", "#16a34a"], ["failed", "Failed", "#dc2626"], ["blocked", "Blocked", "#7c3aed"], ["retest", "Retest", "#d97706"], ["in_progress", "In progress", "#2563eb"], ["not_run", "Not run", "#64748b"]];

/** UAT: the scenarios with their results, and the defects found. The numbers above are counted from the records below, as of today. */
export default function UatTab({ projectId, onChanged }: { projectId: string; onChanged: () => void }) {
  const [sum, setSum] = useState<Summary | null>(null);
  const [sub, setSub] = useState<"uat-scenarios" | "uat-defects">("uat-scenarios");
  const [preset, setPreset] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => {
    try { setError(null); setSum(await api<Summary>(`/projects/${projectId}/uat/summary?as_of=${today()}`)); } catch (e) { setError(e instanceof Error ? e.message : "Failed to load"); }
  }, [projectId]);
  useEffect(() => { void load(); }, [load]);
  const changed = () => { void load(); onChanged(); };
  const S = sum?.scenarios, D = sum?.defects;

  return (
    <div>
      <div className="mb-3"><h2 className="text-xl font-semibold text-blue-950">User acceptance testing</h2>
        <p className="text-xs text-slate-500">Passed and Failed need a tester and the date it was run; Failed needs the actual result; a scenario cannot be Passed while it has an open defect. Import a UAT sheet under Smart Import, or add scenarios here (Quick add also works).</p></div>
      <ErrorBox message={error} />
      {sum && S && D && (sum.available ? (
        <div className="mb-4">
          <div className="mb-2 grid grid-cols-3 gap-2 sm:grid-cols-6 lg:grid-cols-9">
            <Kpi value={S.pass_rate === null ? "n/a" : `${S.pass_rate}%`} label="Pass rate" sub={`${S.by_result.passed ?? 0} of ${S.total}`} />
            {RESULTS.map(([k, l, c]) => <Kpi key={k} value={S.by_result[k] ?? 0} label={l} color={c} onClick={() => { setSub("uat-scenarios"); setPreset({ result: k }); }} active={sub === "uat-scenarios" && preset.result === k} />)}
            <Kpi value={S.overdue} label="Overdue to run" color={S.overdue ? "#dc2626" : "#16a34a"} sub="planned date passed" />
            <Kpi value={D.open} label="Open defects" color={D.open ? "#dc2626" : "#16a34a"} onClick={() => { setSub("uat-defects"); setPreset({}); }} sub={D.open ? `${D.open_by_severity.critical} critical · ${D.open_by_severity.high} high` : undefined} />
          </div>
          {S.by_module.length > 0 && (
            <details className="text-xs">
              <summary className="cursor-pointer text-blue-900">Results by module and cycle</summary>
              <div className="mt-2 grid gap-4 md:grid-cols-2">
                {[["Module", S.by_module], ["UAT cycle", S.by_cycle]].map(([title, rows]) => (
                  <table key={String(title)} className="w-full text-left"><thead className="border-b border-slate-300 uppercase text-slate-500"><tr><th className="py-1">{String(title)}</th><th>Total</th><th>Passed</th><th>Failed</th><th>Blocked</th><th>Retest</th><th>Pass %</th></tr></thead>
                    <tbody>{(rows as Group[]).map((g) => <tr key={g.name} className="border-b border-slate-100"><td className="py-1 pr-2">{g.name}</td><td>{g.total}</td><td>{g.passed}</td><td>{g.failed}</td><td>{g.blocked}</td><td>{g.retest}</td><td>{g.pass_rate ?? "n/a"}</td></tr>)}</tbody></table>
                ))}
              </div>
              <p className="mt-2 text-[11px] text-slate-500">{sum.formula}</p>
            </details>
          )}
        </div>
      ) : <div className="mb-4"><Empty>No UAT scenarios or defects yet. Add a scenario below, or import a UAT sheet under Smart Import.</Empty></div>)}
      <div className="mb-3 inline-flex max-w-full overflow-x-auto rounded-lg bg-slate-100 p-0.5">
        {(["uat-scenarios", "uat-defects"] as const).map((k) => (
          <button key={k} onClick={() => { setSub(k); setPreset({}); }} className={`px-3 py-1 transition-colors duration-150 whitespace-nowrap text-sm ${sub === k ? "rounded-md bg-white font-medium text-blue-950 shadow-sm" : "rounded-md text-slate-600 hover:text-slate-900"}`}>
            {BY_SLUG[k].label} <span className={sub === k ? "text-slate-400" : "text-slate-400"}>{k === "uat-scenarios" ? S?.total ?? "" : D?.total ?? ""}</span>
          </button>
        ))}
      </div>
      <RecordsTab key={sub} projectId={projectId} cfg={BY_SLUG[sub]} preset={preset} onChanged={changed} />
    </div>
  );
}
