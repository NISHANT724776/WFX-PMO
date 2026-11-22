"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { Badge, Button, Empty, ErrorBox, Input, Label, PageHeader, Pager, Select, Loading } from "@/components/ui";
import { api, qs, type Page, type Row } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import {
  downloadErrorReport, fmtSize, type Batch, type Issue, type SheetColumn, type SheetDetail, type Suggestion, type ValidationSheet,
} from "@/lib/imports";

const TABS = ["Sheets", "Mapping", "Relationships", "Validation", "Preview", "Import"] as const;
type Tab = (typeof TABS)[number];
const LEVEL_TONE = { high: "green", medium: "amber", low: "red", none: "slate", manual: "slate" } as const;
const SEV_TONE = { error: "red", warning: "amber", info: "slate" } as const;

export default function BatchPage() {
  const { id } = useParams<{ id: string }>();
  const [batch, setBatch] = useState<Batch | null>(null);
  const [tab, setTab] = useState<Tab>("Sheets");
  const [sheetId, setSheetId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const b = await api<Batch>(`/imports/${id}`);
      setBatch(b);
      setSheetId((cur) => cur ?? b.sheets?.find((s) => s.entity)?.id ?? b.sheets?.[0]?.id ?? null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load import");
    }
  }, [id]);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    if (!batch || (batch.status !== "uploaded" && batch.status !== "analyzing")) return;
    const t = setTimeout(() => void load(), 1500);
    return () => clearTimeout(t);
  }, [batch, load]);

  if (!batch) return <><ErrorBox message={error} />{!error && <Loading />}</>;

  const locked = batch.status !== "ready";
  return (
    <>
      <PageHeader
        title={batch.filename}
        subtitle={`${fmtSize(batch.size_bytes)} · uploaded ${new Date(batch.uploaded_at).toLocaleString()} by ${batch.uploaded_by} · ${batch.status.replace("_", " ")}${batch.template ? ` · template: ${batch.template}` : ""}`}
        actions={<Link className="text-sm text-blue-900 underline" href="/excel-intelligence">All imports</Link>}
      />
      <ErrorBox message={error ?? batch.error} />
      {(batch.status === "analyzing" || batch.status === "uploaded") && <p className="mb-3 text-sm text-slate-600">Analysing workbook…</p>}
      {batch.sheets && batch.sheets.length > 0 && (
        <>
          <div className="mb-4 flex gap-1 border-b border-slate-200">
            {TABS.map((t) => (
              <button key={t} onClick={() => setTab(t)}
                className={`px-3 py-1.5 text-sm ${tab === t ? "border-b-2 border-blue-900 font-medium text-blue-950" : "text-slate-600 hover:text-slate-900"}`}>{t}</button>
            ))}
          </div>
          {locked && batch.status !== "committed" && <p className="mb-3 text-sm text-slate-500">This import is {batch.status.replace("_", " ")}; mappings are read-only.</p>}
          {tab === "Sheets" && <SheetsTab batch={batch} locked={locked} reload={load} openMapping={(s) => { setSheetId(s); setTab("Mapping"); }} />}
          {tab === "Mapping" && <MappingTab batch={batch} sheetId={sheetId} setSheetId={setSheetId} locked={locked} reload={load} />}
          {tab === "Relationships" && <RelationsTab batchId={batch.id} />}
          {tab === "Validation" && <ValidationTab batch={batch} locked={locked} reload={load} />}
          {tab === "Preview" && <PreviewTab batch={batch} sheetId={sheetId} setSheetId={setSheetId} />}
          {tab === "Import" && <ImportTab batch={batch} reload={load} />}
        </>
      )}
    </>
  );
}

