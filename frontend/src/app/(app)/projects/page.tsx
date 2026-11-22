"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { Button, Empty, ErrorBox, Input, Label, PageHeader, Pager, Select, Loading } from "@/components/ui";
import { api, qs, type Page, type Row } from "@/lib/api";
import { useAuth } from "@/lib/auth";

const SIZE = 20;

export default function ProjectsPage() {
  const { can } = useAuth();
  const [data, setData] = useState<Page<Row> | null>(null);
  const [customers, setCustomers] = useState<Row[]>([]);
  const [page, setPage] = useState(1);
  const [q, setQ] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  const load = useCallback(async () => {
    try {
      setError(null);
      setData(await api<Page<Row>>(`/projects${qs({ page, size: SIZE, q })}`));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    }
  }, [page, q]);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    if (can("master:read")) api<Page<Row>>("/customers?size=200").then((p) => setCustomers(p.items)).catch(() => {});
  }, [can]);

  const cname = (id: unknown) => String(customers.find((c) => c.id === id)?.name ?? "");

  return (
    <>
      <PageHeader title="Projects" actions={can("projects:create") && <Button onClick={() => setCreating(true)}>New project</Button>} />
      <ErrorBox message={error} />
      {creating && <NewProject customers={customers} onCancel={() => setCreating(false)} onCreated={async () => { setCreating(false); await load(); }} />}
      <div className="mb-3 max-w-xs">
        <Input placeholder="Search code or name…" value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} />
      </div>
      {!data ? <Loading /> : data.items.length === 0 ? (
        <Empty>No projects{q ? " match your search" : " yet, or none assigned to you"}.</Empty>
      ) : (
        <>
          <table className="w-full text-left text-sm">
            <thead className="border-b border-slate-300 text-xs uppercase text-slate-500">
              <tr><th className="py-2 pr-4">Code</th><th className="pr-4">Name</th><th className="pr-4">Customer</th><th className="pr-4">Status</th><th className="pr-4">Start</th><th>Go-live</th></tr>
            </thead>
            <tbody>
              {data.items.map((p) => (
                <tr key={p.id} className="border-b border-slate-100">
                  <td className="py-1.5 pr-4"><Link className="text-blue-900 underline" href={`/projects/${p.id}`}>{String(p.code)}</Link></td>
                  <td className="pr-4">{String(p.name)}</td>
                  <td className="pr-4">{cname(p.customer_id)}</td>
                  <td className="pr-4">{String(p.status)}</td>
                  <td className="pr-4">{String(p.start_date ?? "")}</td>
                  <td>{String(p.target_go_live ?? "")}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <Pager page={page} size={SIZE} total={data.total} onPage={setPage} />
        </>
      )}
    </>
  );
}

function NewProject({ customers, onCancel, onCreated }: { customers: Row[]; onCancel: () => void; onCreated: () => void | Promise<void> }) {
  const [v, setV] = useState({ customer_id: "", code: "", name: "", start_date: "", target_go_live: "" });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (k: string) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setV((s) => ({ ...s, [k]: e.target.value }));

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api("/projects", { method: "POST", body: { ...v, start_date: v.start_date || null, target_go_live: v.target_go_live || null } });
      await onCreated();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Create failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="mb-4 max-w-2xl rounded-md border border-slate-200 bg-slate-50 p-4">
      <ErrorBox message={error} />
      <div className="grid grid-cols-2 gap-3">
        <Label text="Customer *"><Select required value={v.customer_id} onChange={set("customer_id")}><option value="">Select…</option>{customers.map((c) => <option key={c.id} value={c.id}>{String(c.name)}</option>)}</Select></Label>
        <Label text="Code *"><Input required value={v.code} onChange={set("code")} /></Label>
        <Label text="Name *"><Input required value={v.name} onChange={set("name")} /></Label>
        <span />
        <Label text="Start date"><Input type="date" value={v.start_date} onChange={set("start_date")} /></Label>
        <Label text="Target go-live"><Input type="date" value={v.target_go_live} onChange={set("target_go_live")} /></Label>
      </div>
      <div className="mt-4 flex gap-2">
        <Button type="submit" disabled={busy}>{busy ? "Creating…" : "Create"}</Button>
        <Button type="button" variant="ghost" onClick={onCancel}>Cancel</Button>
      </div>
    </form>
  );
}
