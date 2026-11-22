"use client";

import { useCallback, useEffect, useState } from "react";
import RecordsTab from "@/components/delivery/RecordsTab";
import { ConfirmDialog } from "@/components/manage/Workspace";
import { Badge, Empty, ErrorBox, Input, Label, Select, Loading } from "@/components/ui";
import { api, qs, type Page, type Row } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { Attention, Card, WeekDash } from "@/lib/dash";
import { fmt, iso, toDate, today } from "@/lib/plan";
import { BY_SLUG, type Rec } from "@/lib/records";

export type OpenRecord = { kind: string; id: string | null; initial?: Record<string, string> };
export const mondayOf = (s: string): string => { const d = toDate(s)!; return iso(new Date(d.getTime() - ((d.getUTCDay() + 6) % 7) * 86400000)); };

/* ------------------------------------------------------------------ department x location coverage */
type Cov = {
  available: boolean; formula: string; total: Tot;
  departments: (Tot & { id: string; code: string; name: string })[]; locations: (Tot & { id: string; code: string; name: string })[];
  cells: (Tot & { department_id: string; location_id: string })[];
};
type Tot = { planned: number; completed: number; pct: number | null; activities: number };
const tone = (p: number | null) => (p === null ? "bg-slate-100 text-slate-500" : p >= 80 ? "bg-green-100 text-green-900" : p >= 40 ? "bg-amber-100 text-amber-900" : "bg-red-100 text-red-900");
const pctText = (t: Tot) => (t.pct === null ? "n/a" : `${t.pct}%`);

export function CoverageView({ projectId, products }: { projectId: string; products: Row[] }) {
  const [data, setData] = useState<Cov | null>(null);
  const [productId, setProductId] = useState("");
  const [preset, setPreset] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => {
    try { setError(null); setData(await api<Cov>(`/projects/${projectId}/dashboards/coverage${qs({ product_id: productId })}`)); }
    catch (e) { setError(e instanceof Error ? e.message : "Failed to load coverage"); }
  }, [projectId, productId]);
  useEffect(() => { void load(); }, [load]);
  const cell = (d: string, l: string) => data?.cells.find((c) => c.department_id === d && c.location_id === l);

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-end justify-between gap-3">
        <div><h2 className="text-xl font-semibold text-blue-950">Department and location coverage</h2><p className="text-xs text-slate-500">Calculated from the activities below; nothing here is typed in.</p></div>
        <Label text="Product"><Select value={productId} onChange={(e) => setProductId(e.target.value)}><option value="">All products</option>{products.map((p) => <option key={String(p.id)} value={String(p.id)}>{String(p.code)}</option>)}</Select></Label>
      </div>
      <ErrorBox message={error} />
      {!data ? <Loading /> : !data.available ? (
        <Empty>No coverage activities yet. Add the departments and locations under Master data, then add activities below (department, location, planned and completed counts). The percentages appear as soon as there is something planned.</Empty>
      ) : (
        <div className="mb-6 grid gap-5 lg:grid-cols-[2fr_1fr]">
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-xs">
              <thead><tr><th className="border-b border-slate-300 p-1.5 text-left text-slate-500">Department \ Location</th>
                {data.locations.map((l) => <th key={l.id} className="cursor-pointer border-b border-slate-300 p-1.5 text-center font-semibold text-blue-950 hover:underline" title="Show this location's activities" onClick={() => setPreset({ location_id: l.id })}>{l.name}</th>)}
                <th className="border-b border-slate-300 p-1.5 text-center text-slate-500">All locations</th></tr></thead>
              <tbody>
                {data.departments.map((d) => (
                  <tr key={d.id}>
                    <td className="cursor-pointer border-b border-slate-100 p-1.5 font-semibold text-blue-950 hover:underline" onClick={() => setPreset({ department_id: d.id })}>{d.name}</td>
                    {data.locations.map((l) => { const c = cell(d.id, l.id); return (
                      <td key={l.id} className="border-b border-slate-100 p-1">
                        {c ? <button className={`w-full rounded-md px-1 py-1 text-center ${tone(c.pct)}`} title={`${c.completed} of ${c.planned} completed in ${c.activities} activit${c.activities === 1 ? "y" : "ies"}`} onClick={() => setPreset({ department_id: d.id, location_id: l.id })}><b>{pctText(c)}</b><div className="text-[10px] opacity-70">{c.completed}/{c.planned}</div></button> : <div className="text-center text-slate-300">–</div>}
                      </td>); })}
                    <td className="border-b border-slate-100 p-1"><div className={`rounded-md px-1 py-1 text-center font-semibold ${tone(d.pct)}`}>{pctText(d)}<div className="text-[10px] font-normal opacity-70">{d.completed}/{d.planned}</div></div></td>
                  </tr>
                ))}
                <tr><td className="p-1.5 font-semibold text-slate-600">All departments</td>
                  {data.locations.map((l) => <td key={l.id} className="p-1"><div className={`rounded-md px-1 py-1 text-center font-semibold ${tone(l.pct)}`}>{pctText(l)}<div className="text-[10px] font-normal opacity-70">{l.completed}/{l.planned}</div></div></td>)}
                  <td className="p-1"><div className={`rounded-md px-1 py-1 text-center font-bold ${tone(data.total.pct)}`}>{pctText(data.total)}<div className="text-[10px] font-normal opacity-70">{data.total.completed}/{data.total.planned}</div></div></td></tr>
              </tbody>
            </table>
            <p className="mt-1 text-[11px] text-slate-500">{data.formula} Click a cell, department or location to filter the activities below.</p>
          </div>
          <div>
            <h3 className="mb-1 text-sm font-semibold text-blue-950">Locations compared</h3>
            {data.locations.map((l) => (
              <div key={l.id} className="mb-1.5 text-xs"><div className="flex justify-between"><span>{l.name}</span><span className="text-slate-600">{pctText(l)} · {l.completed}/{l.planned}</span></div>
                <div className="h-2 rounded-md bg-slate-100"><div className="h-2 rounded-md bg-blue-900" style={{ width: `${l.pct ?? 0}%` }} /></div></div>
            ))}
          </div>
        </div>
      )}
      {Object.keys(preset).length > 0 && <p className="mb-1 text-xs text-blue-900">Filtered from the table. <button className="underline" onClick={() => setPreset({})}>Show all activities</button></p>}
      <RecordsTab projectId={projectId} cfg={BY_SLUG["coverage-activities"]} preset={preset} onChanged={load} />
    </div>
  );
}

