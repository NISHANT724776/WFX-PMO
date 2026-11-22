"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Drilldown from "@/components/dash/Drilldown";
import { ConfirmDialog } from "@/components/manage/Workspace";
import { useDirtyGuard } from "@/components/Unsaved";
import { Badge, Button, ErrorBox, Input, Label, Select, Loading } from "@/components/ui";
import { api, type Page, type Row } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { SCOPE_LABEL, cleanConfig, firstFree, newId, settle, type Layout, type LayoutConfig, type LayoutSummary, type PlacedWidget, type SettingDef, type WidgetType } from "@/lib/builder";
import Grid from "./Grid";
import { WidgetBody, useWidgetData } from "./widgets";

type Dlg = null | { kind: "add" } | { kind: "settings"; id: string } | { kind: "saveas" } | { kind: "restore" } | { kind: "delete" } | { kind: "discard"; then: () => void };
const clone = <T,>(x: T): T => JSON.parse(JSON.stringify(x));

export default function Builder({ projectId, products, asOf, refreshKey, onItem, onDirty }: {
  projectId: string; products: Row[]; asOf: string; refreshKey: number; onItem: (id: string) => void; onDirty: (dirty: boolean) => void;
}) {
  const { can } = useAuth();
  const [types, setTypes] = useState<Record<string, WidgetType>>({});
  const [list, setList] = useState<LayoutSummary[]>([]);
  const [layout, setLayout] = useState<Layout | null>(null);
  const [widgets, setWidgets] = useState<PlacedWidget[]>([]);
  const [filters, setFilters] = useState<LayoutConfig["filters"]>({});
  const [editing, setEditing] = useState(false);
  const [locations, setLocations] = useState<Row[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [dlg, setDlg] = useState<Dlg>(null);
  const [drill, setDrill] = useState<{ metric: string; productId?: string } | null>(null);

  const canEdit = !!layout?.can_edit;
  const dirty = canEdit && !!layout && (JSON.stringify(widgets) !== JSON.stringify(layout.config.widgets) || JSON.stringify(filters) !== JSON.stringify(layout.config.filters ?? {}));
  useEffect(() => { onDirty(dirty); return () => onDirty(false); }, [dirty, onDirty]);
  useDirtyGuard(dirty); // warns on closing the tab, following a link or switching a tab

  const show = useCallback(async (id: string) => {
    const l = await api<Layout>(`/dashboard-layouts/${id}`);
    setLayout(l); setWidgets(clone(l.config.widgets)); setFilters(clone(l.config.filters ?? {})); setEditing(false);
    return l;
  }, []);
  const loadList = useCallback(async (open?: string) => {
    try {
      setError(null);
      const r = await api<{ items: LayoutSummary[]; active_id: string }>(`/dashboard-layouts?project_id=${projectId}`);
      setList(r.items);
      await show(open ?? r.active_id);
    } catch (e) { setError(e instanceof Error ? e.message : "Failed to load dashboards"); }
  }, [projectId, show]);
  useEffect(() => {
    api<{ types: WidgetType[] }>("/widget-types").then((r) => setTypes(Object.fromEntries(r.types.map((t) => [t.type, t])))).catch((e) => setError(e instanceof Error ? e.message : "Failed to load widget types"));
    api<Page<Row>>("/locations?size=200").then((p) => setLocations(p.items)).catch(() => {});
  }, []);
  useEffect(() => { void loadList(); }, [loadList]);

  const guard = (go: () => void) => (dirty ? setDlg({ kind: "discard", then: go }) : go());
  const choose = (id: string) => guard(async () => {
    try { await show(id); await api(`/projects/${projectId}/dashboard-pref`, { method: "PUT", body: { layout_id: id } }); } catch (e) { setError(e instanceof Error ? e.message : "Could not open that dashboard"); }
  });

  async function save() {
    if (!layout) return;
    try {
      setError(null);
      const l = await api<Layout>(`/dashboard-layouts/${layout.id}`, { method: "PUT", body: { version: layout.version, config: { version: 1, filters, widgets: widgets.map((w) => ({ ...w, config: cleanConfig(w.config) })) } } });
      setLayout(l); setWidgets(clone(l.config.widgets)); setFilters(clone(l.config.filters ?? {}));
      setList((x) => x.map((i) => (i.id === l.id ? { ...i, version: l.version, widgets: l.widgets } : i)));
      setNotice(`Saved “${l.name}” (version ${l.version}).`);
    } catch (e) { setError(e instanceof Error ? e.message : "Save failed"); }
  }
  async function saveAs(name: string, scope: string) {
    const body = { name, scope, project_id: scope === "project" ? projectId : null, config: { version: 1, filters, widgets: widgets.map((w) => ({ ...w, config: cleanConfig(w.config) })) } };
    const l = await api<Layout>("/dashboard-layouts", { method: "POST", body });
    await api(`/projects/${projectId}/dashboard-pref`, { method: "PUT", body: { layout_id: l.id } });
    setDlg(null);
    await loadList(l.id);
    setEditing(true);
    setNotice(`Created “${l.name}”.`);
  }
  async function restoreDefault() {
    if (!layout) return;
    const l = await api<Layout>(`/dashboard-layouts/${layout.id}/restore-default`, { method: "POST", body: { version: layout.version } });
    setLayout(l); setWidgets(clone(l.config.widgets)); setFilters(clone(l.config.filters ?? {}));
    setDlg(null); setNotice("The default arrangement is back.");
  }
  async function remove() {
    if (!layout) return;
    await api(`/dashboard-layouts/${layout.id}`, { method: "DELETE" });
    setDlg(null); setNotice(`Deleted “${layout.name}”.`);
    await loadList();
  }

  const add = (t: WidgetType) => {
    const pos = firstFree(widgets, t.default_size.w, t.default_size.h);
    const defaults = cleanConfig(Object.fromEntries(t.settings.filter((s) => s.default !== null && s.default !== undefined && s.key !== "title").map((s) => [s.key, s.default])));
    setWidgets(settle([...widgets, { id: newId(widgets), type: t.type, ...pos, w: t.default_size.w, h: t.default_size.h, config: defaults }]));
    setDlg(null);
  };
  const grouped = useMemo(() => (["template", "personal", "project", "management"] as const).map((s) => [s, list.filter((l) => l.scope === s)] as const).filter(([, l]) => l.length), [list]);
  const scopes = [["personal", "Personal: only me"], ...(can("projects:write") ? [["project", "Project: everyone on this project"]] : []), ...(can("dashboards:manage") ? [["management", "Management: the whole organisation"]] : [])];
  const settingsOf = dlg?.kind === "settings" ? widgets.find((w) => w.id === dlg.id) : undefined;

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-end gap-3 rounded-lg border border-slate-200 bg-slate-50/70 p-3 print:hidden">
        <Label text="Dashboard">
          <Select value={layout?.id ?? ""} onChange={(e) => choose(e.target.value)} className="min-w-64">
            {grouped.map(([s, items]) => <optgroup key={s} label={SCOPE_LABEL[s]}>{items.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}</optgroup>)}
          </Select>
        </Label>
        <Label text="Product"><Select value={filters.product_id ?? ""} onChange={(e) => setFilters((f) => ({ ...f, product_id: e.target.value || undefined }))}><option value="">All products</option>{products.map((p) => <option key={String(p.id)} value={String(p.id)}>{String(p.code)}</option>)}</Select></Label>
        <Label text="Location (coverage widgets)"><Select value={filters.location_id ?? ""} onChange={(e) => setFilters((f) => ({ ...f, location_id: e.target.value || undefined }))}><option value="">All locations</option>{locations.map((l) => <option key={String(l.id)} value={String(l.id)}>{String(l.name)}</option>)}</Select></Label>
        <div className="flex flex-wrap gap-2 pb-0.5">
          {canEdit && !editing && <Button onClick={() => setEditing(true)}>Edit layout</Button>}
          {!canEdit && layout && <Button onClick={() => setDlg({ kind: "saveas" })}>Customise (save a copy)</Button>}
          {editing && <>
            <Button variant="ghost" onClick={() => setDlg({ kind: "add" })}>＋ Add widget</Button>
            <Button onClick={save} disabled={!dirty}>Save</Button>
            <Button variant="ghost" onClick={() => layout && guard(() => { setWidgets(clone(layout.config.widgets)); setFilters(clone(layout.config.filters ?? {})); setEditing(false); })}>{dirty ? "Discard changes" : "Done"}</Button>
          </>}
          {layout && <Button variant="ghost" onClick={() => setDlg({ kind: "saveas" })}>{canEdit ? "Duplicate / save as…" : "Save as…"}</Button>}
          {editing && canEdit && <Button variant="ghost" onClick={() => setDlg({ kind: "restore" })}>Restore default layout</Button>}
          {editing && canEdit && <Button variant="danger" onClick={() => setDlg({ kind: "delete" })}>Delete dashboard</Button>}
        </div>
      </div>
      {layout && <p className="mb-2 text-xs text-slate-500">
        <Badge tone={layout.scope === "management" ? "amber" : layout.scope === "project" ? "green" : "slate"}>{layout.scope === "template" ? "default template" : layout.scope}</Badge>
        {layout.description ? ` ${layout.description}` : layout.updated_by ? ` Saved by ${layout.updated_by}, version ${layout.version}.` : ""}
        {!canEdit && layout.scope !== "template" ? " You can view this dashboard; ask its owner to change it, or save a copy." : ""}
        {dirty && <span className="ml-2 font-semibold text-amber-700">Unsaved changes</span>}
        <span className="ml-2">Numbers are read live from the database each time; a saved dashboard stores only the arrangement.</span></p>}
      <ErrorBox message={error} />
      {error && layout && <p className="-mt-2 mb-2 text-xs"><button className="text-blue-900 underline" onClick={() => void loadList(layout.id)}>Reload this dashboard</button> (discards your unsaved changes)</p>}
      {notice && <div role="status" className="mb-2 rounded-md border border-green-200 bg-green-50 px-3 py-1.5 text-xs text-green-900">{notice} <button className="ml-2 underline" onClick={() => setNotice(null)}>dismiss</button></div>}
      {!layout ? <Loading /> : widgets.length === 0 ? <p className="rounded-md border border-dashed border-slate-300 p-8 text-center text-sm text-slate-500">This dashboard is empty.{canEdit ? " Choose Edit layout, then Add widget." : ""}</p> : (
        <Grid widgets={widgets} types={types} editing={editing} onChange={setWidgets}
          header={(w) => (
            <>
              <span className="min-w-0 flex-1 truncate font-semibold text-blue-950">{String(w.config.title || types[w.type]?.title || w.type)}</span>
              {editing && <>
                <button className="rounded-md px-1 hover:bg-blue-100" aria-label="Widget settings" title="Settings" onPointerDown={(e) => e.stopPropagation()} onClick={() => setDlg({ kind: "settings", id: w.id })}>⚙</button>
                <button className="rounded-md px-1 text-red-700 hover:bg-red-50" aria-label="Remove widget" title="Remove" onPointerDown={(e) => e.stopPropagation()} onClick={() => setWidgets(settle(widgets.filter((x) => x.id !== w.id)))}>✕</button>
              </>}
            </>
          )}>
          {(w) => <Frame projectId={projectId} w={w} filters={filters} asOf={asOf} refreshKey={refreshKey} onDrill={(metric, p) => setDrill({ metric, productId: p })} />}
        </Grid>
      )}

      {drill && <Drilldown refreshKey={refreshKey} projectId={projectId} metric={drill.metric} asOf={asOf} productId={drill.productId || filters.product_id} onClose={() => setDrill(null)} onItem={onItem} />}
      {dlg?.kind === "add" && <AddDialog types={Object.values(types)} onPick={add} onClose={() => setDlg(null)} />}
      {dlg?.kind === "settings" && settingsOf && types[settingsOf.type] && (
        <SettingsDialog t={types[settingsOf.type]} value={settingsOf.config} products={products} locations={locations} onClose={() => setDlg(null)}
          onApply={(c) => { setWidgets(widgets.map((w) => (w.id === settingsOf.id ? { ...w, config: c } : w))); setDlg(null); }} />
      )}
      {dlg?.kind === "saveas" && layout && <SaveAsDialog defaultName={layout.scope === "template" ? "My dashboard" : `${layout.name} (copy)`} scopes={scopes} onClose={() => setDlg(null)} onCreate={saveAs} />}
      {dlg?.kind === "restore" && <ConfirmDialog title="Restore the default layout?" confirmLabel="Restore" danger onCancel={() => setDlg(null)} onConfirm={restoreDefault}>The widgets and their positions go back to the default status layout. This is saved at once.</ConfirmDialog>}
      {dlg?.kind === "delete" && layout && <ConfirmDialog title="Delete this dashboard?" confirmLabel="Delete" danger onCancel={() => setDlg(null)} onConfirm={remove}>“{layout.name}” is removed for {layout.scope === "personal" ? "you" : "everyone who can see it"}. The data it shows is not affected.</ConfirmDialog>}
      {dlg?.kind === "discard" && <ConfirmDialog title="Discard unsaved changes?" confirmLabel="Discard" danger onCancel={() => setDlg(null)} onConfirm={() => { const go = dlg.then; setDlg(null); go(); }}>You changed this dashboard and have not saved it.</ConfirmDialog>}
    </div>
  );
}

