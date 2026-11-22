"use client";

import { useCallback, useEffect, useState } from "react";
import { Empty, ErrorBox, Input, PageHeader, Pager, Loading } from "@/components/ui";
import { api, qs, type Page } from "@/lib/api";

type Entry = { id: string; at: string; user_email: string | null; action: string; entity_type: string; entity_id: string | null; before: object | null; after: object | null };
const SIZE = 25;

export default function AuditPage() {
  const [data, setData] = useState<Page<Entry> | null>(null);
  const [page, setPage] = useState(1);
  const [entity, setEntity] = useState("");
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try { setError(null); setData(await api<Page<Entry>>(`/audit-logs${qs({ page, size: SIZE, entity_type: entity })}`)); }
    catch (e) { setError(e instanceof Error ? e.message : "Failed to load"); }
  }, [page, entity]);

  useEffect(() => { void load(); }, [load]);

  return (
    <>
      <PageHeader title="Audit Log" subtitle="Every create, update, delete and login event" />
      <ErrorBox message={error} />
      <div className="mb-3 max-w-xs"><Input placeholder="Filter by entity type (e.g. customer)" value={entity} onChange={(e) => { setEntity(e.target.value); setPage(1); }} /></div>
      {!data ? <Loading /> : data.items.length === 0 ? <Empty>No audit events.</Empty> : (
        <>
          <table className="w-full text-left text-sm">
            <thead className="border-b border-slate-300 text-xs uppercase text-slate-500"><tr><th className="py-2 pr-4">When</th><th className="pr-4">User</th><th className="pr-4">Action</th><th className="pr-4">Entity</th><th>Change</th></tr></thead>
            <tbody>
              {data.items.map((a) => (
                <tr key={a.id} className="border-b border-slate-100 align-top">
                  <td className="py-1.5 pr-4 whitespace-nowrap">{new Date(a.at).toLocaleString()}</td>
                  <td className="pr-4">{a.user_email ?? "—"}</td>
                  <td className="pr-4">{a.action}</td>
                  <td className="pr-4">{a.entity_type}</td>
                  <td>
                    {(a.before || a.after) && (
                      <details><summary className="cursor-pointer text-blue-900">view</summary>
                        <pre className="mt-1 max-w-xl overflow-auto rounded-md bg-slate-50 p-2 text-xs">{JSON.stringify({ before: a.before, after: a.after }, null, 2)}</pre>
                      </details>
                    )}
                  </td>
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
