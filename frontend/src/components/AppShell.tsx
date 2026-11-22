"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Icon, type IconName } from "@/components/icons";
import { QuickAddProvider } from "@/components/QuickAdd";
import { ToastProvider } from "@/components/Toast";
import { UnsavedProvider } from "@/components/Unsaved";
import { useAuth } from "@/lib/auth";
import { Loading, Skeleton } from "@/components/ui";
import { MASTER } from "@/lib/masterConfig";

type NavItem = { href: string; label: string; icon: IconName; perm?: string };
const MASTER_ICON: Record<string, IconName> = { customers: "customers", products: "products", locations: "locations", departments: "departments", resources: "resources", "status-configs": "status" };
const NAV: { group: string; items: NavItem[] }[] = [
  { group: "Overview", items: [{ href: "/", label: "Home", icon: "home" }] },
  { group: "Projects", items: [{ href: "/projects", label: "Projects", icon: "projects", perm: "projects:read" }] },
  {
    group: "Master Data",
    items: Object.entries(MASTER).map(([k, v]) => ({ href: `/master/${k}`, label: v.title, icon: MASTER_ICON[k] ?? "resources", perm: "master:read" })),
  },
  { group: "Excel Intelligence", items: [{ href: "/excel-intelligence", label: "Smart Import", icon: "import" }] },
  {
    group: "Administration",
    items: [
      { href: "/admin/users", label: "Users", icon: "users", perm: "users:read" },
      { href: "/admin/flex-fields", label: "Flex fields", icon: "flex", perm: "custom_fields:write" },
      { href: "/admin/audit", label: "Audit Log", icon: "audit", perm: "audit:read" },
    ],
  },
];
const ALL = NAV.flatMap((g) => g.items.map((i) => ({ ...i, group: g.group })));

const isActive = (href: string, path: string) => (href === "/" ? path === "/" : path === href || path.startsWith(href + "/"));

type Crumb = { label: string; href?: string };
/** Breadcrumb trail built from the current route; every step that has a page links to it, ids in the path show as "Details". */
function crumbs(path: string): Crumb[] {
  if (path === "/") return [{ label: "Home" }];
  const hit = ALL.filter((i) => i.href !== "/" && isActive(i.href, path)).sort((a, b) => b.href.length - a.href.length)[0];
  if (hit) {
    const rest = path.slice(hit.href.length).split("/").filter(Boolean);
    const first = NAV.find((g) => g.group === hit.group)?.items[0];
    return [{ label: hit.group, href: first && first.href !== hit.href ? first.href : undefined }, { label: hit.label, href: rest.length ? hit.href : undefined }, ...(rest.length ? [{ label: "Details" }] : [])];
  }
  const seg = path.split("/").filter(Boolean);
  const first = seg[0] === "projects" ? "Projects" : seg[0] === "master" ? "Master Data" : (seg[0] ?? "").replace(/-/g, " ");
  return [{ label: first.charAt(0).toUpperCase() + first.slice(1) }, ...(seg.length > 1 ? [{ label: "Details" }] : [])];
}

function store(key: string, value?: string): string | null {
  try {
    if (value === undefined) return window.localStorage.getItem(key);
    window.localStorage.setItem(key, value);
  } catch { /* the preference is only a convenience */ }
  return null;
}

