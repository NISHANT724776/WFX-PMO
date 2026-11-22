"use client";

import { useMemo, useRef, useState } from "react";
import { ConfirmDialog } from "@/components/manage/Workspace";
import { COLORS, barColor, daysBetween, fmt, iso, toDate, type PlanLink, type WorkItem } from "@/lib/plan";

const ROW = 24;
const HEAD = 40;
const LABEL_W = 320;
const MONTHS = ["J", "F", "M", "A", "M", "J", "J", "A", "S", "O", "N", "D"];

type Line = { key: string; kind: "phase" | "task"; label: string; items: WorkItem[]; item?: WorkItem; depth: number; phaseId?: string | null };
export type AddRequest = { type: "task" | "milestone" | "subtask" | "phase"; phaseId?: string | null; parentId?: string | null };
type Drag = { id: string; mode: "move" | "start" | "end"; x0: number; days: number; moved: boolean };
type Reschedule = { item: WorkItem; start: string | null; finish: string | null };

const addDays = (s: string, n: number): string => iso(new Date(toDate(s)!.getTime() + n * 86400000));
const curStart = (i: WorkItem) => i.effective_start ?? i.planned_start ?? i.effective_finish ?? i.planned_finish;
const curFinish = (i: WorkItem) => i.effective_finish ?? i.planned_finish ?? i.effective_start ?? i.planned_start;

export type QuickCreate = { title: string; kind: "task" | "milestone"; phase_id: string | null; planned_start: string; planned_finish: string };

