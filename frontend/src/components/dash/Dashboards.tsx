"use client";

import { useCallback, useEffect, useState } from "react";
import { Badge, Button, Empty, ErrorBox, Input, Label, Select, Loading } from "@/components/ui";
import WorkItemDrawer from "@/components/project/WorkItemDrawer";
import { api, downloadFile, qs, type Row } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import {
  SOURCE_LABEL, STATE_COLOR, type DashRow, type DelayDash, type DelayRow, type Overall, type ProductDash, type Ref, type RowState, type WeekDash,
} from "@/lib/dash";
import { fmt, today, type WorkItem } from "@/lib/plan";
import { RecordDrawer } from "@/components/delivery/RecordsTab";
import Builder from "@/components/builder/Builder";
import Reports from "./Reports";
import { useQuickProduct } from "@/components/QuickAdd";
import { useUnsaved } from "@/components/Unsaved";
import Drilldown from "./Drilldown";
import { AttentionRow, CoverageView, GatesView, WeekCard, mondayOf, type OpenRecord } from "./Manage";
import PlanTab from "@/components/project/PlanTab";
import DevPlan from "./DevPlan";
import { DashFooter, GateRow, Kpi, PhaseTimeline } from "./parts";

type Kind = "overall" | "product" | "next-week" | "delays" | "coverage" | "gates" | "custom" | "reports" | "devplan";
const KINDS: { key: Kind; label: string }[] = [{ key: "overall", label: "Overall status" }, { key: "devplan", label: "Dev plan timeline" }, { key: "product", label: "Product coverage" }, { key: "next-week", label: "Week plan" }, { key: "delays", label: "Delays" }, { key: "coverage", label: "Dept × location" }, { key: "gates", label: "Sign-off gates" }, { key: "custom", label: "My dashboards" }, { key: "reports", label: "Reports & exports" }];
const REPORT_KINDS: Kind[] = ["overall", "product", "next-week", "delays"];