function Frame({ projectId, w, filters, asOf, refreshKey, onDrill }: { projectId: string; w: PlacedWidget; filters: LayoutConfig["filters"]; asOf: string; refreshKey: number; onDrill: (m: string, p?: string) => void }) {
  const { data, error } = useWidgetData(projectId, w.type, cleanConfig(w.config), filters, asOf, refreshKey);
  if (error) return <p role="alert" className="text-xs text-red-700">{error}</p>;
  if (!data) return <Loading compact rows={2} />;
  return <WidgetBody data={data} config={w.config} onDrill={onDrill} />;
}

/* ------------------------------------------------------------------ dialogs */
function Modal({ title, onClose, children, wide }: { title: string; onClose: () => void; children: React.ReactNode; wide?: boolean }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" role="dialog" aria-modal="true" aria-label={title} onClick={onClose} onKeyDown={(e) => { if (e.key === "Escape") onClose(); }}>
      <div className={`max-h-[85vh] w-full overflow-y-auto rounded-md bg-white p-5 shadow-xl ${wide ? "max-w-3xl" : "max-w-md"}`} onClick={(e) => e.stopPropagation()}>
        <div className="mb-3 flex justify-between"><h3 className="text-base font-semibold text-blue-950">{title}</h3><button onClick={onClose} aria-label="Close">✕</button></div>
        {children}
      </div>
    </div>
  );
}

