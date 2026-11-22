"use client";

import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { COLS, GAP, ROW_H, settle, type PlacedWidget, type WidgetType } from "@/lib/builder";

type Drag = { id: string; mode: "move" | "resize"; x0: number; y0: number; orig: PlacedWidget };

/** A 12-column grid. In edit mode a widget can be dragged by its header, resized from its corner, or moved with the arrow keys
 *  (Shift + arrows resizes). Nothing overlaps: the others settle around the widget being moved. */
export default function Grid({ widgets, types, editing, onChange, header, children }: {
  widgets: PlacedWidget[]; types: Record<string, WidgetType>; editing: boolean; onChange: (w: PlacedWidget[]) => void;
  header: (w: PlacedWidget) => ReactNode; children: (w: PlacedWidget) => ReactNode;
}) {
  const box = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(1000);
  const [drag, setDrag] = useState<Drag | null>(null);
  const [preview, setPreview] = useState<PlacedWidget[] | null>(null);
  useEffect(() => {
    if (!box.current) return;
    const ro = new ResizeObserver(([e]) => setWidth(e.contentRect.width));
    ro.observe(box.current);
    return () => ro.disconnect();
  }, []);
  const cw = Math.max(20, (width - GAP * (COLS - 1)) / COLS);
  const shown = preview ?? widgets;
  const rows = useMemo(() => Math.max(4, ...shown.map((w) => w.y + w.h)), [shown]);
  const min = (w: PlacedWidget) => types[w.type]?.min_size ?? { w: 2, h: 1 };

  const next = (orig: PlacedWidget, mode: Drag["mode"], dx: number, dy: number): PlacedWidget => {
    if (mode === "move") return { ...orig, x: Math.min(COLS - orig.w, Math.max(0, orig.x + dx)), y: Math.max(0, orig.y + dy) };
    const m = min(orig);
    return { ...orig, w: Math.min(COLS - orig.x, Math.max(m.w, orig.w + dx)), h: Math.min(24, Math.max(m.h, orig.h + dy)) };
  };
  const apply = (changed: PlacedWidget, final: boolean) => settle(widgets.map((w) => (w.id === changed.id ? changed : w)), final ? undefined : changed.id);

  function down(e: React.PointerEvent, w: PlacedWidget, mode: Drag["mode"]) {
    if (!editing || e.button !== 0) return;
    e.preventDefault();
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    setDrag({ id: w.id, mode, x0: e.clientX, y0: e.clientY, orig: w });
  }
  function move(e: React.PointerEvent) {
    if (!drag) return;
    const dx = Math.round((e.clientX - drag.x0) / (cw + GAP)), dy = Math.round((e.clientY - drag.y0) / (ROW_H + GAP));
    setPreview(apply(next(drag.orig, drag.mode, dx, dy), false));
  }
  function up() {
    if (drag && preview) {
      const c = preview.find((w) => w.id === drag.id)!;
      onChange(apply(c, true));
    }
    setDrag(null);
    setPreview(null);
  }
  function key(e: React.KeyboardEvent, w: PlacedWidget) {
    const d = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] }[e.key];
    if (!editing || !d) return;
    e.preventDefault();
    onChange(apply(next(w, e.shiftKey ? "resize" : "move", d[0], d[1]), true));
  }

  return (
    <div ref={box} className="relative" style={{ height: rows * (ROW_H + GAP) }}>
      {shown.map((w) => {
        const active = drag?.id === w.id;
        return (
          <section key={w.id} aria-label={types[w.type]?.title ?? w.type}
            className={`absolute flex flex-col overflow-hidden rounded-md border bg-white ${active ? "z-20 border-blue-600 shadow-lg" : editing ? "border-blue-300" : "border-slate-200"} ${drag && !active ? "transition-all duration-150" : ""}`}
            style={{ left: w.x * (cw + GAP), top: w.y * (ROW_H + GAP), width: w.w * cw + (w.w - 1) * GAP, height: w.h * ROW_H + (w.h - 1) * GAP }}>
            <div className={`flex shrink-0 items-center gap-1 border-b px-2 py-1 text-xs ${editing ? "cursor-grab bg-blue-50 active:cursor-grabbing" : "bg-slate-50"}`}
              {...(editing ? { tabIndex: 0, role: "button", "aria-label": `Move ${types[w.type]?.title ?? w.type}. Arrow keys move, shift and arrows resize`, onPointerDown: (e: React.PointerEvent) => down(e, w, "move"), onPointerMove: move, onPointerUp: up, onKeyDown: (e: React.KeyboardEvent) => key(e, w) } : {})}>
              {header(w)}
            </div>
            <div className="min-h-0 flex-1 overflow-auto p-2">{children(w)}</div>
            {editing && <div className="absolute bottom-0 right-0 h-4 w-4 cursor-nwse-resize" title="Drag to resize" aria-hidden onPointerDown={(e) => down(e, w, "resize")} onPointerMove={move} onPointerUp={up}
              style={{ background: "linear-gradient(135deg, transparent 50%, #1d4ed8 50%)" }} />}
          </section>
        );
      })}
    </div>
  );
}
