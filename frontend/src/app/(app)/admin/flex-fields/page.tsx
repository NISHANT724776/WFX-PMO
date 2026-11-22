"use client";

import { useCallback, useEffect, useState } from "react";
import { ConfirmDialog } from "@/components/manage/Workspace";
import { Badge, Button, ErrorBox, Input, Label, PageHeader, Select } from "@/components/ui";
import { api, type Page, type Row } from "@/lib/api";
import { useAuth } from "@/lib/auth";

type Def = { id: string; customer_id: string | null; entity_type: string; field_type: "dropdown" | "date" | "text"; slot: number; label: string; options: string[] | null; is_required: boolean };
const TYPES: { key: Def["field_type"]; label: string }[] = [{ key: "dropdown", label: "Drop-down lists" }, { key: "date", label: "Date fields" }, { key: "text", label: "Text fields" }];

/** Define the extra fields (up to 5 drop-downs, 5 dates and 5 text) a record type carries, for every customer or for one customer. */
export default function FlexFieldsPage() {
  const { can } = useAuth();
  const canWrite = can("custom_fields:write");
  const [entities, setEntities] = useState<{ value: string; label: string }[]>([]);
  const [customers, setCustomers] = useState<Row[]>([]);
  const [entity, setEntity] = useState("work_item");
  const [customer, setCustomer] = useState("");
  const [defs, setDefs] = useState<Def[]>([]);
  const [edit, setEdit] = useState<{ type: Def["field_type"]; slot: number; def?: Def } | null>(null);
  const [del, setDel] = useState<Def | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    api<{ value: string; label: string }[]>("/custom-fields/entities").then(setEntities).catch((e) => setError(e instanceof Error ? e.message : "Failed to load"));
    api<Page<Row>>("/customers?size=200").then((p) => setCustomers(p.items)).catch(() => {});
  }, []);
  const load = useCallback(async () => {
    try { setError(null); setDefs(await api<Def[]>(`/custom-fields?entity_type=${entity}`)); } catch (e) { setError(e instanceof Error ? e.message : "Failed to load"); }
  }, [entity]);
  useEffect(() => { void load(); }, [load]);
  const scope = customer || null;
  const mine = defs.filter((d) => d.customer_id === scope);
  const slotOf = (t: Def["field_type"], n: number) => mine.find((d) => d.field_type === t && d.slot === n);

  return (
    <>
      <PageHeader title="Flex fields" subtitle="Extra fields on records: up to 5 drop-downs, 5 dates and 5 text fields per record type" />
      <ErrorBox message={error} />
      {notice && <div role="status" className="mb-3 rounded-md border border-green-200 bg-green-50 px-3 py-2 text-sm text-green-900">{notice} <button className="ml-2 underline" onClick={() => setNotice(null)}>dismiss</button></div>}
      <div className="mb-4 flex flex-wrap items-end gap-3 rounded-lg border border-slate-200 bg-slate-50/70 p-3">
        <Label text="Record type"><Select value={entity} onChange={(e) => setEntity(e.target.value)}>{entities.map((e) => <option key={e.value} value={e.value}>{e.label}</option>)}</Select></Label>
        <Label text="Applies to"><Select value={customer} onChange={(e) => setCustomer(e.target.value)}><option value="">Every customer</option>{customers.map((c) => <option key={String(c.id)} value={String(c.id)}>{String(c.name)} only</option>)}</Select></Label>
        <p className="max-w-xl pb-1 text-xs text-slate-500">A field for every customer shows on every project&apos;s records of this type; a customer&apos;s own fields are added to them. The fields appear in the record&apos;s side panel, under Custom fields.</p>
      </div>
      {!canWrite && <p className="mb-3 text-sm text-amber-700">You can see the fields but not change them.</p>}
      <div className="grid gap-6 lg:grid-cols-3">
        {TYPES.map((t) => (
          <section key={t.key}>
            <h3 className="mb-1 text-sm font-semibold text-blue-950">{t.label}</h3>
            <ul className="divide-y divide-slate-200 rounded-md border border-slate-200">
              {[1, 2, 3, 4, 5].map((n) => {
                const d = slotOf(t.key, n);
                return (
                  <li key={n} className="flex items-center justify-between gap-2 px-3 py-2 text-sm">
                    <div className="min-w-0">
                      <span className="mr-2 text-xs text-slate-400">{n}</span>
                      {d ? <><b>{d.label}</b>{d.is_required && <Badge tone="amber">required</Badge>}{d.options && <div className="truncate text-[11px] text-slate-500" title={d.options.join(", ")}>{d.options.join(" · ")}</div>}</> : <span className="text-slate-400">not used</span>}
                    </div>
                    {canWrite && (d ? <div className="flex shrink-0 gap-1"><Button variant="ghost" onClick={() => setEdit({ type: t.key, slot: n, def: d })}>Edit</Button><Button variant="danger" onClick={() => setDel(d)}>Remove</Button></div>
                      : <Button variant="ghost" onClick={() => setEdit({ type: t.key, slot: n })}>Define</Button>)}
                  </li>
                );
              })}
            </ul>
          </section>
        ))}
      </div>
      {!scope && defs.some((d) => d.customer_id) && <p className="mt-3 text-xs text-slate-500">{defs.filter((d) => d.customer_id).length} field(s) for individual customers also exist for this record type; choose the customer above to see them.</p>}
      {edit && <EditDialog type={edit.type} slot={edit.slot} def={edit.def} entity={entity} customerId={scope} onClose={() => setEdit(null)} onSaved={async (msg) => { setEdit(null); setNotice(msg); await load(); }} />}
      {del && (
        <ConfirmDialog title="Remove this field?" confirmLabel="Remove field" danger onCancel={() => setDel(null)}
          onConfirm={async () => { await api(`/custom-fields/${del.id}`, { method: "DELETE" }); setDel(null); setNotice(`“${del.label}” removed.`); await load(); }}>
          “{del.label}” is taken off every record, <b>and the values people entered in it are deleted</b>. This cannot be undone.
        </ConfirmDialog>
      )}
    </>
  );
}

