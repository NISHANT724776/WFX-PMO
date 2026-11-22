"use client";

import { useCallback, useEffect, useState } from "react";
import { Badge, Empty, ErrorBox, Input, Label, Pager, Select, Loading } from "@/components/ui";
import { api, qs } from "@/lib/api";
import { STATE_COLOR, type RowState } from "@/lib/dash";
import { fmt } from "@/lib/plan";

type Act = {
  id: string; type: "task" | "event"; title: string; is_milestone: boolean; phase: string | null; product: string | null; owner: string | null; responsible: string | null;
  original_finish: string | null; revised_finish: string | null; current_finish: string | null; actual_finish: string | null; days_late: number; slippage_days: number;
  status: string | null; is_overdue: boolean; is_closed: boolean; editable: boolean;
};
type PhaseRow = { label: string; area: string; state: RowState; pct: number; start: string | null; end: string | null; items: number; done: number; late_items: number };
type Resp<T> = { metric: string; label: string; rule: string; total: number; unfiltered_total?: number; page: number; size: number; as_of: string; grace_days?: number; items: T[] };
const SIZE = 25;
const SORTS = [["days_late", "Delay"], ["current", "Current date"], ["original", "Original date"], ["title", "Activity"], ["owner", "Owner"], ["phase", "Phase"]] as const;

/** The records behind a KPI tile. Server-side filter, sort and paging: the browser only ever holds one page. */
export default function Drilldown({ projectId, metric, asOf, productId, refreshKey = 0, onClose, onItem }: {
  refreshKey?: number; projectId: string; metric: string; asOf: string; productId?: string; onClose: () => void; onItem: (id: string) => void;
}) {
  const [data, setData] = useState<Resp<Act | PhaseRow> | null>(null);
  const [q, setQ] = useState("");
  const [owner, setOwner] = useState("");
  const [sort, setSort] = useState<string>("days_late");
  const [direction, setDirection] = useState("desc");
  const [page, setPage] = useState(1);
  const [error, setError] = useState<string | null>(null);
  const phases = metric === "phases";

  const load = useCallback(async () => {
    try {
      setError(null);
      setData(await api<Resp<Act | PhaseRow>>(`/projects/${projectId}/dashboards/drilldown/${metric}${qs({ as_of: asOf, product_id: productId, q, owner, sort, direction, page, size: SIZE })}`));
    } catch (e) { setError(e instanceof Error ? e.message : "Failed to load"); }
  }, [projectId, metric, asOf, productId, q, owner, sort, direction, page]);
  useEffect(() => { void load(); }, [load, refreshKey]); // refreshKey: the dashboard says a record was edited

  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-black/30 print:hidden" onClick={onClose} onKeyDown={(e) => { if (e.key === "Escape") onClose(); }}>
      <aside className="h-full w-full max-w-5xl overflow-y-auto bg-white p-5 shadow-xl" role="dialog" aria-label={data?.label ?? "Records"} onClick={(e) => e.stopPropagation()}>
        <div className="mb-1 flex items-start justify-between">
          <h2 className="text-base font-semibold text-blue-950">{data?.label ?? "Records"} <span className="font-normal text-slate-500">· {data ? data.total : "…"}{data && !phases && data.unfiltered_total !== undefined && data.unfiltered_total !== data.total ? ` of ${data.unfiltered_total}` : ""}</span></h2>
          <button className="text-slate-500 hover:text-slate-900" onClick={onClose} aria-label="Close">✕</button>
        </div>
        {data && <p className="mb-3 text-xs text-slate-500">Counted as: {data.rule}. Report date {fmt(data.as_of)}{data.grace_days ? ` · grace ${data.grace_days} day(s)` : ""}. The number on the tile and this list use the same rule.</p>}
        <ErrorBox message={error} />
        {!phases && (
          <div className="mb-4 flex flex-wrap items-end gap-3 rounded-lg border border-slate-200 bg-slate-50/70 p-3">
            <Label text="Search activity"><Input value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} placeholder="Title…" /></Label>
            <Label text="Owner / responsible"><Input value={owner} onChange={(e) => { setOwner(e.target.value); setPage(1); }} placeholder="Name…" /></Label>
            <Label text="Sort by"><Select value={sort} onChange={(e) => { setSort(e.target.value); setPage(1); }}>{SORTS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</Select></Label>
            <Label text="Order"><Select value={direction} onChange={(e) => { setDirection(e.target.value); setPage(1); }}><option value="desc">Highest / latest first</option><option value="asc">Lowest / earliest first</option></Select></Label>
          </div>
        )}
        {!data ? <Loading /> : data.items.length === 0 ? <Empty>Nothing matches. {q || owner ? "Clear the search to see all." : "No records are counted in this tile."}</Empty> : phases ? (
          <table className="w-full text-left text-xs">
            <thead className="border-b border-slate-300 uppercase text-slate-500"><tr><th className="py-2">Phase</th><th>Area</th><th>State</th><th>Done</th><th>Items</th><th>Late items</th><th>Start</th><th>End</th></tr></thead>
            <tbody>{(data.items as PhaseRow[]).map((r, i) => (
              <tr key={i} className="border-b border-slate-100"><td className="py-1 pr-3">{r.label}</td><td>{r.area}</td><td><span className="font-medium" style={{ color: STATE_COLOR[r.state] }}>{r.state.replace("_", " ")}</span></td><td>{r.pct}%</td><td>{r.done}/{r.items}</td><td>{r.late_items || ""}</td><td>{fmt(r.start)}</td><td>{fmt(r.end)}</td></tr>
            ))}</tbody>
          </table>
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className="border-b border-slate-300 uppercase text-slate-500"><tr>{["Activity", "Phase", "Product", "Owner", "Original", "Revised", "Current", "Delay", "Status"].map((h) => <th key={h} className="py-2 pr-3">{h}</th>)}</tr></thead>
                <tbody>
                  {(data.items as Act[]).map((r) => (
                    <tr key={`${r.type}-${r.id}`} onClick={r.editable ? () => onItem(r.id) : undefined} title={r.editable ? "Open to edit" : "Tracker milestone from the import (read-only here)"}
                      className={`border-b border-slate-100 align-top ${r.editable ? "cursor-pointer hover:bg-blue-50" : "text-slate-600"}`}>
                      <td className="max-w-72 py-1 pr-3">{r.is_milestone && <span className="mr-1 text-blue-950">★</span>}{r.title}{!r.editable && <span className="ml-1 text-[10px] text-slate-400">tracker</span>}</td>
                      <td className="max-w-40 truncate pr-2">{r.phase ?? ""}</td><td className="pr-2">{r.product ?? ""}</td>
                      <td className="max-w-36 truncate pr-2" title={`${r.owner ?? ""} ${r.responsible ?? ""}`}>{r.owner || r.responsible || <span className="text-slate-400">unassigned</span>}</td>
                      <td className="whitespace-nowrap pr-2">{fmt(r.original_finish)}</td>
                      <td className="whitespace-nowrap pr-2">{r.revised_finish ? fmt(r.revised_finish) : <span className="text-slate-400">–</span>}</td>
                      <td className="whitespace-nowrap pr-2">{fmt(r.current_finish)}</td>
                      <td className="whitespace-nowrap pr-2">{r.is_overdue ? <Badge tone="red">{r.days_late} d late</Badge> : r.slippage_days > 0 ? <span className="text-amber-700">+{r.slippage_days} d vs original</span> : ""}</td>
                      <td>{r.status ?? ""}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pager page={page} size={SIZE} total={data.total} onPage={setPage} />
          </>
        )}
      </aside>
    </div>
  );
}