export default function Dashboards({ projectId, products, onChanged }: { projectId: string; products: Row[]; onChanged: () => void }) {
  const { can } = useAuth();
  const [kind, setKind] = useState<Kind>("overall");
  const [asOf, setAsOf] = useState(today());
  const [productId, setProductId] = useState("");
  const [period, setPeriod] = useState("next_week");
  const [result, setResult] = useState<{ key: string; data: unknown } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [phases, setPhases] = useState<Row[]>([]);
  const [rowOpen, setRowOpen] = useState<DashRow | null>(null);
  const [itemOpen, setItemOpen] = useState<string | null>(null);
  const [drill, setDrill] = useState<string | null>(null);
  const [recOpen, setRecOpen] = useState<OpenRecord | null>(null);
  const unsaved = useUnsaved();
  const [tick, setTick] = useState(0);
  const [editing, setEditing] = useState(false); // the editable plan timeline stays open while the dashboard refreshes under it
  const [busy, setBusy] = useState(false);

  useQuickProduct(kind === "product" ? productId : undefined);
  const viewKey = `${kind}|${kind === "product" ? productId : ""}|${kind === "next-week" ? period : ""}|${asOf}`;
  // only ever render a payload that belongs to the view being shown (never the previous dashboard's data)
  const data = result && result.key === viewKey ? result.data : null;
  useEffect(() => { if (!productId && products.length) setProductId(String(products[0].id)); }, [products, productId]);
  const load = useCallback(async () => {
    if (kind === "product" && !productId) return;
    if (!REPORT_KINDS.includes(kind)) { setResult(null); return; } // coverage and gates load their own data
    try {
      setError(null);
      const path = kind === "product" ? `product/${productId}` : kind;
      const payload = await api(`/projects/${projectId}/dashboards/${path}${qs({ as_of: asOf, period: kind === "next-week" ? period : undefined })}`);
      setResult({ key: viewKey, data: payload });
      setPhases(await api<Row[]>(`/projects/${projectId}/phases`));
    } catch (e) { setResult(null); setError(e instanceof Error ? e.message : "Failed to load dashboard"); }
  }, [projectId, kind, productId, asOf, period, viewKey]);
  useEffect(() => { void load(); }, [load]);
  const refresh = async () => { await load(); setTick((t) => t + 1); onChanged(); }; // the open drill-down list reloads too

  async function exportExcel() {
    setBusy(true);
    try { await downloadFile(`/projects/${projectId}/dashboard-exports/next_week${qs({ as_of: asOf, period, format: "xlsx" })}`, "week-plan.xlsx"); }
    catch (e) { setError(e instanceof Error ? e.message : "Export failed"); }
    finally { setBusy(false); }
  }

  async function exportPptx() {
    setBusy(true);
    try { await downloadFile(`/projects/${projectId}/dashboard-exports/${kind}${qs({ as_of: asOf, product_id: kind === "product" ? productId : undefined, period: kind === "next-week" ? period : undefined })}`, "dashboard.pptx"); }
    catch (e) { setError(e instanceof Error ? e.message : "Export failed"); }
    finally { setBusy(false); }
  }

  return (
    <>
      <div className="mb-4 flex flex-wrap items-end gap-3 rounded-lg border border-slate-200 bg-slate-50/70 p-3 print:hidden">
        <div className="inline-flex max-w-full overflow-x-auto rounded-lg bg-slate-100 p-0.5">{KINDS.map((k) => <button key={k.key} onClick={() => { if (!unsaved.confirmLeave()) return; setKind(k.key); }} className={`px-3 py-1 transition-colors duration-150 whitespace-nowrap text-sm ${kind === k.key ? "rounded-md bg-white font-medium text-blue-950 shadow-sm" : "rounded-md text-slate-600 hover:text-slate-900"}`}>{k.label}</button>)}</div>
        {kind === "product" && <Label text="Product"><Select value={productId} onChange={(e) => setProductId(e.target.value)}>{products.map((p) => <option key={String(p.id)} value={String(p.id)}>{String(p.code)} · {String(p.name)}</option>)}</Select></Label>}
        {kind === "next-week" && <Label text="Period"><Select value={period} onChange={(e) => setPeriod(e.target.value)}><option value="this_week">This week</option><option value="next_week">Next week</option><option value="next_month">Next month</option></Select></Label>}
        <Label text="Report date"><Input type="date" value={asOf} onChange={(e) => e.target.value && setAsOf(e.target.value)} /></Label>
        {REPORT_KINDS.includes(kind) && <Button variant="ghost" onClick={() => window.print()}>Print / save as PDF</Button>}
        {REPORT_KINDS.includes(kind) && can("dashboards:export") && <Button disabled={busy || !data} onClick={exportPptx}>{busy ? "Exporting…" : "Export PowerPoint"}</Button>}
        {kind === "next-week" && can("dashboards:export") && <Button variant="ghost" disabled={busy || !data} onClick={exportExcel}>Export Excel</Button>}
      </div>
      <ErrorBox message={error} />
      {kind === "reports" ? <Reports projectId={projectId} products={products} asOf={asOf} />
      : kind === "custom" ? <Builder projectId={projectId} products={products} asOf={asOf} refreshKey={tick} onItem={setItemOpen} onDirty={() => {}} />
      : kind === "devplan" ? <DevPlan projectId={projectId} asOf={asOf} />
      : kind === "coverage" ? <CoverageView projectId={projectId} products={products} /> : kind === "gates" ? <GatesView projectId={projectId} />
      : !data ? (!error && <Loading />) : !(data as { available: boolean }).available && kind !== "next-week" ? (
        <>
          <Empty>Not enough data for this dashboard yet. Import a plan or tracker under Smart Import, or add items to the project. Nothing is shown as zero when there is nothing to measure.</Empty>
          {kind === "overall" && <p className="mb-2 mt-4 text-sm text-slate-600">This project has no plan tasks yet. See its <button className="text-blue-900 underline" onClick={() => setKind("devplan")}>Dev plan timeline</button> built from the imported records{can("projects:write") ? ", or build the plan here:" : "."}</p>}
          {kind === "overall" && can("projects:write") && <PlanTab projectId={projectId} products={products} initialView="Gantt" onChanged={() => { setEditing(true); refresh(); }} />}
        </>
      ) : kind === "overall" ? <OverallDash d={data as Overall} onRow={setRowOpen} onDrill={setDrill} projectId={projectId} products={products} canEdit={can("projects:write")} onChanged={refresh} editing={editing} setEditing={setEditing} />
        : kind === "product" ? <ProductDashboard d={data as ProductDash} projectId={projectId} onRow={setRowOpen} onItem={setItemOpen} onRecord={setRecOpen} onChanged={refresh} />
        : kind === "next-week" ? <WeekPlan d={data as WeekDash} projectId={projectId} onItem={setItemOpen} onRecord={setRecOpen} onChanged={refresh} />
        : <DelayView d={data as DelayDash} onItem={setItemOpen} />}
      {drill && <Drilldown refreshKey={tick} projectId={projectId} metric={drill} asOf={asOf} onClose={() => setDrill(null)} onItem={setItemOpen} />}
      {recOpen && <RecordDrawer projectId={projectId} start={recOpen} onClose={() => setRecOpen(null)} onChanged={refresh} onOpen={(kind, id) => setRecOpen({ kind, id })} />}
      {rowOpen && <RowDrawer projectId={projectId} row={rowOpen} asOf={asOf} onClose={() => setRowOpen(null)} onItem={setItemOpen} />}
      {itemOpen && <WorkItemDrawer projectId={projectId} itemId={itemOpen} phases={phases} products={products} onClose={() => setItemOpen(null)} onChanged={refresh} />}
    </>
  );
}

