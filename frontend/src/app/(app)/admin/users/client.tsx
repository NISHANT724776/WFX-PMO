"use client";

import { useCallback, useEffect, useState } from "react";
import { Badge, Button, Empty, ErrorBox, Input, Label, PageHeader, Pager, Select, Loading } from "@/components/ui";
import { api, qs, type Page } from "@/lib/api";
import { useAuth } from "@/lib/auth";

type Role = { id: string; code: string; name: string };
type User = { id: string; email: string; full_name: string; is_active: boolean; role: Role };
const SIZE = 20;

export default function UsersPage() {
  const { can, me } = useAuth();
  const canWrite = can("users:write");
  const [data, setData] = useState<Page<User> | null>(null);
  const [roles, setRoles] = useState<Role[]>([]);
  const [page, setPage] = useState(1);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  const load = useCallback(async () => {
    try { setError(null); setData(await api<Page<User>>(`/users${qs({ page, size: SIZE })}`)); }
    catch (e) { setError(e instanceof Error ? e.message : "Failed to load"); }
  }, [page]);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => { api<Role[]>("/users/roles").then(setRoles).catch(() => {}); }, []);

  async function patch(u: User, body: object) {
    try { setError(null); await api(`/users/${u.id}`, { method: "PATCH", body }); await load(); }
    catch (e) { setError(e instanceof Error ? e.message : "Update failed"); }
  }

  return (
    <>
      <PageHeader title="Users" actions={canWrite && <Button onClick={() => setCreating(true)}>New user</Button>} />
      <ErrorBox message={error} />
      {creating && <NewUser roles={roles} onCancel={() => setCreating(false)} onCreated={async () => { setCreating(false); await load(); }} />}
      {!data ? <Loading /> : data.items.length === 0 ? <Empty>No users.</Empty> : (
        <>
          <table className="w-full text-left text-sm">
            <thead className="border-b border-slate-300 text-xs uppercase text-slate-500"><tr><th className="py-2 pr-4">Email</th><th className="pr-4">Name</th><th className="pr-4">Role</th><th className="pr-4">Status</th><th /></tr></thead>
            <tbody>
              {data.items.map((u) => (
                <tr key={u.id} className="border-b border-slate-100">
                  <td className="py-1.5 pr-4">{u.email}</td>
                  <td className="pr-4">{u.full_name}</td>
                  <td className="pr-4">
                    {canWrite && u.id !== me?.id ? (
                      <Select value={u.role.code} onChange={(e) => patch(u, { role_code: e.target.value })}>{roles.map((r) => <option key={r.id} value={r.code}>{r.name}</option>)}</Select>
                    ) : u.role.name}
                  </td>
                  <td className="pr-4"><Badge tone={u.is_active ? "green" : "slate"}>{u.is_active ? "Active" : "Inactive"}</Badge></td>
                  <td className="text-right">{canWrite && u.id !== me?.id && <Button variant="ghost" onClick={() => patch(u, { is_active: !u.is_active })}>{u.is_active ? "Deactivate" : "Activate"}</Button>}</td>
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

function NewUser({ roles, onCancel, onCreated }: { roles: Role[]; onCancel: () => void; onCreated: () => void | Promise<void> }) {
  const [v, setV] = useState({ email: "", full_name: "", password: "", role_code: "" });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (k: string) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setV((s) => ({ ...s, [k]: e.target.value }));

  async function submit(e: React.FormEvent) {
    e.preventDefault(); setBusy(true); setError(null);
    try { await api("/users", { method: "POST", body: v }); await onCreated(); }
    catch (err) { setError(err instanceof Error ? err.message : "Create failed"); }
    finally { setBusy(false); }
  }

  return (
    <form onSubmit={submit} className="mb-4 max-w-2xl rounded-md border border-slate-200 bg-slate-50 p-4">
      <ErrorBox message={error} />
      <div className="grid grid-cols-2 gap-3">
        <Label text="Email *"><Input type="email" required value={v.email} onChange={set("email")} /></Label>
        <Label text="Full name *"><Input required value={v.full_name} onChange={set("full_name")} /></Label>
        <Label text="Password * (min 10 characters)"><Input type="password" required minLength={10} autoComplete="new-password" value={v.password} onChange={set("password")} /></Label>
        <Label text="Role *"><Select required value={v.role_code} onChange={set("role_code")}><option value="">Select…</option>{roles.map((r) => <option key={r.id} value={r.code}>{r.name}</option>)}</Select></Label>
      </div>
      <div className="mt-4 flex gap-2"><Button type="submit" disabled={busy}>{busy ? "Creating…" : "Create"}</Button><Button type="button" variant="ghost" onClick={onCancel}>Cancel</Button></div>
    </form>
  );
}
