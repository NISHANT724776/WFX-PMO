"use client";

import { CountUp } from "@/components/ui";
import { useMemo } from "react";
import { GATE_COLOR, GATE_LABEL, STATE_COLOR, statusText, type DashRow, type Gate, type Meta } from "@/lib/dash";
import { daysBetween, fmt, toDate } from "@/lib/plan";

function span(a: string, b: string): string {
  const f = (s: string, y: boolean) => new Date(`${s}T00:00:00Z`).toLocaleDateString(undefined, y ? { month: "short", year: "2-digit", timeZone: "UTC" } : { month: "short", timeZone: "UTC" });
  const cross = a.slice(0, 4) !== b.slice(0, 4);
  return `${f(a, cross)} - ${f(b, cross)}`;
}

export function Kpi({ value, label, color = "#0b1f4b", onClick, active, sub }: { value: string | number; label: string; color?: string; onClick?: () => void; active?: boolean; sub?: string }) {
  const body = (
    <>
      <div className="text-2xl font-bold leading-7" style={{ color }}><CountUp value={value} /></div>
      <div className="mt-0.5 text-[11px] leading-tight text-slate-500">{label}</div>
      {sub && <div className="text-[10px] text-slate-400">{sub}</div>}
    </>
  );
  const cls = `wfx-enter rounded-lg border px-3 py-2.5 text-center shadow-[0_1px_2px_rgba(16,24,40,0.04)] transition-[border-color,background-color,box-shadow] duration-150 ${active ? "border-blue-900 bg-blue-50" : "border-slate-200 bg-white"}`;
  return onClick ? <button onClick={onClick} className={`${cls} hover:border-blue-300 hover:shadow-md print:hover:bg-slate-50`}>{body}</button> : <div className={cls}>{body}</div>;
}

export function DashFooter({ meta, extra }: { meta: Meta; extra?: string }) {
  return (
    <div className="mt-3 border-t border-slate-200 pt-2 text-[11px] text-slate-500">
      <div className="mb-1 flex flex-wrap gap-4">
        <Swatch c={STATE_COLOR.done} t="Completed" /><Swatch c={STATE_COLOR.in_progress} t="In progress (fill = % done)" /><Swatch c={STATE_COLOR.overdue} t="Overdue / planned start passed" /><Swatch c={STATE_COLOR.upcoming} t="Upcoming" />
        <span><b className="text-blue-950">★</b> Key milestone / sign-off</span><span><span className="inline-block w-0.5 bg-red-600 align-middle" style={{ height: 10 }} /> Today</span>
      </div>
      <div>% = {meta.formulas.completion} · Source: imported plan and trackers ({Object.entries(meta.sources).map(([k, v]) => `${v} ${k.replace(/_/g, " ")}`).join(", ")}) · Report date {fmt(meta.as_of)} · grace {meta.grace_days} day(s){extra ? ` · ${extra}` : ""}</div>
      <div>{meta.formulas.gates}. {meta.formulas.phase_state}.</div>
    </div>
  );
}

function Swatch({ c, t }: { c: string; t: string }) {
  return <span className="flex items-center gap-1"><span className="inline-block h-2.5 w-4 rounded-sm" style={{ background: c }} />{t}</span>;
}

export function GateRow({ g, onClick }: { g: Gate; onClick?: () => void }) {
  const plan = g.actual && g.planned && g.actual !== g.planned ? ` (plan ${fmt(g.planned).slice(0, 6)})` : "";
  return (
    <button onClick={onClick} disabled={!onClick} className="flex w-full items-center justify-between gap-2 rounded-md bg-slate-50 px-2 py-1.5 text-left hover:bg-blue-50 disabled:hover:bg-slate-50 print:hover:bg-slate-50">
      <div className="min-w-0"><div className="truncate text-xs font-semibold text-slate-800">{g.name}</div><div className="text-[11px] text-slate-500">{fmt(g.actual ?? g.planned)}{plan}{g.owner ? ` · ${g.owner}` : ""}</div></div>
      <span className="shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold text-white" style={{ background: GATE_COLOR[g.state] }}>{GATE_LABEL[g.state]}</span>
    </button>
  );
}

