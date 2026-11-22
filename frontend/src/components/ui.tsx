"use client";

import { EmptyArt } from "@/components/illustrations";
import { fmt } from "@/lib/plan";
import { useEffect, useRef, useState, type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes } from "react";

const field =
  "w-full rounded-md border border-slate-300 bg-white px-2.5 py-1.5 text-sm text-slate-900 shadow-[0_1px_1px_rgba(16,24,40,0.03)] transition-[border-color,box-shadow] duration-150 placeholder:text-slate-400 hover:border-slate-400 focus:border-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-700/20";

export function Button({
  variant = "primary",
  className = "",
  ...p
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "ghost" | "danger" }) {
  const v = {
    primary: "bg-blue-900 text-white shadow-sm hover:bg-blue-800 active:bg-blue-950",
    ghost: "border border-slate-300 bg-white text-slate-700 hover:bg-slate-50 hover:border-slate-400",
    danger: "border border-red-300 bg-white text-red-700 hover:bg-red-50",
  }[variant];
  return (
    <button
      {...p}
      className={`rounded-md px-3 py-1.5 text-sm font-medium transition-colors duration-150 disabled:cursor-not-allowed disabled:opacity-50 ${v} ${className}`}
    />
  );
}

export function Input(p: InputHTMLAttributes<HTMLInputElement>) {
  return <input {...p} className={`${field} ${p.className ?? ""}`} />;
}

export function Select(p: SelectHTMLAttributes<HTMLSelectElement>) {
  return <select {...p} className={`${field} ${p.className ?? ""}`} />;
}

export function Label({ text, children }: { text: string; children: ReactNode }) {
  return (
    <label className="block text-xs font-medium text-slate-600">
      <span className="mb-1 block">{text}</span>
      {children}
    </label>
  );
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: string; actions?: ReactNode }) {
  return (
    <div className="wfx-enter mb-5 flex flex-wrap items-end justify-between gap-3 border-b border-slate-100 pb-4">
      <div className="min-w-0">
        <h1 className="text-[22px] font-semibold tracking-tight text-blue-950">{title}</h1>
        {subtitle && <p className="mt-0.5 text-sm text-slate-500">{subtitle}</p>}
      </div>
      <div className="flex flex-wrap gap-2">{actions}</div>
    </div>
  );
}