/* ------------------------------------------------------------------ sign-off gates */
export function GatesView({ projectId }: { projectId: string }) {
  const [sum, setSum] = useState<{ total: number; approved: number; overdue: number; truncated: boolean } | null>(null);
  const load = useCallback(async () => {
    try {
      const r = await api<Page<Rec>>(`/projects/${projectId}/records/approval-gates${qs({ size: 200, as_of: today() })}`);
      setSum({ total: r.total, approved: r.items.filter((g) => g.is_closed).length, overdue: r.items.filter((g) => g.is_overdue).length, truncated: r.total > r.items.length });
    } catch { setSum(null); }
  }, [projectId]);
  useEffect(() => { void load(); }, [load]);
  return (
    <div>
      <div className="mb-3"><h2 className="text-xl font-semibold text-blue-950">Sign-off gates</h2>
        <p className="text-xs text-slate-500">Approving needs the approve permission, a submission date and an approval date. Rejecting or requesting changes needs a reason in Comments. States are set under Status Configuration (entity approval_gate).</p></div>
      {sum && <p className="mb-3 text-sm text-slate-600">{sum.total} gate(s) · <Badge tone="green">{sum.approved} approved</Badge> <Badge tone={sum.overdue ? "red" : "slate"}>{sum.overdue} overdue</Badge>{sum.truncated ? " (first 200 counted)" : ""}</p>}
      <RecordsTab projectId={projectId} cfg={BY_SLUG["approval-gates"]} onChanged={load} />
    </div>
  );
}

