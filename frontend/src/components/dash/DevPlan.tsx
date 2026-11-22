"use client";

import { useEffect, useMemo, useState } from "react";
import { Empty, ErrorBox, Label, Select, Loading } from "@/components/ui";
import { api, qs, type Page, type Row } from "@/lib/api";
import { fmt } from "@/lib/plan";
import type { DashRow, RowState } from "@/lib/dash";
import { STATE_COLOR } from "@/lib/dash";
import { Kpi, PhaseTimeline } from "./parts";

const REGISTERS: { slug: string; label: string }[] = [
  { slug: "delivery-items", label: "Delivery items" },
  { slug: "gap-specifications", label: "Gaps & specifications" },
  { slug: "requirements", label: "Requirements (BRD)" },
  { slug: "helpdesk-items", label: "Helpdesk & operations" },
  { slug: "discussions", label: "Open discussions" },
  { slug: "integration-items", label: "Integrations" },
  { slug: "report-items", label: "Reports + prints" },
  { slug: "uat-scenarios", label: "UAT scenarios" },
];
const GROUPS = [["module", "Module"], ["stream", "Stream"], ["tech_owner", "Technical owner"], ["functional_owner", "Functional owner"], ["priority", "Priority"], ["owner_name", "Owner"]] as const;
const ISO = /^\d{4}-\d{2}-\d{2}$/;
const DATE_KEY = /(_date|_actual|_on|dev_initiation|dev_completion|qa_release|uat_release|customer_release|customer_uat_closure|actual_completion)$/;
const STAR_KEYS: [string, string][] = [["spec_closure_date", "Spec closure"], ["dev_completion", "Dev complete"], ["qa_release", "QA release"], ["customer_release", "Customer UAT release"], ["customer_uat_closure", "UAT closure"], ["effective_target_date", "Target"]];

/** The dates on a record, leaving out placeholder dates (year 1900 or 2099 style) and anything far outside the project's own window. */
const dates = (r: Row, lo: string, hi: string): string[] => Object.entries(r).filter(([k, v]) => DATE_KEY.test(k) && !/^(created|updated)/.test(k) && typeof v === "string" && ISO.test(v) && v >= lo && v <= hi).map(([, v]) => v as string);
const shift = (d: string | null, years: number, fallback: string) => (d ? `${Number(d.slice(0, 4)) + years}${d.slice(4)}` : fallback);

/**
 * A timeline for any project, built from the dated records an Excel import filled (delivery schedule, gaps, requirements ...).
 * Each bar runs from the earliest to the latest date on the records of one group; fill = share closed; ★ = key stage dates.
 */
