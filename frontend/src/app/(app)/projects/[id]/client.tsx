"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import Dashboards from "@/components/dash/Dashboards";
import { Icon, type IconName } from "@/components/icons";
import DeliveryTab from "@/components/delivery/DeliveryTab";
import PendingTab from "@/components/project/PendingTab";
import PlanTab from "@/components/project/PlanTab";
import ArchiveTab from "@/components/manage/ArchiveTab";
import DeliverablesTab from "@/components/qa/DeliverablesTab";
import UatTab from "@/components/qa/UatTab";
import TrackersTab from "@/components/project/TrackersTab";
import { Button, ErrorBox, Input, Label, PageHeader, Select, Loading, CountUp } from "@/components/ui";
import { useQuickAdd, useQuickContext } from "@/components/QuickAdd";
import { useToast } from "@/components/Toast";
import { useUnsaved } from "@/components/Unsaved";
import { api, type Page, type Row } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmt, today } from "@/lib/plan";

type Project = {
  id: string; code: string; name: string; status: string; start_date: string | null; target_go_live: string | null; delay_grace_days: number;
  products: { id: string; go_live_date: string | null; product: { code: string; name: string } }[];
  sites: { id: string; entity_name: string | null; location: { code: string; name: string; country: string | null } }[];
};
const TABS = ["Overview", "Dashboards", "Plan", "Delivery", "Pending", "UAT", "Reports & integrations", "Trackers", "Archive"] as const;
type Tab = (typeof TABS)[number];
const TAB_ICON: Record<Tab, IconName> = { Overview: "overview", Dashboards: "dashboards", Plan: "plan", Delivery: "delivery", Pending: "pending", UAT: "uat", "Reports & integrations": "reports", Trackers: "trackers", Archive: "archive" };

