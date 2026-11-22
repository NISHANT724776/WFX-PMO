"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { ActionSteps, ConfirmDialog, Discussion, LifecycleBar } from "@/components/manage/Workspace";
import InlineCell from "@/components/InlineCell";
import { useToast } from "@/components/Toast";
import { useDirtyGuard, useUnsaved } from "@/components/Unsaved";
import { Badge, Button, DateJourney, Empty, ErrorBox, Input, Label, Pager, Select, Loading } from "@/components/ui";
import { api, qs, type Page } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmt, today, type Status } from "@/lib/plan";
import { FlexFields } from "@/components/project/WorkItemDrawer";
import { BY_SLUG, BY_TYPE, type KindConfig, type Rec, type RefKind, type Suggestion } from "@/lib/records";

type Facets = Record<string, { value: string | null; count: number }[]>;
const SIZE = 50;
type State = "active" | "archived" | "deleted";
type Refs = Partial<Record<RefKind, Record<string, string>>>;
const val = (r: Rec, c: { key: string; date?: boolean; ref?: RefKind }, refs: Refs = {}) =>
  c.date ? fmt(r[c.key] as string | null) : c.ref ? (refs[c.ref]?.[String(r[c.key] ?? "")] ?? "") : String(r[c.key] ?? "");

/** Names for the master records a list refers to (product, department, location), loaded once. */
export function useRefs(cfg: KindConfig, projectId?: string): { refs: Refs; options: Partial<Record<RefKind, { id: string; label: string }[]>> } {
  const [data, setData] = useState<Partial<Record<RefKind, { id: string; label: string }[]>>>({});
  const needed = useMemo(() => [...new Set([...cfg.columns.map((c) => c.ref), ...cfg.filters.map((f) => f.ref), ...cfg.fields.map((f) => f.ref)].filter(Boolean) as RefKind[])], [cfg]);
  useEffect(() => {
    needed.forEach((k) => {
      if (k === "scenarios") {  // UAT scenarios of this project, so a defect can be tied to one
        if (projectId) api<Page<{ id: string; scenario_id: string | null; title: string }>>(`/projects/${projectId}/records/uat-scenarios?size=200`).then((p) =>
          setData((d) => ({ ...d, scenarios: p.items.map((x) => ({ id: x.id, label: `${x.scenario_id ? x.scenario_id + " " : ""}${x.title}`.slice(0, 80) })) }))).catch(() => {});
        return;
      }
      api<Page<{ id: string; code: string; name: string }>>(`/${k}?size=200`).then((p) =>
        setData((d) => ({ ...d, [k]: p.items.map((x) => ({ id: x.id, label: k === "products" ? x.code : x.name })) }))).catch(() => {});
    });
  }, [needed, projectId]);
  const refs = useMemo(() => Object.fromEntries(Object.entries(data).map(([k, v]) => [k, Object.fromEntries(v!.map((x) => [x.id, x.label]))])) as Refs, [data]);
  return { refs, options: data };
}

