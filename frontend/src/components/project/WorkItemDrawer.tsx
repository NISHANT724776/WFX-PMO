"use client";

import { useCallback, useEffect, useState } from "react";
import { Discussion, LifecycleBar } from "@/components/manage/Workspace";
import { useToast } from "@/components/Toast";
import { useDirtyGuard, useUnsaved } from "@/components/Unsaved";
import { Badge, Button, DateJourney, ErrorBox, Input, Label, Select } from "@/components/ui";
import { api, qs, type Page, type Row } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmt, today, type Revision, type Status, type WorkItem, type WorkItemDetail } from "@/lib/plan";

type Flex = { definition_id: string; label: string; field_type: string; options: string[] | null; is_required: boolean; value: string | null };

export type Prefill = { phase_id?: string | null; parent_id?: string | null; kind?: "task" | "milestone" };

export default function WorkItemDrawer({ projectId, itemId, phases, products, prefill, onClose, onChanged }: {
  prefill?: Prefill; projectId: string; itemId: string | null; phases: Row[]; products: Row[]; onClose: () => void; onChanged: () => Promise<void> | void;
}) {
  const { can } = useAuth();
  const canWrite = can("projects:write");
  const [d, setD] = useState<WorkItemDetail | null>(null);
  const [statuses, setStatuses] = useState<Status[]>([]);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!itemId) return;
    try { setError(null); setD(await api<WorkItemDetail>(`/projects/${projectId}/work-items/${itemId}?as_of=${today()}`)); }
    catch (e) { setError(e instanceof Error ? e.message : "Failed to load"); }
  }, [projectId, itemId]);
  useEffect(() => { void load(); }, [load]);
  useEffect(() => { api<Page<Status>>(`/status-configs?q=work_item&size=50`).then((p) => setStatuses(p.items.filter((s) => s.entity_type === "work_item"))).catch(() => {}); }, []);

  const after = async () => { await load(); await onChanged(); };
  const unsaved = useUnsaved();
  const requestClose = () => { if (!unsaved.confirmLeave("Discard your unsaved changes?")) return; onClose(); };

  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-black/30" onClick={requestClose} onKeyDown={(e) => { if (e.key === "Escape") requestClose(); }}>
      <aside className="h-full w-full max-w-xl overflow-y-auto bg-white p-5 shadow-xl" onClick={(e) => e.stopPropagation()}>
        <div className="mb-3 flex items-start justify-between">
          <h2 className="pr-4 text-base font-semibold text-blue-950">{itemId ? d?.title ?? "Loading…" : prefill?.parent_id ? "New subtask" : prefill?.kind === "milestone" ? "New milestone" : "New task"}</h2>
          <button className="text-slate-500 hover:text-slate-900" onClick={requestClose} aria-label="Close">✕</button>
        </div>
        <ErrorBox message={error} />
        {!itemId ? (
          <CreateForm prefill={prefill} projectId={projectId} phases={phases} products={products} statuses={statuses} onDone={async () => { await onChanged(); onClose(); }} setError={setError} />
        ) : d && (
          <>
            <EditForm d={d} projectId={projectId} phases={phases} products={products} statuses={statuses} canWrite={canWrite} onSaved={after} setError={setError} />
            <Revisions d={d} projectId={projectId} canWrite={canWrite} onChanged={after} setError={setError} />
            <Dependencies d={d} projectId={projectId} canWrite={canWrite} onChanged={after} setError={setError} />
            <FlexFields entity="work_item" id={d.id} canWrite={canWrite} setError={setError} />
            <Discussion projectId={projectId} type="work_item" id={d.id} />
            <LifecycleBar projectId={projectId} type="work_item" id={d.id} state="active" onDone={after} onGone={async () => { await onChanged(); onClose(); }} setError={setError} />
          </>
        )}
      </aside>
    </div>
  );
}