export default function ProjectWorkspace() {
  const tabRefs = useRef<Record<string, HTMLButtonElement | null>>({});
  const [ind, setInd] = useState({ left: 0, width: 0 });
  const { id } = useParams<{ id: string }>();
  const { can } = useAuth();
  const [p, setP] = useState<Project | null>(null);
  const [tab, setTab] = useState<Tab>("Overview");
  useLayoutEffect(() => {
    const place = () => { const el = tabRefs.current[tab]; if (el) setInd({ left: el.offsetLeft, width: el.offsetWidth }); };
    place();
    window.addEventListener("resize", place);
    return () => window.removeEventListener("resize", place);
  }, [tab, p]);
  const [products, setProducts] = useState<Row[]>([]);
  const [kpi, setKpi] = useState<{ tasks: number; late: number; pending: number; pendingLate: number } | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try { setError(null); setP(await api<Project>(`/projects/${id}`)); }
    catch (e) { setError(e instanceof Error ? e.message : "Failed to load"); }
  }, [id]);
  const loadKpi = useCallback(async () => {
    try {
      const a = today();
      const [all, late, pend] = await Promise.all([
        api<{ total: number }>(`/projects/${id}/work-items?size=1&as_of=${a}`),
        api<{ total: number }>(`/projects/${id}/work-items?size=1&as_of=${a}&overdue=true`),
        api<{ by_owner: Record<string, { open: number; overdue: number }> }>(`/projects/${id}/pending-summary?as_of=${a}`),
      ]);
      const o = Object.values(pend.by_owner);
      setKpi({ tasks: all.total, late: late.total, pending: o.reduce((n, x) => n + x.open, 0), pendingLate: o.reduce((n, x) => n + x.overdue, 0) });
    } catch { setKpi(null); }
  }, [id]);
  useEffect(() => { void load(); void loadKpi(); }, [load, loadKpi]);
  useQuickContext(id);
  const { version } = useQuickAdd();
  const unsaved = useUnsaved();
  const toast = useToast();
  const [shown, setShown] = useState(version);
  useEffect(() => {
    if (version === shown) return;
    if (!unsaved.anyDirty()) { setShown(version); void loadKpi(); }  // something was added with Quick Add: redraw this view
    else toast.ok("Created. Save or discard your edits, then refresh to see it.", { label: "Refresh now", onClick: () => { setShown(version); void loadKpi(); } });
  }, [version]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (can("master:read")) api<Page<Row>>("/products?size=200").then((r) => setProducts(r.items)).catch(() => {}); }, [can]);

  if (!p) return <><ErrorBox message={error} />{!error && <Loading />}<Link className="text-sm text-blue-900 underline" href="/projects">Back to projects</Link></>;
  const scoped = products.filter((x) => p.products.some((pp) => pp.product.code === x.code));

  return (
    <>
      <PageHeader title={`${p.code} · ${p.name}`} subtitle={`${p.status} · ${fmt(p.start_date)} → ${fmt(p.target_go_live)}`} actions={<Link className="inline-flex items-center gap-1 rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-slate-700 transition-colors hover:border-slate-400 hover:bg-slate-50" href="/projects">← Projects</Link>} />
      <ErrorBox message={error} />
      <div className="relative mb-5 flex gap-1 overflow-x-auto overflow-y-hidden border-b border-slate-200" role="tablist">
        <span aria-hidden="true" className="pointer-events-none absolute bottom-0 h-0.5 rounded-full bg-blue-900 transition-[left,width] duration-300 ease-[cubic-bezier(0.22,1,0.36,1)]" style={{ left: ind.left, width: ind.width, opacity: ind.width ? 1 : 0 }} />
        {TABS.map((t) => <button key={t} ref={(el) => { tabRefs.current[t] = el; }} onClick={() => { if (unsaved.confirmLeave()) setTab(t); }} role="tab" aria-selected={tab === t} className={`-mb-px flex items-center gap-1.5 whitespace-nowrap border-b-2 px-3 py-2 text-[13px] transition-colors duration-150 ${tab === t ? "border-transparent font-semibold text-blue-950" : "border-transparent text-slate-500 hover:border-slate-300 hover:text-slate-900"}`}><Icon name={TAB_ICON[t]} size={15} />{t}</button>)}
      </div>
      <div key={shown} className="wfx-enter">
      {tab === "Overview" && <Overview p={p} kpi={kpi} reload={async () => { await load(); await loadKpi(); }} products={products} />}
      {tab === "Dashboards" && <Dashboards projectId={id} products={scoped.length ? scoped : products} onChanged={loadKpi} />}
      {tab === "Plan" && <PlanTab projectId={id} products={scoped.length ? scoped : products} onChanged={loadKpi} />}
      {tab === "Delivery" && <DeliveryTab projectId={id} onChanged={loadKpi} />}
      {tab === "Pending" && <PendingTab projectId={id} products={scoped.length ? scoped : products} onChanged={loadKpi} />}
      {tab === "UAT" && <UatTab projectId={id} onChanged={loadKpi} />}
      {tab === "Reports & integrations" && <DeliverablesTab projectId={id} onChanged={loadKpi} />}
      {tab === "Trackers" && <TrackersTab projectId={id} products={products} />}
      {tab === "Archive" && <ArchiveTab projectId={id} onChanged={loadKpi} />}
      </div>
    </>
  );
}