function Title({ t, sub }: { t: string; sub: string }) {
  return <div className="mb-3"><h2 className="text-xl font-semibold text-blue-950">{t}</h2><p className="text-xs text-slate-500">{sub}</p></div>;
}

/* ------------------------------------------------------------------ A. overall */
function OverallDash({ d, onRow, onDrill , projectId, products, canEdit, onChanged, editing, setEditing }: { d: Overall; onRow: (r: DashRow) => void; onDrill: (metric: string) => void , projectId: string; products: Row[]; canEdit: boolean; onChanged: () => void; editing: boolean; setEditing: (e: boolean) => void }) {
  const [filter, setFilter] = useState<RowState | null>(null);
  const k = d.kpis;
  const act = k.activities;
  const rows = filter ? d.rows.filter((r) => r.state === filter) : d.rows;
  const tog = (s: RowState) => setFilter((f) => (f === s ? null : s));
  return (
    <div>
      <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
        <Title t={`${d.project.customer ?? d.project.name}  ·  Project Status`} sub={`${d.project.name} · Status as of ${fmt(d.as_of)}`} />
        <div className="grid grid-cols-5 gap-2">
          <Kpi value={k.overall.pct_display === null ? "n/a" : `${k.overall.pct_display}%`} label="OVERALL" sub={`${k.overall.done}/${k.overall.total} items`} />
          <Kpi value={k.completed.value} label="COMPLETED" color={STATE_COLOR.done} onClick={() => tog("done")} active={filter === "done"} />
          <Kpi value={k.in_progress.value} label="IN PROGRESS" color={STATE_COLOR.in_progress} onClick={() => tog("in_progress")} active={filter === "in_progress"} />
          <Kpi value={k.overdue.value} label="OVERDUE PHASES" color={STATE_COLOR.overdue} onClick={() => tog("overdue")} active={filter === "overdue"} />
          <Kpi value={k.upcoming.value} label="UPCOMING" color={STATE_COLOR.upcoming} onClick={() => tog("upcoming")} active={filter === "upcoming"} />
        </div>
      </div>
      <div className="mb-3 grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
        <Kpi value={act.phases} label="TOTAL PHASES" sub="click for the list" onClick={() => onDrill("phases")} />
        <Kpi value={act.completed} label="COMPLETED ACTIVITIES" color={STATE_COLOR.done} sub={`of ${act.all}`} onClick={() => onDrill("completed")} />
        <Kpi value={act.in_progress} label="IN-PROGRESS ACTIVITIES" color={STATE_COLOR.in_progress} onClick={() => onDrill("in_progress")} />
        <Kpi value={act.overdue} label="OVERDUE ACTIVITIES" color={act.overdue ? STATE_COLOR.overdue : STATE_COLOR.done} onClick={() => onDrill("overdue")} />
        <Kpi value={act.not_started} label="UPCOMING ACTIVITIES" color={STATE_COLOR.upcoming} onClick={() => onDrill("not_started")} />
        <Kpi value={act.upcoming_milestones} label="UPCOMING MILESTONES" color="#b45309" onClick={() => onDrill("upcoming_milestones")} />
      </div>
      {filter && <p className="mb-2 text-xs text-blue-900 print:hidden">Showing only the {rows.length} row(s) counted in that tile. Click the tile again to see all.</p>}
      {canEdit && (
        <div className="mb-2 flex flex-wrap items-center gap-2 print:hidden">
          <div className="inline-flex rounded-lg bg-slate-100 p-0.5">
            {([false, true] as const).map((e) => (
              <button key={String(e)} onClick={() => setEditing(e)} className={`rounded-md px-3 py-1 text-sm transition-colors duration-150 ${editing === e ? "bg-white font-medium text-blue-950 shadow-sm" : "text-slate-600 hover:text-slate-900"}`}>{e ? "Edit timeline" : "Status view"}</button>
            ))}
          </div>
          {editing && <span className="text-xs text-slate-500">Edit the plan right here: drag bars, stretch them, mark ★ milestones, change status colours, add tasks. Every date change keeps the original and asks for a reason.</span>}
        </div>
      )}
      {editing && canEdit ? <PlanTab projectId={projectId} products={products} initialView="Gantt" onChanged={onChanged} /> : <PhaseTimeline rows={rows} asOf={d.as_of} onRow={onRow} />}
      <DashFooter meta={d} extra={d.notes[0]} />
    </div>
  );
}