/* ------------------------------------------------------------------ Needs attention: raise and follow an action */
export function AttentionRow({ a, projectId, productId, onItem, onRecord, onChanged }: {
  a: Attention; projectId: string; productId?: string; onItem: (id: string) => void; onRecord: (r: OpenRecord) => void; onChanged: () => void;
}) {
  const { can } = useAuth();
  const [ask, setAsk] = useState(false);
  const task = a.refs.find((r) => r.type === "task" && r.id);
  const src = a.refs.find((r) => r.id && r.type !== "action");
  const inner = <><span className={a.severity === "high" ? "text-red-600" : "text-amber-600"}>●</span> {a.text}</>;
  return (
    <li className="text-xs leading-snug text-slate-800">
      {task ? <button className="text-left hover:underline print:no-underline" onClick={() => onItem(task.id!)}>{inner}</button>
        : a.kind === "action" && a.action ? <button className="text-left hover:underline print:no-underline" onClick={() => onRecord({ kind: "action-items", id: a.action!.id })}>{inner}</button> : inner}
      {a.action && a.kind !== "action" && (
        <button className="mt-0.5 block text-left text-[11px] text-blue-900 hover:underline print:no-underline" onClick={() => onRecord({ kind: "action-items", id: a.action!.id })}>
          Action: {a.action.owner ?? "unassigned"} · {a.action.status.replace("_", " ")}{a.action.due ? ` · due ${fmt(a.action.due)}` : ""}{a.action.overdue ? " (overdue)" : ""}{a.action.last_action ? ` — latest: ${a.action.last_action}` : ""}{a.action.last_action_by ? ` (${a.action.last_action_by})` : ""}
        </button>
      )}
      {!a.action && src && can("projects:write") && <button className="mt-0.5 block text-[11px] text-blue-900 underline print:hidden" onClick={() => setAsk(true)}>Create action</button>}
      {ask && src && <ActionDialog a={a} source={src} projectId={projectId} productId={productId} onCancel={() => setAsk(false)} onDone={() => { setAsk(false); onChanged(); }} />}
    </li>
  );
}

function ActionDialog({ a, source, projectId, productId, onCancel, onDone }: { a: Attention; source: { type: string; id: string | null }; projectId: string; productId?: string; onCancel: () => void; onDone: () => void }) {
  const [owner, setOwner] = useState("");
  const [priority, setPriority] = useState(a.severity === "high" ? "high" : "medium");
  const [due, setDue] = useState("");
  return (
    <ConfirmDialog title="Create an action" confirmLabel="Create action" reasonLabel="What must happen" initial={a.text.slice(0, 200)} onCancel={onCancel}
      onConfirm={async (title) => {
        await api(`/projects/${projectId}/records/action-items`, { method: "POST", body: { title, owner_name: owner || null, priority, due_date: due || null, source_type: source.type, source_id: source.id, product_id: productId || null, description: a.text } });
        onDone();
      }}>
      <div className="mb-2 text-xs text-slate-500">Raised from: {a.text}</div>
      <div className="grid grid-cols-3 gap-2">
        <Label text="Owner"><Input value={owner} onChange={(e) => setOwner(e.target.value)} /></Label>
        <Label text="Priority"><Select value={priority} onChange={(e) => setPriority(e.target.value)}><option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option><option value="critical">Critical</option></Select></Label>
        <Label text="Due date"><Input type="date" value={due} onChange={(e) => setDue(e.target.value)} /></Label>
      </div>
    </ConfirmDialog>
  );
}

