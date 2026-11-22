"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Badge, Button, Empty, ErrorBox, Input, Label, Select, Slip, Loading } from "@/components/ui";
import { api, qs, type Page, type Row } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmt, today, type PlanLink, type Status, type WorkItem } from "@/lib/plan";
import { ConfirmDialog } from "@/components/manage/Workspace";
import InlineCell from "@/components/InlineCell";
import { useQuickProduct } from "@/components/QuickAdd";
import { useToast } from "@/components/Toast";
import Calendar from "./Calendar";
import Gantt, { QuickAddBar, type AddRequest, type QuickCreate } from "./Gantt";
import WorkItemDrawer, { type Prefill } from "./WorkItemDrawer";

type Res = { items: WorkItem[]; total: number; as_of: string; grace_days: number };
const VIEWS = ["Table", "Gantt", "Calendar"] as const;

export default function PlanTab({ projectId, products, onChanged, initialView = "Table" }: { projectId: string; products: Row[]; onChanged: () => void; initialView?: (typeof VIEWS)[number] }) {
  const { can } = useAuth();
  const [view, setView] = useState<(typeof VIEWS)[number]>(initialView);
  const [productId, setProductId] = useState("");
  const [onlyTagged, setOnlyTagged] = useState(false);
  const [status, setStatus] = useState("");
  const [late, setLate] = useState(false);
  const [q, setQ] = useState("");
  const [asOf, setAsOf] = useState(today());
  const [res, setRes] = useState<Res | null>(null);
  const [open, setOpen] = useState<string | "new" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [phases, setPhases] = useState<Row[]>([]);
  const [links, setLinks] = useState<PlanLink[]>([]);
  const [prefill, setPrefill] = useState<Prefill | undefined>(undefined);
  const [statuses, setStatuses] = useState<Status[]>([]);
  const [quickDate, setQuickDate] = useState<WorkItem | null>(null);
  const toast = useToast();
  useQuickProduct(productId || undefined);
  useEffect(() => { api<Page<Status>>("/status-configs?q=work_item&size=50").then((p) => setStatuses(p.items.filter((x) => x.entity_type === "work_item"))).catch(() => {}); }, []);
  const [phaseDialog, setPhaseDialog] = useState<null | { id: string | null; name: string }>(null);

  const load = useCallback(async () => {
    try {
      setError(null);
      setRes(await api<Res>(`/projects/${projectId}/work-items${qs({ size: 500, as_of: asOf, product_id: productId, include_unassigned: !onlyTagged, status_category: status, overdue: late ? true : undefined, q })}`));
      setPhases(await api<Row[]>(`/projects/${projectId}/phases`));
      setLinks(await api<PlanLink[]>(`/projects/${projectId}/dependencies${qs({ as_of: asOf })}`));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load plan");
    }
  }, [projectId, asOf, productId, onlyTagged, status, late, q]);
  useEffect(() => { void load(); }, [load]);

  const grouped = useMemo(() => {
    const m = new Map<string, WorkItem[]>();
    (res?.items ?? []).forEach((w) => m.set(w.phase_name ?? "(no phase)", [...(m.get(w.phase_name ?? "(no phase)") ?? []), w]));
    return [...m.entries()];
  }, [res]);
  const overdue = res?.items.filter((i) => i.is_overdue).length ?? 0;
  const startLate = res?.items.filter((i) => i.is_start_delayed).length ?? 0;
  const done = res?.items.filter((i) => i.is_closed).length ?? 0;
  const changed = async () => { await load(); onChanged(); };

  function add(r: AddRequest) {
    if (r.type === "phase") { setPhaseDialog({ id: null, name: "" }); return; }
    setPrefill({ phase_id: r.phaseId ?? undefined, parent_id: r.parentId ?? undefined, kind: r.type === "milestone" ? "milestone" : "task" });
    setOpen("new");
  }
  async function reschedule(item: WorkItem, start: string | null, finish: string | null, reason: string): Promise<string[]> {
    const r = await api<{ successor_conflicts: { title: string; earliest: string }[] }>(`/projects/${projectId}/work-items/${item.id}/reschedule`,
      { method: "POST", body: { start, finish, reason, approve: can("plan:approve") } });
    await changed();
    return r.successor_conflicts.map((c) => `'${c.title}' now starts before its predecessor finishes (earliest ${fmt(c.earliest)})`);
  }
  async function link(pred: string, succ: string): Promise<string[]> {
    const r = await api<{ warnings: string[] }>(`/projects/${projectId}/work-items/${succ}/dependencies`, { method: "POST", body: { predecessor_id: pred, lag_days: 0 } });
    await changed();
    return r.warnings;
  }
  async function unlink(id: string) { await api(`/projects/${projectId}/dependencies/${id}`, { method: "DELETE" }); await changed(); }
  async function savePhase(name: string) {
    if (!phaseDialog) return;
    if (phaseDialog.id) await api(`/projects/${projectId}/phases/${phaseDialog.id}`, { method: "PATCH", body: { name } });
    else await api(`/projects/${projectId}/phases`, { method: "POST", body: { name } });
    setPhaseDialog(null);
    await changed();
  }

  const statusColors = useMemo(() => Object.fromEntries(statuses.filter((s) => s.color).map((s) => [s.label, String(s.color)])), [statuses]);
  async function quickCreate(b: QuickCreate) {
    await api(`/projects/${projectId}/work-items`, { method: "POST", body: { title: b.title, kind: b.kind, phase_id: b.phase_id, planned_start: b.planned_start, planned_finish: b.planned_finish, status: "not_started", ...(productId ? { product_id: productId } : {}) } });
    await changed();
  }
  const patch = async (id: string, body: Record<string, unknown>) => { await api(`/projects/${projectId}/work-items/${id}`, { method: "PATCH", body }); await changed(); };
  async function setFinish(date: string, reason: string) {
    if (!quickDate) return;
    await api(`/projects/${projectId}/work-items/${quickDate.id}/reschedule`, { method: "POST", body: { finish: date, reason, approve: can("plan:approve") } });
    toast.ok(`${quickDate.title}: finish date changed. The original date and your reason are in its history.`);
    setQuickDate(null);
    await changed();
  }

  async function tagPhase(phaseName: string) {
    const ph = phases.find((p) => p.name === phaseName);
    if (!ph) return;
    const pid = window.prompt(`Tag every task in "${phaseName}" with a product.\nType the product code (${products.map((p) => p.code).join(", ")}) or leave empty to clear:`, "");
    if (pid === null) return;
    const prod = products.find((p) => String(p.code).toLowerCase() === pid.trim().toLowerCase());
    if (pid.trim() && !prod) { setError(`Unknown product code '${pid}'`); return; }
    try { await api(`/projects/${projectId}/phases/${ph.id}/assign-product`, { method: "POST", body: { product_id: prod?.id ?? null } }); await changed(); }
    catch (e) { setError(e instanceof Error ? e.message : "Could not assign product"); }
  }

  return (
    <>
      <ErrorBox message={error} />
      <div className="mb-4 flex flex-wrap items-end gap-3 rounded-lg border border-slate-200 bg-slate-50/70 p-3">
        <div className="inline-flex max-w-full overflow-x-auto rounded-lg bg-slate-100 p-0.5">{VIEWS.map((v) => <button key={v} onClick={() => setView(v)} className={`px-3 py-1 transition-colors duration-150 whitespace-nowrap text-sm ${view === v ? "rounded-md bg-white font-medium text-blue-950 shadow-sm" : "rounded-md text-slate-600 hover:text-slate-900"}`}>{v}</button>)}</div>
        <Label text="Product"><Select value={productId} onChange={(e) => setProductId(e.target.value)}><option value="">All products</option>{products.map((p) => <option key={String(p.id)} value={String(p.id)}>{String(p.code)}</option>)}</Select></Label>
        {productId && <label className="pb-1.5 text-xs text-slate-600"><input type="checkbox" checked={onlyTagged} onChange={(e) => setOnlyTagged(e.target.checked)} /> only tasks tagged to this product</label>}
        <Label text="Status"><Select value={status} onChange={(e) => setStatus(e.target.value)}><option value="">Any</option><option value="not_started">Not started</option><option value="in_progress">In progress</option><option value="done">Done</option><option value="blocked">Blocked</option></Select></Label>
        <label className="pb-1.5 text-xs text-slate-600"><input type="checkbox" checked={late} onChange={(e) => setLate(e.target.checked)} /> delayed only</label>
        <Label text="Search"><Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Task…" /></Label>
        <Label text="Report date"><Input type="date" value={asOf} onChange={(e) => e.target.value && setAsOf(e.target.value)} /></Label>
        {can("projects:write") && <Button onClick={() => { setPrefill(undefined); setOpen("new"); }}>New task</Button>}
      </div>
      {res && (
        <p className="mb-3 text-sm text-slate-600">
          {res.total} items · <Badge tone="green">{done} done</Badge> <Badge tone={overdue ? "red" : "slate"}>{overdue} overdue</Badge> <Badge tone={startLate ? "amber" : "slate"}>{startLate} start delayed</Badge>
          <span className="ml-2 text-xs text-slate-500">as of {fmt(res.as_of)}, grace {res.grace_days} day(s)</span>
        </p>
      )}
      {!res ? <Loading /> : res.items.length === 0 ? <>{can("projects:write") && <QuickAddBar phaseList={phases.map((p) => ({ id: String(p.id), name: String(p.name) }))} onQuickCreate={quickCreate} />}<Empty>No plan items match. Import a project plan under Smart Import, or add a task above.</Empty></> : view === "Gantt" ? (
        <Gantt items={res.items} phaseList={phases.map((p) => ({ id: String(p.id), name: String(p.name) }))} links={links} asOf={asOf} canEdit={can("projects:write")} onOpen={setOpen} onReschedule={reschedule} onLink={link} onUnlink={unlink} onAdd={add} statuses={statuses} statusColors={statusColors} onPatch={can("projects:write") ? patch : undefined} onQuickCreate={can("projects:write") ? quickCreate : undefined} onRenamePhase={(id, name) => setPhaseDialog({ id, name })} />
      ) : view === "Calendar" ? (
        <Calendar items={res.items} asOf={asOf} onOpen={setOpen} />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="border-b border-slate-300 uppercase text-slate-500">
              <tr><th className="py-2 pr-3">Task</th><th className="pr-3">Responsible</th><th className="pr-3">Owner</th><th className="pr-3">Location</th><th className="pr-3">Mode</th><th className="pr-3">Planned</th><th className="pr-3">Revised</th><th className="pr-3">Actual</th><th className="pr-3">Status</th><th>Flag</th></tr>
            </thead>
            <tbody>
              {grouped.map(([phase, list]) => (
                <PhaseRows key={phase} phase={phase} list={list} onOpen={setOpen} onTag={can("projects:write") ? () => tagPhase(phase) : undefined} canWrite={can("projects:write")} statuses={statuses} onPatch={patch} onQuickDate={setQuickDate} />
              ))}
            </tbody>
          </table>
        </div>
      )}
      {open && <WorkItemDrawer projectId={projectId} itemId={open === "new" ? null : open} prefill={open === "new" ? prefill : undefined} phases={phases} products={products} onClose={() => setOpen(null)} onChanged={changed} />}
      {quickDate && <QuickFinish w={quickDate} onCancel={() => setQuickDate(null)} onApply={setFinish} />}
      {phaseDialog && (
        <ConfirmDialog title={phaseDialog.id ? "Rename phase" : "Add a phase"} confirmLabel={phaseDialog.id ? "Rename" : "Add phase"} reasonLabel="Phase name" minReason={1} initial={phaseDialog.name}
          onCancel={() => setPhaseDialog(null)} onConfirm={savePhase}>A phase groups tasks on the plan and on the dashboards. Add tasks to it afterwards.</ConfirmDialog>
      )}
    </>
  );
}