/* ------------------------------------------------------------------ B. product */
function ProductDashboard({ d, projectId, onRow, onItem, onRecord, onChanged }: { d: ProductDash; projectId: string; onRow: (r: DashRow) => void; onItem: (id: string) => void; onRecord: (r: OpenRecord) => void; onChanged: () => void }) {
  const [lateOpen, setLateOpen] = useState(false);
  const k = d.kpis;
  const ng = k.next_gate;
  return (
    <div>
      <Title t={`${d.product.code}  —  Coverage & Status`} sub={`${d.product.name} · ${d.project.customer ?? ""} · Status as of ${fmt(d.as_of)}`} />
      <div className="mb-4 grid grid-cols-2 gap-2 md:grid-cols-5">
        <Kpi value={k.overall.pct_display === null ? "n/a" : `${k.overall.pct_display}%`} label="Overall completion" />
        <Kpi value={`${k.items.done} / ${k.items.total}`} label={k.items.label} />
        <Kpi value={k.late.value} label="Items overdue / start delayed" color={k.late.value ? STATE_COLOR.overdue : STATE_COLOR.done} onClick={k.late.value ? () => setLateOpen(true) : undefined} />
        <Kpi value={ng ? fmt(ng.planned) : "–"} label={ng ? `Next gate: ${ng.name}` : "Next gate: none upcoming"} color="#b45309" />
        <Kpi value={fmt(k.go_live)} label="Go-Live" />
      </div>
      <div className="grid gap-5 lg:grid-cols-[2fr_1fr]">
        <div className="min-w-0"><PhaseTimeline rows={d.rows} asOf={d.as_of} onRow={onRow} labelWidth={210} /></div>
        <div className="space-y-4">
          <section>
            <h3 className="mb-1 text-sm font-semibold text-blue-950">Sign-Off Gate Tracker</h3>
            {d.gates.length === 0 ? <p className="text-xs text-slate-500">No sign-off gates found in the imported tracker.</p> : <div className="space-y-1">{d.gates.map((g, i) => <GateRow key={i} g={g} />)}</div>}
          </section>
          {d.approvals.length > 0 && (
            <section>
              <h3 className="mb-1 text-sm font-semibold text-blue-950">Blueprint approvals by department</h3>
              {Object.entries(d.approval_summary).map(([set, s]) => <p key={set} className="text-xs text-slate-700">{set.replace(/_/g, " ")}: <b>{s.approved}</b> of {s.total} approved</p>)}
              <ul className="mt-1 max-h-40 overflow-y-auto text-[11px] text-slate-600">{d.approvals.filter((a) => a.state !== "done").slice(0, 12).map((a) => <li key={a.id}>• {a.name} <span className="text-slate-400">({a.status ?? "open"})</span></li>)}</ul>
            </section>
          )}
          <section>
            <h3 className="mb-1 text-sm font-semibold text-red-700">Needs attention</h3>
            {d.needs_attention.length === 0 ? <p className="text-xs text-slate-500">Nothing is overdue or waiting.</p> : (
              <ul className="space-y-1.5">{d.needs_attention.map((a, i) => <AttentionRow key={i} a={a} projectId={projectId} productId={d.product.id} onItem={onItem} onRecord={onRecord} onChanged={onChanged} />)}</ul>
            )}
          </section>
        </div>
      </div>
      <DashFooter meta={d} extra={d.notes[0]} />
      {lateOpen && <RefsList title="Items overdue / start delayed" refs={k.late.refs} onItem={(id) => { setLateOpen(false); onItem(id); }} onClose={() => setLateOpen(false)} />}
    </div>
  );
}