function AddDialog({ types, onPick, onClose }: { types: WidgetType[]; onPick: (t: WidgetType) => void; onClose: () => void }) {
  return (
    <Modal title="Add a widget" onClose={onClose} wide>
      <div className="grid gap-2 sm:grid-cols-2">
        {types.map((t) => (
          <button key={t.type} onClick={() => onPick(t)} className="rounded-md border border-slate-200 p-3 text-left hover:border-blue-700 hover:bg-blue-50">
            <div className="text-sm font-semibold text-blue-950">{t.title}</div>
            <div className="mt-0.5 text-xs text-slate-600">{t.description}</div>
            {t.sources.length > 0 && <div className="mt-1 text-[11px] text-slate-400">Data: {t.sources.join(", ")}</div>}
          </button>
        ))}
      </div>
    </Modal>
  );
}

function SettingsDialog({ t, value, products, locations, onApply, onClose }: { t: WidgetType; value: Record<string, unknown>; products: Row[]; locations: Row[]; onApply: (c: Record<string, unknown>) => void; onClose: () => void }) {
  const [v, setV] = useState<Record<string, unknown>>(value);
  const set = (k: string, x: unknown) => setV((s) => ({ ...s, [k]: x }));
  return (
    <Modal title={`${t.title}: settings`} onClose={onClose}>
      <div className="space-y-3">
        {t.settings.map((s: SettingDef) => (
          <Label key={s.key} text={s.label}>
            {s.kind === "select" ? <Select value={String(v[s.key] ?? "")} onChange={(e) => set(s.key, e.target.value)}>{s.options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}</Select>
              : s.kind === "multiselect" ? <div className="space-y-0.5">{s.options.map((o) => { const cur = (v[s.key] as string[] | undefined) ?? (s.default as string[] | null) ?? []; return <label key={o.value} className="flex items-center gap-2 text-sm font-normal"><input type="checkbox" checked={cur.includes(o.value)} onChange={(e) => set(s.key, e.target.checked ? [...cur, o.value] : cur.filter((x) => x !== o.value))} />{o.label}</label>; })}</div>
              : s.kind === "product" ? <Select value={String(v[s.key] ?? "")} onChange={(e) => set(s.key, e.target.value)}><option value="">Use the dashboard filter / all</option>{products.map((p) => <option key={String(p.id)} value={String(p.id)}>{String(p.code)}</option>)}</Select>
              : s.kind === "location" ? <Select value={String(v[s.key] ?? "")} onChange={(e) => set(s.key, e.target.value)}><option value="">Use the dashboard filter / all</option>{locations.map((l) => <option key={String(l.id)} value={String(l.id)}>{String(l.name)}</option>)}</Select>
              : s.kind === "number" ? <Input type="number" min={s.min ?? undefined} max={s.max ?? undefined} value={String(v[s.key] ?? s.default ?? "")} onChange={(e) => set(s.key, e.target.value === "" ? "" : Number(e.target.value))} />
              : s.kind === "longtext" ? <textarea className="w-full rounded-md border border-slate-300 px-2.5 py-1.5 text-sm" rows={3} value={String(v[s.key] ?? "")} onChange={(e) => set(s.key, e.target.value)} />
              : <Input value={String(v[s.key] ?? "")} onChange={(e) => set(s.key, e.target.value)} />}
          </Label>
        ))}
      </div>
      <div className="mt-4 flex justify-end gap-2"><Button variant="ghost" onClick={onClose}>Cancel</Button><Button onClick={() => onApply(cleanConfig(v))}>Apply</Button></div>
    </Modal>
  );
}

function SaveAsDialog({ defaultName, scopes, onCreate, onClose }: { defaultName: string; scopes: string[][]; onCreate: (name: string, scope: string) => Promise<void>; onClose: () => void }) {
  const [name, setName] = useState(defaultName);
  const [scope, setScope] = useState("personal");
  const [error, setError] = useState<string | null>(null);
  return (
    <Modal title="Save as a new dashboard" onClose={onClose}>
      <ErrorBox message={error} />
      <div className="space-y-3">
        <Label text="Name"><Input autoFocus value={name} onChange={(e) => setName(e.target.value)} maxLength={120} /></Label>
        <Label text="Who can see it"><Select value={scope} onChange={(e) => setScope(e.target.value)}>{scopes.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</Select></Label>
        <p className="text-xs text-slate-500">The widgets and settings you see now are copied, including unsaved changes. The original stays as it was.</p>
      </div>
      <div className="mt-4 flex justify-end gap-2"><Button variant="ghost" onClick={onClose}>Cancel</Button><Button disabled={!name.trim()} onClick={async () => { try { await onCreate(name, scope); } catch (e) { setError(e instanceof Error ? e.message : "Failed"); } }}>Create</Button></div>
    </Modal>
  );
}