function Overview({ p, kpi, reload, products }: { p: Project; kpi: { tasks: number; late: number; pending: number; pendingLate: number } | null; reload: () => Promise<void>; products: Row[] }) {
  const { can } = useAuth();
  const canWrite = can("projects:write");
  const [locations, setLocations] = useState<Row[]>([]);
  const [prodSel, setProdSel] = useState("");
  const [locSel, setLocSel] = useState("");
  const [grace, setGrace] = useState(String(p.delay_grace_days));
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { if (can("master:read")) api<Page<Row>>("/locations?size=200").then((r) => setLocations(r.items)).catch(() => {}); }, [can]);

  async function act(fn: () => Promise<unknown>) {
    try { setError(null); await fn(); await reload(); } catch (e) { setError(e instanceof Error ? e.message : "Action failed"); }
  }
  return (
    <>
      <ErrorBox message={error} />
      {kpi && (
        <div className="mb-6 grid grid-cols-2 gap-3 md:grid-cols-4">
          <Tile icon="status" label="Plan items" value={kpi.tasks} /><Tile icon="alert" label="Delayed plan items" value={kpi.late} bad={kpi.late > 0} />
          <Tile icon="pending" label="Open pending items" value={kpi.pending} /><Tile icon="alert" label="Overdue pending items" value={kpi.pendingLate} bad={kpi.pendingLate > 0} />
        </div>
      )}
      <div className="grid items-start gap-4 lg:grid-cols-3">
      <div className="rounded-xl border border-slate-200 bg-slate-50/60 p-4">
        <h2 className="mb-1 text-sm font-semibold text-blue-950">Delay rule</h2>
        <p className="mb-2 text-xs text-slate-600">An item counts as delayed once its latest approved date plus this many grace days has passed. The business has not fixed this rule yet, so it starts at 0 (delayed from the day after).</p>
        <div className="flex items-end gap-2">
          <Label text="Grace days"><Input type="number" min={0} max={60} className="w-24" disabled={!canWrite} value={grace} onChange={(e) => setGrace(e.target.value)} /></Label>
          {canWrite && <Button disabled={grace === String(p.delay_grace_days)} onClick={() => act(() => api(`/projects/${p.id}`, { method: "PATCH", body: { delay_grace_days: Number(grace) } }))}>Save</Button>}
        </div>
      </div>
        <section className="rounded-xl border border-slate-200 bg-white p-4">
          <h2 className="mb-2 text-sm font-semibold text-blue-950">Products</h2>
          {p.products.length === 0 && <p className="text-sm text-slate-500">No products on this project.</p>}
          <ul className="divide-y divide-slate-100 text-sm">{p.products.map((x) => (
            <li key={x.id} className="flex items-center justify-between py-1.5"><span>{x.product.code} · {x.product.name}</span>{canWrite && <Button variant="danger" onClick={() => act(() => api(`/projects/${p.id}/products/${x.id}`, { method: "DELETE" }))}>Remove</Button>}</li>
          ))}</ul>
          {canWrite && <div className="mt-3 flex items-end gap-2"><Label text="Add product"><Select value={prodSel} onChange={(e) => setProdSel(e.target.value)}><option value="">Select…</option>{products.map((r) => <option key={String(r.id)} value={String(r.id)}>{String(r.code)} · {String(r.name)}</option>)}</Select></Label>
            <Button disabled={!prodSel} onClick={() => act(async () => { await api(`/projects/${p.id}/products`, { method: "POST", body: { product_id: prodSel } }); setProdSel(""); })}>Add</Button></div>}
        </section>
        <section className="rounded-xl border border-slate-200 bg-white p-4">
          <h2 className="mb-2 text-sm font-semibold text-blue-950">Sites / locations</h2>
          {p.sites.length === 0 && <p className="text-sm text-slate-500">No sites on this project.</p>}
          <ul className="divide-y divide-slate-100 text-sm">{p.sites.map((x) => (
            <li key={x.id} className="flex items-center justify-between py-1.5"><span>{x.entity_name ?? x.location.name} · {x.location.name}{x.location.country ? ` (${x.location.country})` : ""}</span>{canWrite && <Button variant="danger" onClick={() => act(() => api(`/projects/${p.id}/sites/${x.id}`, { method: "DELETE" }))}>Remove</Button>}</li>
          ))}</ul>
          {canWrite && <div className="mt-3 flex items-end gap-2"><Label text="Add location"><Select value={locSel} onChange={(e) => setLocSel(e.target.value)}><option value="">Select…</option>{locations.map((r) => <option key={String(r.id)} value={String(r.id)}>{String(r.name)}</option>)}</Select></Label>
            <Button disabled={!locSel} onClick={() => act(async () => { await api(`/projects/${p.id}/sites`, { method: "POST", body: { location_id: locSel } }); setLocSel(""); })}>Add</Button></div>}
        </section>
      </div>
      
    </>
  );
}

function Tile({ label, value, bad, icon }: { label: string; value: number; bad?: boolean; icon: IconName }) {
  return <div className="wfx-enter rounded-xl border border-slate-200 bg-white p-4 shadow-[0_1px_2px_rgba(16,24,40,0.04)] transition-[box-shadow,transform] duration-200 hover:-translate-y-0.5 hover:shadow-md"><span className={`mb-2 grid h-8 w-8 place-items-center rounded-lg ${bad ? "bg-red-50 text-red-700" : "bg-blue-50 text-blue-900"}`}><Icon name={icon} size={16} /></span><div className={`text-3xl font-semibold tabular-nums tracking-tight ${bad ? "text-red-700" : "text-blue-950"}`}><CountUp value={value} /></div><div className="text-xs text-slate-500">{label}</div></div>;
}