function CreateForm({ prefill, projectId, phases, products, statuses, onDone, setError }: { prefill?: Prefill; projectId: string; phases: Row[]; products: Row[]; statuses: Status[]; onDone: () => Promise<void>; setError: (m: string | null) => void }) {
  const [v, setV] = useState({ title: "", kind: prefill?.kind ?? "task", phase_id: prefill?.phase_id ?? "", parent_id: prefill?.parent_id ?? "", product_id: "", responsible_party: "", owner_name: "", planned_start: "", planned_finish: "", delivery_mode: "", status: "not_started" });
  const set = (k: string) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setV((s) => ({ ...s, [k]: e.target.value }));
  const toast = useToast();
  useDirtyGuard(!!v.title.trim());
  async function save(e: React.FormEvent) {
    e.preventDefault(); setError(null);
    const body = Object.fromEntries(Object.entries(v).map(([k, x]) => [k, x === "" ? null : x]));
    try { await api(`/projects/${projectId}/work-items`, { method: "POST", body }); toast.ok("Task created"); await onDone(); }
    catch (err) { setError(err instanceof Error ? err.message : "Create failed"); }
  }
  return (
    <form onSubmit={save} className="space-y-3">
      <Label text="Title *"><Input required value={v.title} onChange={set("title")} /></Label>
      <div className="grid grid-cols-2 gap-3">
        <Label text="Type"><Select value={v.kind} onChange={set("kind")}><option value="task">Task</option><option value="milestone">Milestone</option></Select></Label>
        <Label text="Phase"><Select value={v.phase_id} onChange={set("phase_id")}><option value="">—</option>{phases.map((p) => <option key={String(p.id)} value={String(p.id)}>{String(p.name)}</option>)}</Select></Label>
        <Label text="Product"><Select value={v.product_id} onChange={set("product_id")}><option value="">All products</option>{products.map((p) => <option key={String(p.id)} value={String(p.id)}>{String(p.code)}</option>)}</Select></Label>
        <Label text="Status"><Select value={v.status} onChange={set("status")}>{statuses.map((s) => <option key={s.code} value={s.code}>{s.label}</option>)}</Select></Label>
        <Label text="Responsible party"><Input value={v.responsible_party} onChange={set("responsible_party")} placeholder="WFX / Tegra / JOINT" /></Label>
        <Label text="Owner"><Input value={v.owner_name} onChange={set("owner_name")} /></Label>
        <Label text="Planned start (baseline)"><Input type="date" value={v.planned_start} onChange={set("planned_start")} /></Label>
        <Label text="Planned finish (baseline)"><Input type="date" value={v.planned_finish} onChange={set("planned_finish")} /></Label>
        <Label text="Onsite / Online"><Select value={v.delivery_mode} onChange={set("delivery_mode")}><option value="">—</option><option value="onsite">Onsite</option><option value="online">Online</option></Select></Label>
      </div>
      <p className="text-xs text-slate-500">Planned dates become the baseline. Later changes are made as date revisions, so the original plan is never lost.</p>
      <Button type="submit">Create</Button>
    </form>
  );
}

