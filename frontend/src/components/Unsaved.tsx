"use client";

import { createContext, useCallback, useContext, useEffect, useId, useMemo, useRef, type ReactNode } from "react";

type Ctx = { register: (id: string, dirty: boolean) => void; anyDirty: () => boolean; confirmLeave: (what?: string) => boolean };
const UnsavedCtx = createContext<Ctx>({ register: () => {}, anyDirty: () => false, confirmLeave: () => true });

/** One place that knows whether anything on screen has unsaved changes, and warns before the user walks away from it
 *  (closing the tab, following a link, switching a tab). */
export function UnsavedProvider({ children }: { children: ReactNode }) {
  const dirty = useRef(new Set<string>());
  const register = useCallback((id: string, d: boolean) => { if (d) dirty.current.add(id); else dirty.current.delete(id); }, []);
  const anyDirty = useCallback(() => dirty.current.size > 0, []);
  const confirmLeave = useCallback((what = "You have unsaved changes. Leave without saving?") => !dirty.current.size || window.confirm(what), []);
  useEffect(() => {
    const unload = (e: BeforeUnloadEvent) => { if (dirty.current.size) e.preventDefault(); };
    const click = (e: MouseEvent) => {
      if (!dirty.current.size || e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey) return;
      const a = (e.target as HTMLElement | null)?.closest?.("a[href]") as HTMLAnchorElement | null;
      if (!a || a.target === "_blank" || !a.getAttribute("href")?.startsWith("/")) return;
      if (!window.confirm("You have unsaved changes. Leave without saving?")) { e.preventDefault(); e.stopPropagation(); }
    };
    window.addEventListener("beforeunload", unload);
    document.addEventListener("click", click, true);
    return () => { window.removeEventListener("beforeunload", unload); document.removeEventListener("click", click, true); };
  }, []);
  const value = useMemo(() => ({ register, anyDirty, confirmLeave }), [register, anyDirty, confirmLeave]);
  return <UnsavedCtx.Provider value={value}>{children}</UnsavedCtx.Provider>;
}

export const useUnsaved = () => useContext(UnsavedCtx);

/** Call with true while a form has edits that are not saved. */
export function useDirtyGuard(dirty: boolean) {
  const id = useId();
  const { register } = useUnsaved();
  useEffect(() => { register(id, dirty); return () => register(id, false); }, [id, dirty, register]);
}