export default function Gantt({ items, phaseList, links, asOf, canEdit, onOpen, onReschedule, onLink, onUnlink, onAdd, onRenamePhase, statuses = [], statusColors = {}, onPatch, onQuickCreate }: {
  items: WorkItem[]; phaseList: { id: string; name: string }[]; links: PlanLink[]; asOf: string; canEdit: boolean; onOpen: (id: string) => void;
  statuses?: { code: string; label: string }[]; statusColors?: Record<string, string>;
  onPatch?: (id: string, body: Record<string, unknown>) => Promise<void>;
  onQuickCreate?: (b: QuickCreate) => Promise<void>;
  onReschedule: (item: WorkItem, start: string | null, finish: string | null, reason: string) => Promise<string[] | void>;
  onLink: (predecessorId: string, successorId: string) => Promise<string[] | void>;
  onUnlink: (linkId: string) => Promise<void>;
  onAdd: (r: AddRequest) => void;
  onRenamePhase: (phaseId: string, current: string) => void;
}) {
  const [ppd, setPpd] = useState(3);
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});
  const [drag, setDrag] = useState<Drag | null>(null);
  const [pending, setPending] = useState<Reschedule | null>(null);
  const [linking, setLinking] = useState<{ from: string; x: number; y: number } | null>(null);
  const [hover, setHover] = useState<string | null>(null);
  const [picked, setPicked] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ tone: "ok" | "warn" | "err"; text: string } | null>(null);
  const area = useRef<HTMLDivElement>(null);
  const [renaming, setRenaming] = useState<{ id: string; text: string } | null>(null);
  const [dropOn, setDropOn] = useState<string | null>(null);
  /** the bar colour: the colour set for the status in Status Configuration when there is one, else the standard state colour */
  const colorOf = (i: WorkItem) => statusColors[i.status_raw ?? ""] ?? barColor(i);
  const guard = async (fn: () => Promise<void>, ok?: string) => {
    try { await fn(); if (ok) setNotice({ tone: "ok", text: ok }); } catch (err) { setNotice({ tone: "err", text: err instanceof Error ? err.message : "Could not save the change" }); }
  };

  const model = useMemo(() => {
    const dated = items.filter((i) => i.effective_start || i.effective_finish || i.planned_start || i.planned_finish);
    const dates: Date[] = [];
    dated.forEach((i) => [i.planned_start, i.planned_finish, i.effective_start, i.effective_finish, i.actual_start, i.actual_finish].forEach((d) => { const x = toDate(d); if (x) dates.push(x); }));
    const a = toDate(asOf);
    if (a) dates.push(a);
    if (!dates.length) return null;
    const min = new Date(Math.min(...dates.map((d) => d.getTime())) - 45 * 86400000); // room to drag earlier
    const max = new Date(Math.max(...dates.map((d) => d.getTime())) + 60 * 86400000);
    const start = new Date(Date.UTC(min.getUTCFullYear(), min.getUTCMonth(), 1));
    const end = new Date(Date.UTC(max.getUTCFullYear(), max.getUTCMonth() + 1, 1));
    const months: { label: string; q: string; x: number; w: number; year: number; m: number }[] = [];
    for (let d = new Date(start); d < end; d = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + 1, 1))) {
      const next = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + 1, 1));
      months.push({ label: MONTHS[d.getUTCMonth()], q: `Q${Math.floor(d.getUTCMonth() / 3) + 1} ${d.getUTCFullYear()}`, x: daysBetween(start, d), w: daysBetween(d, next), year: d.getUTCFullYear(), m: d.getUTCMonth() });
    }
    const quarters: { q: string; x: number; w: number }[] = [];
    months.forEach((m) => { const last = quarters[quarters.length - 1]; if (last && last.q === m.q) last.w += m.w; else quarters.push({ q: m.q, x: m.x, w: m.w }); });
    const phases = new Map<string, { id: string | null; list: WorkItem[] }>();
    phaseList.forEach((p) => phases.set(p.name, { id: p.id, list: [] })); // empty phases stay visible so tasks can be added to them
    items.forEach((i) => { const k = i.phase_name ?? "(no phase)"; const e = phases.get(k) ?? { id: i.phase_id, list: [] }; e.list.push(i); phases.set(k, e); });
    const rows: Line[] = [];
    phases.forEach(({ id, list }, name) => {
      rows.push({ key: `p:${name}`, kind: "phase", label: name, items: list, depth: 0, phaseId: id });
      if (collapsed[name]) return;
      const ids = new Set(list.map((i) => i.id));
      const kids = new Map<string, WorkItem[]>();
      list.forEach((i) => { if (i.parent_id && ids.has(i.parent_id)) kids.set(i.parent_id, [...(kids.get(i.parent_id) ?? []), i]); });
      const walk = (i: WorkItem, depth: number) => { rows.push({ key: i.id, kind: "task", label: i.title, items: [i], item: i, depth, phaseId: id }); (kids.get(i.id) ?? []).forEach((c) => walk(c, depth + 1)); };
      list.filter((i) => !(i.parent_id && ids.has(i.parent_id))).forEach((i) => walk(i, 0));
    });
    return { start, totalDays: daysBetween(start, end), months, quarters, rows };
  }, [items, phaseList, asOf, collapsed]);

  const rowIndex = useMemo(() => new Map((model?.rows ?? []).map((r, i) => [r.key, i])), [model]);
  if (!model) return <p className="text-sm text-slate-500">No dated items to draw.</p>;
  const x = (s: string | Date | null) => { const d = typeof s === "string" ? toDate(s) : s; return d ? daysBetween(model.start, d) * ppd : 0; };
  const width = model.totalDays * ppd;
  const todayX = x(asOf);
  const byId = new Map(items.map((i) => [i.id, i]));

  /** the dates a bar would have if the drag ended now */
  const live = (i: WorkItem): { s: string | null; f: string | null } => {
    const s = curStart(i), f = curFinish(i);
    if (!drag || drag.id !== i.id || !s || !f) return { s, f };
    if (drag.mode === "move" || i.kind === "milestone") return { s: addDays(s, drag.days), f: addDays(f, drag.days) };
    if (drag.mode === "start") return { s: addDays(s, Math.min(drag.days, daysBetween(toDate(s)!, toDate(f)!))), f };
    return { s, f: addDays(f, Math.max(drag.days, -daysBetween(toDate(s)!, toDate(f)!))) };
  };

  function down(e: React.PointerEvent, i: WorkItem, mode: Drag["mode"]) {
    if (!canEdit || e.button !== 0) return;
    e.stopPropagation();
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    setDrag({ id: i.id, mode, x0: e.clientX, days: 0, moved: false });
  }
  function move(e: React.PointerEvent) {
    if (!drag) return;
    const days = Math.round((e.clientX - drag.x0) / ppd);
    setDrag({ ...drag, days, moved: drag.moved || Math.abs(e.clientX - drag.x0) > 3 });
  }
  function up(i: WorkItem) {
    if (!drag) return;
    const d = drag;
    setDrag(null);
    if (!d.moved) { onOpen(i.id); return; }
    if (d.days === 0) return;
    const { s, f } = { s: curStart(i), f: curFinish(i) };
    if (!s || !f) { setNotice({ tone: "err", text: "This item has no dates yet. Open it and set them first." }); return; }
    const l = (() => {
      if (d.mode === "move" || i.kind === "milestone") return { s: addDays(s, d.days), f: addDays(f, d.days) };
      if (d.mode === "start") return { s: addDays(s, Math.min(d.days, daysBetween(toDate(s)!, toDate(f)!))), f };
      return { s, f: addDays(f, Math.max(d.days, -daysBetween(toDate(s)!, toDate(f)!))) };
    })();
    setPending({ item: i, start: l.s !== s ? l.s : null, finish: l.f !== f ? l.f : null });
  }
  async function confirmMove(reason: string) {
    if (!pending) return;
    try {
      const warnings = (await onReschedule(pending.item, pending.start, pending.finish, reason)) ?? [];
      setNotice({ tone: warnings.length ? "warn" : "ok", text: `${pending.item.title}: dates changed${pending.start ? ` · start ${fmt(pending.start)}` : ""}${pending.finish ? ` · finish ${fmt(pending.finish)}` : ""}. The baseline is kept and the reason is in the revision history.${warnings.length ? ` Check: ${warnings.join("; ")}` : ""}` });
      setPending(null);
    } catch (err) { setPending(null); setNotice({ tone: "err", text: err instanceof Error ? err.message : "Could not change the dates" }); }
  }

  function startLink(e: React.PointerEvent, i: WorkItem) {
    if (!canEdit) return;
    e.stopPropagation();
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    setLinking({ from: i.id, x: e.clientX, y: e.clientY });
  }
  async function endLink(e: React.PointerEvent) {
    if (!linking) return;
    const from = linking.from;
    setLinking(null);
    const target = (document.elementFromPoint(e.clientX, e.clientY) as HTMLElement | null)?.closest("[data-wid]")?.getAttribute("data-wid");
    if (!target || target === from) return;
    try { const w = (await onLink(from, target)) ?? []; setNotice({ tone: w.length ? "warn" : "ok", text: `Dependency created: ${byId.get(from)?.title} → ${byId.get(target)?.title}${w.length ? `. ${w.join("; ")}` : ""}` }); }
    catch (err) { setNotice({ tone: "err", text: err instanceof Error ? err.message : "Could not create the dependency" }); }
  }

  const related = new Set<string>();
  if (hover) links.forEach((l) => { if (l.predecessor_id === hover) related.add(l.successor_id); if (l.successor_id === hover) related.add(l.predecessor_id); });

  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center gap-3 text-xs text-slate-600">
        <label>Zoom <select className="rounded-md border border-slate-300 px-1" value={ppd} onChange={(e) => setPpd(Number(e.target.value))}><option value={1.5}>Year</option><option value={3}>Quarter</option><option value={6}>Month</option><option value={12}>Weeks</option></select></label>
        <button className="underline" onClick={() => setCollapsed(Object.fromEntries(model.rows.filter((r) => r.kind === "phase").map((r) => [r.label, true])))}>Collapse phases</button>
        <button className="underline" onClick={() => setCollapsed({})}>Expand all</button>
        {canEdit && <>
          <span className="mx-1 text-slate-300">|</span>
          <button className="rounded-md border border-slate-300 px-2 py-0.5 hover:bg-slate-100" onClick={() => onAdd({ type: "phase" })}>＋ Phase</button>
          <button className="rounded-md border border-slate-300 px-2 py-0.5 hover:bg-slate-100" onClick={() => onAdd({ type: "task" })}>＋ Task</button>
          <button className="rounded-md border border-slate-300 px-2 py-0.5 hover:bg-slate-100" onClick={() => onAdd({ type: "milestone" })}>＋ Milestone</button>
          <span className="text-slate-500">Drag a bar to move it, drag its ends to resize, drag the ○ at its end onto another bar to link them. Drag a task name onto a phase to move it there. Double-click a name to rename. ★ marks a milestone.</span>
        </>}
      </div>
      {canEdit && onQuickCreate && <QuickAddBar phaseList={phaseList} onQuickCreate={onQuickCreate} onNotice={setNotice} />}
      {notice && <div role="status" className={`mb-2 rounded-md border px-3 py-1.5 text-xs ${notice.tone === "ok" ? "border-green-200 bg-green-50 text-green-900" : notice.tone === "warn" ? "border-amber-200 bg-amber-50 text-amber-900" : "border-red-200 bg-red-50 text-red-800"}`}>{notice.text} <button className="ml-2 underline" onClick={() => setNotice(null)}>dismiss</button></div>}
      <div className="overflow-x-auto rounded-md border border-slate-200">
        <div ref={area} style={{ width: LABEL_W + width }} className="relative select-none">
          <div className="sticky top-0 z-10 flex border-b border-slate-300 bg-white" style={{ height: HEAD }}>
            <div style={{ width: LABEL_W }} className="sticky left-0 z-20 border-r border-slate-300 bg-white px-2 pt-6 text-[11px] font-semibold text-blue-950">Phase / task</div>
            <div className="relative" style={{ width }}>
              {model.quarters.map((q) => <div key={q.q + q.x} className="absolute top-0 border-l border-slate-300 bg-blue-950 px-1 text-[11px] font-semibold leading-5 text-white" style={{ left: q.x * ppd, width: q.w * ppd }}>{q.w * ppd > 50 ? q.q : ""}</div>)}
              {model.months.map((m) => <div key={m.year * 12 + m.m} className="absolute border-l border-slate-200 text-center text-[10px] leading-5 text-slate-600" style={{ left: m.x * ppd, width: m.w * ppd, top: 20 }}>{m.label}</div>)}
            </div>
          </div>
          {model.rows.map((r) => {
            const isPhase = r.kind === "phase";
            const starts = r.items.map(curStart).filter(Boolean) as string[];
            const ends = r.items.map(curFinish).filter(Boolean) as string[];
            const s0 = [...starts].sort()[0], e0 = [...ends].sort().slice(-1)[0];
            const it = r.item;
            const done = r.items.filter((i) => i.is_closed).length;
            const late = r.items.filter((i) => i.is_overdue).length;
            const dim = hover && it && it.id !== hover && !related.has(it.id);
            return (
              <div key={r.key} className={`group flex border-b border-slate-100 transition-colors ${isPhase ? "bg-slate-50" : ""} ${dropOn === r.key ? "bg-blue-100 outline outline-2 -outline-offset-2 outline-blue-500" : ""}`} style={{ height: ROW }}
                onDragOver={canEdit && onPatch && r.phaseId ? (e) => { if (e.dataTransfer.types.includes("text/wfx-task")) { e.preventDefault(); setDropOn(r.key); } } : undefined}
                onDragLeave={() => setDropOn((k) => (k === r.key ? null : k))}
                onDrop={canEdit && onPatch && r.phaseId ? (e) => {
                  const id = e.dataTransfer.getData("text/wfx-task"); setDropOn(null);
                  const moved = byId.get(id);
                  if (!id || !moved || moved.phase_id === r.phaseId) return;
                  void guard(() => onPatch(id, { phase_id: r.phaseId, parent_id: null }), `${moved.title} moved to ${r.phaseId ? (isPhase ? r.label : moved.phase_name ?? "the phase") : "the phase"}.`);
                } : undefined}>
                <div style={{ width: LABEL_W }} className={`sticky left-0 z-10 flex items-center border-r border-slate-200 px-2 text-xs ${isPhase ? "bg-slate-50 font-semibold text-blue-950" : "bg-white text-slate-700"}`}>
                  {renaming && it && renaming.id === it.id ? (
                    <input autoFocus className="min-w-0 flex-1 rounded-md border border-blue-500 bg-white px-1 text-xs" style={{ marginLeft: 8 + r.depth * 12 }} value={renaming.text}
                      onChange={(e) => setRenaming({ id: it.id, text: e.target.value })}
                      onBlur={() => setRenaming(null)}
                      onKeyDown={(e) => {
                        if (e.key === "Escape") setRenaming(null);
                        if (e.key === "Enter" && renaming.text.trim() && renaming.text.trim() !== it.title && onPatch) { const t = renaming.text.trim(); setRenaming(null); void guard(() => onPatch(it.id, { title: t }), "Renamed."); }
                        else if (e.key === "Enter") setRenaming(null);
                      }} />
                  ) : (
                    <span className={`min-w-0 flex-1 truncate ${canEdit && onPatch && it ? "cursor-grab" : "cursor-pointer"}`} title={canEdit && it ? `${r.label}\nDrag onto a phase to move it. Double-click to rename.` : r.label} style={{ paddingLeft: isPhase ? 0 : 8 + r.depth * 12 }}
                      draggable={!!(canEdit && onPatch && it)}
                      onDragStart={it ? (e) => { e.dataTransfer.setData("text/wfx-task", it.id); e.dataTransfer.effectAllowed = "move"; } : undefined}
                      onDoubleClick={canEdit && onPatch && it ? () => setRenaming({ id: it.id, text: it.title }) : undefined}
                      onClick={() => isPhase ? setCollapsed((c) => ({ ...c, [r.label]: !c[r.label] })) : it && onOpen(it.id)}>
                      {isPhase ? `${collapsed[r.label] ? "▸" : "▾"} ${r.label}  (${done}/${r.items.length}${late ? `, ${late} late` : ""})` : <>{it?.kind === "milestone" ? <span style={{ color: colorOf(it) }}>★ </span> : r.depth ? "↳ " : ""}{r.label}</>}
                    </span>
                  )}
                  {canEdit && (
                    <span className="ml-1 hidden shrink-0 gap-1 group-hover:flex">
                      {isPhase ? <>
                        <button className="rounded-md border border-slate-300 bg-white px-1 text-[10px] font-normal text-slate-700 hover:bg-slate-100" title="Add a task to this phase" onClick={() => onAdd({ type: "task", phaseId: r.phaseId })}>＋ task</button>
                        <button className="rounded-md border border-slate-300 bg-white px-1 text-[10px] font-normal text-slate-700 hover:bg-slate-100" title="Add a milestone to this phase" onClick={() => onAdd({ type: "milestone", phaseId: r.phaseId })}>＋ ◆</button>
                        {r.phaseId && <button className="rounded-md border border-slate-300 bg-white px-1 text-[10px] font-normal text-slate-700 hover:bg-slate-100" title="Rename the phase" onClick={() => onRenamePhase(r.phaseId!, r.label)}>✎</button>}
                      </> : it && <>
                        {onPatch && <button className={`rounded-md border px-1 text-[11px] ${it.kind === "milestone" ? "border-amber-400 bg-amber-50 text-amber-700" : "border-slate-300 bg-white text-slate-500 hover:bg-slate-100"}`} title={it.kind === "milestone" ? "This is a milestone (★). Click to make it a normal task" : "Mark as a milestone (★)"} onClick={() => guard(() => onPatch(it.id, { kind: it.kind === "milestone" ? "task" : "milestone" }), it.kind === "milestone" ? "Now a task." : "Marked as a milestone ★.")}>★</button>}
                        {onPatch && statuses.length > 0 && <select className="max-w-24 rounded-md border border-slate-300 bg-white px-0.5 text-[10px] text-slate-700" title="Change the status (the bar colour follows it)" value={statuses.find((x) => x.label === it.status_raw)?.code ?? ""} onChange={(e) => e.target.value && guard(() => onPatch(it.id, { status: e.target.value }), `Status changed to ${statuses.find((x) => x.code === e.target.value)?.label}.`)}><option value="">{it.status_raw ?? "Status"}</option>{statuses.map((x) => <option key={x.code} value={x.code}>{x.label}</option>)}</select>}
                        {it.kind === "task" && <button className="rounded-md border border-slate-300 bg-white px-1 text-[10px] text-slate-700 hover:bg-slate-100" title="Add a subtask" onClick={() => onAdd({ type: "subtask", phaseId: r.phaseId, parentId: it.id })}>＋ sub</button>}
                      </>}
                    </span>
                  )}
                </div>
                <div className="relative" style={{ width }}>
                  {model.months.map((m) => <div key={m.year * 12 + m.m} className="absolute top-0 h-full border-l border-slate-100" style={{ left: m.x * ppd }} />)}
                  {isPhase && s0 && e0 && <div className="absolute rounded-sm bg-blue-950/70" style={{ left: x(s0), width: Math.max(3, x(e0) - x(s0) + ppd), top: 9, height: 6 }} />}
                  {it && (() => {
                    const { s: bs, f: be } = live(it);
                    if (!bs || !be) return null;
                    const left = x(bs), w = Math.max(it.kind === "milestone" ? 0 : 4, x(be) - x(bs) + ppd);
                    const revised = it.slippage_days !== 0 || it.revised_start;
                    const dragging = drag?.id === it.id && drag.moved;
                    const pct = it.percent_complete ?? (it.is_closed ? 100 : 0);
                    const tip = `${it.title}\nPlan ${fmt(it.planned_start)} → ${fmt(it.planned_finish)}${revised ? `\nCurrent ${fmt(it.effective_start)} → ${fmt(it.effective_finish)} (${it.slippage_days > 0 ? "+" : ""}${it.slippage_days} d)` : ""}\nActual ${fmt(it.actual_start)} → ${fmt(it.actual_finish)}\n${it.status_raw ?? ""}${it.percent_complete != null ? ` · ${it.percent_complete}% reported` : ""}${it.is_overdue ? ` · ${it.days_late} d late` : ""}${it.has_pending_revision ? "\nA date change is awaiting approval" : ""}${it.is_critical_milestone ? "\nCritical milestone: overdue, or blocked by a late predecessor" : ""}`;
                    return (
                      <div data-wid={it.id} className={dim ? "opacity-30" : ""} onPointerEnter={() => setHover(it.id)} onPointerLeave={() => setHover(null)}>
                        {revised && it.planned_start && it.planned_finish && <div className="absolute border-b-2 border-dashed border-slate-400" style={{ left: x(it.planned_start), width: x(it.planned_finish) - x(it.planned_start) + ppd, top: 19 }} title="Baseline" />}
                        {it.kind === "milestone" ? (
                          <div className={`absolute flex h-5 w-5 items-center justify-center text-[18px] leading-none transition-transform hover:scale-125 ${canEdit ? "cursor-grab" : "cursor-pointer"} ${dragging ? "scale-125" : ""}`} style={{ left: left - 10, top: 2, color: colorOf(it), textShadow: it.is_critical_milestone ? "0 0 0 #b45309, 0 0 4px #f59e0b" : "0 0 1px rgba(15,23,42,.55)" }}
                            title={tip} onPointerDown={(e) => down(e, it, "move")} onPointerMove={move} onPointerUp={() => up(it)} onClick={() => { if (!canEdit) onOpen(it.id); }}>★</div>
                        ) : (
                          <div className={`wfx-grow absolute rounded-sm ${canEdit ? "cursor-grab" : "cursor-pointer"} ${it.is_start_delayed ? "ring-1 ring-red-600" : ""} ${dragging ? "ring-2 ring-blue-600" : ""} ${picked === it.id ? "ring-2 ring-blue-900" : ""}`}
                            style={{ left, width: w, top: 5, height: 11, background: colorOf(it), opacity: it.is_closed ? 0.85 : 1, outline: it.has_pending_revision ? "2px dotted #1d4ed8" : undefined, outlineOffset: 1 }}
                            title={tip} onPointerDown={(e) => down(e, it, "move")} onPointerMove={move} onPointerUp={() => up(it)} onClick={() => { if (!canEdit) onOpen(it.id); }}>
                            {pct > 0 && pct < 100 && <div className="absolute left-0 top-0 h-full rounded-sm bg-black/30" style={{ width: `${pct}%` }} />}
                            {canEdit && <>
                              <div className="absolute left-0 top-0 h-full w-1.5 cursor-ew-resize" onPointerDown={(e) => down(e, it, "start")} onPointerMove={move} onPointerUp={() => up(it)} />
                              <div className="absolute right-0 top-0 h-full w-1.5 cursor-ew-resize" onPointerDown={(e) => down(e, it, "end")} onPointerMove={move} onPointerUp={() => up(it)} />
                            </>}
                          </div>
                        )}
                        {canEdit && !drag && (
                          <div className={`absolute z-[6] h-2.5 w-2.5 cursor-crosshair rounded-full border border-blue-900 bg-white ${linking?.from === it.id ? "opacity-100" : "opacity-40 group-hover:opacity-100"}`} style={{ left: x(be) + ppd + 3, top: 7 }} title="Drag onto another bar to make it depend on this one"
                            onPointerDown={(e) => startLink(e, it)} onPointerMove={(e) => linking && setLinking({ ...linking, x: e.clientX, y: e.clientY })} onPointerUp={endLink} />
                        )}
                        {it.actual_start && <div className="absolute bg-slate-900/70" style={{ left: x(it.actual_start), width: Math.max(2, x(it.actual_finish ?? asOf) - x(it.actual_start) + ppd), top: 17, height: 2 }} title="Actual" />}
                        {dragging && <div className="pointer-events-none absolute z-30 whitespace-nowrap rounded-md bg-blue-950 px-1.5 py-0.5 text-[10px] text-white" style={{ left: left + w + 6, top: 3 }}>{fmt(bs)} → {fmt(be)}</div>}
                      </div>
                    );
                  })()}
                </div>
              </div>
            );
          })}
          {/* dependency arrows */}
          <svg className="pointer-events-none absolute z-[4]" style={{ left: LABEL_W, top: HEAD }} width={width} height={model.rows.length * ROW}>
            <defs>
              {["#64748b", "#dc2626", "#ea580c", "#1d4ed8"].map((c) => <marker key={c} id={`arrow${c.slice(1)}`} markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto"><path d="M0,0 L6,3 L0,6 z" fill={c} /></marker>)}
            </defs>
            {links.map((l) => {
              const a = byId.get(l.predecessor_id), b = byId.get(l.successor_id);
              const ia = rowIndex.get(l.predecessor_id), ib = rowIndex.get(l.successor_id);
              if (!a || !b || ia === undefined || ib === undefined) return null;
              const la = live(a), lb = live(b);
              if (!la.f || !lb.s) return null;
              const x1 = x(la.f) + ppd, y1 = ia * ROW + 10.5, x2 = x(lb.s), y2 = ib * ROW + 10.5;
              const mid = Math.max(x1 + 6, Math.min(x2 - 6, x1 + 10));
              const d = x2 >= x1 + 12 ? `M${x1},${y1} H${mid} V${y2} H${x2}` : `M${x1},${y1} H${x1 + 8} V${(y1 + y2) / 2} H${x2 - 8} V${y2} H${x2}`;
              const hot = hover === l.predecessor_id || hover === l.successor_id || picked === l.id;
              const c = hot ? "#1d4ed8" : l.violated ? "#dc2626" : l.critical ? "#ea580c" : "#64748b";
              return (
                <g key={l.id}>
                  <path d={d} fill="none" stroke={c} strokeWidth={hot ? 2 : 1} strokeDasharray={l.violated ? "4 2" : undefined} markerEnd={`url(#arrow${c.slice(1)})`} />
                  {canEdit && <path d={d} fill="none" stroke="transparent" strokeWidth={8} style={{ pointerEvents: "stroke", cursor: "pointer" }} onClick={() => setPicked(picked === l.id ? null : l.id)}><title>{`${a.title} → ${b.title}${l.slack_days !== null ? ` · slack ${l.slack_days} d` : ""}${l.violated ? " · violated" : ""} (click to select)`}</title></path>}
                </g>
              );
            })}
          </svg>
          <div className="pointer-events-none absolute z-[5] border-l-2 border-red-600" style={{ left: LABEL_W + todayX, top: HEAD, bottom: 0 }}>
            <span className="absolute -top-5 -translate-x-1/2 rounded-md bg-red-600 px-1 text-[10px] font-semibold text-white">{fmt(asOf)}</span>
          </div>
        </div>
      </div>
      {linking && <svg className="pointer-events-none fixed inset-0 z-50 h-full w-full"><circle cx={linking.x} cy={linking.y} r={5} fill="#1d4ed8" /></svg>}
      {picked && (() => {
        const l = links.find((k) => k.id === picked);
        if (!l) return null;
        return (
          <div className="mt-2 flex flex-wrap items-center gap-3 rounded-md border border-blue-200 bg-blue-50 px-3 py-1.5 text-xs">
            <span><b>{byId.get(l.predecessor_id)?.title}</b> must finish before <b>{byId.get(l.successor_id)?.title}</b> starts{l.lag_days ? ` (+${l.lag_days} d lag)` : ""}.</span>
            <span className={l.violated ? "font-semibold text-red-700" : "text-slate-600"}>{l.slack_days === null ? "No dates to compare." : l.violated ? `Violated by ${-l.slack_days} d.` : `Slack ${l.slack_days} d${l.critical ? " (critical: predecessor still open and no room)" : ""}.`}</span>
            <button className="rounded-md border border-red-300 bg-white px-2 py-0.5 text-red-700" onClick={async () => { try { await onUnlink(l.id); setPicked(null); setNotice({ tone: "ok", text: "Dependency removed." }); } catch (e) { setNotice({ tone: "err", text: e instanceof Error ? e.message : "Could not remove" }); } }}>Remove dependency</button>
            <button className="underline" onClick={() => setPicked(null)}>Close</button>
          </div>
        );
      })()}
      <div className="mt-2 flex flex-wrap gap-4 text-xs text-slate-600">
        <Legend c={COLORS.done} t="Done" /><Legend c={COLORS.in_progress} t="In progress" /><Legend c={COLORS.overdue} t="Overdue" /><Legend c={COLORS.idle} t="Not started / upcoming" />
        <span>★ milestone (coloured by its status) · <span className="font-semibold text-amber-700">★ glowing = critical milestone</span> (overdue, or blocked by a late predecessor)</span>
        <span><span className="inline-block w-4 border-b-2 border-dashed border-slate-400 align-middle" /> baseline</span><span><span className="inline-block h-0.5 w-4 bg-slate-900/70 align-middle" /> actual</span>
        <span><span className="inline-block h-2 w-4 rounded-sm outline-dotted outline-2 outline-blue-700" /> date change awaiting approval</span>
        <span><span className="inline-block w-4 border-t-2 border-red-600 align-middle" /> violated / <span className="inline-block w-4 border-t-2 border-orange-600 align-middle" /> critical link</span>
        <span className="text-slate-500">Darker fill = % complete reported on the task. Today marker = report date. Bars follow the latest approved revision.</span>
      </div>
      {pending && (
        <ConfirmDialog title="Change the dates?" confirmLabel="Change dates" reasonLabel="Why are the dates changing?" onCancel={() => setPending(null)} onConfirm={confirmMove}>
          <b>{pending.item.title}</b>
          {pending.start && <div>Start: {fmt(curStart(pending.item))} → <b>{fmt(pending.start)}</b></div>}
          {pending.finish && <div>Finish: {fmt(curFinish(pending.item))} → <b>{fmt(pending.finish)}</b></div>}
          <div className="mt-1 text-xs text-slate-500">The original planned dates are kept. This is recorded as a date revision with your reason.</div>
        </ConfirmDialog>
      )}
    </div>
  );
}

