"use client";

import { useCallback, useEffect, useState } from "react";
import { Empty, ErrorBox, Input, Pager, Select, Loading } from "@/components/ui";
import { api, qs, type Page, type Row } from "@/lib/api";
import { fmt } from "@/lib/plan";

const KINDS = [
  { key: "tracker-events", label: "Milestone events by product" },
  { key: "approval-gates", label: "Sign-off gates" },
  { key: "gap-specifications", label: "Gap / specification tracker" },
] as const;

const COLS: Record<string, { k: string; label: string; date?: boolean }[]> = {
  "tracker-events": [{ k: "product", label: "Product" }, { k: "event_name", label: "Event" }, { k: "responsibility", label: "Responsibility" }, { k: "spoc", label: "SPOC" }, { k: "planned_date", label: "Planned", date: true }, { k: "actual_date", label: "Actual", date: true }],
  "approval-gates": [{ k: "gate_type", label: "Gate set" }, { k: "name", label: "Department / gate" }, { k: "planned_date", label: "Target", date: true }, { k: "submission_date", label: "Submitted", date: true }, { k: "signoff_date", label: "Signed off", date: true }, { k: "approval_status", label: "Status" }, { k: "comments", label: "Comments" }],
  "gap-specifications": [{ k: "external_issue_id", label: "Issue ID" }, { k: "module", label: "Module" }, { k: "description", label: "Description" }, { k: "priority", label: "Priority" }, { k: "spec_status", label: "Spec status" }, { k: "responsibility", label: "Responsibility" }, { k: "target_date", label: "Target", date: true }, { k: "approval_status", label: "Approval" }],
};

export default function TrackersTab({ projectId, products }: { projectId: string; products: Row[] }) {
  const [kind, setKind] = useState<string>(KINDS[0].key);
  const [page, setPage] = useState(1);
  const [q, setQ] = useState("");
  const [productId, setProductId] = useState("");
  const [data, setData] = useState<Page<Row> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const size = 50;

  const load = useCallback(async () => {
    try {
      setError(null);
      setData(await api<Page<Row>>(`/projects/${projectId}/${kind}${qs({ page, size, q: kind === "gap-specifications" ? q : undefined, product_id: kind === "tracker-events" ? productId : undefined })}`));
    } catch (e) { setError(e instanceof Error ? e.message : "Failed to load"); }
  }, [projectId, kind, page, q, productId]);
  useEffect(() => { void load(); }, [load]);
  const pname = (id: unknown) => String(products.find((p) => p.id === id)?.code ?? "");

  return (
    <>
      <ErrorBox message={error} />
      <div className="mb-4 flex flex-wrap items-end gap-3 rounded-lg border border-slate-200 bg-slate-50/70 p-3">
        <div className="inline-flex max-w-full overflow-x-auto rounded-lg bg-slate-100 p-0.5">{KINDS.map((k) => <button key={k.key} onClick={() => { setKind(k.key); setPage(1); }} className={`px-3 py-1 transition-colors duration-150 whitespace-nowrap text-sm ${kind === k.key ? "rounded-md bg-white font-medium text-blue-950 shadow-sm" : "rounded-md text-slate-600 hover:text-slate-900"}`}>{k.label}</button>)}</div>
        {kind === "tracker-events" && <Select className="max-w-40" value={productId} onChange={(e) => { setProductId(e.target.value); setPage(1); }}><option value="">All products</option>{products.map((p) => <option key={String(p.id)} value={String(p.id)}>{String(p.code)}</option>)}</Select>}
        {kind === "gap-specifications" && <Input className="max-w-xs" placeholder="Search description or module…" value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} />}
      </div>
      {!data ? <Loading /> : data.items.length === 0 ? <Empty>Nothing here yet. Records arrive through Smart Import.</Empty> : (
        <>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="border-b border-slate-300 uppercase text-slate-500"><tr>{COLS[kind].map((c) => <th key={c.k} className="py-2 pr-3">{c.label}</th>)}</tr></thead>
              <tbody>
                {data.items.map((r) => (
                  <tr key={String(r.id)} className="border-b border-slate-100 align-top">
                    {COLS[kind].map((c) => <td key={c.k} className="max-w-md py-1 pr-3">{c.k === "product" ? pname(r.product_id) : c.date ? fmt(r[c.k] as string | null) : String(r[c.k] ?? "")}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Pager page={page} size={size} total={data.total} onPage={setPage} />
        </>
      )}
    </>
  );
}
