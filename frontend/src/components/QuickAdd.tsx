"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { Button, ErrorBox, Input, Label, Select } from "@/components/ui";
import { useToast } from "@/components/Toast";
import { useDirtyGuard } from "@/components/Unsaved";
import { api, type Page, type Row } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { iso, toDate, today } from "@/lib/plan";

type QType = "task" | "milestone" | "activity" | "delivery" | "dependency" | "discussion" | "weekly" | "gate" | "uat" | "integration" | "report";
type Ctx = { projectId?: string; productId?: string };
type V = Record<string, string>;

const QuickCtx = createContext<{ setCtx: (f: (c: Ctx) => Ctx) => void; version: number; open: (t?: QType) => void }>({ setCtx: () => {}, version: 0, open: () => {} });
export const useQuickAdd = () => useContext(QuickCtx);

/** Pages call this so Quick Add opens already knowing the project and product they are showing. */
export function useQuickContext(projectId?: string, productId?: string) {
  const { setCtx } = useQuickAdd();
  useEffect(() => { setCtx((c) => ({ ...c, projectId, productId })); return () => setCtx((c) => ({ ...c, projectId: undefined, productId: undefined })); }, [projectId, productId, setCtx]);
}

/** A product workspace (a product dashboard, a plan filtered to one product) calls this so Quick Add opens set to that product. */
export function useQuickProduct(productId?: string) {
  const { setCtx } = useQuickAdd();
  useEffect(() => { setCtx((c) => ({ ...c, productId })); return () => setCtx((c) => ({ ...c, productId: undefined })); }, [productId, setCtx]);
}

const mondayOf = (s: string) => { const d = toDate(s)!; return iso(new Date(d.getTime() - ((d.getUTCDay() + 6) % 7) * 86400000)); };
const nz = (s: string | undefined) => (s && s.trim() ? s.trim() : null);

type Field = { key: string; label: string; kind?: "text" | "area" | "date" | "select" | "phase" | "task"; options?: [string, string][]; required?: boolean; wide?: boolean; show?: (v: V) => boolean };
type Def = { label: string; hint: string; fields: Field[]; primary: string[]; submit: (a: { project: string; product: string | null; v: V }) => Promise<string> };
const post = (path: string, body: unknown) => api<{ id?: string }>(path, { method: "POST", body });