function EditForm({ d, projectId, phases, products, statuses, canWrite, onSaved, setError }: { d: WorkItemDetail; projectId: string; phases: Row[]; products: Row[]; statuses: Status[]; canWrite: boolean; onSaved: () => Promise<void>; setError: (m: string | null) => void }) {
  const initial = () => ({ title: d.title, phase_id: d.phase_id ?? "", product_id: d.product_id ?? "", responsible_party: d.responsible_party ?? "", owner_name: d.owner_name ?? "", delivery_mode: d.delivery_mode ?? "", actual_start: d.actual_start ?? "", actual_finish: d.actual_finish ?? "", percent_complete: d.percent_complete == null ? "" : String(d.percent_complete), status: statuses.find((s) => s.label === d.status_raw)?.code ?? "", remarks: d.remarks ?? "", location_label: d.location_label ?? "" });
  const [v, setV] = useState(initial);
  useEffect(() => setV(initial()), [d, statuses]); // eslint-disable-line react-hooks/exhaustive-deps
  const set = (k: string) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) => setV((s) => ({ ...s, [k]: e.target.value }));
  const toast = useToast();
  useDirtyGuard(canWrite && JSON.stringify(v) !== JSON.stringify(initial()));
  async function save(e: React.FormEvent) {
    e.preventDefault(); setError(null);
    const body: Record<string, unknown> = {};
    for (const [k, x] of Object.entries(v)) body[k] = x === "" ? null : x;
    if (!body.status) delete body.status;
    if (body.percent_complete !== null) body.percent_complete = Number(body.percent_complete);
    try { await api(`/projects/${projectId}/work-items/${d.id}`, { method: "PATCH", body }); toast.ok("Changes saved"); await onSaved(); }
    catch (err) { setError(err instanceof Error ? err.message : "Save failed"); }
  }
  const dis = !canWrite;
  return (
    <form onSubmit={save} className="mb-6 space-y-3">
      <div className="flex flex-wrap gap-2 text-xs">
        {d.is_overdue && <Badge tone="red">{d.days_late} days late</Badge>}{d.is_start_delayed && <Badge tone="amber">start delayed</Badge>}{d.kind === "milestone" && <Badge tone="slate">milestone</Badge>}
        <span className="text-slate-500">Baseline {fmt(d.planned_start)} → {fmt(d.planned_finish)}{d.revised_start || d.revised_finish ? ` · current ${fmt(d.effective_start)} → ${fmt(d.effective_finish)} (${d.slippage_days > 0 ? "+" : ""}${d.slippage_days} d vs baseline)` : ""}</span>
      </div>
      <Label text="Title"><Input disabled={dis} value={v.title} onChange={set("title")} /></Label>
      <div className="grid grid-cols-2 gap-3">
        <Label text="Status"><Select disabled={dis} value={v.status} onChange={set("status")}><option value="">{d.status_raw ?? "—"}</option>{statuses.map((s) => <option key={s.code} value={s.code}>{s.label}</option>)}</Select></Label>
        <Label text="Phase"><Select disabled={dis} value={v.phase_id} onChange={set("phase_id")}><option value="">—</option>{phases.map((p) => <option key={String(p.id)} value={String(p.id)}>{String(p.name)}</option>)}</Select></Label>
        <Label text="Product"><Select disabled={dis} value={v.product_id} onChange={set("product_id")}><option value="">All products</option>{products.map((p) => <option key={String(p.id)} value={String(p.id)}>{String(p.code)}</option>)}</Select></Label>
        <Label text="Onsite / Online"><Select disabled={dis} value={v.delivery_mode} onChange={set("delivery_mode")}><option value="">—</option><option value="onsite">Onsite</option><option value="online">Online</option></Select></Label>
        <Label text="Responsible party"><Input disabled={dis} value={v.responsible_party} onChange={set("responsible_party")} /></Label>
        <Label text="Owner"><Input disabled={dis} value={v.owner_name} onChange={set("owner_name")} /></Label>
        <Label text="Location"><Input disabled={dis} value={v.location_label} onChange={set("location_label")} /></Label>
        <span />
        <Label text="Actual start"><Input disabled={dis} type="date" value={v.actual_start} onChange={set("actual_start")} /></Label>
        <Label text="Actual finish"><Input disabled={dis} type="date" value={v.actual_finish} onChange={set("actual_finish")} /></Label>
        <Label text="% complete (reported on this task)"><Input disabled={dis} type="number" min={0} max={100} value={v.percent_complete} onChange={set("percent_complete")} /></Label>
      </div>
      {d.percent_mismatch && <p className="text-xs text-amber-700">The reported % and the status disagree ({d.percent_complete}% reported, status {d.status_raw}). The status decides what the dashboards count; change one of them so they agree.</p>}
      {v.status === "done" && !v.actual_finish && <p className="text-xs text-amber-700">Marked done without an actual finish date. Enter the date the work really finished; it is not assumed.</p>}
      <Label text="Remarks"><textarea disabled={dis} className="w-full rounded-md border border-slate-300 px-2.5 py-1.5 text-sm" rows={2} value={v.remarks} onChange={set("remarks")} /></Label>
      {d.dependencies_text && <p className="text-xs text-slate-500">Dependencies in source file: {d.dependencies_text}</p>}
      {canWrite && <div className="flex gap-2"><Button type="submit">Save</Button></div>}
    </form>
  );
}

