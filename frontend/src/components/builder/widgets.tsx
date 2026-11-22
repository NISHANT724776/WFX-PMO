"use client";

import { useEffect, useMemo, useState } from "react";
import { GateRow, Kpi, PhaseTimeline } from "@/components/dash/parts";
import { api } from "@/lib/api";
import type { Gate } from "@/lib/dash";
import { fmt } from "@/lib/plan";

/* The renderers know the SHAPES a widget can return (see modules/dashboards/widgets.py), not the widget types:
   a new backend widget that returns one of these shapes is drawn with no front-end change. */
type D = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any

/** Loads a widget's data live from the database. Re-loads when its settings, the dashboard filters, the report date or `refreshKey` change. */
export function useWidgetData(projectId: string, type: string, config: Record<string, unknown>, filters: Record<string, unknown>, asOf: string, refreshKey: number) {
  const [state, setState] = useState<{ data: D | null; error: string | null; key: string }>({ data: null, error: null, key: "" });
  const key = JSON.stringify([type, config, filters, asOf, refreshKey]);
  useEffect(() => {
    let live = true;
    api<D>(`/projects/${projectId}/widgets/${type}/data`, { method: "POST", body: { config, filters, as_of: asOf } })
      .then((d) => live && setState({ data: d, error: null, key }))
      .catch((e) => live && setState({ data: null, error: e instanceof Error ? e.message : "Failed to load", key }));
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, key]);
  return state.key === key ? state : { data: null, error: null, key };
}

export function WidgetBody({ data, config, onDrill }: { data: D; config: Record<string, unknown>; onDrill: (metric: string, productId?: string) => void }) {
  switch (data.shape) {
    case "kpis": return <Kpis d={data} onDrill={onDrill} />;
    case "series": return <Series d={data} chart={String(config.chart_type ?? "bar")} />;
    case "table": return <Table d={data} />;
    case "timeline": return data.rows.length ? <PhaseTimeline rows={data.rows} asOf={data.as_of} labelWidth={200} /> : <Note>No phases match.</Note>;
    case "attention": return <Attention d={data} />;
    case "gates": return <Gates d={data} />;
    case "week": return <Week d={data} />;
    case "matrix": return <Matrix d={data} />;
    case "text": return data.size === "heading" ? <h3 className="text-lg font-semibold text-blue-950">{data.text}</h3> : <p className="whitespace-pre-wrap text-sm text-slate-700">{data.text}</p>;
    case "empty": return <Note>{data.message}</Note>;
    default: return <Note>This widget returned data in a shape this screen cannot draw yet ({String(data.shape)}).</Note>;
  }
}

const Note = ({ children }: { children: React.ReactNode }) => <p className="text-xs text-slate-500">{children}</p>;

function Kpis({ d, onDrill }: { d: D; onDrill: (m: string, p?: string) => void }) {
  return (
    <div className="grid h-full gap-2" style={{ gridTemplateColumns: `repeat(${Math.max(1, Math.min(d.items.length, 6))}, minmax(0, 1fr))`, alignContent: "start" }}>
      {d.items.map((i: D) => <Kpi key={i.key} value={i.value} label={i.label} sub={i.sub ?? (i.drill ? "click for the list" : undefined)} color={i.color} onClick={i.drill ? () => onDrill(i.drill, d.product_id ?? undefined) : undefined} />)}
    </div>
  );
}

