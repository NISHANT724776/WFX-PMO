"use client";

import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { Badge, Button, Empty, ErrorBox, Input, Label, PageHeader, Pager, Select, Loading } from "@/components/ui";
import { api, qs, type Page, type Row } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { MASTER, type FieldDef } from "@/lib/masterConfig";

const SIZE = 20;

export default function MasterPage() {
  const { entity } = useParams<{ entity: string }>();
  const def = MASTER[entity];
  const { can } = useAuth();
  const canWrite = can("master:write");

  const [data, setData] = useState<Page<Row> | null>(null);
  const [page, setPage] = useState(1);
  const [q, setQ] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState<Row | "new" | null>(null);
  const [refs, setRefs] = useState<Record<string, Row[]>>({});

  const load = useCallback(async () => {
    if (!def) return;
    setLoading(true);
    setError(null);
    try {
      setData(await api<Page<Row>>(`${def.path}${qs({ page, size: SIZE, q })}`));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }, [def, page, q]);

  useEffect(() => { setPage(1); setEditing(null); }, [entity]);
  useEffect(() => { void load(); }, [load]);

  useEffect(() => {
    if (!def) return;
    def.fields.filter((f) => f.type === "ref").forEach((f) =>
      api<Page<Row>>(`${f.refPath}?size=200`).then((p) => setRefs((r) => ({ ...r, [f.key]: p.items }))).catch(() => {}),
    );
  }, [def]);

  if (!def) return <Empty>Unknown master data type.</Empty>;

  const refName = (f: string, id: unknown) => {
    const field = def.fields.find((x) => x.key === f)!;
    const row = refs[f]?.find((r) => r.id === id);
    return row ? String(row[field.refLabel ?? "name"]) : id ? String(id) : "";
  };

  async function remove(row: Row) {
    if (!confirm("Delete this record? If other records use it, deactivate it instead.")) return;
    try {
      await api(`${def.path}/${row.id}`, { method: "DELETE" });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Delete failed");
    }
  }

  return (
    <>
      <PageHeader
        title={def.title}
        actions={canWrite && <Button onClick={() => setEditing("new")}>New</Button>}
      />
      <ErrorBox message={error} />
      {editing && (
        <RecordForm
          def={def}
          row={editing === "new" ? null : editing}
          refs={refs}
          onCancel={() => setEditing(null)}
          onSaved={async () => { setEditing(null); await load(); }}
        />
      )}
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-slate-200 bg-slate-50/70 p-3">
        <div className="w-full max-w-xs"><Input placeholder="Search…" value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} /></div>
        {data && <span className="rounded-full bg-white px-3 py-1 text-xs text-slate-600 ring-1 ring-slate-200">{data.total} record{data.total === 1 ? "" : "s"}</span>}
      </div>
      {loading && !data ? (
        <Loading />
      ) : !data || data.items.length === 0 ? (
        <Empty>No records{q ? " match your search" : " yet"}.</Empty>
      ) : (
        <>
          <div className="overflow-x-auto rounded-xl border border-slate-200">
          <table className="w-full text-left text-sm [&_td]:border-r [&_td]:border-slate-100 [&_td:last-child]:border-r-0 [&_th]:border-r [&_th]:border-slate-200/70 [&_th:last-child]:border-r-0">
            <thead className="border-b border-slate-200 text-xs uppercase text-slate-500">
              <tr>
                {def.columns.map((c) => <th key={c} className="px-3 py-2.5">{c.replace(/_/g, " ")}</th>)}
                {canWrite && <th />}
              </tr>
            </thead>
            <tbody>
              {data.items.map((r) => (
                <tr key={r.id} className="border-b border-slate-100 even:bg-slate-50/40">
                  {def.columns.map((c) => (
                    <td key={c} className="px-3 py-2">
                      {c === "is_active" ? (
                        <Badge tone={r[c] ? "green" : "slate"}>{r[c] ? "Active" : "Inactive"}</Badge>
                      ) : c === "color" ? (
                        r[c] ? <span className="inline-flex items-center gap-2"><span className="h-4 w-4 rounded-full ring-1 ring-black/10" style={{ background: String(r[c]) }} />{String(r[c])}</span> : <span className="text-slate-400">default</span>
                      ) : c === "category" ? (
                        <Badge tone={r[c] === "done" ? "green" : r[c] === "in_progress" ? "amber" : r[c] === "blocked" ? "red" : "slate"}>{String(r[c]).replace(/_/g, " ")}</Badge>
                      ) : c === "code" ? (
                        <span className="font-mono text-xs font-semibold text-blue-950">{String(r[c])}</span>
                      ) : c === "entity_type" ? (
                        <span className="rounded-md bg-slate-100 px-1.5 py-0.5 text-xs text-slate-700">{String(r[c]).replace(/_/g, " ")}</span>
                      ) : c.endsWith("_id") ? refName(c, r[c]) : String(r[c] ?? "")}
                    </td>
                  ))}
                  {canWrite && (
                    <td className="space-x-2 whitespace-nowrap px-3 text-right">
                      <Button variant="ghost" onClick={() => setEditing(r)}>Edit</Button>
                      <Button variant="danger" onClick={() => remove(r)}>Delete</Button>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
          </div>
          <Pager page={page} size={SIZE} total={data.total} onPage={setPage} />
        </>
      )}
    </>
  );
}

function RecordForm({
  def, row, refs, onCancel, onSaved,
}: {
  def: (typeof MASTER)[string];
  row: Row | null;
  refs: Record<string, Row[]>;
  onCancel: () => void;
  onSaved: () => void | Promise<void>;
}) {
  const [vals, setVals] = useState<Record<string, unknown>>(() => {
    const init: Record<string, unknown> = {};
    def.fields.forEach((f) => (init[f.key] = row ? row[f.key] : f.type === "checkbox" ? true : f.type === "number" ? 0 : ""));
    return init;
  });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const body: Record<string, unknown> = {};
    for (const f of def.fields) {
      const v = vals[f.key];
      body[f.key] = f.type === "number" ? Number(v) : v === "" ? null : v;
    }
    try {
      await api(row ? `${def.path}/${row.id}` : def.path, { method: row ? "PATCH" : "POST", body });
      await onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setBusy(false);
    }
  }

  const input = (f: FieldDef) => {
    const v = vals[f.key];
    const set = (x: unknown) => setVals((s) => ({ ...s, [f.key]: x }));
    if (f.type === "checkbox")
      return <input type="checkbox" checked={!!v} onChange={(e) => set(e.target.checked)} className="h-4 w-4" />;
    if (f.type === "select" || f.type === "ref") {
      const opts = f.type === "select" ? f.options!.map((o) => ({ id: o, name: o })) : (refs[f.key] ?? []).map((r) => ({ id: String(r.id), name: String(r[f.refLabel ?? "name"]) }));
      return (
        <Select required={f.required} value={String(v ?? "")} onChange={(e) => set(e.target.value)}>
          <option value="">{f.required ? "Select…" : "—"}</option>
          {opts.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
        </Select>
      );
    }
    if (f.type === "color")
      return (
        <div className="flex items-center gap-2">
          <input type="color" value={/^#[0-9a-fA-F]{6}$/.test(String(v ?? "")) ? String(v) : "#94a3b8"} onChange={(e) => set(e.target.value)} className="h-9 w-14 cursor-pointer rounded-md border border-slate-300 bg-white p-0.5" />
          <span className="text-xs text-slate-500">{v ? String(v) : "default colour"}</span>
          {!!v && <button type="button" className="text-xs text-blue-900 underline" onClick={() => set("")}>use default</button>}
        </div>
      );
    return (
      <Input
        type={f.type === "email" ? "email" : f.type === "number" ? "number" : "text"}
        required={f.required}
        value={String(v ?? "")}
        onChange={(e) => set(e.target.value)}
      />
    );
  };

  return (
    <form onSubmit={submit} className="mb-4 max-w-2xl rounded-md border border-slate-200 bg-slate-50 p-4">
      <h2 className="mb-3 text-sm font-semibold text-blue-950">{row ? "Edit" : "New"} {def.title.toLowerCase()}</h2>
      <ErrorBox message={error} />
      <div className="grid grid-cols-2 gap-3">
        {def.fields.map((f) => <Label key={f.key} text={f.label + (f.required ? " *" : "")}>{input(f)}</Label>)}
      </div>
      <div className="mt-4 flex gap-2">
        <Button type="submit" disabled={busy}>{busy ? "Saving…" : "Save"}</Button>
        <Button type="button" variant="ghost" onClick={onCancel}>Cancel</Button>
      </div>
    </form>
  );
}