function PhaseRows({ phase, list, onOpen, onTag, canWrite, statuses, onPatch, onQuickDate }: { phase: string; list: WorkItem[]; onOpen: (id: string) => void; onTag?: () => void; canWrite: boolean; statuses: Status[]; onPatch: (id: string, body: Record<string, unknown>) => Promise<void>; onQuickDate: (w: WorkItem) => void }) {
  const [shut, setShut] = useState(false);
  const done = list.filter((i) => i.is_closed).length;
  return (
    <>
      <tr className="cursor-pointer bg-slate-100" onClick={() => setShut((s) => !s)}>
        <td colSpan={10} className="px-2 py-1 font-semibold text-blue-950">
          {shut ? "▸" : "▾"} {phase} <span className="font-normal text-slate-500">({done}/{list.length} done{list.some((i) => i.is_overdue) ? `, ${list.filter((i) => i.is_overdue).length} overdue` : ""})</span>
          {onTag && <button className="ml-3 text-[11px] font-normal text-blue-900 underline" onClick={(e) => { e.stopPropagation(); onTag(); }}>tag with product</button>}
        </td>
      </tr>
      {!shut && list.map((w) => (
        <tr key={w.id} className="cursor-pointer border-b border-slate-100 hover:bg-blue-50" onClick={() => onOpen(w.id)}>
          <td className="max-w-md py-1 pr-3">{w.kind === "milestone" ? "◆ " : ""}{w.title}</td>
          <td className="pr-3">{w.responsible_party}</td><td className="pr-3"><InlineCell label="Owner" value={w.owner_name ?? ""} disabled={!canWrite} onSave={(v) => onPatch(w.id, { owner_name: v || null })} /></td><td className="max-w-40 truncate pr-3">{w.location_label}</td><td className="pr-3">{w.delivery_mode}</td>
          <td className={`whitespace-nowrap pr-3 ${w.revised_start || w.revised_finish ? "text-slate-500" : ""}`}>{fmt(w.planned_start)} → {fmt(w.planned_finish)}</td>
          <td className="whitespace-nowrap pr-3">{w.revised_start || w.revised_finish ? <span className="font-medium text-blue-950">{`${fmt(w.revised_start ?? w.planned_start)} → ${fmt(w.revised_finish ?? w.planned_finish)}`}</span> : ""}<Slip days={w.slippage_days} />
            {canWrite && <button className="ml-1 rounded-md px-1 text-[11px] text-slate-400 transition-colors hover:bg-blue-100 hover:text-blue-900" title="Change the finish date (needs a reason; the original is kept)" onClick={(e) => { e.stopPropagation(); onQuickDate(w); }}>{w.revised_start || w.revised_finish ? "✎" : "✎ date"}</button>}</td>
          <td className={`whitespace-nowrap pr-3 ${w.actual_finish ? "text-green-700" : ""}`}>{fmt(w.actual_start)} → {fmt(w.actual_finish)}</td>
          <td className="pr-3"><InlineCell label="Status" kind="select" value={statuses.find((x) => x.label === w.status_raw)?.code ?? ""} display={w.status_raw ?? ""} disabled={!canWrite || !statuses.length} options={statuses.map((x) => ({ value: x.code, label: x.label }))} onSave={(v) => onPatch(w.id, { status: v })} /></td>
          <td>{w.is_overdue ? <Badge tone="red">{w.days_late}d late</Badge> : w.is_start_delayed ? <Badge tone="amber">start delayed</Badge> : null}</td>
        </tr>
      ))}
    </>
  );
}

function QuickFinish({ w, onCancel, onApply }: { w: WorkItem; onCancel: () => void; onApply: (date: string, reason: string) => Promise<void> }) {
  const [date, setDate] = useState(w.effective_finish ?? "");
  return (
    <ConfirmDialog title="Change the finish date" confirmLabel="Change date" reasonLabel="Why is the date changing?" onCancel={onCancel} onConfirm={(reason) => onApply(date, reason)}>
      <div className="mb-2"><b>{w.title}</b></div>
      <div className="mb-2 text-xs text-slate-500">Now {fmt(w.effective_finish)}{w.planned_finish && w.planned_finish !== w.effective_finish ? ` (originally ${fmt(w.planned_finish)})` : ""}. The original planned date is kept and this goes into the date history.</div>
      <label className="mb-3 block text-xs font-medium text-slate-600"><span className="mb-1 block">New finish date</span><Input type="date" value={date} onChange={(e) => setDate(e.target.value)} /></label>
    </ConfirmDialog>
  );
}