function RefsList({ title, refs, onItem, onClose }: { title: string; refs: Ref[]; onItem: (id: string) => void; onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-black/30 print:hidden" onClick={onClose}>
      <aside className="h-full w-full max-w-lg overflow-y-auto bg-white p-5 shadow-xl" onClick={(e) => e.stopPropagation()}>
        <div className="mb-3 flex justify-between"><h3 className="text-base font-semibold text-blue-950">{title} ({refs.length})</h3><button onClick={onClose} aria-label="Close">✕</button></div>
        <ul className="divide-y divide-slate-100 text-sm">{refs.map((r, i) => <li key={i} className="py-1.5">{r.type === "task" && r.id ? <button className="text-left text-blue-900 hover:underline" onClick={() => onItem(r.id!)}>{r.title}</button> : <span>{r.title} <span className="text-xs text-slate-400">(tracker event)</span></span>}</li>)}</ul>
      </aside>
    </div>
  );
}

/* ------------------------------------------------------------------ row drill-down (source records behind a bar) */
function RowDrawer({ projectId, row, asOf, onClose, onItem }: { projectId: string; row: DashRow; asOf: string; onClose: () => void; onItem: (id: string) => void }) {
  const [items, setItems] = useState<WorkItem[] | null>(null);
  const [events, setEvents] = useState<Row[] | null>(null);
  useEffect(() => {
    if (row.kind === "phase" && row.phase_id) api<{ items: WorkItem[] }>(`/projects/${projectId}/work-items${qs({ phase_id: row.phase_id, size: 500, as_of: asOf })}`).then((r) => setItems(r.items)).catch(() => setItems([]));
    else if (row.kind === "events" && row.product_id) api<{ items: Row[] }>(`/projects/${projectId}/tracker-events${qs({ product_id: row.product_id, size: 200 })}`).then((r) => setEvents(r.items)).catch(() => setEvents([]));
    else setItems([]);
  }, [projectId, row, asOf]);
  return (
    <div className="fixed inset-0 z-30 flex justify-end bg-black/30 print:hidden" onClick={onClose}>
      <aside className="h-full w-full max-w-2xl overflow-y-auto bg-white p-5 shadow-xl" onClick={(e) => e.stopPropagation()}>
        <div className="mb-1 flex justify-between"><h3 className="text-base font-semibold text-blue-950">{row.label}</h3><button onClick={onClose} aria-label="Close">✕</button></div>
        <p className="mb-3 text-xs text-slate-500">{row.area} · {row.done} of {row.items} done · {row.start ? `${fmt(row.start)} → ${fmt(row.end)}` : "no dates"} · these are the source records behind the bar{row.kind === "phase" ? "; click a task to open and update it" : ""}.</p>
        {!items && !events ? <Loading /> : items ? (
          <table className="w-full text-left text-xs"><thead className="border-b border-slate-300 uppercase text-slate-500"><tr><th className="py-1 pr-2">Task</th><th className="pr-2">Planned</th><th className="pr-2">Current</th><th className="pr-2">Status</th><th /></tr></thead>
            <tbody>{items.map((w) => (
              <tr key={w.id} className="cursor-pointer border-b border-slate-100 hover:bg-blue-50" onClick={() => onItem(w.id)}>
                <td className="py-1 pr-2">{w.kind === "milestone" ? "◆ " : ""}{w.title}</td><td className="whitespace-nowrap pr-2">{fmt(w.planned_finish)}</td><td className="whitespace-nowrap pr-2">{fmt(w.effective_finish)}</td><td className="pr-2">{w.status_raw}</td>
                <td>{w.is_overdue ? <Badge tone="red">{w.days_late}d late</Badge> : w.is_start_delayed ? <Badge tone="amber">start delayed</Badge> : null}</td>
              </tr>))}</tbody></table>
        ) : (
          <table className="w-full text-left text-xs"><thead className="border-b border-slate-300 uppercase text-slate-500"><tr><th className="py-1 pr-2">Event</th><th className="pr-2">Responsibility</th><th className="pr-2">Planned</th><th className="pr-2">Actual</th></tr></thead>
            <tbody>{(events ?? []).map((e) => <tr key={String(e.id)} className="border-b border-slate-100"><td className="py-1 pr-2">{String(e.event_name)}</td><td className="pr-2">{String(e.responsibility ?? "")}</td><td className="pr-2">{fmt(e.planned_date as string | null)}</td><td className="pr-2">{fmt(e.actual_date as string | null)}</td></tr>)}</tbody></table>
        )}
      </aside>
    </div>
  );
}