function Legend({ c, t }: { c: string; t: string }) {
  return <span className="flex items-center gap-1"><span className="inline-block h-2.5 w-4 rounded-sm" style={{ background: c }} />{t}</span>;
}

/** Add a task or milestone straight onto the timeline: name, type, phase and dates. Works on an empty plan too. */
export function QuickAddBar({ phaseList, onQuickCreate, onNotice }: { phaseList: { id: string; name: string }[]; onQuickCreate: (b: QuickCreate) => Promise<void>; onNotice?: (n: { tone: "ok" | "warn" | "err"; text: string }) => void }) {
  const [qa, setQa] = useState({ title: "", kind: "task" as "task" | "milestone", phase: "", start: "", finish: "" });
  const [busy, setBusy] = useState(false);
  const [local, setLocal] = useState<{ tone: "ok" | "err"; text: string } | null>(null);
  const say = (n: { tone: "ok" | "err"; text: string }) => { if (onNotice) onNotice(n); else setLocal(n); };
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!qa.title.trim() || !qa.start) return;
    const finish = qa.kind === "milestone" ? qa.start : qa.finish || qa.start;
    setBusy(true);
    try {
      await onQuickCreate({ title: qa.title.trim(), kind: qa.kind, phase_id: qa.phase || null, planned_start: qa.start, planned_finish: finish });
      setQa({ ...qa, title: "" });
      say({ tone: "ok", text: `${qa.kind === "milestone" ? "Milestone" : "Task"} added to the plan.` });
    } catch (err) { say({ tone: "err", text: err instanceof Error ? err.message : "Could not add it" }); }
    finally { setBusy(false); }
  }
  return (
    <>
      <form className="mb-3 flex flex-wrap items-end gap-2 rounded-lg border border-blue-200 bg-blue-50/60 p-2 text-xs" onSubmit={submit}>
        <span className="pb-1.5 font-semibold text-blue-950">Add directly</span>
        <label className="flex flex-col gap-0.5">Name<input required className="w-56 rounded-md border border-slate-300 bg-white px-2 py-1" placeholder="New task or milestone" value={qa.title} onChange={(e) => setQa({ ...qa, title: e.target.value })} /></label>
        <label className="flex flex-col gap-0.5">Type<select className="rounded-md border border-slate-300 bg-white px-1.5 py-1" value={qa.kind} onChange={(e) => setQa({ ...qa, kind: e.target.value as "task" | "milestone" })}><option value="task">Task</option><option value="milestone">★ Milestone</option></select></label>
        <label className="flex flex-col gap-0.5">Phase<select className="rounded-md border border-slate-300 bg-white px-1.5 py-1" value={qa.phase} onChange={(e) => setQa({ ...qa, phase: e.target.value })}><option value="">No phase</option>{phaseList.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label>
        <label className="flex flex-col gap-0.5">{qa.kind === "milestone" ? "Date" : "Start"}<input required type="date" className="rounded-md border border-slate-300 bg-white px-1.5 py-1" value={qa.start} onChange={(e) => setQa({ ...qa, start: e.target.value })} /></label>
        {qa.kind === "task" && <label className="flex flex-col gap-0.5">Finish<input type="date" min={qa.start || undefined} className="rounded-md border border-slate-300 bg-white px-1.5 py-1" value={qa.finish} onChange={(e) => setQa({ ...qa, finish: e.target.value })} /></label>}
        <button type="submit" disabled={busy || !qa.title.trim() || !qa.start} className="rounded-md bg-blue-900 px-3 py-1.5 font-medium text-white hover:bg-blue-800 disabled:opacity-50">{busy ? "Adding…" : "Add"}</button>
      </form>
      {local && <div role="status" className={`mb-2 rounded-md border px-3 py-1.5 text-xs ${local.tone === "ok" ? "border-green-200 bg-green-50 text-green-900" : "border-red-200 bg-red-50 text-red-800"}`}>{local.text}</div>}
    </>
  );
}