export default function RecordsTab({ projectId, cfg, onChanged, preset }: { projectId: string; cfg: KindConfig; onChanged: () => void; preset?: Record<string, string> }) {
  const { can } = useAuth();
  const { refs } = useRefs(cfg, projectId);
  const [data, setData] = useState<Page<Rec> | null>(null);
  const [facets, setFacets] = useState<Facets>({});
  const [filters, setFilters] = useState<Record<string, string>>({});
  const [q, setQ] = useState("");
  const [late, setLate] = useState(false);
  const [asOf, setAsOf] = useState(today());
  const [page, setPage] = useState(1);
  const [open, setOpen] = useState<{ kind: string; id: string | null; state?: State; initial?: Record<string, string> } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [state, setState] = useState<State>("active");
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [bulk, setBulk] = useState<null | { action: string; label: string; danger?: boolean }>(null);
  const [bulkField, setBulkField] = useState("");
  const [bulkValue, setBulkValue] = useState("");
  const [notice, setNotice] = useState<string | null>(null);
  const [statuses, setStatuses] = useState<Status[]>([]);
  useEffect(() => { if (cfg.statusEntity) api<Page<Status>>(`/status-configs?q=${cfg.statusEntity}&size=50`).then((p) => setStatuses(p.items.filter((x) => x.entity_type === cfg.statusEntity))).catch(() => {}); else setStatuses([]); }, [cfg.statusEntity]);
  const statusKey = cfg.statusField ?? "status_raw";
  const hasDelay = cfg.slug !== "scope-decisions"; // every other record type has a date that can pass

  const presetKey = JSON.stringify(preset ?? {});
  useEffect(() => { setFilters(JSON.parse(presetKey)); setQ(""); setLate(false); setPage(1); setOpen(null); setState("active"); setPicked(new Set()); }, [cfg.slug, presetKey]);
  useEffect(() => { api<Facets>(`/projects/${projectId}/records/${cfg.slug}/facets`).then(setFacets).catch(() => setFacets({})); }, [projectId, cfg.slug, data?.total]);
  const load = useCallback(async () => {
    try {
      setError(null);
      setData(await api<Page<Rec>>(`/projects/${projectId}/records/${cfg.slug}${qs({ ...filters, q, overdue: late ? true : undefined, as_of: asOf, state, page, size: SIZE })}`));
    } catch (e) { setError(e instanceof Error ? e.message : "Failed to load"); }
  }, [projectId, cfg.slug, filters, q, late, asOf, page, state]);
  useEffect(() => { void load(); }, [load]);
  const changed = async () => { setPicked(new Set()); await load(); onChanged(); };
  const patchRecord = async (id: string, body: Record<string, unknown>) => { await api(`/projects/${projectId}/records/${cfg.slug}/${id}`, { method: "PATCH", body }); await changed(); };
  /** Simple fields are edited where they are; everything else opens the side panel. Derived dates (revisions) and calculated columns are never inline. */
  const cell = (r: Rec, c: KindConfig["columns"][number]) => {
    const plain = val(r, c, refs);
    if (!can("projects:write") || state !== "active") return plain;
    if (cfg.statusEntity && c.key === statusKey && statuses.length)
      return <InlineCell label="Status" kind="select" value={statuses.find((x) => x.label === r[c.key])?.code ?? ""} display={String(r[c.key] ?? "")} options={statuses.map((x) => ({ value: x.code, label: x.label }))} onSave={(v) => patchRecord(r.id, { status: v })} />;
    const f = cfg.fields.find((x) => x.key === c.key);
    if (!f || c.ref || !["text", "date", "select"].includes(f.kind)) return plain;
    if (f.kind === "select") return <InlineCell label={f.label} kind="select" value={String(r[c.key] ?? "")} options={f.options!.map((o) => ({ value: o, label: o }))} onSave={(v) => patchRecord(r.id, { [c.key]: v })} />;
    return <InlineCell label={f.label} kind={f.kind as "text" | "date"} value={String(r[c.key] ?? "")} onSave={(v) => patchRecord(r.id, { [c.key]: v || null })} />;
  };
  const editableFields = cfg.fields.filter((f) => f.kind !== "date" && f.kind !== "area" && f.kind !== undefined);
  async function runBulk() {
    if (!bulk) return;
    const body: Record<string, unknown> = { ids: [...picked], action: bulk.action, confirm: true };
    if (bulk.action === "update") body.fields = { [bulkField]: bulkValue };
    const r = await api<{ done: number; skipped: { reason: string }[] }>(`/projects/${projectId}/lifecycle/${cfg.typeName}/bulk`, { method: "POST", body });
    setBulk(null); setBulkValue("");
    setNotice(`${r.done} record(s) ${bulk.action === "update" ? "updated" : bulk.label.toLowerCase() + "d"}${r.skipped.length ? `, ${r.skipped.length} skipped (${r.skipped[0].reason})` : ""}.`);
    await changed();
  }

  return (
    <>
      <ErrorBox message={error} />
      <div className="mb-4 flex flex-wrap items-end gap-3 rounded-lg border border-slate-200 bg-slate-50/70 p-3">
        <Label text="Search"><Input value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} placeholder="Text, ID…" /></Label>
        {cfg.filters.map((f) => (
          <Label key={f.key} text={f.label}>
            <Select value={filters[f.key] ?? ""} onChange={(e) => { setFilters((s) => ({ ...s, [f.key]: e.target.value })); setPage(1); }}>
              <option value="">All</option>
              {(facets[f.key] ?? []).map((o) => <option key={String(o.value)} value={o.value ?? "__none__"}>{(f.ref && o.value ? refs[f.ref]?.[o.value] : o.value) ?? "(blank)"} ({o.count})</option>)}
            </Select>
          </Label>
        ))}
        {hasDelay && <label className="pb-1.5 text-xs text-slate-600"><input type="checkbox" checked={late} onChange={(e) => { setLate(e.target.checked); setPage(1); }} /> delayed only</label>}
        {hasDelay && <Label text="Report date"><Input type="date" value={asOf} onChange={(e) => e.target.value && setAsOf(e.target.value)} /></Label>}
        <Label text="Show"><Select value={state} onChange={(e) => { setState(e.target.value as State); setPage(1); setPicked(new Set()); }}><option value="active">Active</option><option value="archived">Archived</option><option value="deleted">Trash</option></Select></Label>
        {can("projects:write") && state === "active" && <Button onClick={() => setOpen({ kind: cfg.slug, id: null })}>New {cfg.singular}</Button>}
      </div>
      {notice && <div role="status" className="mb-3 rounded-md border border-green-200 bg-green-50 px-3 py-2 text-sm text-green-900">{notice} <button className="ml-2 underline" onClick={() => setNotice(null)}>dismiss</button></div>}
      {can("projects:write") && picked.size > 0 && (
        <div className="mb-3 flex flex-wrap items-end gap-2 rounded-md border border-blue-200 bg-blue-50 p-2 text-sm">
          <b>{picked.size} selected</b>
          {state === "active" && <><Button variant="ghost" onClick={() => setBulk({ action: "archive", label: "Archive" })}>Archive</Button>
            <Button variant="danger" onClick={() => setBulk({ action: "delete", label: "Delete", danger: true })}>Delete</Button>
            <Label text="Set field"><Select value={bulkField} onChange={(e) => setBulkField(e.target.value)}><option value="">Choose…</option>{editableFields.map((f) => <option key={f.key} value={f.key}>{f.label}</option>)}</Select></Label>
            <Label text="To"><Input value={bulkValue} onChange={(e) => setBulkValue(e.target.value)} /></Label>
            <Button variant="ghost" disabled={!bulkField} onClick={() => setBulk({ action: "update", label: "Update" })}>Apply</Button></>}
          {state !== "active" && <Button variant="ghost" onClick={() => setBulk({ action: "restore", label: "Restore" })}>Restore</Button>}
          {state === "deleted" && can("projects:create") && <Button variant="danger" onClick={() => setBulk({ action: "purge", label: "Delete permanently", danger: true })}>Delete permanently</Button>}
          <Button variant="ghost" onClick={() => setPicked(new Set())}>Clear</Button>
        </div>
      )}
      {bulk && (
        <ConfirmDialog title={`${bulk.label} ${picked.size} record(s)?`} confirmLabel={bulk.label} danger={bulk.danger} onCancel={() => setBulk(null)} onConfirm={runBulk}>
          {bulk.action === "purge" ? "This removes them, their links and revision history for good. It cannot be undone."
            : bulk.action === "delete" ? "They move to the trash and can be restored."
            : bulk.action === "update" ? `Sets ${editableFields.find((f) => f.key === bulkField)?.label} to “${bulkValue}” on every selected record. If any record rejects the value, none are changed.`
            : bulk.action === "archive" ? "They are hidden from lists and dashboards and can be restored." : "They return to the active lists."}
        </ConfirmDialog>
      )}
      {!data ? <Loading /> : data.items.length === 0 ? <Empty>{state === "active" ? `No ${cfg.label.toLowerCase()} match. Import the matching sheet under Smart Import, or add one.` : `Nothing is ${state === "deleted" ? "in the trash" : "archived"} here.`}</Empty> : (
        <>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="border-b border-slate-300 uppercase text-slate-500"><tr>{can("projects:write") && <th className="w-6 py-2"><input type="checkbox" aria-label="Select all on this page" checked={data.items.length > 0 && data.items.every((r) => picked.has(r.id))} onChange={(e) => setPicked(e.target.checked ? new Set(data.items.map((r) => r.id)) : new Set())} /></th>}{cfg.columns.map((c) => <th key={c.key} className="py-2 pr-3">{c.label}</th>)}<th>Flag</th></tr></thead>
              <tbody>
                {data.items.map((r) => (
                  <tr key={r.id} className="cursor-pointer border-b border-slate-100 align-top hover:bg-blue-50" onClick={() => setOpen({ kind: cfg.slug, id: r.id, state })}>
                    {can("projects:write") && <td className="py-1" onClick={(e) => e.stopPropagation()}><input type="checkbox" aria-label="Select record" checked={picked.has(r.id)} onChange={(e) => setPicked((p) => { const n = new Set(p); if (e.target.checked) n.add(r.id); else n.delete(r.id); return n; })} /></td>}
                    {cfg.columns.map((c) => <td key={c.key} className={`py-1 pr-3 ${c.wide ? "max-w-md" : "max-w-40 truncate"}`} title={val(r, c, refs)}>{cell(r, c)}</td>)}
                    <td className="whitespace-nowrap">{r.is_overdue ? <Badge tone="red">{r.days_late}d late</Badge> : r.is_start_delayed ? <Badge tone="amber">start delayed</Badge> : r.is_closed ? <Badge tone="green">closed</Badge> : null}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Pager page={page} size={SIZE} total={data.total} onPage={setPage} />
        </>
      )}
      {open && <RecordDrawer projectId={projectId} start={open} onClose={() => setOpen(null)} onChanged={changed} onOpen={(kind, id) => setOpen({ kind, id })} />}
    </>
  );
}

/* ------------------------------------------------------------------ drawer */
export function RecordDrawer({ projectId, start, onClose, onChanged, onOpen }: {
  projectId: string; start: { kind: string; id: string | null; state?: State; initial?: Record<string, string> }; onClose: () => void; onChanged: () => Promise<void> | void; onOpen: (kind: string, id: string) => void;
}) {
  const { can } = useAuth();
  const cfg = BY_SLUG[start.kind];
  const { options: refOptions } = useRefs(cfg, projectId);
  const toast = useToast();
  const unsaved = useUnsaved();
  const rstate: State = start.state ?? "active";
  const canWrite = can("projects:write") && rstate === "active";
  const [rec, setRec] = useState<Rec | null>(null);
  const [vals, setVals] = useState<Record<string, string>>({});
  const [statusCode, setStatusCode] = useState("");
  const [statuses, setStatuses] = useState<Status[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const load = useCallback(async () => {
    if (!start.id) { setRec(null); setVals(start.initial ?? {}); return; }
    try {
      setError(null);
      const r = await api<Rec>(`/projects/${projectId}/records/${cfg.slug}/${start.id}?as_of=${today()}&state=${rstate}`);
      setRec(r);
      setVals(Object.fromEntries(cfg.fields.map((f) => [f.key, r[f.key] == null ? "" : String(r[f.key])])));
      setStatusCode("");
    } catch (e) { setError(e instanceof Error ? e.message : "Failed to load"); }
  }, [projectId, cfg, start.id, rstate, start.initial]);
  useEffect(() => { void load(); }, [load]);
  useEffect(() => { if (cfg.statusEntity) api<Page<Status>>(`/status-configs?q=${cfg.statusEntity}&size=50`).then((p) => setStatuses(p.items.filter((s) => s.entity_type === cfg.statusEntity))).catch(() => {}); }, [cfg.statusEntity]);

  const dirty = canWrite && (rec ? cfg.fields.some((f) => (vals[f.key] ?? "") !== (rec[f.key] == null ? "" : String(rec[f.key]))) || !!statusCode : Object.entries(vals).some(([k, x]) => !!x && x !== (start.initial?.[k] ?? "")));
  useDirtyGuard(dirty);
  const requestClose = () => { if (dirty && !unsaved.confirmLeave("Discard your unsaved changes?")) return; onClose(); };

  async function save(e: React.FormEvent) {
    e.preventDefault(); setError(null); setSaved(false);
    const body: Record<string, unknown> = {};
    for (const f of cfg.fields) {
      if (f.createOnly && rec) continue; // baseline dates are set once; later changes go through the revision form
      const now = vals[f.key] ?? "", before = rec ? (rec[f.key] == null ? "" : String(rec[f.key])) : "";
      if (!rec || now !== before) body[f.key] = now === "" ? null : now;
    }
    if (statusCode) body.status = statusCode;
    try {
      if (!rec) { await api(`/projects/${projectId}/records/${cfg.slug}`, { method: "POST", body }); toast.ok(`${cfg.singular[0].toUpperCase()}${cfg.singular.slice(1)} created`); await onChanged(); onClose(); return; }
      if (Object.keys(body).length) await api(`/projects/${projectId}/records/${cfg.slug}/${rec.id}`, { method: "PATCH", body });
      await load(); await onChanged(); setSaved(true); toast.ok("Changes saved");
    } catch (err) { setError(err instanceof Error ? err.message : "Save failed"); }
  }
  const after = async () => { await load(); await onChanged(); };

  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-black/30" onClick={requestClose} onKeyDown={(e) => { if (e.key === "Escape") requestClose(); }}>
      <aside className="h-full w-full max-w-2xl overflow-y-auto bg-white p-5 shadow-xl" onClick={(e) => e.stopPropagation()}>
        <div className="mb-3 flex items-start justify-between">
          <h2 className="pr-4 text-base font-semibold text-blue-950">{rec ? `${cfg.singular[0].toUpperCase()}${cfg.singular.slice(1)}: ${rec.title}` : `New ${cfg.singular}`}</h2>
          <button className="text-slate-500 hover:text-slate-900" onClick={requestClose} aria-label="Close">✕</button>
        </div>
        <ErrorBox message={error} />
        {rec && (
          <div className="mb-3 flex flex-wrap items-center gap-2 text-xs">
            {rec.is_overdue && <Badge tone="red">{rec.days_late} days late</Badge>}{rec.is_start_delayed && !rec.is_overdue && <Badge tone="amber">start delayed</Badge>}{rec.is_closed && <Badge tone="green">closed</Badge>}
            {rec.effective_target_date && <span className="text-slate-500">Current date {fmt(rec.effective_target_date)}{rec.slippage_days ? ` (${rec.slippage_days > 0 ? "+" : ""}${rec.slippage_days} d vs baseline)` : ""}</span>}
            {rec.sources && <span className="text-slate-500">Source: {rec.sources.map((s) => s.replace(/_/g, " ")).join(" + ")}</span>}
          </div>
        )}
        {rec && rec.effective_target_date && (() => {
          const olds = (rec.revisions ?? []).filter((r) => r.old_date).sort((a, b) => a.requested_at.localeCompare(b.requested_at));
          return <DateJourney original={olds[0]?.old_date ?? rec.effective_target_date} current={rec.effective_target_date} actual={[rec.actual_date, rec.closed_on, rec.actual_closure_date].find((x): x is string => typeof x === "string") ?? null} days={rec.slippage_days} />;
        })()}
        {rec?.stages && <Lifecycle stages={rec.stages} />}
        {rec && cfg.slug === "action-items" && rstate === "active" && <ActionSteps projectId={projectId} rec={rec} onDone={after} setError={setError} />}
        <form onSubmit={save} className="mb-6">
          <div className="grid grid-cols-2 gap-3">
            {cfg.statusEntity && rec && (
              <Label text="Status"><Select disabled={!canWrite} value={statusCode} onChange={(e) => setStatusCode(e.target.value)}><option value="">{String(rec[cfg.statusField ?? "status_raw"] ?? "—")}</option>{statuses.map((s) => <option key={s.code} value={s.code}>{s.label}</option>)}</Select></Label>
            )}
            {cfg.fields.filter((f) => !(f.createOnly && rec)).map((f) => (
              <div key={f.key} className={f.wide ? "col-span-2" : ""}>
                <Label text={f.label + (cfg.required.includes(f.key) ? " *" : "")}>
                  {f.kind === "area" ? <textarea disabled={!canWrite} className="w-full rounded-md border border-slate-300 px-2.5 py-1.5 text-sm" rows={2} value={vals[f.key] ?? ""} onChange={(e) => setVals((s) => ({ ...s, [f.key]: e.target.value }))} />
                    : f.kind === "ref" ? <Select disabled={!canWrite} value={vals[f.key] ?? ""} onChange={(e) => setVals((s) => ({ ...s, [f.key]: e.target.value }))}><option value="">{cfg.required.includes(f.key) ? "Choose…" : "—"}</option>{(refOptions[f.ref!] ?? []).map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}</Select>
                    : f.kind === "select" ? <Select disabled={!canWrite} value={vals[f.key] ?? ""} onChange={(e) => setVals((s) => ({ ...s, [f.key]: e.target.value }))}>{f.options!.map((o) => <option key={o} value={o}>{o}</option>)}</Select>
                    : <Input disabled={!canWrite} type={f.kind === "date" ? "date" : f.kind === "number" ? "number" : "text"} min={f.kind === "number" ? 0 : undefined} value={vals[f.key] ?? ""} onChange={(e) => setVals((s) => ({ ...s, [f.key]: e.target.value }))} />}
                </Label>
              </div>
            ))}
          </div>
          {canWrite && <div className="mt-3 flex items-center gap-2"><Button type="submit">{rec ? "Save" : "Create"}</Button>{saved && <span className="text-xs text-green-700">Saved</span>}</div>}
        </form>
        {rec && <FlexFields entity={cfg.typeName} id={rec.id} canWrite={canWrite} setError={setError} />}
        {rec && rec.merge_notes && Object.keys(rec.merge_notes).length > 0 && <MergeNotes notes={rec.merge_notes} />}
        {rec && cfg.revisionLabel && <Revisions projectId={projectId} cfg={cfg} rec={rec} canWrite={canWrite} onChanged={after} setError={setError} />}
        {rec && <Links projectId={projectId} cfg={cfg} rec={rec} canWrite={canWrite} onChanged={after} onOpen={onOpen} setError={setError} />}
        {rec && <Discussion projectId={projectId} type={cfg.typeName} id={rec.id} readOnly={rstate !== "active"} />}
        {rec && <LifecycleBar projectId={projectId} type={cfg.typeName} id={rec.id} state={rstate} onDone={after} onGone={async () => { await onChanged(); onClose(); }} setError={setError} />}
      </aside>
    </div>
  );
}

function Lifecycle({ stages }: { stages: NonNullable<Rec["stages"]> }) {
  const color = { done: "#16a34a", late: "#dc2626", upcoming: "#94a3b8", none: "#e2e8f0" } as const;
  return (
    <div className="mb-4">
      <div className="flex items-start">
        {stages.map((s, i) => (
          <div key={s.key} className="flex-1 text-center">
            <div className="flex items-center"><div className={`h-0.5 flex-1 ${i === 0 ? "bg-transparent" : "bg-slate-200"}`} /><div className="h-3 w-3 rounded-full" style={{ background: color[s.state] }} /><div className={`h-0.5 flex-1 ${i === stages.length - 1 ? "bg-transparent" : "bg-slate-200"}`} /></div>
            <div className="mt-1 px-0.5 text-[10px] leading-tight text-slate-600">{s.label}</div>
            <div className={`text-[10px] ${s.state === "late" ? "font-semibold text-red-700" : "text-slate-500"}`}>{s.date ? fmt(s.date) : "–"}</div>
          </div>
        ))}
      </div>
      <p className="mt-1 text-[10px] text-slate-400">Stage dates are planned dates. A stage shows done only when the ticket is closed or there is evidence (actual spec closure, work started); red = planned date passed.</p>
    </div>
  );
}

function MergeNotes({ notes }: { notes: NonNullable<Rec["merge_notes"]> }) {
  return (
    <section className="mb-6 rounded-md border border-amber-200 bg-amber-50 p-3">
      <h3 className="mb-1 text-sm font-semibold text-amber-900">The two source sheets disagree on {Object.keys(notes).length} field(s)</h3>
      <p className="mb-2 text-xs text-amber-900">Delivery Schedule decides the customer-facing dates, Tech_Final decides owners and QA fields. Otherwise the first value is kept. Nothing was lost.</p>
      <ul className="text-xs text-slate-800">
        {Object.entries(notes).map(([k, n]) => <li key={k}><b>{k.replace(/_/g, " ")}</b>: kept “{String(n.kept ?? "")}” · {n.replaced !== undefined ? `replaced “${String(n.replaced)}”` : `ignored “${String(n.ignored ?? "")}”`} (from {n.from.replace(/_/g, " ")})</li>)}
      </ul>
    </section>
  );
}

function Revisions({ projectId, cfg, rec, canWrite, onChanged, setError }: { projectId: string; cfg: KindConfig; rec: Rec; canWrite: boolean; onChanged: () => Promise<void>; setError: (m: string | null) => void }) {
  const { can } = useAuth();
  const [date, setDate] = useState("");
  const [reason, setReason] = useState("");
  const [approve, setApprove] = useState(false);
  async function propose(e: React.FormEvent) {
    e.preventDefault(); setError(null);
    try { await api(`/projects/${projectId}/records/${cfg.slug}/${rec.id}/revisions`, { method: "POST", body: { field: "x", new_date: date, reason, approve } }); setDate(""); setReason(""); await onChanged(); }
    catch (err) { setError(err instanceof Error ? err.message : "Could not save revision"); }
  }
  async function decide(id: string, ok: boolean) {
    try { await api(`/projects/${projectId}/revisions/${id}/decision`, { method: "POST", body: { approve: ok } }); await onChanged(); } catch (err) { setError(err instanceof Error ? err.message : "Failed"); }
  }
  const revs = rec.revisions ?? [];
  return (
    <section className="mb-6">
      <h3 className="mb-1 text-sm font-semibold text-blue-950">{cfg.revisionLabel}: revision history</h3>
      <p className="mb-2 text-xs text-slate-500">The original date is kept; each change needs a reason and only approved revisions move the date.</p>
      {revs.length === 0 ? <p className="mb-2 text-sm text-slate-500">No revisions.</p> : (
        <ul className="mb-3 ml-1.5 space-y-3 border-l-2 border-slate-200 text-xs">
          {revs.map((r) => (
            <li key={r.id} className="relative pl-4"><span className={`absolute -left-[7px] top-1 h-3 w-3 rounded-full border-2 border-white ${r.status === "approved" ? "bg-green-500" : r.status === "rejected" ? "bg-slate-300" : "bg-amber-400"}`} /><div className="flex flex-wrap items-center gap-2"><Badge tone={r.status === "approved" ? "green" : r.status === "rejected" ? "slate" : "amber"}>{r.status}</Badge>{fmt(r.old_date)} → <b>{fmt(r.new_date)}</b>
              {r.status === "proposed" && can("plan:approve") && <><Button variant="ghost" onClick={() => decide(r.id, true)}>Approve</Button><Button variant="ghost" onClick={() => decide(r.id, false)}>Reject</Button></>}</div>
              <div className="text-slate-600">“{r.reason}” — {r.requested_by_email}</div></li>
          ))}
        </ul>
      )}
      {canWrite && (
        <form onSubmit={propose} className="grid grid-cols-2 gap-2 rounded-md border border-slate-200 bg-slate-50 p-3">
          <Label text="New date"><Input required type="date" value={date} onChange={(e) => setDate(e.target.value)} /></Label>
          <Label text="Reason *"><Input required minLength={3} value={reason} onChange={(e) => setReason(e.target.value)} /></Label>
          <div className="col-span-2 flex items-center gap-3"><Button type="submit">{approve ? "Revise and approve" : "Propose revision"}</Button>{can("plan:approve") && <label className="text-xs text-slate-600"><input type="checkbox" checked={approve} onChange={(e) => setApprove(e.target.checked)} /> approve immediately</label>}</div>
        </form>
      )}
    </section>
  );
}

function Links({ projectId, cfg, rec, canWrite, onChanged, onOpen, setError }: { projectId: string; cfg: KindConfig; rec: Rec; canWrite: boolean; onChanged: () => Promise<void>; onOpen: (kind: string, id: string) => void; setError: (m: string | null) => void }) {
  const [targetKind, setTargetKind] = useState(cfg.slug === "delivery-items" ? "requirements" : "delivery-items");
  const [q, setQ] = useState("");
  const [options, setOptions] = useState<Rec[]>([]);
  const [pick, setPick] = useState("");
  useEffect(() => {
    if (q.length < 2) { setOptions([]); return; }
    api<Page<Rec>>(`/projects/${projectId}/records/${targetKind}${qs({ q, size: 25 })}`).then((r) => setOptions(r.items.filter((x) => x.id !== rec.id))).catch(() => {});
  }, [q, targetKind, projectId, rec.id]);
  async function add() {
    try { setError(null); await api(`/projects/${projectId}/links`, { method: "POST", body: { source_type: cfg.typeName, source_id: rec.id, target_type: BY_SLUG[targetKind].typeName, target_id: pick, link_type: "related" } }); setPick(""); setQ(""); await onChanged(); }
    catch (err) { setError(err instanceof Error ? err.message : "Could not link"); }
  }
  async function remove(id: string) {
    try { await api(`/projects/${projectId}/links/${id}`, { method: "DELETE" }); await onChanged(); } catch (err) { setError(err instanceof Error ? err.message : "Could not remove"); }
  }
  const links = rec.links ?? [];
  return (
    <section className="mb-6">
      <h3 className="mb-1 text-sm font-semibold text-blue-950">Linked records ({links.length})</h3>
      {links.length === 0 ? <p className="mb-2 text-sm text-slate-500">Not linked to anything yet.</p> : (
        <ul className="mb-3 divide-y divide-slate-100 text-xs">
          {links.map((l) => (
            <li key={l.id} className="flex items-center justify-between gap-2 py-1.5">
              <div className="min-w-0"><button className="text-left text-blue-900 hover:underline" onClick={() => onOpen(l.kind, l.record_id)}><span className="mr-1 text-slate-400">{BY_TYPE[l.type]?.singular ?? l.type} ›</span>{l.title}</button>
                <div className="text-[11px] text-slate-500">{l.link_type.replace(/_/g, " ")}{l.basis ? ` · ${l.basis}` : ""}</div></div>
              {canWrite && <button className="shrink-0 text-red-700" onClick={() => remove(l.id)} aria-label="Remove link">✕</button>}
            </li>
          ))}
        </ul>
      )}
      {canWrite && (
        <div className="flex flex-wrap items-end gap-2">
          <Label text="Link to"><Select value={targetKind} onChange={(e) => { setTargetKind(e.target.value); setPick(""); }}>{Object.values(BY_SLUG).map((k) => <option key={k.slug} value={k.slug}>{k.label}</option>)}</Select></Label>
          <Label text="Search (2+ letters)"><Input value={q} onChange={(e) => setQ(e.target.value)} /></Label>
          <Select value={pick} onChange={(e) => setPick(e.target.value)} className="max-w-56"><option value="">Select…</option>{options.map((o) => <option key={o.id} value={o.id}>{o.title.slice(0, 60)}</option>)}</Select>
          <Button disabled={!pick} onClick={add}>Link</Button>
        </div>
      )}
    </section>
  );
}

/* ------------------------------------------------------------------ suggested links */
export function LinkSuggestions({ projectId, onClose, onChanged }: { projectId: string; onClose: () => void; onChanged: () => void }) {
  const [data, setData] = useState<{ suggestions: Suggestion[]; unmatched: Record<string, number> } | null>(null);
  const [chosen, setChosen] = useState<Set<number>>(new Set());
  const [rule, setRule] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => {
    try {
      const r = await api<{ suggestions: Suggestion[]; unmatched: Record<string, number> }>(`/projects/${projectId}/link-suggestions`);
      setData(r); setChosen(new Set(r.suggestions.map((s, i) => (s.ambiguous ? -1 : i)).filter((i) => i >= 0)));
    } catch (e) { setError(e instanceof Error ? e.message : "Failed to load"); }
  }, [projectId]);
  useEffect(() => { void load(); }, [load]);
  const rules = useMemo(() => [...new Set((data?.suggestions ?? []).map((s) => s.rule))], [data]);
  const shown = (data?.suggestions ?? []).map((s, i) => ({ s, i })).filter(({ s }) => !rule || s.rule === rule);
  async function apply() {
    try {
      const links = [...chosen].map((i) => data!.suggestions[i]).map((s) => ({ source_type: s.source_type, source_id: s.source_id, target_type: s.target_type, target_id: s.target_id, link_type: s.link_type, basis: s.basis }));
      const r = await api<{ created: number; skipped: unknown[] }>(`/projects/${projectId}/links/bulk`, { method: "POST", body: { links } });
      setMsg(`${r.created} link(s) created${r.skipped.length ? `, ${r.skipped.length} skipped` : ""}.`); await load(); onChanged();
    } catch (e) { setError(e instanceof Error ? e.message : "Could not apply"); }
  }
  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-black/30" onClick={onClose}>
      <aside className="h-full w-full max-w-3xl overflow-y-auto bg-white p-5 shadow-xl" onClick={(e) => e.stopPropagation()}>
        <div className="mb-2 flex justify-between"><h2 className="text-base font-semibold text-blue-950">Suggested links</h2><button onClick={onClose} aria-label="Close">✕</button></div>
        <p className="mb-3 text-xs text-slate-600">Each suggestion shows the evidence in the data. Nothing is linked until you apply. Items where the same ID appears on several records are unticked: tick the ones you want.</p>
        <ErrorBox message={error} />
        {msg && <div className="mb-3 rounded-md border border-green-200 bg-green-50 px-3 py-2 text-sm text-green-900">{msg}</div>}
        {!data ? <Loading /> : data.suggestions.length === 0 ? <Empty>No further links are suggested by the data.</Empty> : (
          <>
            <div className="mb-2 flex flex-wrap items-center gap-3">
              <Select className="max-w-52" value={rule} onChange={(e) => setRule(e.target.value)}><option value="">All rules ({data.suggestions.length})</option>{rules.map((r) => <option key={r} value={r}>{r.replace(/_/g, " ")}</option>)}</Select>
              <Button variant="ghost" onClick={() => setChosen(new Set(shown.filter(({ s }) => !s.ambiguous).map(({ i }) => i)))}>Tick unambiguous</Button>
              <Button variant="ghost" onClick={() => setChosen(new Set())}>Untick all</Button>
              <Button onClick={apply} disabled={chosen.size === 0}>Apply {chosen.size} link(s)</Button>
            </div>
            <p className="mb-2 text-xs text-slate-500">Not matched: {data.unmatched.helpdesk_without_delivery} helpdesk item(s) have no delivery ticket with that ID; {data.unmatched.discussions_without_requirement} discussion(s) name a BRD serial that is not in the requirements.</p>
            <table className="w-full text-left text-xs">
              <thead className="border-b border-slate-300 uppercase text-slate-500"><tr><th /><th className="py-1 pr-2">From</th><th className="pr-2">To</th><th>Evidence</th></tr></thead>
              <tbody>
                {shown.slice(0, 200).map(({ s, i }) => (
                  <tr key={i} className="border-b border-slate-100 align-top">
                    <td className="py-1 pr-2"><input type="checkbox" checked={chosen.has(i)} onChange={(e) => setChosen((c) => { const n = new Set(c); if (e.target.checked) n.add(i); else n.delete(i); return n; })} /></td>
                    <td className="max-w-48 pr-2">{s.source_title}</td><td className="max-w-48 pr-2">{s.target_title}</td>
                    <td className="text-slate-600">{s.basis}{s.ambiguous && <Badge tone="amber">same ID on several records</Badge>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {shown.length > 200 && <p className="mt-1 text-xs text-slate-500">Showing 200 of {shown.length}; apply, then reopen for the rest.</p>}
          </>
        )}
      </aside>
    </div>
  );
}
