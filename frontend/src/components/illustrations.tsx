import { Icon, type IconName } from "@/components/icons";

const STAGES: { icon: IconName; label: string }[] = [
  { icon: "import", label: "Import" },
  { icon: "plan", label: "Plan" },
  { icon: "delivery", label: "Deliver" },
  { icon: "uat", label: "Test" },
  { icon: "flag", label: "Go-live" },
];

/** The life of an ERP implementation as a pipeline. Purely illustrative: the same five stages the project tabs follow. */
export function ErpFlow({ dark = false }: { dark?: boolean }) {
  return (
    <div className="flex items-center" role="img" aria-label="ERP implementation pipeline: import, plan, deliver, test, go-live">
      {STAGES.map((s, i) => (
        <div key={s.label} className="flex items-center">
          {i > 0 && <span className={`wfx-grow h-0.5 w-8 sm:w-14 ${dark ? "bg-white/35" : "bg-blue-200"}`} style={{ animationDelay: `${i * 140}ms` }} />}
          <div className="flex flex-col items-center gap-1.5">
            <span
              className={`wfx-pop grid h-11 w-11 place-items-center rounded-full ring-1 ${dark ? "bg-white/10 text-white ring-white/30" : "bg-white text-blue-900 shadow-sm ring-blue-200"}`}
              style={{ animation: "wfx-pop 420ms cubic-bezier(0.22,1,0.36,1) both", animationDelay: `${i * 140 + 100}ms` }}
            >
              <Icon name={s.icon} size={20} />
            </span>
            <span className={`text-[11px] font-medium ${dark ? "text-blue-100" : "text-slate-500"}`}>{s.label}</span>
          </div>
        </div>
      ))}
    </div>
  );
}

/** Soft illustration for an empty list: a tray with a card in it. */
export function EmptyArt() {
  return (
    <svg width="64" height="52" viewBox="0 0 64 52" fill="none" aria-hidden="true" className="mx-auto mb-3">
      <rect x="10" y="6" width="44" height="30" rx="4" className="fill-blue-50 stroke-blue-200" strokeWidth="1.5" />
      <path d="M18 16h20M18 22h28M18 28h14" className="stroke-blue-300" strokeWidth="2" strokeLinecap="round" />
      <path d="M4 32h16l3 6h18l3-6h16v12a4 4 0 0 1-4 4H8a4 4 0 0 1-4-4V32Z" className="fill-white stroke-slate-300" strokeWidth="1.5" strokeLinejoin="round" />
    </svg>
  );
}