function Series({ d, chart }: { d: D; chart: string }) {
  const rows = d.series as { label: string; value: number | null; color: string | null; detail?: string }[];
  const unit = d.unit ?? "";
  const total = rows.reduce((n, r) => n + (r.value ?? 0), 0);
  const max = Math.max(1, ...rows.map((r) => r.value ?? 0));
  if (!rows.length) return <Note>Nothing to show yet.</Note>;
  if (chart === "table")
    return (
      <table className="w-full text-left text-xs"><thead className="border-b border-slate-200 uppercase text-slate-500"><tr><th className="py-1">Item</th><th className="text-right">Value</th></tr></thead>
        <tbody>{rows.map((r) => <tr key={r.label} className="border-b border-slate-100"><td className="py-1">{r.label}</td><td className="text-right font-medium">{r.value === null ? "n/a" : `${r.value}${unit}`}{r.detail ? <span className="ml-1 font-normal text-slate-400">({r.detail})</span> : null}</td></tr>)}</tbody></table>
    );
  if (chart === "donut") {
    const R = 36, C = 2 * Math.PI * R;
    let off = 0;
    return (
      <div className="flex items-center gap-4">
        <svg viewBox="0 0 100 100" className="h-28 w-28 shrink-0 -rotate-90" role="img" aria-label="Donut chart">
          {total === 0 ? <circle cx="50" cy="50" r={R} fill="none" stroke="#e2e8f0" strokeWidth="16" /> : rows.map((r) => {
            const len = ((r.value ?? 0) / total) * C;
            const el = <circle key={r.label} cx="50" cy="50" r={R} fill="none" stroke={r.color ?? "#64748b"} strokeWidth="16" strokeDasharray={`${len} ${C - len}`} strokeDashoffset={-off} />;
            off += len;
            return el;
          })}
          <text x="50" y="54" textAnchor="middle" className="rotate-90 fill-slate-800 text-[16px] font-bold" style={{ transformOrigin: "50px 50px" }}>{unit ? "" : total}</text>
        </svg>
        <ul className="text-xs">{rows.map((r) => <li key={r.label} className="flex items-center gap-1.5 py-0.5"><span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: r.color ?? "#64748b" }} />{r.label}: <b>{r.value === null ? "n/a" : `${r.value}${unit}`}</b>{total && !unit ? <span className="text-slate-400">({Math.round(((r.value ?? 0) / total) * 100)}%)</span> : null}</li>)}</ul>
      </div>
    );
  }
  return (
    <div className="space-y-1.5">
      {rows.map((r) => (
        <div key={r.label} className="text-xs">
          <div className="flex justify-between"><span className="truncate pr-2">{r.label}</span><span className="shrink-0 text-slate-600"><b>{r.value === null ? "n/a" : `${r.value}${unit}`}</b>{r.detail ? ` · ${r.detail}` : ""}</span></div>
          <div className="h-2 rounded-md bg-slate-100"><div className="h-2 rounded-md" style={{ width: `${((r.value ?? 0) / (unit === "%" ? 100 : max)) * 100}%`, background: r.color ?? "#1e3a8a" }} /></div>
        </div>
      ))}
    </div>
  );
}

function Table({ d }: { d: D }) {
  if (!d.rows.length) return <Note>Nothing to show.</Note>;
  return (
    <table className="w-full text-left text-xs"><thead className="border-b border-slate-200 uppercase text-slate-500"><tr>{d.columns.map((c: D) => <th key={c.key} className="py-1 pr-2">{c.label}</th>)}</tr></thead>
      <tbody>{d.rows.map((r: D, i: number) => <tr key={i} className="border-b border-slate-100">{d.columns.map((c: D) => <td key={c.key} className="py-1 pr-2">{c.kind === "date" ? fmt(r[c.key]) : String(r[c.key] ?? "")}</td>)}</tr>)}</tbody></table>
  );
}

function Attention({ d }: { d: D }) {
  if (!d.items.length) return <Note>Nothing is overdue or waiting.</Note>;
  return (
    <ul className="space-y-1.5">
      {d.items.map((a: D, i: number) => (
        <li key={i} className="text-xs leading-snug text-slate-800"><span className={a.severity === "high" ? "text-red-600" : "text-amber-600"}>●</span> {a.text}
          {a.action && <div className="text-[11px] text-blue-900">Action: {a.action.owner ?? "unassigned"} · {String(a.action.status).replace("_", " ")}{a.action.due ? ` · due ${fmt(a.action.due)}` : ""}{a.action.last_action ? ` · ${a.action.last_action}` : ""}</div>}</li>
      ))}
      {d.total > d.items.length && <li className="text-[11px] text-slate-500">+ {d.total - d.items.length} more</li>}
    </ul>
  );
}

