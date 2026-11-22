"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Icon, type IconName } from "@/components/icons";
import { ErpFlow } from "@/components/illustrations";
import { Badge, CountUp, PageHeader } from "@/components/ui";
import { fmt } from "@/lib/plan";
import { api, type Page, type Row } from "@/lib/api";
import { useAuth } from "@/lib/auth";

const COUNTS: { label: string; path: string; href: string; perm: string; icon: IconName }[] = [
  { icon: "customers", label: "Customers", path: "/customers", href: "/master/customers", perm: "master:read" },
  { icon: "projects", label: "Projects", path: "/projects", href: "/projects", perm: "projects:read" },
  { icon: "products", label: "Products", path: "/products", href: "/master/products", perm: "master:read" },
  { icon: "locations", label: "Locations", path: "/locations", href: "/master/locations", perm: "master:read" },
];

export default function Home() {
  const { me, can } = useAuth();
  const [counts, setCounts] = useState<Record<string, number | null>>({});
  const [projects, setProjects] = useState<Row[]>([]);
  const [customers, setCustomers] = useState<Row[]>([]);

  useEffect(() => {
    COUNTS.filter((c) => can(c.perm)).forEach((c) =>
      api<Page<unknown>>(`${c.path}?size=1`)
        .then((p) => setCounts((s) => ({ ...s, [c.label]: p.total })))
        .catch(() => setCounts((s) => ({ ...s, [c.label]: null }))),
    );
    if (can("projects:read")) api<Page<Row>>("/projects?size=12").then((p) => setProjects(p.items)).catch(() => {});
    if (can("master:read")) api<Page<Row>>("/customers?size=200").then((p) => setCustomers(p.items)).catch(() => {});
  }, [can]);

  const first = (me?.full_name ?? "").split(" ")[0];
  return (
    <>
      <PageHeader title={first ? `Welcome back, ${first}` : "Home"} subtitle={`Signed in as ${me?.email}`} />
      <div className="wfx-enter mb-6 flex flex-wrap items-center justify-between gap-6 overflow-hidden rounded-2xl bg-gradient-to-br from-blue-950 via-blue-950 to-blue-800 px-6 py-5 text-white shadow-sm">
        <div className="max-w-md">
          <div className="text-xs font-medium uppercase tracking-wider text-blue-200">ERP implementation tracker</div>
          <div className="mt-1 text-xl font-semibold tracking-tight">From the first Excel import to go-live, in one place</div>
          <p className="mt-1 text-sm text-blue-100">Plan, deliver, test and sign off each customer project. Dates are never lost: original, revised and actual stay side by side.</p>
        </div>
        <ErpFlow dark />
      </div>
      <h2 className="mb-2 text-xs font-medium uppercase tracking-wider text-slate-400">At a glance</h2>
      <div className="grid max-w-4xl grid-cols-2 gap-3 md:grid-cols-4">
        {COUNTS.filter((c) => can(c.perm)).map((c, i) => (
          <Link
            key={c.label}
            href={c.href}
            style={{ animationDelay: `${i * 40}ms` }}
            className="wfx-enter group rounded-xl border border-slate-200 bg-white p-4 shadow-[0_1px_2px_rgba(16,24,40,0.04)] transition-[border-color,box-shadow,transform] duration-150 hover:-translate-y-px hover:border-blue-200 hover:shadow-md"
          >
            <div className="flex items-center justify-between text-slate-400 group-hover:text-blue-900">
              <Icon name={c.icon} size={18} />
              <Icon name="slash" size={14} className="opacity-0 transition-opacity group-hover:opacity-100" />
            </div>
            <div className="mt-3 text-3xl font-semibold tabular-nums tracking-tight text-blue-950">{counts[c.label] == null ? "–" : <CountUp value={counts[c.label] as number} />}</div>
            <div className="mt-0.5 text-xs text-slate-500">{c.label}</div>
          </Link>
        ))}
      </div>
      {projects.length > 0 && (
        <>
          <h2 className="mb-2 mt-8 text-xs font-medium uppercase tracking-wider text-slate-400">Projects</h2>
          <div className="grid max-w-4xl gap-3 md:grid-cols-2">
            {projects.map((p, i) => <ProjectCard key={String(p.id)} p={p} customer={String(customers.find((c) => c.id === p.customer_id)?.name ?? "")} delay={i * 60} />)}
          </div>
        </>
      )}
      <Link href="/guide" className="wfx-enter mt-6 flex max-w-4xl items-center justify-between rounded-xl border border-slate-200 bg-slate-50/60 px-4 py-3 text-sm transition-colors hover:border-blue-200 hover:bg-blue-50/50">
        <span><b className="text-blue-950">How WFX PMO works</b><span className="ml-2 text-slate-500">A nine-stage visual guide with the ten business requirements</span></span>
        <Icon name="slash" size={16} className="text-slate-400" />
      </Link>
    </>
  );
}

/** One project as a tracker card: status, customer, and how much of the time from start to go-live has passed. */
function ProjectCard({ p, customer, delay }: { p: Row; customer: string; delay: number }) {
  const [now] = useState(() => Date.now());
  const start = p.start_date ? Date.parse(String(p.start_date)) : NaN;
  const end = p.target_go_live ? Date.parse(String(p.target_go_live)) : NaN;
  const known = !Number.isNaN(start) && !Number.isNaN(end) && end > start;
  const pct = known ? Math.min(100, Math.max(0, Math.round(((now - start) / (end - start)) * 100))) : null;
  const late = known && now > end;
  return (
    <Link href={`/projects/${String(p.id)}`} style={{ animationDelay: `${delay}ms` }} className="wfx-enter group rounded-xl border border-slate-200 bg-white p-4 shadow-[0_1px_2px_rgba(16,24,40,0.04)] transition-[border-color,box-shadow,transform] duration-200 hover:-translate-y-0.5 hover:border-blue-200 hover:shadow-md">
      <div className="flex items-start justify-between gap-2">
        <div className="flex min-w-0 items-center gap-3">
          <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-blue-50 text-blue-900"><Icon name="box" size={18} /></span>
          <div className="min-w-0">
            <div className="truncate text-sm font-semibold text-blue-950">{String(p.code)}</div>
            <div className="truncate text-xs text-slate-500">{customer ? `${customer} · ` : ""}{String(p.name)}</div>
          </div>
        </div>
        <Badge tone={late ? "red" : "blue"}>{String(p.status)}</Badge>
      </div>
      <div className="mt-4">
        <div className="h-1.5 overflow-hidden rounded-full bg-slate-100" role="img" aria-label={pct === null ? "No start or go-live date" : `${pct}% of the time to go-live has passed`}>
          <div className={`wfx-grow h-full rounded-full ${late ? "bg-red-500" : "bg-blue-700"}`} style={{ width: `${pct ?? 0}%` }} />
        </div>
        <div className="mt-1.5 flex justify-between text-[11px] text-slate-500">
          <span>{fmt(p.start_date ? String(p.start_date) : null)}</span>
          <span>{pct === null ? "no dates set" : `${pct}% of time elapsed`}</span>
          <span>{fmt(p.target_go_live ? String(p.target_go_live) : null)}</span>
        </div>
      </div>
    </Link>
  );
}
