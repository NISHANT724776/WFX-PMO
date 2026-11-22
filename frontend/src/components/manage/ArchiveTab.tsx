"use client";

import { useCallback, useEffect, useState } from "react";
import { ConfirmDialog } from "@/components/manage/Workspace";
import { Badge, Button, Empty, ErrorBox, Loading } from "@/components/ui";
import { api, type Page } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmt } from "@/lib/plan";

const LABEL: Record<string, string> = {
  work_item: "Plan tasks and milestones", dependency_item: "Pending items", approval_gate: "Sign-off gates", delivery_item: "Delivery items", brd_requirement: "Requirements (BRD)",
  helpdesk_item: "Helpdesk & operations", gap_specification: "Gaps & specifications", discussion_item: "Open discussions", scope_decision: "Out of scope", action_item: "Actions",
};
type Summary = Record<string, { archived?: number; deleted?: number }>;
type Item = { id: string; title: string; state: "archived" | "deleted"; archived_at: string | null; deleted_at: string | null };

/** Everything archived or in the trash, across all record types, with restore (and permanent delete for those allowed). */
export default function ArchiveTab({ projectId, onChanged }: { projectId: string; onChanged: () => void }) {
  const { can } = useAuth();
  const [summary, setSummary] = useState<Summary | null>(null);
  const [items, setItems] = useState<Record<string, Item[]>>({});
  const [error, setError] = useState<string | null>(null);
  const [purge, setPurge] = useState<{ type: string; item: Item } | null>(null);

  const load = useCallback(async () => {
    try {
      setError(null);
      const s = await api<Summary>(`/projects/${projectId}/lifecycle`);
      setSummary(s);
      const next: Record<string, Item[]> = {};
      for (const [type, c] of Object.entries(s)) {
        const rows: Item[] = [];
        for (const st of ["archived", "deleted"] as const) if (c[st]) rows.push(...(await api<Page<Item>>(`/projects/${projectId}/lifecycle/${type}?state=${st}&size=200`)).items);
        next[type] = rows;
      }
      setItems(next);
    } catch (e) { setError(e instanceof Error ? e.message : "Failed to load"); }
  }, [projectId]);
  useEffect(() => { void load(); }, [load]);

  async function restore(type: string, it: Item) {
    try { await api(`/projects/${projectId}/lifecycle/${type}/${it.id}/restore`, { method: "POST", body: {} }); await load(); onChanged(); }
    catch (e) { setError(e instanceof Error ? e.message : "Could not restore"); }
  }

  return (
    <>
      <ErrorBox message={error} />
      <p className="mb-3 text-sm text-slate-600">Archived records are hidden from lists and dashboards but kept. Records in the trash can be restored until someone with permission deletes them permanently.</p>
      {!summary ? <Loading /> : Object.keys(summary).length === 0 ? <Empty>Nothing is archived or in the trash.</Empty> : (
        Object.entries(items).map(([type, rows]) => (
          <section key={type} className="mb-5">
            <h3 className="mb-1 text-sm font-semibold text-blue-950">{LABEL[type] ?? type} ({rows.length})</h3>
            <ul className="divide-y divide-slate-100 text-sm">
              {rows.map((it) => (
                <li key={it.id} className="flex items-center justify-between gap-3 py-1.5">
                  <div className="min-w-0 truncate"><Badge tone={it.state === "deleted" ? "red" : "amber"}>{it.state === "deleted" ? "trash" : "archived"}</Badge> <span className="ml-1">{it.title}</span>
                    <span className="ml-2 text-xs text-slate-500">{fmt((it.deleted_at ?? it.archived_at ?? "").slice(0, 10))}</span></div>
                  {can("projects:write") && (
                    <div className="flex shrink-0 gap-2">
                      <Button variant="ghost" onClick={() => restore(type, it)}>Restore</Button>
                      {it.state === "deleted" && can("projects:create") && <Button variant="danger" onClick={() => setPurge({ type, item: it })}>Delete permanently</Button>}
                    </div>
                  )}
                </li>
              ))}
            </ul>
          </section>
        ))
      )}
      {purge && (
        <ConfirmDialog title="Delete permanently?" confirmLabel="Delete permanently" danger onCancel={() => setPurge(null)}
          onConfirm={async () => { await api(`/projects/${projectId}/lifecycle/${purge.type}/${purge.item.id}/purge`, { method: "POST", body: { confirm: true } }); setPurge(null); await load(); onChanged(); }}>
          “{purge.item.title}” will be removed with its links and revision history. This cannot be undone. The audit log keeps a copy.
        </ConfirmDialog>
      )}
    </>
  );
}