const DEFS: Record<QType, Def> = {
  task: {
    label: "Task", hint: "A plan task with planned dates", primary: ["title"],
    fields: [{ key: "title", label: "Task", required: true, wide: true }, { key: "phase_id", label: "Phase", kind: "phase" }, { key: "owner_name", label: "Owner" }, { key: "planned_start", label: "Planned start", kind: "date" }, { key: "planned_finish", label: "Planned finish", kind: "date" }],
    submit: async ({ project, product, v }) => { await post(`/projects/${project}/work-items`, { title: v.title, kind: "task", phase_id: nz(v.phase_id), product_id: product, owner_name: nz(v.owner_name), planned_start: nz(v.planned_start), planned_finish: nz(v.planned_finish), status: "not_started" }); return v.title; },
  },
  milestone: {
    label: "Milestone", hint: "A single key date on the plan", primary: ["title"],
    fields: [{ key: "title", label: "Milestone", required: true, wide: true }, { key: "phase_id", label: "Phase", kind: "phase" }, { key: "owner_name", label: "Owner" }, { key: "date", label: "Date", kind: "date", required: true }],
    submit: async ({ project, product, v }) => { await post(`/projects/${project}/work-items`, { title: v.title, kind: "milestone", phase_id: nz(v.phase_id), product_id: product, owner_name: nz(v.owner_name), planned_start: v.date, planned_finish: v.date, status: "not_started" }); return v.title; },
  },
  activity: {
    label: "Project activity", hint: "Something a named person must do by a date (an action)", primary: ["title"],
    fields: [{ key: "title", label: "What must happen", required: true, wide: true, kind: "area" }, { key: "owner_name", label: "Owner" }, { key: "priority", label: "Priority", kind: "select", options: [["medium", "Medium"], ["low", "Low"], ["high", "High"], ["critical", "Critical"]] }, { key: "due_date", label: "Due date", kind: "date" }],
    submit: async ({ project, product, v }) => { await post(`/projects/${project}/records/action-items`, { title: v.title, owner_name: nz(v.owner_name), priority: v.priority || "medium", due_date: nz(v.due_date), product_id: product }); return v.title; },
  },
  delivery: {
    label: "Delivery item", hint: "A development / delivery ticket", primary: ["description"],
    fields: [{ key: "description", label: "Description", required: true, wide: true, kind: "area" }, { key: "external_id", label: "Ticket / helpdesk ID" }, { key: "stream", label: "Stream" }, { key: "module", label: "Module" }, { key: "tech_owner", label: "Technical owner" }],
    submit: async ({ project, product, v }) => { await post(`/projects/${project}/records/delivery-items`, { description: v.description, external_id: nz(v.external_id), stream: nz(v.stream), module: nz(v.module), tech_owner: nz(v.tech_owner), product_id: product }); return v.description; },
  },
  dependency: {
    label: "Dependency", hint: "Waiting on someone, or one task that must finish before another", primary: ["description"],
    fields: [
      { key: "mode", label: "Kind of dependency", kind: "select", options: [["pending", "Waiting on someone (pending item)"], ["tasks", "One task must finish before another"]] },
      { key: "description", label: "What is needed", required: true, wide: true, kind: "area", show: (v) => (v.mode || "pending") === "pending" },
      { key: "pending_with", label: "Pending with", kind: "select", required: true, options: [["customer", "Customer"], ["wfx", "WFX"], ["external", "External partner"], ["internal", "Internal team"]], show: (v) => (v.mode || "pending") === "pending" },
      { key: "owner_name", label: "Owner", show: (v) => (v.mode || "pending") === "pending" },
      { key: "target", label: "Target date", kind: "date", show: (v) => (v.mode || "pending") === "pending" },
      { key: "predecessor", label: "Must finish first", kind: "task", required: true, show: (v) => v.mode === "tasks" },
      { key: "successor", label: "Can start after that", kind: "task", required: true, show: (v) => v.mode === "tasks" },
    ],
    submit: async ({ project, product, v }) => {
      if (v.mode === "tasks") { await post(`/projects/${project}/work-items/${v.successor}/dependencies`, { predecessor_id: v.predecessor, lag_days: 0 }); return "task dependency"; }
      await post(`/projects/${project}/pending-items`, { pending_with: v.pending_with || "customer", description: v.description, owner_name: nz(v.owner_name), original_target_date: nz(v.target), product_id: product, status: "not_started" });
      return v.description;
    },
  },
  discussion: {
    label: "Discussion point", hint: "An open point to decide with the customer", primary: ["name"],
    fields: [{ key: "name", label: "Topic", required: true, wide: true, kind: "area" }, { key: "concern", label: "Concern", wide: true, kind: "area" }, { key: "module", label: "Module" }, { key: "responsibility", label: "Responsibility" }, { key: "target_date", label: "Target date", kind: "date" }],
    submit: async ({ project, product, v }) => { await post(`/projects/${project}/records/discussions`, { name: v.name, concern: nz(v.concern), module: nz(v.module), responsibility: nz(v.responsibility), target_date: nz(v.target_date), product_id: product }); return v.name; },
  },
  weekly: {
    label: "Weekly activity", hint: "Put work on a week's plan (Monday to Sunday)", primary: ["title"],
    fields: [{ key: "title", label: "Activity", required: true, wide: true, kind: "area" }, { key: "workstream", label: "Workstream" }, { key: "owner_name", label: "Owner" }, { key: "module", label: "Module" }, { key: "target_date", label: "Target date (empty = this week)", kind: "date" }],
    submit: async ({ project, product, v }) => { await post(`/projects/${project}/records/week-plan-items`, { title: v.title, workstream: nz(v.workstream), owner_name: nz(v.owner_name), module: nz(v.module), target_date: nz(v.target_date), week_start: mondayOf(v.target_date || today()), product_id: product }); return v.title; },
  },
  gate: {
    label: "Sign-off gate", hint: "An approval someone must give", primary: ["name"],
    fields: [{ key: "name", label: "Gate", required: true, wide: true }, { key: "gate_type", label: "Set (e.g. blueprint sign-off)" }, { key: "approver_name", label: "Approver" }, { key: "planned_date", label: "Planned date", kind: "date" }],
    submit: async ({ project, product, v }) => { await post(`/projects/${project}/records/approval-gates`, { name: v.name, gate_type: nz(v.gate_type), approver_name: nz(v.approver_name), planned_date: nz(v.planned_date), product_id: product }); return v.name; },
  },
  uat: {
  label: "UAT scenario", hint: "A test scenario for user acceptance testing", primary: ["title"],
  fields: [{ key: "title", label: "Scenario", required: true, wide: true, kind: "area" }, { key: "scenario_id", label: "Scenario ID" }, { key: "module", label: "Module" }, { key: "tester", label: "Tester" }, { key: "planned_date", label: "Planned date", kind: "date" }],
  submit: async ({ project, product, v }) => { await post(`/projects/${project}/records/uat-scenarios`, { title: v.title, scenario_id: nz(v.scenario_id), module: nz(v.module), tester: nz(v.tester), planned_date: nz(v.planned_date), product_id: product }); return v.title; },
  },
  integration: {
  label: "Integration", hint: "An interface with a partner or another system", primary: ["name"],
  fields: [{ key: "name", label: "Integration", required: true, wide: true }, { key: "partner", label: "Partner" }, { key: "direction", label: "Direction", kind: "select", options: [["", "Not set"], ["inbound", "Inbound"], ["outbound", "Outbound"], ["bidirectional", "Both ways"]] }, { key: "technology", label: "Technology (API, SFTP…)" }, { key: "owner_name", label: "Owner" }, { key: "target_date", label: "Target date", kind: "date" }],
  submit: async ({ project, product, v }) => { await post(`/projects/${project}/records/integration-items`, { name: v.name, partner: nz(v.partner), direction: nz(v.direction), technology: nz(v.technology), owner_name: nz(v.owner_name), target_date: nz(v.target_date), product_id: product }); return v.name; },
  },
  report: {
  label: "Report / print", hint: "A report, print or form to be built", primary: ["name"],
  fields: [{ key: "name", label: "Report / print", required: true, wide: true }, { key: "report_type", label: "Type (report, print, form…)" }, { key: "module", label: "Module" }, { key: "owner_name", label: "Owner" }, { key: "target_date", label: "Target date", kind: "date" }],
  submit: async ({ project, product, v }) => { await post(`/projects/${project}/records/report-items`, { name: v.name, report_type: nz(v.report_type), module: nz(v.module), owner_name: nz(v.owner_name), target_date: nz(v.target_date), product_id: product }); return v.name; },
  },
};
const ORDER: QType[] = ["task", "milestone", "activity", "delivery", "dependency", "discussion", "weekly", "gate", "uat", "integration", "report"];