export default function AppShell({ children }: { children: React.ReactNode }) {
  const { me, loading, logout, can } = useAuth();
  const router = useRouter();
  const path = usePathname();
  const [collapsed, setCollapsed] = useState(false);
  const [closed, setClosed] = useState<Record<string, boolean>>({});
  const [drawer, setDrawer] = useState(false);
  // Rail tooltips are drawn once, fixed to the viewport, because the scrolling nav would clip a child tooltip.
  const [tip, setTip] = useState<{ label: string; top: number } | null>(null);
  const showTip = (label: string) => (e: React.SyntheticEvent<HTMLElement>) => { const r = e.currentTarget.getBoundingClientRect(); setTip({ label, top: r.top + r.height / 2 }); };
  const hideTip = () => setTip(null);

  useEffect(() => {
    if (!loading && !me) router.replace("/login");
  }, [loading, me, router]);
  useEffect(() => {
    // Restore the saved sidebar preferences after the first paint (they live in this browser only).
    setCollapsed(store("wfx_nav_collapsed") === "1");
    try { setClosed(JSON.parse(store("wfx_nav_groups") ?? "{}")); } catch { /* ignore */ }
  }, []);

  if (loading || !me) return <div className="flex min-h-screen bg-canvas"><div className="hidden w-60 shrink-0 space-y-3 border-r border-slate-200/80 p-4 lg:block"><Skeleton className="h-7 w-28" />{Array.from({ length: 8 }).map((_, i) => <Skeleton key={i} className="h-6 w-full" />)}</div><div className="flex-1 p-4"><Skeleton className="mb-4 h-8 w-48" /><div className="rounded-xl border border-slate-200/80 bg-white p-6"><Loading /></div></div></div>;

  const toggleCollapsed = () => { setCollapsed((c) => { store("wfx_nav_collapsed", c ? "0" : "1"); return !c; }); };
  const toggleGroup = (g: string) => setClosed((s) => { const n = { ...s, [g]: !s[g] }; store("wfx_nav_groups", JSON.stringify(n)); return n; });
  const initials = me.full_name.split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join("").toUpperCase();
  const trail = crumbs(path).reduce<Crumb[]>((acc, c) => { const last = acc[acc.length - 1]; if (last && last.label === c.label) acc[acc.length - 1] = { label: c.label, href: c.href ?? last.href }; else acc.push(c); return acc; }, []);

  // `rail` is the icon-only sidebar; it only applies on wide screens (below that the sidebar is a drawer).
  const rail = collapsed;
  return (
    <ToastProvider><UnsavedProvider><QuickAddProvider>
    <div className="flex min-h-screen bg-canvas">
      <div key={path} className="wfx-progress pointer-events-none fixed left-0 right-0 top-0 z-[70] h-0.5 bg-gradient-to-r from-blue-700 via-blue-600 to-blue-300 print:hidden" aria-hidden="true" />
      {drawer && <div className="fixed inset-0 z-40 bg-slate-900/40 lg:hidden print:hidden" onClick={() => setDrawer(false)} aria-hidden="true" />}
      <aside
        aria-label="Main navigation"
        className={`fixed inset-y-0 left-0 z-50 flex w-60 flex-col border-r border-slate-200/80 bg-nav transition-[width,transform] duration-200 ease-out lg:sticky lg:top-0 lg:h-screen lg:translate-x-0 print:hidden ${drawer ? "translate-x-0 shadow-xl" : "-translate-x-full"} ${rail ? "lg:w-16" : "lg:w-60"}`}
      >
        <div className={`flex h-14 shrink-0 items-center gap-2.5 px-4 ${rail ? "lg:justify-center lg:px-0" : ""}`}>
          <span className="grid h-7 w-7 shrink-0 place-items-center rounded-lg bg-gradient-to-br from-blue-700 to-blue-950 text-xs font-bold text-white shadow-sm">W</span>
          <span className={`whitespace-nowrap text-sm font-semibold tracking-tight text-blue-950 ${rail ? "lg:hidden" : ""}`}>WFX PMO</span>
          <button onClick={() => setDrawer(false)} className="ml-auto rounded-md p-1 text-slate-500 hover:bg-slate-200/70 lg:hidden" aria-label="Close navigation"><Icon name="close" size={16} /></button>
        </div>
        <nav className="flex-1 overflow-y-auto overflow-x-hidden px-2.5 pb-3">
          {NAV.map((g, gi) => {
            const items = g.items.filter((i) => !i.perm || can(i.perm));
            if (!items.length) return null;
            const open = rail || !closed[g.group];
            return (
              <div key={g.group} className={`wfx-enter ${gi ? "mt-3" : ""}`} style={{ animationDelay: `${gi * 70}ms` }}>
                <button
                  onClick={() => toggleGroup(g.group)}
                  aria-expanded={open}
                  className={`flex w-full items-center justify-between rounded-md px-2.5 py-1 text-[11px] font-medium uppercase tracking-wider text-slate-400 hover:text-slate-600 ${rail ? "lg:hidden" : ""}`}
                >
                  {g.group}
                  <Icon name="chevron" size={13} className={`transition-transform duration-200 ${open ? "" : "-rotate-90"}`} />
                </button>
                {rail && gi > 0 && <div className="mx-2 mb-2 hidden h-px bg-slate-200 lg:block" />}
                <div className={`grid transition-[grid-template-rows] duration-200 ease-out ${open ? "grid-rows-[1fr]" : "grid-rows-[0fr]"}`}>
                  <div className="overflow-hidden"><div className="space-y-0.5 py-0.5">
                    {items.map((i) => {
                      const active = isActive(i.href, path);
                      return (
                        <Link
                          key={i.href}
                          href={i.href}
                          onClick={() => setDrawer(false)}
                          aria-current={active ? "page" : undefined}
                          onMouseEnter={rail ? showTip(i.label) : undefined}
                          onFocus={rail ? showTip(i.label) : undefined}
                          onMouseLeave={hideTip}
                          onBlur={hideTip}
                          className={`group relative flex h-8 items-center gap-2.5 rounded-md px-2.5 text-[13px] transition-colors duration-150 ${rail ? "lg:justify-center lg:px-0" : ""} ${active ? "bg-blue-50 font-medium text-blue-900" : "text-slate-600 hover:bg-slate-200/60 hover:text-slate-900"}`}
                        >
                          {active && <span className="absolute left-0 top-1.5 bottom-1.5 w-0.5 rounded-full bg-blue-900" />}
                          <Icon name={i.icon} size={17} className={active ? "text-blue-900" : "text-slate-400 group-hover:text-slate-600"} />
                          <span className={`truncate ${rail ? "lg:hidden" : ""}`}>{i.label}</span>
                        </Link>
                      );
                    })}
                  </div></div>
                </div>
              </div>
            );
          })}
        </nav>
        <div className="hidden shrink-0 border-t border-slate-200/80 p-2.5 lg:block">
          <button
            onClick={() => { toggleCollapsed(); hideTip(); }}
            onMouseEnter={rail ? showTip("Expand sidebar") : undefined}
            onFocus={rail ? showTip("Expand sidebar") : undefined}
            onMouseLeave={hideTip}
            onBlur={hideTip}
            aria-label={rail ? "Expand sidebar" : "Collapse sidebar"}
            className={`group relative flex h-8 w-full items-center gap-2.5 rounded-md px-2.5 text-[13px] text-slate-500 transition-colors hover:bg-slate-200/60 hover:text-slate-900 ${rail ? "justify-center px-0" : ""}`}
          >
            <Icon name="panel" size={17} />
            {!rail && <span>Collapse</span>}
          </button>
        </div>
      </aside>
      {rail && tip && <div role="tooltip" style={{ top: tip.top }} className="pointer-events-none fixed left-[68px] z-[60] hidden -translate-y-1/2 whitespace-nowrap rounded-md bg-slate-900 px-2 py-1 text-xs font-medium text-white shadow-lg lg:block">{tip.label}</div>}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex h-14 shrink-0 items-center gap-3 bg-canvas/85 px-4 backdrop-blur lg:px-5 print:hidden">
          <button onClick={() => setDrawer(true)} className="rounded-md p-1.5 text-slate-600 hover:bg-slate-200/70 lg:hidden" aria-label="Open navigation"><Icon name="menu" size={18} /></button>
          <Link href="/" title="Home" aria-label="Home" aria-current={path === "/" ? "page" : undefined} className={`grid h-8 w-8 shrink-0 place-items-center rounded-lg border transition-colors ${path === "/" ? "border-blue-200 bg-blue-50 text-blue-900" : "border-slate-200 bg-white text-slate-600 hover:border-slate-300 hover:bg-slate-50 hover:text-slate-900"}`}><Icon name="home" size={16} /></Link>
          <nav aria-label="Breadcrumb" className="flex min-w-0 items-center gap-1 text-[13px] text-slate-500">
            {trail.map((c, i) => (
              <span key={i} className="flex min-w-0 items-center gap-1">
                {i > 0 && <Icon name="slash" size={13} className="text-slate-300" />}
                {c.href && i < trail.length - 1 ? <Link href={c.href} className="truncate rounded px-1 py-0.5 transition-colors hover:bg-slate-200/70 hover:text-slate-900">{c.label}</Link> : <span className={`truncate px-1 ${i === trail.length - 1 ? "font-medium text-slate-900" : ""}`} aria-current={i === trail.length - 1 ? "page" : undefined}>{c.label}</span>}
              </span>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-2">
            {can("users:read") ? (
              <Link href="/admin/users" title="Open Users" className="group flex items-center gap-2 rounded-lg px-1.5 py-1 transition-colors hover:bg-slate-200/70">
                <div className="hidden text-right leading-tight sm:block">
                  <div className="text-[13px] font-medium text-slate-800">{me.full_name}</div>
                  <div className="text-[11px] capitalize text-slate-500">{me.role}</div>
                </div>
                <span className="grid h-8 w-8 place-items-center rounded-full bg-blue-100 text-xs font-semibold text-blue-900 transition-shadow group-hover:ring-2 group-hover:ring-blue-300">{initials}</span>
              </Link>
            ) : (
              <div className="flex items-center gap-2 px-1.5">
                <div className="hidden text-right leading-tight sm:block">
                  <div className="text-[13px] font-medium text-slate-800">{me.full_name}</div>
                  <div className="text-[11px] capitalize text-slate-500">{me.role}</div>
                </div>
                <span className="grid h-8 w-8 place-items-center rounded-full bg-blue-100 text-xs font-semibold text-blue-900">{initials}</span>
              </div>
            )}
            <button
              className="rounded-md p-1.5 text-slate-500 transition-colors hover:bg-slate-200/70 hover:text-slate-900"
              title="Sign out"
              aria-label="Sign out"
              onClick={() => { logout(); router.replace("/login"); }}
            >
              <Icon name="logout" size={17} />
            </button>
          </div>
        </header>
        <main className="flex-1 px-3 pb-3 lg:px-4 lg:pb-4 print:p-0">
          <div className="min-h-full overflow-x-auto rounded-xl border border-slate-200/80 bg-white px-5 py-5 shadow-[0_1px_2px_rgba(16,24,40,0.04)] lg:px-6 print:border-0 print:p-0 print:shadow-none"><div key={path} className="wfx-enter">{children}</div></div>
        </main>
      </div>
    </div>
    </QuickAddProvider></UnsavedProvider></ToastProvider>
  );
}