/* ------------------------------------------------------------------ C. week plan */
function WeekPlan({ d, projectId, onItem, onRecord, onChanged }: { d: WeekDash; projectId: string; onItem: (id: string) => void; onRecord: (r: OpenRecord) => void; onChanged: () => void }) {
  const { can } = useAuth();
  return (
    <div>
      <div className="mb-3 flex items-start justify-between gap-3">
        <Title t={`${d.week.label}  —  Plan`} sub={`${d.project.name} · report date ${fmt(d.as_of)} · weeks run Monday to Sunday`} />
        <div className="flex items-start gap-2">
          {can("projects:write") && <Button className="print:hidden" onClick={() => onRecord({ kind: "week-plan-items", id: null, initial: { week_start: mondayOf(d.week.start) } })}>＋ Add activity</Button>}
          <div className="rounded-lg bg-blue-950 px-4 py-2 text-center text-white"><div className="text-[10px] uppercase opacity-70">Period</div><div className="text-sm font-semibold">{fmt(d.week.start)} – {fmt(d.week.end)}</div></div>
        </div>
      </div>
      {d.groups.length === 0 && <Empty>Nothing is due or planned in this period. Use “Add activity” to put work on the plan.</Empty>}
      <div className="grid gap-3" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(270px, 1fr))" }}>
        {d.groups.map((g) => (
          <section key={g.name}>
            <div className="rounded-t bg-blue-900 px-3 py-1.5 text-sm font-semibold text-white">{g.name} <span className="font-normal opacity-80">· {g.count} activit{g.count === 1 ? "y" : "ies"}</span></div>
            <div className="space-y-2 rounded-b border border-t-0 border-slate-200 p-2">
              {g.cards.map((c) => <WeekCard key={c.seq} c={c} group={g.name} d={d} projectId={projectId} onItem={onItem} onRecord={onRecord} onChanged={onChanged} />)}
              {g.carry_over_hidden > 0 && <p className="text-[11px] text-slate-500">+ {g.carry_over_hidden} more overdue carry-over(s) not shown (see Delays)</p>}
            </div>
          </section>
        ))}
      </div>
      <DashFooter meta={d} extra={d.notes[0]} />
    </div>
  );
}

