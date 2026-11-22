"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui";
import { api, qs, type Page } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { DELIVERY_KINDS as KINDS } from "@/lib/records";
import RecordsTab, { LinkSuggestions } from "./RecordsTab";

export default function DeliveryTab({ projectId, onChanged }: { projectId: string; onChanged: () => void }) {
  const { can } = useAuth();
  const [kind, setKind] = useState(KINDS[0].slug);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [suggest, setSuggest] = useState(false);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    KINDS.forEach((k) => api<Page<unknown>>(`/projects/${projectId}/records/${k.slug}${qs({ size: 1 })}`).then((p) => setCounts((c) => ({ ...c, [k.slug]: p.total }))).catch(() => {}));
  }, [projectId, tick]);
  const cfg = KINDS.find((k) => k.slug === kind)!;
  const changed = () => { setTick((t) => t + 1); onChanged(); };

  return (
    <>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div className="inline-flex max-w-full overflow-x-auto rounded-lg bg-slate-100 p-0.5">
          {KINDS.map((k) => (
            <button key={k.slug} onClick={() => setKind(k.slug)} className={`px-3 py-1 transition-colors duration-150 whitespace-nowrap text-sm ${kind === k.slug ? "rounded-md bg-white font-medium text-blue-950 shadow-sm" : "rounded-md text-slate-600 hover:text-slate-900"}`}>
              {k.label} <span className={kind === k.slug ? "text-slate-400" : "text-slate-400"}>{counts[k.slug] ?? ""}</span>
            </button>
          ))}
        </div>
        {can("projects:read") && <Button variant="ghost" onClick={() => setSuggest(true)}>Suggested links</Button>}
      </div>
      <RecordsTab key={cfg.slug} projectId={projectId} cfg={cfg} onChanged={changed} />
      {suggest && <LinkSuggestions projectId={projectId} onClose={() => setSuggest(false)} onChanged={changed} />}
    </>
  );
}