/** The phase timeline of the status slides: area, phase, month/quarter axis, bar (fill = % done), stars, status, today line. */
export function PhaseTimeline({ rows, asOf, onRow, labelWidth = 290 }: { rows: DashRow[]; asOf: string; onRow?: (r: DashRow) => void; labelWidth?: number }) {
  const axis = useMemo(() => {
    const ds = rows.flatMap((r) => [r.start, r.end]).filter(Boolean).map((s) => toDate(s as string)!) as Date[];
    const a = toDate(asOf);
    if (a) ds.push(a);
    if (!ds.length) return null;
    const min = new Date(Math.min(...ds.map((d) => d.getTime()))), max = new Date(Math.max(...ds.map((d) => d.getTime())));
    const lo = new Date(Date.UTC(min.getUTCFullYear(), min.getUTCMonth(), 1)), hi = new Date(Date.UTC(max.getUTCFullYear(), max.getUTCMonth() + 1, 1));
    const total = daysBetween(lo, hi);
    const months: { m: number; y: number; x: number; w: number }[] = [];
    for (let d = new Date(lo); d < hi; d = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + 1, 1))) {
      const n = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + 1, 1));
      months.push({ m: d.getUTCMonth(), y: d.getUTCFullYear(), x: (daysBetween(lo, d) / total) * 100, w: (daysBetween(d, n) / total) * 100 });
    }
    const quarters: { q: string; x: number; w: number }[] = [];
    months.forEach((m) => { const q = `Q${Math.floor(m.m / 3) + 1} ${m.y}`; const l = quarters[quarters.length - 1]; if (l && l.q === q) l.w += m.w; else quarters.push({ q, x: m.x, w: m.w }); });
    return { lo, total, months, quarters };
  }, [rows, asOf]);
  if (!axis) return <p className="text-sm text-slate-500">No dated items to draw.</p>;
  const pos = (s: string) => (daysBetween(axis.lo, toDate(s)!) / axis.total) * 100;
  const todayX = pos(asOf);
  const status = (r: DashRow) => ({ color: r.state === "overdue" ? "#dc2626" : r.state === "done" ? "#16a34a" : "#475569", bold: r.state === "overdue" });

  return (
    <div className="text-xs">
      <div className="flex border-b border-slate-300">
        <div style={{ width: labelWidth }} className="shrink-0 py-1 pr-2 text-[11px] font-semibold text-blue-950">Area · Phase</div>
        <div className="relative h-9 flex-1">
          {axis.quarters.map((q) => <div key={q.q + q.x} className="absolute top-0 truncate border-l border-white bg-blue-950 px-1 text-[10px] font-semibold leading-4 text-white" style={{ left: `${q.x}%`, width: `${q.w}%` }}>{q.w > 7 ? q.q : ""}</div>)}
          {axis.months.map((m) => <div key={m.y * 12 + m.m} className="absolute top-4 border-l border-slate-200 text-center text-[10px] leading-4 text-slate-500" style={{ left: `${m.x}%`, width: `${m.w}%` }}>{"JFMAMJJASOND"[m.m]}</div>)}
        </div>
        <div className="w-28 shrink-0 py-1 text-center text-[11px] font-semibold text-blue-950">Status</div>
      </div>
      <div className="relative">
        {rows.map((r, i) => {
          const first = i === 0 || rows[i - 1].area !== r.area;
          const col = STATE_COLOR[r.state];
          const st = status(r);
          return (
            <div key={`${r.area}|${r.label}|${i}`} className={`flex items-stretch ${first && i > 0 ? "border-t border-slate-300" : "border-t border-slate-100"}`} style={{ height: 24 }}>
              <div style={{ width: labelWidth }} className="flex shrink-0 items-center gap-1 pr-2">
                <span className="w-14 shrink-0 truncate text-[10px] font-bold uppercase text-blue-800">{first ? (r.area === "Project-wide" ? "All" : r.area) : ""}</span>
                <button className="truncate text-left text-slate-800 hover:underline print:no-underline" title={`${r.label} · ${r.done}/${r.items} done${r.late_items ? ` · ${r.late_items} late` : ""}`} onClick={() => onRow?.(r)}>{r.label}</button>
              </div>
              <div className="relative flex-1 cursor-pointer" onClick={() => onRow?.(r)}>
                {axis.months.map((m) => <div key={m.y * 12 + m.m} className="absolute top-0 h-full border-l border-slate-100" style={{ left: `${m.x}%` }} />)}
                {r.start && r.end && (
                  <div className="wfx-grow absolute top-1 h-4 overflow-hidden rounded-sm" style={{ animationDelay: `${Math.min(i, 24) * 30}ms`, left: `${pos(r.start)}%`, width: `max(4px, ${pos(r.end) - pos(r.start)}%)`, background: r.state === "done" || r.state === "upcoming" ? col : `${col}22`, border: `1px solid ${col}` }}
                    title={`${fmt(r.start)} → ${fmt(r.end)}`}>
                    {(r.state === "in_progress" || r.state === "overdue") && <div className="h-full" style={{ width: `${r.pct}%`, background: col }} />}
                  </div>
                )}
                {r.start && r.end && pos(r.end) - pos(r.start) > 9 && (
                  <span className="pointer-events-none absolute top-1 text-center text-[9px] leading-4 text-slate-900" style={{ left: `${pos(r.start)}%`, width: `${pos(r.end) - pos(r.start)}%` }}>
                    {span(r.start, r.end)}
                  </span>
                )}
                {r.stars.filter((s) => s.date).map((s, k) => <span key={k} title={`${s.title} · ${fmt(s.date)}`} className="absolute top-0 -translate-x-1/2 text-[13px] leading-6 text-blue-950" style={{ left: `${pos(s.date!)}%` }}>★</span>)}
              </div>
              <div className="w-28 shrink-0 text-center text-[11px] leading-6" style={{ color: st.color, fontWeight: st.bold ? 700 : 400 }}>{statusText(r)}</div>
            </div>
          );
        })}
        <div className="pointer-events-none absolute top-0 bottom-0" style={{ left: labelWidth, right: 112 }}>
          <div className="absolute top-0 bottom-0 border-l-2 border-red-600" style={{ left: `${todayX}%` }}><span className="absolute -bottom-4 -translate-x-1/2 text-[10px] font-semibold text-red-600">Today</span></div>
        </div>
      </div>
      <div className="h-4" />
    </div>
  );
}