export default function DevPlan({ projectId, asOf }: { projectId: string; asOf: string }) {
  const [totals, setTotals] = useState<Record<string, number> | null>(null);
  const [slug, setSlug] = useState("");
  const [groupBy, setGroupBy] = useState("module");
  const [recs, setRecs] = useState<Row[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [win, setWin] = useState<{ lo: string; hi: string }>({ lo: "2000-01-01", hi: "2060-12-31" });

  useEffect(() => {
    api<Row>(`/projects/${projectId}`).then((p) => setWin({ lo: shift(p.start_date ? String(p.start_date) : null, -1, "2000-01-01"), hi: shift(p.target_go_live ? String(p.target_go_live) : null, 1, "2060-12-31") })).catch(() => {});
  }, [projectId]);

  useEffect(() => {
    let live = true;
    Promise.all(REGISTERS.map((g) => api<Page<Row>>(`/projects/${projectId}/records/${g.slug}${qs({ size: 1, as_of: asOf })}`).then((p) => [g.slug, p.total] as const).catch(() => [g.slug, 0] as const)))
      .then((e) => { if (!live) return; const t = Object.fromEntries(e); setTotals(t); setSlug((s) => s || REGISTERS.find((g) => t[g.slug] > 0)?.slug || ""); });
    return () => { live = false; };
  }, [projectId, asOf]);

  useEffect(() => {
    if (!slug) return;
    let live = true;
    (async () => {
      try {
        setError(null);
        const all: Row[] = [];
        for (let page = 1; page <= 20; page++) {
          const p = await api<Page<Row>>(`/projects/${projectId}/records/${slug}${qs({ size: 200, page, as_of: asOf })}`);
          all.push(...p.items);
          if (all.length >= p.total || p.items.length === 0) break;
        }
        if (live) setRecs(all);
      } catch (e) { if (live) setError(e instanceof Error ? e.message : "Failed to load"); }
    })();
    return () => { live = false; };
  }, [projectId, slug, asOf]);

  const groupKeys = useMemo(() => GROUPS.filter(([k]) => (recs ?? []).some((r) => r[k])), [recs]);
  const by = groupKeys.some(([k]) => k === groupBy) ? groupBy : groupKeys[0]?.[0] ?? "";

  const rows = useMemo<DashRow[]>(() => {
    const m = new Map<string, Row[]>();
    (recs ?? []).forEach((r) => { const k = String((by && r[by]) || "(not set)"); m.set(k, [...(m.get(k) ?? []), r]); });
    const out: DashRow[] = [];
    m.forEach((list, label) => {
      const ds = list.flatMap((r) => dates(r, win.lo, win.hi)).sort();
      if (!ds.length) return;
      const done = list.filter((r) => r.is_closed).length;
      const late = list.filter((r) => r.is_overdue).length;
      const started = list.filter((r) => r.is_closed || r.status_category === "in_progress").length;
      const state: RowState = done === list.length ? "done" : late > 0 ? "overdue" : started > 0 ? "in_progress" : "upcoming";
      const stars = STAR_KEYS.map(([k, title]) => ({ k, title, d: list.map((r) => r[k]).filter((v): v is string => typeof v === "string" && ISO.test(v) && v >= win.lo && v <= win.hi).sort().slice(-1)[0] })).filter((s) => s.d).slice(0, 4)
        .map((s) => ({ date: s.d as string, title: s.title, id: "", type: "" }));
      out.push({ label, area: String(list[0].stream ?? ""), state, pct: Math.round((done / list.length) * 100), start: ds[0], end: ds[ds.length - 1], items: list.length, done, late_items: late, stars, refs: [], kind: "events" });
    });
    return out.sort((a, b) => (a.start ?? "").localeCompare(b.start ?? ""));
  }, [recs, by, win]);

  if (!totals) return <Loading />;
  const available = REGISTERS.filter((g) => totals[g.slug] > 0);
  if (!available.length) return <Empty>No records with dates yet. Import this project&apos;s workbook under Smart Import (delivery schedule, gaps, requirements, plan) and its timeline appears here.</Empty>;
  const sum = (f: (r: DashRow) => number) => rows.reduce((a, r) => a + f(r), 0);

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-end gap-3 rounded-lg border border-slate-200 bg-slate-50/70 p-3 print:hidden">
        <Label text="Timeline of"><Select value={slug} onChange={(e) => { setRecs(null); setSlug(e.target.value); }}>{available.map((g) => <option key={g.slug} value={g.slug}>{g.label} ({totals[g.slug]})</option>)}</Select></Label>
        {groupKeys.length > 1 && <Label text="One bar per"><Select value={by} onChange={(e) => setGroupBy(e.target.value)}>{groupKeys.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</Select></Label>}
        <p className="max-w-xl pb-1 text-xs text-slate-500">Built from the dates on the imported records, so it works for every project. Edit the records themselves in the Delivery tab; edit plan tasks under Overall status → Edit timeline.</p>
      </div>
      <ErrorBox message={error} />
      {!recs ? <Loading /> : rows.length === 0 ? <Empty>These records carry no dates, so there is nothing to draw. Pick another register above.</Empty> : (
        <>
          <div className="mb-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
            <Kpi value={sum((r) => r.items)} label="RECORDS" />
            <Kpi value={sum((r) => r.done)} label="CLOSED" color={STATE_COLOR.done} />
            <Kpi value={sum((r) => r.late_items)} label="OVERDUE" color={sum((r) => r.late_items) ? STATE_COLOR.overdue : STATE_COLOR.done} />
            <Kpi value={rows.length} label="BARS" sub={by ? `by ${GROUPS.find(([k]) => k === by)?.[1].toLowerCase()}` : undefined} />
          </div>
          <PhaseTimeline rows={rows} asOf={asOf} />
          <p className="mt-2 text-[11px] text-slate-500">Each bar runs from the earliest to the latest date on its records ({fmt(rows[0].start)} → {fmt(rows.map((r) => r.end ?? "").sort().slice(-1)[0])} overall). Fill = share closed. ★ = latest spec, development, release and target dates in the group.</p>
        </>
      )}
    </div>
  );
}