export function ErrorBox({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <div role="alert" className="mb-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
      {message}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="wfx-enter rounded-lg border border-dashed border-slate-300 bg-slate-50/50 p-8 text-center text-sm text-slate-500"><EmptyArt />{children}</div>;
}

export function Pager({
  page,
  size,
  total,
  onPage,
}: {
  page: number;
  size: number;
  total: number;
  onPage: (p: number) => void;
}) {
  const pages = Math.max(1, Math.ceil(total / size));
  return (
    <div className="mt-3 flex items-center justify-between text-sm text-slate-600">
      <span>{total} record{total === 1 ? "" : "s"}</span>
      <div className="flex items-center gap-2">
        <Button variant="ghost" disabled={page <= 1} onClick={() => onPage(page - 1)}>Prev</Button>
        <span>Page {page} / {pages}</span>
        <Button variant="ghost" disabled={page >= pages} onClick={() => onPage(page + 1)}>Next</Button>
      </div>
    </div>
  );
}

export function Badge({ tone, children }: { tone: "green" | "amber" | "red" | "blue" | "slate"; children: ReactNode }) {
  const t = {
    green: "bg-green-50 text-green-700 ring-green-600/20",
    amber: "bg-amber-50 text-amber-800 ring-amber-600/20",
    red: "bg-red-50 text-red-700 ring-red-600/20",
    blue: "bg-blue-50 text-blue-800 ring-blue-700/20",
    slate: "bg-slate-100 text-slate-700 ring-slate-500/20",
  }[tone];
  return <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${t}`}>{children}</span>;
}

/** Days a date has moved against its original: amber when later, green when earlier. */
export function Slip({ days }: { days: number | null | undefined }) {
  if (!days) return null;
  return <span title={days > 0 ? `${days} day(s) later than the original date` : `${-days} day(s) earlier than the original date`} className={`ml-1 inline-flex items-center rounded-full px-1.5 py-px text-[11px] font-medium tabular-nums ring-1 ring-inset ${days > 0 ? "bg-amber-50 text-amber-800 ring-amber-600/20" : "bg-green-50 text-green-700 ring-green-600/20"}`}>{days > 0 ? "+" : "−"}{Math.abs(days)}d</span>;
}

/** The life of one date: the original commitment, the latest approved date, and what actually happened. Only data the record already holds. */
export function DateJourney({ original, current, actual, days, originalLabel = "Original (baseline)" }: { original: string | null; current: string | null; actual?: string | null; days?: number | null; originalLabel?: string }) {
  const moved = !!original && !!current && original !== current;
  const cell = (label: string, value: string | null, tone: string, extra?: React.ReactNode) => (
    <div className={`min-w-0 flex-1 rounded-lg border px-3 py-2 ${tone}`}>
      <div className="text-[10px] font-medium uppercase tracking-wider opacity-70">{label}</div>
      <div className="mt-0.5 flex items-center text-sm font-semibold tabular-nums">{value ? fmt(value) : <span className="font-normal opacity-60">not set</span>}{extra}</div>
    </div>
  );
  return (
    <div className="mb-3 flex items-stretch gap-1.5" aria-label="Date commitment: original, current and actual">
      {cell(originalLabel, original, "border-slate-200 bg-slate-50 text-slate-600")}
      <span className="self-center text-slate-300" aria-hidden="true">→</span>
      {cell(moved ? "Current (approved)" : "Current", current, moved ? "border-amber-200 bg-amber-50/60 text-blue-950" : "border-blue-200 bg-blue-50/60 text-blue-950", moved ? <Slip days={days ?? undefined} /> : <span className="ml-1.5 text-[11px] font-normal text-slate-500">unchanged</span>)}
      <span className="self-center text-slate-300" aria-hidden="true">→</span>
      {cell("Actual", actual ?? null, actual ? "border-green-200 bg-green-50/60 text-green-800" : "border-dashed border-slate-200 bg-white text-slate-500")}
    </div>
  );
}

/** A shimmering placeholder block. */
export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`wfx-shimmer rounded-md bg-slate-200/70 ${className}`} aria-hidden="true" />;
}

/** Placeholder for a list or table that is still loading: a header line and a few rows that fade in one after another. */
export function Loading({ rows = 5, compact = false }: { rows?: number; compact?: boolean }) {
  return (
    <div role="status" aria-label="Loading" className={compact ? "space-y-2 py-1" : "space-y-3 py-2"}>
      <Skeleton className="h-3 w-1/3" />
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="wfx-enter flex items-center gap-3" style={{ animationDelay: `${i * 70}ms` }}>
          <Skeleton className="h-4 w-1/4" /><Skeleton className="h-4 flex-1" /><Skeleton className="hidden h-4 w-1/6 sm:block" />
        </div>
      ))}
      <span className="sr-only">Loading…</span>
    </div>
  );
}

/** A number that counts up to its value when it first appears. Text such as "n/a" or "12%" is handled; reduced-motion users see the final value at once. */
export function CountUp({ value, ms = 700 }: { value: number | string; ms?: number }) {
  const m = typeof value === "number" ? [String(value), String(value), ""] : String(value).match(/^(-?\d+)(%?)$/);
  const target = m ? Number(m[1]) : null;
  const suffix = typeof value === "number" ? "" : m ? m[2] : "";
  const [shown, setShown] = useState<number | null>(null);
  const raf = useRef(0);
  useEffect(() => {
    if (target === null) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) { raf.current = requestAnimationFrame(() => setShown(target)); return () => cancelAnimationFrame(raf.current); }
    const t0 = performance.now();
    const tick = (t: number) => {
      const k = Math.min(1, (t - t0) / ms);
      setShown(Math.round(target * (1 - Math.pow(1 - k, 3))));
      if (k < 1) raf.current = requestAnimationFrame(tick);
    };
    raf.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf.current);
  }, [target, ms]);
  if (target === null) return <>{value}</>;
  return <span className="tabular-nums">{shown ?? 0}{suffix}</span>;
}