/* ------------------------------------------------------------------ week plan card */
export function WeekCard({ c, group, d, projectId, onItem, onRecord, onChanged }: {
  c: Card; group: string; d: WeekDash; projectId: string; onItem: (id: string) => void; onRecord: (r: OpenRecord) => void; onChanged: () => void;
}) {
  const { can } = useAuth();
  const canWrite = can("projects:write");
  const [ask, setAsk] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const planned = c.source.type === "week_plan_item";
  const late = c.tag === "carry_over";
  const tag = c.tag === "due" ? "Due" : c.tag === "starts" ? "Starts" : c.tag === "planned" ? "Planned" : `OVERDUE ${c.days_late} d · was due`;
  const act = async (fn: () => Promise<unknown>) => { try { setError(null); await fn(); onChanged(); } catch (e) { setError(e instanceof Error ? e.message : "Failed"); } };
  const addToPlan = () => act(() => {
    const inPeriod = c.due && c.due >= d.week.start && c.due <= d.week.end && !late;
    return api(`/projects/${projectId}/records/week-plan-items`, { method: "POST", body: {
      title: c.title, owner_name: c.owner, workstream: group, week_start: mondayOf(inPeriod ? c.due! : d.week.start), target_date: inPeriod ? c.due : null, source_type: c.source.type, source_id: c.source.id } });
  });
  const clickable = (c.source.type === "task" && c.source.id) || planned;
  return (
    <div className={`flex gap-2 rounded-md border bg-white p-2 ${late ? "border-red-200" : planned ? "border-blue-300" : "border-slate-200"}`}>
      <div className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-[11px] font-bold text-white ${late ? "bg-red-600" : "bg-blue-950"}`}>{String(c.seq).padStart(2, "0")}</div>
      <div className="min-w-0 flex-1 text-xs">
        {clickable ? <button className="text-left font-semibold text-slate-900 hover:underline print:no-underline" onClick={() => (planned ? onRecord({ kind: "week-plan-items", id: c.source.id }) : onItem(c.source.id!))}>{c.title}</button> : <div className="font-semibold text-slate-900">{c.title}</div>}
        {c.description && <div className="mt-0.5 text-slate-500">{c.description}</div>}
        <div className={`mt-1 ${late ? "font-semibold text-red-700" : "text-blue-900"}`}>{tag} {fmt(c.due)} · {c.owner ?? c.responsibility ?? "unassigned"}{planned && c.plan_status ? ` · ${c.plan_status.replace("_", " ")}` : ""}</div>
        {planned && c.percent_complete != null && <div className="mt-1 flex items-center gap-1.5"><div className="h-1.5 flex-1 rounded-md bg-slate-100"><div className="h-1.5 rounded-md bg-green-600" style={{ width: `${c.percent_complete}%` }} /></div><span className="text-[10px] text-slate-500">{c.percent_complete}%</span></div>}
        {c.in_plan && <div className="mt-1"><Badge tone="green">on the plan</Badge></div>}
        {error && <div className="mt-1 text-red-700">{error}</div>}
        {canWrite && (
          <div className="mt-1.5 flex flex-wrap gap-1 print:hidden">
            {planned ? <>
              <button className="rounded-md border border-slate-300 px-1.5 hover:bg-slate-100" title="Move to the previous week" onClick={() => act(() => api(`/projects/${projectId}/records/week-plan-items/${c.source.id}/move`, { method: "POST", body: { weeks: -1 } }))}>‹ week</button>
              <button className="rounded-md border border-slate-300 px-1.5 hover:bg-slate-100" title="Move to the next week" onClick={() => act(() => api(`/projects/${projectId}/records/week-plan-items/${c.source.id}/move`, { method: "POST", body: { weeks: 1 } }))}>week ›</button>
              <button className="rounded-md border border-red-300 px-1.5 text-red-700 hover:bg-red-50" onClick={() => setAsk(true)}>Remove</button>
            </> : !c.in_plan && c.source.id && <button className="rounded-md border border-slate-300 px-1.5 hover:bg-slate-100" onClick={addToPlan}>＋ Add to plan</button>}
          </div>
        )}
      </div>
      {ask && (
        <ConfirmDialog title="Remove from the plan?" confirmLabel="Remove" danger onCancel={() => setAsk(false)}
          onConfirm={async () => { await api(`/projects/${projectId}/lifecycle/week_plan_item/${c.source.id}/archive`, { method: "POST", body: {} }); setAsk(false); onChanged(); }}>
          “{c.title}” leaves this week&apos;s plan. It is archived, not deleted, and can be restored from the project&apos;s Archive tab.
        </ConfirmDialog>
      )}
    </div>
  );
}
