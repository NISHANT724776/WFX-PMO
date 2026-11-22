"use client";

import { useEffect, useRef, useState } from "react";
import { useToast } from "@/components/Toast";
import { fmt } from "@/lib/plan";

type Opt = { value: string; label: string };

/** A value you can change where it is: click, edit, Enter or leave the field to save, Escape to cancel.
 *  A failed save keeps the old value on screen and says why; nothing is shown as saved until the server accepted it. */
export default function InlineCell({ value, kind = "text", options, disabled, label, display, onSave, className = "" }: {
  value: string; kind?: "text" | "date" | "select"; options?: Opt[]; disabled?: boolean; label: string; display?: string;
  onSave: (v: string) => Promise<void>; className?: string;
}) {
  const toast = useToast();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);
  const [busy, setBusy] = useState(false);
  const ref = useRef<HTMLInputElement & HTMLSelectElement>(null);
  useEffect(() => { if (editing) ref.current?.focus(); }, [editing]);
  useEffect(() => { if (!editing) setDraft(value); }, [value, editing]);

  async function commit(v: string) {
    setEditing(false);
    if (v === value) return;
    setBusy(true);
    try { await onSave(v); toast.ok(`${label} updated`); }
    catch (e) { setDraft(value); toast.err(`${label} not saved: ${e instanceof Error ? e.message : "failed"}`); }
    finally { setBusy(false); }
  }
  const shown = display ?? (kind === "date" ? fmt(value || null) : kind === "select" ? options?.find((o) => o.value === value)?.label ?? value : value);

  if (disabled) return <span className={className}>{shown}</span>;
  if (!editing)
    return (
      <button type="button" disabled={busy} title={`Click to change ${label.toLowerCase()}`} onClick={(e) => { e.stopPropagation(); setEditing(true); }}
        className={`min-h-5 min-w-8 rounded-md px-1 text-left hover:bg-blue-100 focus:bg-blue-100 focus:outline-none ${busy ? "opacity-50" : ""} ${className}`}>
        {shown || <span className="text-slate-300">—</span>}
      </button>
    );
  const common = { ref, "aria-label": label, className: "w-full rounded-md border border-blue-600 bg-white px-1 py-0.5 text-xs", onClick: (e: React.MouseEvent) => e.stopPropagation(),
    onKeyDown: (e: React.KeyboardEvent) => { if (e.key === "Escape") { setDraft(value); setEditing(false); } if (e.key === "Enter") { e.preventDefault(); void commit(draft); } } };
  return kind === "select" ? (
    <select {...common} value={draft} onChange={(e) => { setDraft(e.target.value); void commit(e.target.value); }} onBlur={() => setEditing(false)}>
      {!options?.some((o) => o.value === value) && <option value={value}>{shown || "—"}</option>}
      {options?.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
    </select>
  ) : (
    <input {...common} type={kind === "date" ? "date" : "text"} value={draft} onChange={(e) => setDraft(e.target.value)} onBlur={() => void commit(draft)} />
  );
}