export function QuickAddProvider({ children }: { children: ReactNode }) {
  const { can } = useAuth();
  const [ctx, setCtxState] = useState<Ctx>({});
  const [version, setVersion] = useState(0);
  const [openType, setOpenType] = useState<QType | "choose" | null>(null);
  const setCtx = useCallback((f: (c: Ctx) => Ctx) => setCtxState(f), []);
  const open = useCallback((t?: QType) => setOpenType(t ?? "choose"), []);
  useEffect(() => {
    const k = (e: KeyboardEvent) => { if (e.altKey && e.key.toLowerCase() === "q" && can("projects:write")) { e.preventDefault(); setOpenType((o) => (o ? o : "choose")); } };
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [can]);
  const value = useMemo(() => ({ setCtx, version, open }), [setCtx, version, open]);
  return (
    <QuickCtx.Provider value={value}>
      {children}
      {can("projects:write") && (
        <button onClick={() => open()} title="Quick add (Alt+Q)" className="fixed bottom-5 right-5 z-30 rounded-full bg-blue-900 px-4 py-2.5 text-sm font-semibold text-white shadow-lg hover:bg-blue-800 print:hidden">＋ Quick add</button>
      )}
      {openType && <QuickAddModal initial={openType === "choose" ? null : openType} ctx={ctx} onClose={() => setOpenType(null)} onCreated={() => setVersion((n) => n + 1)} />}
    </QuickCtx.Provider>
  );
}

function QuickAddModal({ initial, ctx, onClose, onCreated }: { initial: QType | null; ctx: Ctx; onClose: () => void; onCreated: () => void }) {
  const toast = useToast();
  const [type, setType] = useState<QType | null>(initial);
  const [projects, setProjects] = useState<Row[]>([]);
  const [customers, setCustomers] = useState<Record<string, string>>({});
  const [allProducts, setAllProducts] = useState<Row[]>([]);
  const [projectProducts, setProjectProducts] = useState<string[]>([]);
  const [phases, setPhases] = useState<Row[]>([]);
  const [project, setProject] = useState(ctx.projectId ?? "");
  const [product, setProduct] = useState(ctx.productId ?? "");
  const [v, setV] = useState<V>({});
  const [keep, setKeep] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const def = type ? DEFS[type] : null;
  const typed = !!def && def.fields.some((f) => f.kind !== "select" && v[f.key]);
  useDirtyGuard(typed);

  useEffect(() => {
    api<Page<Row>>("/projects?size=100").then((p) => { setProjects(p.items); setProject((cur) => cur || (p.items.length === 1 ? String(p.items[0].id) : "")); }).catch((e) => setError(e instanceof Error ? e.message : "Could not load projects"));
    api<Page<Row>>("/customers?size=200").then((p) => setCustomers(Object.fromEntries(p.items.map((c) => [String(c.id), String(c.name)])))).catch(() => {});
    api<Page<Row>>("/products?size=200").then((p) => setAllProducts(p.items)).catch(() => {});
  }, []);
  useEffect(() => {
    if (!project) { setPhases([]); setProjectProducts([]); return; }
    api<Row[]>(`/projects/${project}/phases`).then(setPhases).catch(() => setPhases([]));
    api<{ products: { product: { code: string } }[] }>(`/projects/${project}`).then((p) => setProjectProducts(p.products.map((x) => x.product.code))).catch(() => setProjectProducts([]));
  }, [project]);
  // a product that does not belong to the chosen project must not stay selected
  const products = useMemo(() => (projectProducts.length ? allProducts.filter((p) => projectProducts.includes(String(p.code))) : allProducts), [allProducts, projectProducts]);
  useEffect(() => { if (product && products.length && !products.some((p) => String(p.id) === product)) setProduct(""); }, [products, product]);

  const proj = projects.find((p) => String(p.id) === project);
  const close = () => { if (typed && !window.confirm("Discard what you typed?")) return; onClose(); };
  const set = (k: string) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) => setV((s) => ({ ...s, [k]: e.target.value }));
  const visible = def?.fields.filter((f) => !f.show || f.show(v)) ?? [];
  const missing = visible.filter((f) => f.required && !(v[f.key] ?? "").trim() && !(f.kind === "select" && f.options?.length && !v[f.key]));

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!def || !type) return;
    if (!project) { setError("Choose the project first."); return; }
    if (missing.length) { setError(`Fill in: ${missing.map((f) => f.label).join(", ")}`); return; }
    setBusy(true); setError(null);
    try {
      const title = await def.submit({ project, product: product || null, v });
      toast.ok(`${def.label} created: ${title.length > 70 ? title.slice(0, 70) + "…" : title}`);
      onCreated();
      if (keep) setV((s) => Object.fromEntries(Object.entries(s).filter(([k]) => !def.primary.includes(k) && k !== "predecessor" && k !== "successor")));
      else onClose();
    } catch (err) { setError(err instanceof Error ? err.message : "Could not create it"); }
    finally { setBusy(false); }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/40 p-4 pt-16" role="dialog" aria-modal="true" aria-label="Quick add" onClick={close} onKeyDown={(e) => { if (e.key === "Escape") close(); }}>
      <div className="w-full max-w-2xl rounded-md bg-white p-5 shadow-xl" onClick={(e) => e.stopPropagation()}>
        <div className="mb-3 flex items-start justify-between">
          <h2 className="text-base font-semibold text-blue-950">Quick add{def ? `: ${def.label}` : ""}</h2>
          <button onClick={close} aria-label="Close">✕</button>
        </div>
        <div className="mb-3 grid grid-cols-4 gap-1.5">
          {ORDER.map((t) => (
            <button key={t} onClick={() => { setType(t); setError(null); setV({}); }} title={DEFS[t].hint} className={`rounded-md border px-2 py-1.5 text-xs ${type === t ? "border-blue-900 bg-blue-900 text-white" : "border-slate-300 text-slate-700 hover:bg-slate-100"}`}>{DEFS[t].label}</button>
          ))}
        </div>
        {!def ? <p className="py-6 text-center text-sm text-slate-500">Choose what to add. It opens already set to the project and product you are looking at.</p> : (
          <form onSubmit={submit}>
            <p className="mb-2 text-xs text-slate-500">{def.hint}.</p>
            <div className="mb-3 grid grid-cols-3 gap-2 rounded-md border border-slate-200 bg-slate-50 p-2">
              <Label text="Project *"><Select value={project} onChange={(e) => { setProject(e.target.value); setV((s) => ({ ...s, phase_id: "", predecessor: "", successor: "" })); }}><option value="">Choose…</option>{projects.map((p) => <option key={String(p.id)} value={String(p.id)}>{String(p.code)}</option>)}</Select></Label>
              <Label text="Customer"><div className="rounded-md border border-slate-200 bg-white px-2.5 py-1.5 text-sm text-slate-700">{proj ? customers[String(proj.customer_id)] ?? "…" : "–"}</div></Label>
              <Label text="Product"><Select value={product} onChange={(e) => setProduct(e.target.value)}><option value="">All / not specific</option>{products.map((p) => <option key={String(p.id)} value={String(p.id)}>{String(p.code)}</option>)}</Select></Label>
            </div>
            <ErrorBox message={error} />
            <div className="grid grid-cols-2 gap-3">
              {visible.map((f) => (
                <div key={f.key} className={f.wide || f.kind === "task" ? "col-span-2" : ""}>
                  <Label text={f.label + (f.required ? " *" : "")}>
                    {f.kind === "area" ? <textarea className="w-full rounded-md border border-slate-300 px-2.5 py-1.5 text-sm" rows={2} value={v[f.key] ?? ""} onChange={set(f.key)} autoFocus={f === visible[0]} />
                      : f.kind === "date" ? <Input type="date" value={v[f.key] ?? ""} onChange={set(f.key)} />
                      : f.kind === "select" ? <Select value={v[f.key] ?? f.options![0][0]} onChange={set(f.key)}>{f.options!.map(([val, l]) => <option key={val} value={val}>{l}</option>)}</Select>
                      : f.kind === "phase" ? <Select value={v[f.key] ?? ""} onChange={set(f.key)}><option value="">No phase</option>{phases.map((p) => <option key={String(p.id)} value={String(p.id)}>{String(p.name)}</option>)}</Select>
                      : f.kind === "task" ? <TaskPicker project={project} value={v[f.key] ?? ""} onChange={(id) => setV((s) => ({ ...s, [f.key]: id }))} />
                      : <Input value={v[f.key] ?? ""} onChange={set(f.key)} autoFocus={f === visible[0]} />}
                  </Label>
                </div>
              ))}
            </div>
            <div className="mt-4 flex items-center justify-between">
              <label className="text-xs text-slate-600"><input type="checkbox" checked={keep} onChange={(e) => setKeep(e.target.checked)} /> keep open to add another</label>
              <div className="flex gap-2"><Button type="button" variant="ghost" onClick={close}>Cancel</Button><Button type="submit" disabled={busy}>{busy ? "Creating…" : "Create"}</Button></div>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}

function TaskPicker({ project, value, onChange }: { project: string; value: string; onChange: (id: string) => void }) {
  const [q, setQ] = useState("");
  const [options, setOptions] = useState<{ id: string; title: string }[]>([]);
  useEffect(() => {
    if (!project) { setOptions([]); return; }
    const h = setTimeout(() => api<{ items: { id: string; title: string }[] }>(`/projects/${project}/work-items?size=25&q=${encodeURIComponent(q)}`).then((r) => setOptions(r.items)).catch(() => setOptions([])), 250);
    return () => clearTimeout(h);
  }, [project, q]);
  return (
    <div className="flex gap-2">
      <Input className="max-w-48" placeholder="Search tasks…" value={q} onChange={(e) => setQ(e.target.value)} disabled={!project} />
      <Select value={value} onChange={(e) => onChange(e.target.value)}><option value="">{project ? "Select a task…" : "Choose the project first"}</option>{options.map((o) => <option key={o.id} value={o.id}>{o.title.slice(0, 80)}</option>)}</Select>
    </div>
  );
}