/* ------------------------------------------------------------------ Sheets */
function SheetsTab({ batch, locked, reload, openMapping }: { batch: Batch; locked: boolean; reload: () => Promise<void>; openMapping: (id: string) => void }) {
  const [error, setError] = useState<string | null>(null);
  async function toggle(id: string, enabled: boolean) {
    try { setError(null); await api(`/imports/${batch.id}/sheets/${id}`, { method: "PATCH", body: { enabled } }); await reload(); }
    catch (e) { setError(e instanceof Error ? e.message : "Update failed"); }
  }
  return (
    <>
      <ErrorBox message={error} />
      <table className="w-full text-left text-sm">
        <thead className="border-b border-slate-300 text-xs uppercase text-slate-500">
          <tr><th className="py-2 pr-3">Import</th><th className="pr-3">Sheet</th><th className="pr-3">Detected as</th><th className="pr-3">Rows</th><th className="pr-3">Cols</th><th className="pr-3">Notes</th><th /></tr>
        </thead>
        <tbody>
          {batch.sheets!.map((s) => (
            <tr key={s.id} className="border-b border-slate-100 align-top">
              <td className="py-1.5 pr-3"><input type="checkbox" checked={s.enabled} disabled={locked || !s.entity} onChange={(e) => toggle(s.id, e.target.checked)} aria-label={`Import ${s.name}`} /></td>
              <td className="pr-3 font-medium">{s.name}{s.state !== "visible" && <span className="ml-1 text-xs text-slate-500">(hidden)</span>}</td>
              <td className="pr-3">{s.classification_label} <span className="text-xs text-slate-500">{Math.round(s.class_confidence * 100)}%</span></td>
              <td className="pr-3">{s.rows}</td>
              <td className="pr-3">{s.columns}</td>
              <td className="pr-3 text-xs text-slate-600">
                {s.not_yet && <Badge tone="slate">import arrives in {s.not_yet}</Badge>}
                {s.template && <Badge tone="green">template: {s.template}</Badge>}
                {s.unconfirmed > 0 && <Badge tone="amber">{s.unconfirmed} to confirm</Badge>}
              </td>
              <td className="text-right">{s.entity && <Button variant="ghost" onClick={() => openMapping(s.id)}>Review mapping</Button>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

/* ------------------------------------------------------------------ Mapping */
function SheetPicker({ batch, sheetId, setSheetId, onlyMappable }: { batch: Batch; sheetId: string | null; setSheetId: (s: string) => void; onlyMappable?: boolean }) {
  const sheets = batch.sheets!.filter((s) => !onlyMappable || s.entity);
  return (
    <div className="mb-3 max-w-sm"><Label text="Sheet">
      <Select value={sheetId ?? ""} onChange={(e) => setSheetId(e.target.value)}>
        {sheets.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
      </Select>
    </Label></div>
  );
}

function MappingTab({ batch, sheetId, setSheetId, locked, reload }: { batch: Batch; sheetId: string | null; setSheetId: (s: string) => void; locked: boolean; reload: () => Promise<void> }) {
  const { can } = useAuth();
  const [d, setD] = useState<SheetDetail | null>(null);
  const [products, setProducts] = useState<Row[]>([]);
  const [pending, setPending] = useState<Record<string, string>>({}); // column id -> target field ("" = not imported)
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    if (!sheetId) return;
    try { setError(null); setD(await api<SheetDetail>(`/imports/${batch.id}/sheets/${sheetId}`)); setPending({}); }
    catch (e) { setError(e instanceof Error ? e.message : "Failed to load sheet"); }
  }, [batch.id, sheetId]);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => { if (can("master:read")) api<Page<Row>>("/products?size=200").then((p) => setProducts(p.items)).catch(() => {}); }, [can]);

  if (!sheetId || !d) return <><SheetPicker batch={batch} sheetId={sheetId} setSheetId={setSheetId} onlyMappable /><ErrorBox message={error} />{!error && <Loading />}</>;

  async function act(fn: () => Promise<unknown>) {
    setBusy(true);
    try { setError(null); await fn(); await load(); await reload(); }
    catch (e) { setError(e instanceof Error ? e.message : "Update failed"); }
    finally { setBusy(false); }
  }
  const put = (items: { column_id: string; target_field?: string | null; ignore?: boolean }[]) =>
    act(() => api(`/imports/${batch.id}/sheets/${d.id}/mappings`, { method: "PUT", body: { mappings: items } }));
  const patch = (body: object) => act(() => api(`/imports/${batch.id}/sheets/${d.id}`, { method: "PATCH", body }));

  const fieldLabel = (k: string | null) => d.fields.find((f) => f.key === k)?.label ?? "";
  const mappedKeys = new Set(d.columns.filter((c) => c.mapping?.target_field && c.mapping.status !== "ignored").map((c) => pending[c.id] ?? c.mapping!.target_field!));
  const missingRequired = d.fields.filter((f) => f.required && !mappedKeys.has(f.key));
  const medium = d.columns.filter((c) => c.mapping?.level === "medium" && c.mapping.status === "suggested");

  return (
    <>
      <SheetPicker batch={batch} sheetId={sheetId} setSheetId={setSheetId} onlyMappable />
      <ErrorBox message={error} />
      <div className="mb-4 grid max-w-3xl grid-cols-3 gap-3 rounded-md border border-slate-200 bg-slate-50 p-3">
        <Label text="Treat this sheet as">
          <Select disabled={locked || busy} value={d.entity ?? ""} onChange={(e) => patch({ entity: e.target.value })}>
            <option value="">(do not import)</option>
            {d.entities.map((e) => <option key={e.key} value={e.key}>{e.label}</option>)}
          </Select>
        </Label>
        <Label text="Header row">
          <Select disabled={locked || busy} value={d.profile.header_row} onChange={(e) => patch({ header_row: Number(e.target.value) })}>
            {[...new Map([...d.profile.header_candidates.map((c) => [c.row, c] as const), [d.profile.header_row, { row: d.profile.header_row, score: 0, preview: [] as string[] }] as const]).values()].sort((a, b) => a.row - b.row)
              .map((c) => <option key={c.row} value={c.row}>Row {c.row}{c.row === d.profile.header_row ? " (current)" : ""}{c.preview.length ? ` · ${c.preview.slice(0, 3).join(", ")}` : ""}</option>)}
          </Select>
        </Label>
        <div className="text-xs text-slate-600">
          <div>{d.classification_label} ({Math.round(d.class_confidence * 100)}%)</div>
          <div>{d.profile.stats.data_rows} data rows{d.profile.section_rows.count ? ` · ${d.profile.section_rows.count} section rows` : ""}</div>
          {d.profile.stats.hidden_columns.length > 0 && <div>Hidden columns: {d.profile.stats.hidden_columns.join(", ")}</div>}
        </div>
      </div>

      {d.layout === "matrix" && d.config.product_map && (
        <div className="mb-4 max-w-3xl rounded-md border border-slate-200 p-3">
          <h3 className="mb-1 text-sm font-semibold text-blue-950">Product columns</h3>
          <p className="mb-2 text-xs text-slate-600">Each product group becomes its own records (one per event). Link every group to a product or exclude it. Nothing is guessed.</p>
          <div className="grid grid-cols-2 gap-3">
            {Object.entries(d.config.product_map).map(([label, pid]) => (
              <Label key={label} text={`${label}${d.config.product_suggested?.[label] ? " (matched by name)" : ""}`}>
                <Select disabled={locked || busy} value={pid ?? ""} onChange={(e) => patch({ product_map: { [label]: e.target.value || null } })}>
                  <option value="">— choose product —</option>
                  {products.map((p) => <option key={p.id} value={p.id}>{String(p.code)} · {String(p.name)}</option>)}
                  <option value="__exclude__">Exclude this group from the import</option>
                </Select>
              </Label>
            ))}
          </div>
          {!can("master:write") && <p className="mt-2 text-xs text-slate-500">A product that does not exist yet must be created by an administrator or PMO under Master Data → Products.</p>}
        </div>
      )}

      {d.entity === "dependency_item" && d.pending_with_values.length > 0 && (
        <div className="mb-4 max-w-3xl rounded-md border border-slate-200 p-3">
          <h3 className="mb-1 text-sm font-semibold text-blue-950">Who are these items pending with?</h3>
          <p className="mb-2 text-xs text-slate-600">Decide what each value in the responsibility column means. WFX is recognised; anything else is not guessed.</p>
          <div className="grid grid-cols-2 gap-3">
            {d.pending_with_values.map((pv) => (
              <Label key={pv.value} text={`${pv.value} (${pv.count} rows)`}>
                <Select disabled={locked || busy} value={pv.category ?? ""} onChange={(e) => patch({ pending_with_map: { [pv.value]: e.target.value || null } })}>
                  <option value="">— choose —</option><option value="customer">Customer</option><option value="wfx">WFX</option><option value="external">External partner</option><option value="internal">Internal team</option><option value="ignore">Skip these rows</option>
                </Select>
              </Label>
            ))}
          </div>
        </div>
      )}

      {d.status_values.length > 0 && <StatusPanel d={d} locked={locked || busy} onChange={(field, value, category) => patch({ value_maps: { [field]: { [value]: category } } })} />}

      {missingRequired.length > 0 && <div className="mb-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">Required field(s) not mapped: {missingRequired.map((f) => f.label).join(", ")}</div>}
      {medium.length > 0 && !locked && (
        <div className="mb-3 flex items-center gap-3 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
          {medium.length} medium-confidence suggestion(s) need your confirmation before import.
          <Button variant="ghost" disabled={busy} onClick={() => put(medium.map((c) => ({ column_id: c.id, target_field: pending[c.id] ?? c.mapping!.target_field })))}>Confirm all medium</Button>
        </div>
      )}
      <table className="w-full text-left text-sm">
        <thead className="border-b border-slate-300 text-xs uppercase text-slate-500">
          <tr><th className="py-2 pr-3">Excel column</th><th className="pr-3">Type</th><th className="pr-3">Sample values</th><th className="pr-3">Maps to</th><th className="pr-3">Confidence</th><th /></tr>
        </thead>
        <tbody>
          {d.columns.map((c) => <MappingRow key={c.id} c={c} d={d} locked={locked || busy} value={pending[c.id]} onChange={(v) => setPending((p) => ({ ...p, [c.id]: v }))} fieldLabel={fieldLabel}
            onAccept={() => put([{ column_id: c.id, target_field: pending[c.id] ?? c.mapping?.target_field ?? null, ignore: !(pending[c.id] ?? c.mapping?.target_field) }])}
            onIgnore={() => put([{ column_id: c.id, ignore: true }])} />)}
        </tbody>
      </table>
      {Object.keys(pending).length > 0 && !locked && (
        <div className="mt-3"><Button disabled={busy} onClick={() => put(Object.entries(pending).map(([cid, v]) => ({ column_id: cid, target_field: v || null, ignore: !v })))}>Save {Object.keys(pending).length} change(s)</Button></div>
      )}
    </>
  );
}

function MappingRow({ c, d, locked, value, onChange, fieldLabel, onAccept, onIgnore }: {
  c: SheetColumn; d: SheetDetail; locked: boolean; value: string | undefined; onChange: (v: string) => void; fieldLabel: (k: string | null) => string; onAccept: () => void; onIgnore: () => void;
}) {
  const m = c.mapping;
  const current = value ?? (m && m.status !== "ignored" ? (m.target_field ?? "") : "");
  const dates = c.profile.invalid_date_values ?? [];
  return (
    <tr className="border-b border-slate-100 align-top">
      <td className="py-1.5 pr-3"><div className="font-medium">{c.header}</div><div className="text-xs text-slate-500">col {c.letter}{c.group_label ? ` · ${c.group_label}` : ""}{c.profile.hidden ? " · hidden" : ""}</div></td>
      <td className="pr-3 text-xs">{c.inferred_type}{dates.length > 0 && <div className="text-amber-700">non-dates: {dates.map(([v, n]) => `${v} ×${n}`).join(", ")}</div>}</td>
      <td className="max-w-xs truncate pr-3 text-xs text-slate-600" title={(c.profile.samples ?? []).join(" | ")}>{(c.profile.samples ?? []).slice(0, 3).join(" | ")}</td>
      <td className="pr-3">
        {m ? (
          <Select disabled={locked} value={current} onChange={(e) => onChange(e.target.value)}>
            <option value="">— not imported —</option>
            {d.fields.map((f) => <option key={f.key} value={f.key}>{f.label}{f.required ? " *" : ""}</option>)}
          </Select>
        ) : <span className="text-xs text-slate-400">no target</span>}
      </td>
      <td className="pr-3 whitespace-nowrap">
        {m && <><Badge tone={LEVEL_TONE[m.level]}>{m.level === "none" ? "no match" : m.level}</Badge> <span className="text-xs text-slate-500">{m.status === "confirmed" ? "confirmed" : m.status === "ignored" ? "ignored" : m.source !== "auto" ? m.source : ""}</span></>}
        {m?.level === "low" && m.status === "suggested" && <div className="text-xs text-red-700">not applied until confirmed</div>}
      </td>
      <td className="whitespace-nowrap text-right">
        {m && !locked && <>
          {m.status !== "confirmed" && (current !== "" ) && <Button variant="ghost" onClick={onAccept} title={`Confirm → ${fieldLabel(current)}`}>Confirm</Button>}{" "}
          {m.status !== "ignored" && <Button variant="ghost" onClick={onIgnore}>Ignore</Button>}
        </>}
      </td>
    </tr>
  );
}

/* ------------------------------------------------------------------ Relationships */
type Rel = { candidates: { sheet_a: string; column_a: string; sheet_b: string; column_b: string; overlap: number; common_values: number; confidence: number; samples: string[]; decision: string | null }[]; keys: { sheet: string; column: string; unique: number }[]; repeated_references: { sheet: string; column: string; rows: number; distinct: number; note: string }[] };

function RelationsTab({ batchId }: { batchId: string }) {
  const [rel, setRel] = useState<Rel | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => api<Rel>(`/imports/${batchId}/relationships`).then(setRel).catch((e) => setError(e.message)), [batchId]);
  useEffect(() => { void load(); }, [load]);
  if (!rel) return <><ErrorBox message={error} /><Loading /></>;
  const decide = async (i: number, decision: string) => { await api(`/imports/${batchId}/relationships/${i}`, { method: "PATCH", body: { decision } }); await load(); };
  return (
    <div className="max-w-4xl space-y-6">
      <section>
        <h3 className="mb-1 text-sm font-semibold text-blue-950">Possible links between sheets</h3>
        {rel.candidates.length === 0 ? <Empty>No columns share enough values across sheets to suggest a link.</Empty> : (
          <ul className="divide-y divide-slate-100 text-sm">
            {rel.candidates.map((c, i) => (
              <li key={i} className="flex items-center justify-between py-2">
                <div>{c.sheet_a} · <b>{c.column_a}</b> ↔ {c.sheet_b} · <b>{c.column_b}</b><div className="text-xs text-slate-500">{c.common_values} shared values ({Math.round(c.overlap * 100)}%), e.g. {c.samples.join(", ")}</div></div>
                <div className="flex items-center gap-2">{c.decision ? <Badge tone={c.decision === "confirmed" ? "green" : "slate"}>{c.decision}</Badge> : <><Button variant="ghost" onClick={() => decide(i, "confirmed")}>Confirm</Button><Button variant="ghost" onClick={() => decide(i, "rejected")}>Reject</Button></>}</div>
              </li>
            ))}
          </ul>
        )}
        <p className="mt-1 text-xs text-slate-500">Confirmed links are recorded for the next phases; they do not change what this import writes.</p>
      </section>
      <section>
        <h3 className="mb-1 text-sm font-semibold text-blue-950">Unique ID columns</h3>
        {rel.keys.length === 0 ? <p className="text-sm text-slate-500">None found.</p> : <ul className="text-sm">{rel.keys.map((k, i) => <li key={i}>{k.sheet} · <b>{k.column}</b> ({k.unique} unique values)</li>)}</ul>}
      </section>
      <section>
        <h3 className="mb-1 text-sm font-semibold text-blue-950">Repeated references (not unique keys)</h3>
        {rel.repeated_references.length === 0 ? <p className="text-sm text-slate-500">None found.</p> : <ul className="text-sm">{rel.repeated_references.map((k, i) => <li key={i}>{k.sheet} · <b>{k.column}</b>: {k.rows} rows, {k.distinct} distinct. <span className="text-slate-500">{k.note}</span></li>)}</ul>}
      </section>
    </div>
  );
}

/* ------------------------------------------------------------------ Validation */
function ValidationTab({ batch, locked, reload }: { batch: Batch; locked: boolean; reload: () => Promise<void> }) {
  const [sheets, setSheets] = useState<ValidationSheet[] | null>(batch.validation ?? null);
  const [issues, setIssues] = useState<Page<Issue> | null>(null);
  const [sev, setSev] = useState("");
  const [page, setPage] = useState(1);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const loadIssues = useCallback(async () => {
    try { setIssues(await api<Page<Issue>>(`/imports/${batch.id}/errors${qs({ severity: sev, page, size: 25 })}`)); }
    catch (e) { setError(e instanceof Error ? e.message : "Failed to load issues"); }
  }, [batch.id, sev, page]);
  useEffect(() => { if (sheets) void loadIssues(); }, [sheets, loadIssues]);

  async function run() {
    setBusy(true); setError(null);
    try { const r = await api<{ sheets: ValidationSheet[] }>(`/imports/${batch.id}/validate`, { method: "POST" }); setSheets(r.sheets); setPage(1); await reload(); }
    catch (e) { setError(e instanceof Error ? e.message : "Validation failed"); }
    finally { setBusy(false); }
  }

  return (
    <>
      <ErrorBox message={error} />
      <div className="mb-3 flex gap-2">
        {!locked && <Button disabled={busy} onClick={run}>{busy ? "Validating…" : "Run validation"}</Button>}
        {sheets && <Button variant="ghost" onClick={() => downloadErrorReport(batch.id, batch.filename).catch((e) => setError(e.message))}>Download error report (CSV)</Button>}
      </div>
      {!sheets ? <Empty>Run validation to check dates, required fields, statuses and formula errors before anything is imported.</Empty> : (
        <>
          <table className="mb-4 w-full text-left text-sm">
            <thead className="border-b border-slate-300 text-xs uppercase text-slate-500"><tr><th className="py-2 pr-3">Sheet</th><th className="pr-3">Source rows</th><th className="pr-3">Records</th><th className="pr-3">Importable</th><th className="pr-3">Rejected</th><th className="pr-3">Errors</th><th className="pr-3">Warnings</th><th>Blocking</th></tr></thead>
            <tbody>
              {sheets.map((s) => s.skipped ? (
                <tr key={s.sheet_id} className="border-b border-slate-100 text-slate-500"><td className="py-1.5 pr-3">{s.name}</td><td colSpan={7}>Skipped: {s.reason}</td></tr>
              ) : (
                <tr key={s.sheet_id} className="border-b border-slate-100 align-top">
                  <td className="py-1.5 pr-3 font-medium">{s.name}</td><td className="pr-3">{s.source_rows}</td><td className="pr-3">{s.records}</td>
                  <td className="pr-3">{s.importable}</td><td className="pr-3">{s.rejected_rows ? <Badge tone="red">{s.rejected_rows}</Badge> : 0}</td>
                  <td className="pr-3">{s.errors}</td><td className="pr-3">{s.warnings}</td>
                  <td className="text-xs text-red-700">{s.blocking?.map((b) => <div key={b.code + b.message}>{b.message}</div>)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="mb-2 max-w-xs"><Select value={sev} onChange={(e) => { setSev(e.target.value); setPage(1); }}><option value="">All severities</option><option value="error">Errors</option><option value="warning">Warnings</option><option value="info">Info</option></Select></div>
          {!issues ? <Loading /> : issues.items.length === 0 ? <Empty>No issues{sev ? " of this severity" : ""}.</Empty> : (
            <>
              <table className="w-full text-left text-sm">
                <thead className="border-b border-slate-300 text-xs uppercase text-slate-500"><tr><th className="py-2 pr-3">Severity</th><th className="pr-3">Sheet</th><th className="pr-3">Row</th><th className="pr-3">Column</th><th>Message</th></tr></thead>
                <tbody>
                  {issues.items.map((i) => (
                    <tr key={i.id} className="border-b border-slate-100 align-top">
                      <td className="py-1.5 pr-3"><Badge tone={SEV_TONE[i.severity]}>{i.severity}</Badge></td><td className="pr-3">{i.sheet}</td><td className="pr-3">{i.row ?? "–"}</td><td className="pr-3">{i.column ?? ""}</td>
                      <td>{i.message}{i.rejects_row && <span className="ml-2 text-xs text-red-700">row not imported</span>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <Pager page={page} size={25} total={issues.total} onPage={setPage} />
            </>
          )}
        </>
      )}
    </>
  );
}

/* ------------------------------------------------------------------ Preview */
type PreviewData = { fields: { key: string; label: string }[]; rows: { source_row: number; rejected: boolean; product: string | null; values: Record<string, unknown> }[]; counts: { records: number; importable: number; rejected_rows: number; empty_rows: number; section_rows: number }; blocking: { code: string; message: string }[] };

function PreviewTab({ batch, sheetId, setSheetId }: { batch: Batch; sheetId: string | null; setSheetId: (s: string) => void }) {
  const [p, setP] = useState<PreviewData | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!sheetId) return;
    setP(null); setError(null);
    api<PreviewData>(`/imports/${batch.id}/preview${qs({ sheet_id: sheetId })}`).then(setP).catch((e) => setError(e.message));
  }, [batch.id, sheetId, batch.status]);
  return (
    <>
      <SheetPicker batch={batch} sheetId={sheetId} setSheetId={setSheetId} onlyMappable />
      <ErrorBox message={error} />
      {p && (
        <>
          <p className="mb-2 text-sm text-slate-600">{p.counts.importable} of {p.counts.records} records importable · {p.counts.rejected_rows} rejected rows · {p.counts.empty_rows} empty rows skipped · {p.counts.section_rows} section rows (not data). Showing the first {p.rows.length}.</p>
          {p.blocking.map((b) => <div key={b.code + b.message} className="mb-2 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">{b.message}</div>)}
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="border-b border-slate-300 uppercase text-slate-500"><tr><th className="py-2 pr-3">Row</th>{p.rows.some((r) => r.product) && <th className="pr-3">Product</th>}{p.fields.map((f) => <th key={f.key} className="pr-3">{f.label}</th>)}</tr></thead>
              <tbody>
                {p.rows.map((r) => (
                  <tr key={r.source_row + (r.product ?? "")} className={`border-b border-slate-100 ${r.rejected ? "bg-red-50 text-red-800" : ""}`}>
                    <td className="py-1 pr-3">{r.source_row}{r.rejected ? " ✕" : ""}</td>{p.rows.some((x) => x.product) && <td className="pr-3">{r.product}</td>}
                    {p.fields.map((f) => <td key={f.key} className="max-w-xs truncate pr-3" title={String(r.values[f.key] ?? "")}>{String(r.values[f.key] ?? "")}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </>
  );
}

/* ------------------------------------------------------------------ Import */
function ImportTab({ batch, reload }: { batch: Batch; reload: () => Promise<void> }) {
  const { can } = useAuth();
  const [projects, setProjects] = useState<Row[]>([]);
  const [projectId, setProjectId] = useState(batch.project_id ?? "");
  const [mode, setMode] = useState("create_only");
  const [confirm, setConfirm] = useState(false);
  const [template, setTemplate] = useState("");
  const [sugg, setSugg] = useState<Suggestion[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const rejected = (batch.validation ?? []).reduce((n, s) => n + (s.rejected_rows ?? 0), 0);
  const blocked = (batch.validation ?? []).some((s) => !s.skipped && (s.blocking?.length ?? 0) > 0);

  useEffect(() => { api<Page<Row>>("/projects?size=200").then((p) => setProjects(p.items)).catch(() => {}); }, []);
  useEffect(() => { api<Suggestion[]>(`/imports/${batch.id}/dashboard-suggestions`).then(setSugg).catch(() => {}); }, [batch.id, batch.status]);

  async function commit() {
    setBusy(true); setError(null);
    try { await api(`/imports/${batch.id}/commit`, { method: "POST", body: { project_id: projectId, mode, confirm_rejected: confirm, template_name: template.trim() || null } }); await reload(); }
    catch (e) { setError(e instanceof Error ? e.message : "Import failed"); }
    finally { setBusy(false); }
  }
  async function rollback() {
    if (!confirm_("Roll back this import? Records it created are removed and records it updated are restored.")) return;
    setBusy(true); setError(null);
    try { await api(`/imports/${batch.id}/rollback`, { method: "POST" }); await reload(); }
    catch (e) { setError(e instanceof Error ? e.message : "Rollback failed"); }
    finally { setBusy(false); }
  }

  return (
    <div className="max-w-3xl">
      <ErrorBox message={error} />
      {batch.status === "committed" && batch.commit_summary && (
        <div className="mb-6 rounded-md border border-green-200 bg-green-50 p-4">
          <h3 className="mb-2 text-sm font-semibold text-green-900">Imported ({batch.commit_summary.mode.replace("_", " ")})</h3>
          <table className="text-sm"><thead className="text-xs uppercase text-slate-500"><tr><th className="pr-4 text-left">Sheet</th><th className="pr-4">Created</th><th className="pr-4">Updated</th><th className="pr-4">Skipped</th><th>Rejected</th></tr></thead>
            <tbody>{batch.commit_summary.sheets.map((s) => <tr key={s.sheet}><td className="pr-4">{s.sheet}</td><td className="pr-4 text-center">{s.created}</td><td className="pr-4 text-center">{s.updated}</td><td className="pr-4 text-center">{s.skipped}</td><td className="text-center">{s.rejected}</td></tr>)}</tbody></table>
          <div className="mt-3 flex items-center gap-3">
            {batch.project_id && <Link className="text-sm text-blue-900 underline" href={`/projects/${batch.project_id}`}>Open project</Link>}
            {can("imports:rollback") && <Button variant="danger" disabled={busy} onClick={rollback}>Roll back import</Button>}
          </div>
        </div>
      )}
      {batch.status === "ready" && (
        <div className="mb-6 space-y-3 rounded-md border border-slate-200 p-4">
          <h3 className="text-sm font-semibold text-blue-950">Import into a project</h3>
          {!batch.validation && <p className="text-sm text-amber-800">Run validation first; the import re-validates and will refuse if problems remain.</p>}
          {blocked && <p className="text-sm text-red-700">Blocking problems remain (see Validation). Resolve them before importing.</p>}
          <Label text="Project *">
            <Select value={projectId} onChange={(e) => setProjectId(e.target.value)}>
              <option value="">Select…</option>{projects.map((p) => <option key={p.id} value={p.id}>{String(p.code)} · {String(p.name)}</option>)}
            </Select>
          </Label>
          {projects.length === 0 && <p className="text-xs text-slate-500">No project available. Create one under <Link className="underline" href="/projects">Projects</Link> first.</p>}
          <fieldset className="text-sm">
            <label className="mr-6"><input type="radio" checked={mode === "create_only"} onChange={() => setMode("create_only")} /> Add new records only (existing matches are skipped)</label>
            <label><input type="radio" checked={mode === "update"} onChange={() => setMode("update")} /> Add new and update changed (empty cells never erase data)</label>
          </fieldset>
          {rejected > 0 && <label className="block text-sm text-red-800"><input type="checkbox" checked={confirm} onChange={(e) => setConfirm(e.target.checked)} /> I understand {rejected} rejected row(s) will not be imported (see error report)</label>}
          <Label text="Save mapping as reusable template (optional)"><Input value={template} onChange={(e) => setTemplate(e.target.value)} placeholder="e.g. Tegra Tracker Template" /></Label>
          <Button disabled={busy || !projectId || blocked || (rejected > 0 && !confirm) || !can("imports:commit")} onClick={commit}>{busy ? "Importing…" : "Import"}</Button>
          {!can("imports:commit") && <p className="text-xs text-slate-500">Your role can upload and suggest mappings; a project manager or PMO must approve the import.</p>}
        </div>
      )}
      <h3 className="mb-2 text-sm font-semibold text-blue-950">Dashboards this data can support</h3>
      {!sugg ? <Loading /> : (
        <ul className="divide-y divide-slate-100 text-sm">
          {sugg.map((s) => (
            <li key={s.key} className="py-2">
              <div className="flex items-center gap-2"><Badge tone={s.available ? "green" : "slate"}>{s.available ? "data available" : "not enough data"}</Badge><b>{s.label}</b><span className="text-xs text-slate-500">{s.reference}</span></div>
              {Object.entries(s.missing).map(([e, f]) => <div key={e} className="text-xs text-slate-600">Missing for {e.replace("_", " ")}: {f.join(", ")}</div>)}
              {s.note && <div className="text-xs text-slate-600">{s.note}</div>}
            </li>
          ))}
        </ul>
      )}
      <p className="mt-2 text-xs text-slate-500">Only the availability of source fields is checked here. Dashboard numbers are calculated from the imported records in Phase 4.</p>
    </div>
  );
}

const confirm_ = (m: string) => (typeof window !== "undefined" ? window.confirm(m) : false);

const CATEGORIES: [string, string][] = [["not_started", "Not started"], ["in_progress", "In progress"], ["done", "Done / closed"], ["blocked", "Blocked / waiting"], ["cancelled", "Cancelled"]];

function StatusPanel({ d, locked, onChange }: { d: SheetDetail; locked: boolean; onChange: (field: string, value: string, category: string | null) => void }) {
  const [all, setAll] = useState(false);
  const unclassified = d.status_values.filter((v) => !v.category);
  const rows = all ? d.status_values : unclassified;
  return (
    <div className="mb-4 max-w-3xl rounded-md border border-slate-200 p-3">
      <h3 className="mb-1 text-sm font-semibold text-blue-950">Status values ({unclassified.length} unclassified of {d.status_values.length})</h3>
      <p className="mb-2 text-xs text-slate-600">Decide what each status wording means so delays and completion are counted correctly. Wording the tool cannot place is never guessed; it stays unclassified (and is not counted as done) until you choose. Your choices are saved with the mapping template.</p>
      <label className="mb-2 block text-xs text-slate-600"><input type="checkbox" checked={all} onChange={(e) => setAll(e.target.checked)} /> show values that are already classified</label>
      {rows.length === 0 ? <p className="text-xs text-green-700">Every status value is classified.</p> : (
        <table className="w-full text-left text-xs">
          <thead className="border-b border-slate-300 uppercase text-slate-500"><tr><th className="py-1 pr-2">Column</th><th className="pr-2">Value in the file</th><th className="pr-2">Rows</th><th>Counts as</th></tr></thead>
          <tbody>
            {rows.map((v) => (
              <tr key={v.field + v.value} className="border-b border-slate-100">
                <td className="py-1 pr-2 text-slate-500">{v.header}</td><td className="pr-2 font-medium">{v.value}</td><td className="pr-2">{v.count}</td>
                <td><Select disabled={locked} value={v.category ?? ""} onChange={(e) => onChange(v.field, v.value, e.target.value || null)}>
                  <option value="">— unclassified —</option>{CATEGORIES.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</Select></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