function Revisions({ d, projectId, canWrite, onChanged, setError }: { d: WorkItemDetail; projectId: string; canWrite: boolean; onChanged: () => Promise<void>; setError: (m: string | null) => void }) {
  const { can } = useAuth();
  const [field, setField] = useState("planned_finish");
  const [date, setDate] = useState("");
  const [reason, setReason] = useState("");
  const [approve, setApprove] = useState(false);
  async function propose(e: React.FormEvent) {
    e.preventDefault(); setError(null);
    try { await api(`/projects/${projectId}/work-items/${d.id}/revisions`, { method: "POST", body: { field, new_date: date, reason, approve } }); setDate(""); setReason(""); await onChanged(); }
    catch (err) { setError(err instanceof Error ? err.message : "Could not save revision"); }
  }
  async function decide(r: Revision, ok: boolean) {
    try { await api(`/projects/${projectId}/revisions/${r.id}/decision`, { method: "POST", body: { approve: ok } }); await onChanged(); }
    catch (err) { setError(err instanceof Error ? err.message : "Could not record decision"); }
  }
  return (
    <section className="mb-6">
      <h3 className="mb-1 text-sm font-semibold text-blue-950">Date revisions</h3>
      <DateJourney original={d.planned_finish} current={d.revised_finish ?? d.planned_finish} actual={d.actual_finish} days={d.slippage_days} />
      <p className="mb-2 text-xs text-slate-500">Baseline {fmt(d.planned_start)} → {fmt(d.planned_finish)} is never overwritten. Each change is a revision with a reason; only approved revisions move the dates.</p>
      {d.revisions.length === 0 ? <p className="mb-2 text-sm text-slate-500">No revisions.</p> : (
        <ul className="mb-3 ml-1.5 space-y-3 border-l-2 border-slate-200 text-xs">
          {d.revisions.map((r) => (
            <li key={r.id} className="relative pl-4"><span className={`absolute -left-[7px] top-1 h-3 w-3 rounded-full border-2 border-white ${r.status === "approved" ? "bg-green-500" : r.status === "rejected" ? "bg-slate-300" : "bg-amber-400"}`} />
              <div className="flex flex-wrap items-center gap-2"><Badge tone={r.status === "approved" ? "green" : r.status === "rejected" ? "slate" : "amber"}>{r.status}</Badge><b>{r.field.replace("planned_", "")}</b> {fmt(r.old_date)} → <b>{fmt(r.new_date)}</b>
                {r.status === "proposed" && can("plan:approve") && <><Button variant="ghost" onClick={() => decide(r, true)}>Approve</Button><Button variant="ghost" onClick={() => decide(r, false)}>Reject</Button></>}</div>
              <div className="text-slate-600">“{r.reason}” — {r.requested_by_email} · {new Date(r.requested_at).toLocaleString()}{r.decided_by_email ? ` · ${r.status} by ${r.decided_by_email}` : ""}</div>
            </li>
          ))}
        </ul>
      )}
      {canWrite && (
        <form onSubmit={propose} className="grid grid-cols-2 gap-2 rounded-md border border-slate-200 bg-slate-50 p-3">
          <Label text="Change"><Select value={field} onChange={(e) => setField(e.target.value)}><option value="planned_finish">Finish date</option><option value="planned_start">Start date</option></Select></Label>
          <Label text="New date"><Input required type="date" value={date} onChange={(e) => setDate(e.target.value)} /></Label>
          <div className="col-span-2"><Label text="Reason *"><Input required minLength={3} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Why is the date moving?" /></Label></div>
          <div className="col-span-2 flex items-center gap-3">
            <Button type="submit">{approve ? "Revise and approve" : "Propose revision"}</Button>
            {can("plan:approve") && <label className="text-xs text-slate-600"><input type="checkbox" checked={approve} onChange={(e) => setApprove(e.target.checked)} /> approve immediately</label>}
          </div>
        </form>
      )}
    </section>
  );
}