function Gates({ d }: { d: D }) {
  return (
    <div className="space-y-1">
      {d.gates.length === 0 && <Note>No sign-off gates found.</Note>}
      {d.gates.map((g: D, i: number) => <GateRow key={i} g={g as Gate} />)}
      {Object.entries(d.approval_summary as Record<string, { approved: number; total: number }>).map(([k, s]) => <p key={k} className="pt-1 text-xs text-slate-700">{k.replace(/_/g, " ")}: <b>{s.approved}</b> of {s.total} approved</p>)}
    </div>
  );
}

function Week({ d }: { d: D }) {
  if (!d.groups.length) return <Note>Nothing is due or planned in this period.</Note>;
  return (
    <div>
      <p className="mb-1 text-[11px] text-slate-500">{d.week.label}: {fmt(d.week.start)} – {fmt(d.week.end)} · {d.total_cards} activities</p>
      <div className="grid gap-2" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(210px, 1fr))" }}>
        {d.groups.map((g: D) => (
          <div key={g.name}><div className="rounded-t bg-blue-900 px-2 py-1 text-xs font-semibold text-white">{g.name} <span className="font-normal opacity-80">· {g.count}</span></div>
            <ul className="space-y-1 rounded-b border border-t-0 border-slate-200 p-1.5 text-xs">
              {g.cards.map((c: D) => <li key={c.seq}><span className={c.tag === "carry_over" ? "font-semibold text-red-700" : "font-medium"}>{c.title}</span><div className="text-[11px] text-slate-500">{c.tag === "carry_over" ? `overdue ${c.days_late} d` : c.tag === "planned" ? "planned" : c.tag === "starts" ? "starts" : "due"} {fmt(c.due)} · {c.owner ?? c.responsibility ?? "unassigned"}</div></li>)}
              {g.hidden > 0 && <li className="text-[11px] text-slate-500">+ {g.hidden} more</li>}</ul></div>
        ))}
      </div>
    </div>
  );
}

const tone = (p: number | null) => (p === null ? "bg-slate-100 text-slate-500" : p >= 80 ? "bg-green-100 text-green-900" : p >= 40 ? "bg-amber-100 text-amber-900" : "bg-red-100 text-red-900");
function Matrix({ d }: { d: D }) {
  const cell = (dep: string, loc: string) => d.cells.find((c: D) => c.department_id === dep && c.location_id === loc);
  const txt = (t: D) => (t.pct === null ? "n/a" : `${t.pct}%`);
  const rows = useMemo(() => d.departments as D[], [d.departments]);
  return (
    <table className="w-full border-collapse text-xs">
      <thead><tr><th className="p-1 text-left text-slate-500">Dept \\ Location</th>{d.locations.map((l: D) => <th key={l.id} className="p-1 text-center font-semibold text-blue-950">{l.name}</th>)}<th className="p-1 text-center text-slate-500">All</th></tr></thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.id}><td className="p-1 font-semibold text-blue-950">{r.name}</td>
            {d.locations.map((l: D) => { const c = cell(r.id, l.id); return <td key={l.id} className="p-0.5">{c ? <div className={`rounded-md px-1 py-0.5 text-center ${tone(c.pct)}`}><b>{txt(c)}</b><div className="text-[10px] opacity-70">{c.completed}/{c.planned}</div></div> : <div className="text-center text-slate-300">–</div>}</td>; })}
            <td className="p-0.5"><div className={`rounded-md px-1 py-0.5 text-center font-semibold ${tone(r.pct)}`}>{txt(r)}</div></td></tr>
        ))}
        <tr><td className="p-1 font-semibold text-slate-600">All</td>{d.locations.map((l: D) => <td key={l.id} className="p-0.5"><div className={`rounded-md px-1 py-0.5 text-center font-semibold ${tone(l.pct)}`}>{txt(l)}</div></td>)}<td className="p-0.5"><div className={`rounded-md px-1 py-0.5 text-center font-bold ${tone(d.total.pct)}`}>{txt(d.total)}</div></td></tr>
      </tbody>
    </table>
  );
}
