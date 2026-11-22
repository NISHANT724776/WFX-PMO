"use client";

import { useMemo, useState } from "react";
import { Button } from "@/components/ui";
import { barColor, iso, toDate, type WorkItem } from "@/lib/plan";

const DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]; // weeks run Monday to Sunday

export default function Calendar({ items, asOf, onOpen }: { items: WorkItem[]; asOf: string; onOpen: (id: string) => void }) {
  const a = toDate(asOf) ?? new Date();
  const [cursor, setCursor] = useState({ y: a.getUTCFullYear(), m: a.getUTCMonth() });

  const { cells, byDay } = useMemo(() => {
    const first = new Date(Date.UTC(cursor.y, cursor.m, 1));
    const lead = (first.getUTCDay() + 6) % 7; // Monday = 0
    const start = new Date(first.getTime() - lead * 86400000);
    const days = Array.from({ length: 42 }, (_, i) => new Date(start.getTime() + i * 86400000));
    const map = new Map<string, WorkItem[]>();
    items.forEach((w) => { const d = w.effective_finish; if (d) map.set(d, [...(map.get(d) ?? []), w]); });
    return { cells: days, byDay: map };
  }, [items, cursor]);

  const label = new Date(Date.UTC(cursor.y, cursor.m, 1)).toLocaleDateString(undefined, { month: "long", year: "numeric", timeZone: "UTC" });
  const shift = (n: number) => setCursor((c) => { const d = new Date(Date.UTC(c.y, c.m + n, 1)); return { y: d.getUTCFullYear(), m: d.getUTCMonth() }; });

  return (
    <div>
      <div className="mb-2 flex items-center gap-2">
        <Button variant="ghost" onClick={() => shift(-1)}>‹</Button>
        <span className="w-44 text-center text-sm font-semibold text-blue-950">{label}</span>
        <Button variant="ghost" onClick={() => shift(1)}>›</Button>
        <Button variant="ghost" onClick={() => setCursor({ y: a.getUTCFullYear(), m: a.getUTCMonth() })}>Report date</Button>
        <span className="text-xs text-slate-500">Shows when each item is due (latest approved finish date).</span>
      </div>
      <div className="grid grid-cols-7 border-l border-t border-slate-200 text-xs">
        {DOW.map((d) => <div key={d} className="border-b border-r border-slate-200 bg-slate-50 px-1 py-0.5 font-semibold text-slate-600">{d}</div>)}
        {cells.map((d) => {
          const key = iso(d), inMonth = d.getUTCMonth() === cursor.m, list = byDay.get(key) ?? [];
          return (
            <div key={key} className={`min-h-24 border-b border-r border-slate-200 p-1 ${inMonth ? "bg-white" : "bg-slate-50 text-slate-400"} ${key === asOf ? "ring-2 ring-inset ring-red-500" : ""}`}>
              <div className="mb-0.5 text-right text-[11px]">{d.getUTCDate()}</div>
              {list.slice(0, 4).map((w) => (
                <button key={w.id} onClick={() => onOpen(w.id)} title={w.title} className="mb-0.5 block w-full truncate rounded-md px-1 text-left text-[11px] text-white" style={{ background: barColor(w) }}>
                  {w.kind === "milestone" ? "◆ " : ""}{w.title}
                </button>
              ))}
              {list.length > 4 && <div className="text-[10px] text-slate-500">+{list.length - 4} more</div>}
            </div>
          );
        })}
      </div>
    </div>
  );
}