function Dependencies({ d, projectId, canWrite, onChanged, setError }: { d: WorkItemDetail; projectId: string; canWrite: boolean; onChanged: () => Promise<void>; setError: (m: string | null) => void }) {
  const [options, setOptions] = useState<WorkItem[]>([]);
  const [q, setQ] = useState("");
  const [pick, setPick] = useState("");
  useEffect(() => { if (q.length >= 2) api<{ items: WorkItem[] }>(`/projects/${projectId}/work-items${qs({ q, size: 30 })}`).then((r) => setOptions(r.items.filter((i) => i.id !== d.id))).catch(() => {}); else setOptions([]); }, [q, projectId, d.id]);
  async function add() {
    try { setError(null); await api(`/projects/${projectId}/work-items/${d.id}/dependencies`, { method: "POST", body: { predecessor_id: pick } }); setPick(""); setQ(""); await onChanged(); }
    catch (err) { setError(err instanceof Error ? err.message : "Could not add dependency"); }
  }
  async function remove(id: string) {
    try { await api(`/projects/${projectId}/dependencies/${id}`, { method: "DELETE" }); await onChanged(); } catch (err) { setError(err instanceof Error ? err.message : "Could not remove"); }
  }
  return (
    <section className="mb-6">
      <h3 className="mb-1 text-sm font-semibold text-blue-950">Dependencies</h3>
      <div className="grid grid-cols-2 gap-4 text-xs">
        <div><div className="mb-1 font-medium text-slate-600">Waits for</div>{d.predecessors.length === 0 && <div className="text-slate-500">nothing</div>}{d.predecessors.map((p) => <div key={p.id} className="flex justify-between gap-1 py-0.5"><span>{p.title}</span>{canWrite && <button className="text-red-700" onClick={() => remove(p.id)}>✕</button>}</div>)}</div>
        <div><div className="mb-1 font-medium text-slate-600">Blocks</div>{d.successors.length === 0 && <div className="text-slate-500">nothing</div>}{d.successors.map((p) => <div key={p.id} className="py-0.5">{p.title}</div>)}</div>
      </div>
      {canWrite && (
        <div className="mt-2 flex items-end gap-2">
          <Label text="Add a predecessor (type 2+ letters)"><Input value={q} onChange={(e) => setQ(e.target.value)} /></Label>
          <Select value={pick} onChange={(e) => setPick(e.target.value)} className="max-w-56"><option value="">Select…</option>{options.map((o) => <option key={o.id} value={o.id}>{o.title.slice(0, 60)}</option>)}</Select>
          <Button disabled={!pick} onClick={add}>Add</Button>
        </div>
      )}
    </section>
  );
}

export function FlexFields({ entity, id, canWrite, setError }: { entity: string; id: string; canWrite: boolean; setError: (m: string | null) => void }) {
  const [fields, setFields] = useState<Flex[] | null>(null);
  const [vals, setVals] = useState<Record<string, string>>({});
  const [saved, setSaved] = useState(false);
  useEffect(() => {
    api<Flex[]>(`/custom-field-values/${entity}/${id}`).then((f) => { setFields(f); setVals(Object.fromEntries(f.map((x) => [x.definition_id, x.value ?? ""]))); }).catch(() => setFields([]));
  }, [entity, id]);
  if (!fields || fields.length === 0) return null;
  async function save() {
    setError(null); setSaved(false);
    try { await api(`/custom-field-values/${entity}/${id}`, { method: "PUT", body: { values: Object.entries(vals).map(([definition_id, value]) => ({ definition_id, value })) } }); setSaved(true); }
    catch (err) { setError(err instanceof Error ? err.message : "Could not save"); }
  }
  return (
    <section className="mb-6">
      <h3 className="mb-1 text-sm font-semibold text-blue-950">Custom fields</h3>
      <div className="grid grid-cols-2 gap-3">
        {fields.map((f) => (
          <Label key={f.definition_id} text={f.label + (f.is_required ? " *" : "")}>
            {f.field_type === "dropdown" ? (
              <Select disabled={!canWrite} value={vals[f.definition_id] ?? ""} onChange={(e) => setVals((s) => ({ ...s, [f.definition_id]: e.target.value }))}><option value="">—</option>{(f.options ?? []).map((o) => <option key={o} value={o}>{o}</option>)}</Select>
            ) : (
              <Input disabled={!canWrite} type={f.field_type === "date" ? "date" : "text"} value={vals[f.definition_id] ?? ""} onChange={(e) => setVals((s) => ({ ...s, [f.definition_id]: e.target.value }))} />
            )}
          </Label>
        ))}
      </div>
      {canWrite && <div className="mt-2 flex items-center gap-3"><Button onClick={save}>Save custom fields</Button>{saved && <span className="text-xs text-green-700">Saved</span>}</div>}
    </section>
  );
}