function EditDialog({ type, slot, def, entity, customerId, onClose, onSaved }: { type: Def["field_type"]; slot: number; def?: Def; entity: string; customerId: string | null; onClose: () => void; onSaved: (msg: string) => Promise<void> }) {
  const [label, setLabel] = useState(def?.label ?? "");
  const [options, setOptions] = useState((def?.options ?? []).join("\n"));
  const [required, setRequired] = useState(def?.is_required ?? false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const opts = options.split("\n").map((o) => o.trim()).filter(Boolean);
  async function save() {
    setBusy(true); setError(null);
    try {
      if (def) await api(`/custom-fields/${def.id}`, { method: "PATCH", body: { label: label.trim(), is_required: required, ...(type === "dropdown" ? { options: opts } : {}) } });
      else await api("/custom-fields", { method: "POST", body: { customer_id: customerId, entity_type: entity, field_type: type, slot, label: label.trim(), is_required: required, ...(type === "dropdown" ? { options: opts } : {}) } });
      await onSaved(`“${label.trim()}” saved.`);
    } catch (e) { setError(e instanceof Error ? e.message : "Could not save"); setBusy(false); }
  }
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" role="dialog" aria-modal="true" aria-label="Define a field" onClick={onClose}>
      <div className="w-full max-w-md rounded-md bg-white p-5 shadow-xl" onClick={(e) => e.stopPropagation()}>
        <h3 className="mb-3 text-base font-semibold text-blue-950">{def ? "Edit" : "Define"} {type === "dropdown" ? "drop-down" : type} field {slot}</h3>
        <ErrorBox message={error} />
        <div className="space-y-3">
          <Label text="Label (what people see) *"><Input autoFocus value={label} onChange={(e) => setLabel(e.target.value)} maxLength={100} /></Label>
          {type === "dropdown" && <Label text="Choices, one per line *"><textarea className="w-full rounded-md border border-slate-300 px-2.5 py-1.5 text-sm" rows={5} value={options} onChange={(e) => setOptions(e.target.value)} /></Label>}
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={required} onChange={(e) => setRequired(e.target.checked)} /> Required (the record cannot be saved with it empty)</label>
          {def && <p className="text-xs text-slate-500">The kind of field and its position cannot be changed after it is created; remove it and define a new one to change them.</p>}
        </div>
        <div className="mt-4 flex justify-end gap-2"><Button variant="ghost" onClick={onClose}>Cancel</Button><Button onClick={save} disabled={busy || !label.trim() || (type === "dropdown" && opts.length === 0)}>{busy ? "Saving…" : "Save"}</Button></div>
      </div>
    </div>
  );
}