/* ------------------------------------------------------------------ F. delays */
function DelayView({ d, onItem }: { d: DelayDash; onItem: (id: string) => void }) {
  const [src, setSrc] = useState<string | null>(null);
  const rows = src ? d.rows.filter((r) => r.source === src) : d.rows;
  const maxAge = Math.max(1, ...d.ageing.map((a) => a.count));
  const maxProd = Math.max(1, ...d.by_product.map((a) => a.count));
  return (
    <div>
      <Title t="Delay Dashboard" sub={`${d.project.name} · as of ${fmt(d.as_of)} · grace ${d.grace_days} day(s) · plan, trackers, pending activities, gap specifications and sign-off gates`} />
      <div className="mb-4 grid grid-cols-2 gap-2 md:grid-cols-7">
        <Kpi value={d.total} label="Delayed items" color={d.total ? STATE_COLOR.overdue : STATE_COLOR.done} onClick={() => setSrc(null)} active={src === null} />
        {d.sources.map((s) => (
          <div key={s.key} title={s.reason ?? (s.available ? "" : "No data imported for this source")} className={s.available ? "" : "opacity-50"}>
            <Kpi value={s.count === null ? "n/a" : s.count} label={s.label} color={s.available && s.count ? STATE_COLOR.overdue : "#64748b"} onClick={s.available ? () => setSrc(src === s.key ? null : s.key) : undefined} active={src === s.key} sub={s.available ? undefined : s.reason ? "later phase" : "no data"} />
          </div>
        ))}
      </div>
      <div className="mb-5 grid gap-5 md:grid-cols-3">
        <section><h3 className="mb-1 text-sm font-semibold text-blue-950">Ageing (days late)</h3>
          {d.ageing.map((a, i) => <Bar key={a.bucket} label={`${a.bucket} d`} n={a.count} max={maxAge} color={i >= 3 ? STATE_COLOR.overdue : STATE_COLOR.in_progress} />)}</section>
        <section><h3 className="mb-1 text-sm font-semibold text-blue-950">By product</h3>
          {d.by_product.slice(0, 8).map((a) => <Bar key={a.name} label={a.name} n={a.count} max={maxProd} color="#1e3a8a" />)}</section>
        <section><h3 className="mb-1 text-sm font-semibold text-blue-950">Customer vs WFX</h3>
          <ul className="text-xs text-slate-700">{d.by_party.map((p) => <li key={p.party}>{p.party === "other" ? "Other / named person" : p.party[0].toUpperCase() + p.party.slice(1)}: <b>{p.count}</b></li>)}</ul>
          <h3 className="mt-3 mb-1 text-sm font-semibold text-blue-950">Most affected owners</h3>
          <ul className="text-xs text-slate-700">{d.by_owner.slice(0, 5).map((p) => <li key={p.name}>{p.name}: <b>{p.count}</b></li>)}</ul></section>
      </div>
      <h3 className="mb-1 text-sm font-semibold text-blue-950">{src ? SOURCE_LABEL[src] : "All sources"} · most delayed first</h3>
      <DelayTable rows={rows.slice(0, 80)} onItem={onItem} />
      {rows.length > 80 && <p className="mt-1 text-xs text-slate-500">Showing 80 of {rows.length}.</p>}
      {d.slippage.length > 0 && <><h3 className="mt-5 mb-1 text-sm font-semibold text-blue-950">Slippage against the original date</h3><DelayTable rows={d.slippage.slice(0, 15)} onItem={onItem} showSlip /></>}
      <DashFooter meta={d} extra={d.notes.join(" ")} />
    </div>
  );
}

function Bar({ label, n, max, color }: { label: string; n: number; max: number; color: string }) {
  return <div className="mb-1 flex items-center gap-2 text-xs"><span className="w-20 shrink-0 truncate text-slate-600">{label}</span><div className="h-3.5 rounded-sm" style={{ width: `${(n / max) * 60}%`, minWidth: n ? 3 : 0, background: color }} /><b>{n}</b></div>;
}

function DelayTable({ rows, onItem, showSlip }: { rows: DelayRow[]; onItem: (id: string) => void; showSlip?: boolean }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-xs">
        <thead className="border-b border-slate-300 uppercase text-slate-500"><tr><th className="py-1 pr-2">Item</th><th className="pr-2">Source</th><th className="pr-2">Product</th><th className="pr-2">Owner</th><th className="pr-2">Original</th><th className="pr-2">Current due</th><th className="pr-2">Late</th>{showSlip && <th>Slipped</th>}</tr></thead>
        <tbody>
          {rows.map((r) => {
            const click = r.source === "plan_task";
            return (
              <tr key={r.source + r.id} className={`border-b border-slate-100 ${click ? "cursor-pointer hover:bg-blue-50" : ""}`} onClick={click ? () => onItem(r.id) : undefined}>
                <td className="max-w-md py-1 pr-2">{r.title}</td><td className="pr-2">{SOURCE_LABEL[r.source]}</td><td className="pr-2">{r.product}</td><td className="pr-2">{r.owner ?? r.responsibility ?? ""}</td>
                <td className="whitespace-nowrap pr-2">{fmt(r.baseline)}</td><td className="whitespace-nowrap pr-2">{fmt(r.due)}</td><td className="pr-2 font-semibold text-red-700">{r.days_late} d{r.kind === "start_delayed" ? " (start)" : ""}</td>
                {showSlip && <td className="text-amber-700">+{r.slippage} d</td>}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
