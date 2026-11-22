"use client";

import { useCallback, useEffect, useState } from "react";
import { Discussion, LifecycleBar } from "@/components/manage/Workspace";
import { useToast } from "@/components/Toast";
import { useDirtyGuard, useUnsaved } from "@/components/Unsaved";
import { Badge, Button, DateJourney, Empty, ErrorBox, Input, Label, Select, Slip, Loading } from "@/components/ui";
import { api, qs, type Page, type Row } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { PENDING_LABEL, fmt, today, type PendingItem, type Revision, type Status } from "@/lib/plan";
import { FlexFields } from "./WorkItemDrawer";

type Summary = { by_owner: Record<string, { open: number; overdue: number; closed: number }> };
const OWNERS = ["customer", "wfx", "external", "internal"] as const;

export default function PendingTab({ projectId, products, onChanged }: { projectId: string; products: Row[]; onChanged: () => void }) {
  const { can } = useAuth();
  const [who, setWho] = useState<string>("");
  const [lateOnly, setLateOnly] = useState(false);
  const [openOnly, setOpenOnly] = useState(true);
  const [asOf, setAsOf] = useState(today());
  const [q, setQ] = useState("");
  const [data, setData] = useState<Page<PendingItem> | null>(null);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [sel, setSel] = useState<string | "new" | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setError(null);
      setData(await api<Page<PendingItem>>(`/projects/${projectId}/pending-items${qs({ size: 500, as_of: asOf, pending_with: who, overdue: lateOnly ? true : undefined, open_only: openOnly, q })}`));
      setSummary(await api<Summary>(`/projects/${projectId}/pending-summary?as_of=${asOf}`));
    } catch (e) { setError(e instanceof Error ? e.message : "Failed to load"); }
  }, [projectId, asOf, who, lateOnly, openOnly, q]);
  useEffect(() => { void load(); }, [load]);
  const changed = async () => { await load(); onChanged(); };

  return (
    <>
      <ErrorBox message={error} />
      <div className="mb-4 grid max-w-3xl grid-cols-2 gap-3 md:grid-cols-4">
        {OWNERS.map((o) => {
          const s = summary?.by_owner[o];
          return (
            <button key={o} onClick={() => setWho(who === o ? "" : o)} className={`rounded-md border p-3 text-left ${who === o ? "border-blue-900 bg-blue-50" : "border-slate-200 hover:bg-slate-50"}`}>
              <div className="text-xs text-slate-500">Pending with {PENDING_LABEL[o]}</div>
              <div className="text-2xl font-semibold text-blue-950">{s?.open ?? "–"}<span className="ml-1 text-xs font-normal text-slate-500">open</span></div>
              <div className={`text-xs ${s?.overdue ? "text-red-700" : "text-slate-500"}`}>{s?.overdue ?? 0} overdue · {s?.closed ?? 0} closed</div>
            </button>
          );
        })}
      </div>
      <div className="mb-4 flex flex-wrap items-end gap-3 rounded-lg border border-slate-200 bg-slate-50/70 p-3">
        <Label text="Search"><Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Description…" /></Label>
        <label className="pb-1.5 text-xs text-slate-600"><input type="checkbox" checked={openOnly} onChange={(e) => setOpenOnly(e.target.checked)} /> open only</label>
        <label className="pb-1.5 text-xs text-slate-600"><input type="checkbox" checked={lateOnly} onChange={(e) => setLateOnly(e.target.checked)} /> overdue only</label>
        <Label text="Report date"><Input type="date" value={asOf} onChange={(e) => e.target.value && setAsOf(e.target.value)} /></Label>
        {who && <Button variant="ghost" onClick={() => setWho("")}>Showing: {PENDING_LABEL[who]} ✕</Button>}
        {can("projects:write") && <Button onClick={() => setSel("new")}>Add pending item</Button>}
      </div>
      {!data ? <Loading /> : data.items.length === 0 ? <Empty>No pending items match. Import a pending-items sheet under Smart Import, or add one.</Empty> : (
        <table className="w-full text-left text-xs">
          <thead className="border-b border-slate-300 uppercase text-slate-500"><tr><th className="py-2 pr-3">Item</th><th className="pr-3">With</th><th className="pr-3">Owner</th><th className="pr-3">Target</th><th className="pr-3">Revised</th><th className="pr-3">Closed</th><th className="pr-3">Status</th><th>Flag</th></tr></thead>
          <tbody>
            {data.items.map((p) => (
              <tr key={p.id} className="cursor-pointer border-b border-slate-100 hover:bg-blue-50" onClick={() => setSel(p.id)}>
                <td className="max-w-md py-1 pr-3">{p.category && <span className="mr-1 text-slate-400">{p.category} ›</span>}{p.description}</td>
                <td className="pr-3">{PENDING_LABEL[p.pending_with]}</td><td className="pr-3">{p.owner_name}</td>
                <td className="whitespace-nowrap pr-3">{fmt(p.original_target_date)}</td>
                <td className="whitespace-nowrap pr-3">{p.revised_target_date ? <span className="font-medium text-blue-950">{fmt(p.revised_target_date)}</span> : fmt(p.revised_target_date)}<Slip days={p.slippage_days} /></td>
                <td className="whitespace-nowrap pr-3">{fmt(p.actual_closure_date)}</td><td className="pr-3">{p.status_raw}</td>
                <td>{p.is_overdue ? <Badge tone="red">{p.days_late}d late</Badge> : null}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {sel && <PendingDrawer projectId={projectId} id={sel === "new" ? null : sel} products={products} onClose={() => setSel(null)} onChanged={changed} />}
    </>
  );
}

function PendingDrawer({ projectId, id, products, onClose, onChanged }: { projectId: string; id: string | null; products: Row[]; onClose: () => void; onChanged: () => Promise<void> }) {
  const { can } = useAuth();
  const canWrite = can("projects:write");
  const [d, setD] = useState<PendingItem | null>(null);
  const [statuses, setStatuses] = useState<Status[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [v, setV] = useState<Record<string, string>>({ pending_with: "customer", description: "", owner_name: "", category: "", product_id: "", original_target_date: "", remarks: "", status: "not_started", actual_closure_date: "" });
  const [rev, setRev] = useState({ date: "", reason: "", approve: false });

  const load = useCallback(async () => {
    if (!id) return;
    try {
      const x = await api<PendingItem>(`/projects/${projectId}/pending-items/${id}?as_of=${today()}`);
      setD(x);
      setV({ pending_with: x.pending_with, description: x.description, owner_name: x.owner_name ?? "", category: x.category ?? "", product_id: x.product_id ?? "", original_target_date: x.original_target_date ?? "", remarks: x.remarks ?? "", status: "", actual_closure_date: x.actual_closure_date ?? "" });
    } catch (e) { setError(e instanceof Error ? e.message : "Failed to load"); }
  }, [projectId, id]);
  useEffect(() => { void load(); }, [load]);
  useEffect(() => { api<Page<Status>>(`/status-configs?q=dependency&size=50`).then((p) => setStatuses(p.items.filter((s) => s.entity_type === "dependency"))).catch(() => {}); }, []);
  const [touched, setTouched] = useState(false);
  const toast = useToast();
  const unsaved = useUnsaved();
  useDirtyGuard(touched && canWrite);
  const requestClose = () => { if (!unsaved.confirmLeave("Discard your unsaved changes?")) return; onClose(); };
  const set = (k: string) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) => { setTouched(true); setV((s) => ({ ...s, [k]: e.target.value })); };
  const clean = (o: Record<string, string>) => Object.fromEntries(Object.entries(o).map(([k, x]) => [k, x === "" ? null : x]));

  async function save(e: React.FormEvent) {
    e.preventDefault(); setError(null);
    try {
      if (!id) await api(`/projects/${projectId}/pending-items`, { method: "POST", body: { ...clean(v), status: v.status || "not_started" } });
      else { const b = clean(v); delete b.original_target_date; if (!b.status) delete b.status; await api(`/projects/${projectId}/pending-items/${id}`, { method: "PATCH", body: b }); }
      setTouched(false); toast.ok(id ? "Changes saved" : "Pending item created"); await onChanged(); if (!id) onClose(); else await load();
    } catch (err) { setError(err instanceof Error ? err.message : "Save failed"); }
  }
  async function revise(e: React.FormEvent) {
    e.preventDefault(); setError(null);
    try { await api(`/projects/${projectId}/pending-items/${id}/revisions`, { method: "POST", body: { field: "target_date", new_date: rev.date, reason: rev.reason, approve: rev.approve } }); setRev({ date: "", reason: "", approve: false }); await onChanged(); await load(); }
    catch (err) { setError(err instanceof Error ? err.message : "Could not save revision"); }
  }
  async function decide(r: Revision, ok: boolean) {
    try { await api(`/projects/${projectId}/revisions/${r.id}/decision`, { method: "POST", body: { approve: ok } }); await onChanged(); await load(); } catch (err) { setError(err instanceof Error ? err.message : "Failed"); }
  }

  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-black/30" onClick={requestClose} onKeyDown={(e) => { if (e.key === "Escape") requestClose(); }}>
      <aside className="h-full w-full max-w-xl overflow-y-auto bg-white p-5 shadow-xl" onClick={(e) => e.stopPropagation()}>
        <div className="mb-3 flex items-start justify-between"><h2 className="pr-4 text-base font-semibold text-blue-950">{id ? "Pending item" : "New pending item"}</h2><button onClick={requestClose} aria-label="Close" className="text-slate-500">✕</button></div>
        <ErrorBox message={error} />
        {d?.is_overdue && <p className="mb-2"><Badge tone="red">{d.days_late} days overdue</Badge></p>}
        <form onSubmit={save} className="mb-6 space-y-3">
          <Label text="Description *"><textarea required disabled={!canWrite} className="w-full rounded-md border border-slate-300 px-2.5 py-1.5 text-sm" rows={2} value={v.description} onChange={set("description")} /></Label>
          <div className="grid grid-cols-2 gap-3">
            <Label text="Pending with *"><Select disabled={!canWrite} value={v.pending_with} onChange={set("pending_with")}>{OWNERS.map((o) => <option key={o} value={o}>{PENDING_LABEL[o]}</option>)}</Select></Label>
            <Label text="Owner"><Input disabled={!canWrite} value={v.owner_name} onChange={set("owner_name")} /></Label>
            <Label text="Group / category"><Input disabled={!canWrite} value={v.category} onChange={set("category")} /></Label>
            <Label text="Product"><Select disabled={!canWrite} value={v.product_id} onChange={set("product_id")}><option value="">All</option>{products.map((p) => <option key={String(p.id)} value={String(p.id)}>{String(p.code)}</option>)}</Select></Label>
            {!id && <Label text="Target date (baseline)"><Input type="date" value={v.original_target_date} onChange={set("original_target_date")} /></Label>}
            {id && <Label text="Status"><Select disabled={!canWrite} value={v.status} onChange={set("status")}><option value="">{d?.status_raw ?? "—"}</option>{statuses.map((s) => <option key={s.code} value={s.code}>{s.label}</option>)}</Select></Label>}
            {id && <Label text="Actual closure date"><Input disabled={!canWrite} type="date" value={v.actual_closure_date} onChange={set("actual_closure_date")} /></Label>}
          </div>
          <Label text="Remarks"><textarea disabled={!canWrite} className="w-full rounded-md border border-slate-300 px-2.5 py-1.5 text-sm" rows={2} value={v.remarks} onChange={set("remarks")} /></Label>
          {canWrite && <div className="flex gap-2"><Button type="submit">{id ? "Save" : "Create"}</Button></div>}
        </form>
        {id && d && (
          <>
            <section className="mb-6">
              <h3 className="mb-1 text-sm font-semibold text-blue-950">Target date history</h3>
              <DateJourney original={d.original_target_date} current={d.revised_target_date ?? d.original_target_date} actual={d.actual_closure_date ?? null} days={d.slippage_days} />
              <p className="mb-2 text-xs text-slate-500">Baseline {fmt(d.original_target_date)}{d.revised_target_date ? ` · current ${fmt(d.revised_target_date)} (+${d.slippage_days} d)` : ""}</p>
              {(d.revisions ?? []).length === 0 ? <p className="mb-2 text-sm text-slate-500">No revisions.</p> : (
                <ul className="mb-3 ml-1.5 space-y-3 border-l-2 border-slate-200 text-xs">
                  {d.revisions!.map((r) => (
                    <li key={r.id} className="relative pl-4"><span className={`absolute -left-[7px] top-1 h-3 w-3 rounded-full border-2 border-white ${r.status === "approved" ? "bg-green-500" : r.status === "rejected" ? "bg-slate-300" : "bg-amber-400"}`} /><div className="flex flex-wrap items-center gap-2"><Badge tone={r.status === "approved" ? "green" : r.status === "rejected" ? "slate" : "amber"}>{r.status}</Badge>{fmt(r.old_date)} → <b>{fmt(r.new_date)}</b>
                      {r.status === "proposed" && can("plan:approve") && <><Button variant="ghost" onClick={() => decide(r, true)}>Approve</Button><Button variant="ghost" onClick={() => decide(r, false)}>Reject</Button></>}</div>
                      <div className="text-slate-600">“{r.reason}” — {r.requested_by_email}</div></li>
                  ))}
                </ul>
              )}
              {canWrite && (
                <form onSubmit={revise} className="grid grid-cols-2 gap-2 rounded-md border border-slate-200 bg-slate-50 p-3">
                  <Label text="New target date"><Input required type="date" value={rev.date} onChange={(e) => setRev((s) => ({ ...s, date: e.target.value }))} /></Label>
                  <Label text="Reason *"><Input required minLength={3} value={rev.reason} onChange={(e) => setRev((s) => ({ ...s, reason: e.target.value }))} /></Label>
                  <div className="col-span-2 flex items-center gap-3"><Button type="submit">{rev.approve ? "Revise and approve" : "Propose revision"}</Button>{can("plan:approve") && <label className="text-xs text-slate-600"><input type="checkbox" checked={rev.approve} onChange={(e) => setRev((s) => ({ ...s, approve: e.target.checked }))} /> approve immediately</label>}</div>
                </form>
              )}
            </section>
            <FlexFields entity="dependency_item" id={id} canWrite={canWrite} setError={setError} />
            <Discussion projectId={projectId} type="dependency_item" id={id} />
            <LifecycleBar projectId={projectId} type="dependency_item" id={id} state="active" onDone={async () => { await onChanged(); await load(); }} onGone={async () => { await onChanged(); onClose(); }} setError={setError} />
          </>
        )}
      </aside>
    </div>
  );
}
