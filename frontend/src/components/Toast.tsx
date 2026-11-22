"use client";

import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from "react";

type Toast = { id: number; kind: "ok" | "err"; text: string; action?: { label: string; onClick: () => void } };
type Ctx = { ok: (text: string, action?: Toast["action"]) => void; err: (text: string) => void };
const ToastCtx = createContext<Ctx>({ ok: () => {}, err: () => {} });
export const useToast = () => useContext(ToastCtx);

/** Success messages fade after a few seconds; errors stay until dismissed, so a failure is never missed. */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Toast[]>([]);
  const n = useRef(0);
  const drop = useCallback((id: number) => setItems((x) => x.filter((t) => t.id !== id)), []);
  const push = useCallback((kind: Toast["kind"], text: string, action?: Toast["action"]) => {
    const id = ++n.current;
    setItems((x) => [...x.slice(-3), { id, kind, text, action }]);
    if (kind === "ok") setTimeout(() => drop(id), 6000);
  }, [drop]);
  const api = useMemo<Ctx>(() => ({ ok: (t, a) => push("ok", t, a), err: (t) => push("err", t) }), [push]);
  return (
    <ToastCtx.Provider value={api}>
      {children}
      <div className="pointer-events-none fixed bottom-4 left-60 z-[60] flex max-w-md flex-col gap-2 print:hidden" aria-live="polite">
        {items.map((t) => (
          <div key={t.id} role={t.kind === "err" ? "alert" : "status"} className={`wfx-toast pointer-events-auto flex items-start gap-3 rounded-lg border px-3 py-2 text-sm shadow-lg ${t.kind === "ok" ? "border-green-300 bg-green-50 text-green-900" : "border-red-300 bg-red-50 text-red-900"}`}>
            <span className="min-w-0 flex-1">{t.text}</span>
            {t.action && <button className="shrink-0 font-medium underline" onClick={() => { t.action!.onClick(); drop(t.id); }}>{t.action.label}</button>}
            <button className="shrink-0 opacity-60 hover:opacity-100" aria-label="Dismiss" onClick={() => drop(t.id)}>✕</button>
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}
