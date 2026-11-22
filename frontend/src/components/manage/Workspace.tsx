"use client";

import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { Badge, Button, ErrorBox, Input } from "@/components/ui";
import { API_BASE, api, qs, tokenStore } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmt } from "@/lib/plan";

/* ------------------------------------------------------------------ confirmation modal (every destructive step goes through this) */
export function ConfirmDialog({ title, children, confirmLabel, danger, reasonLabel, minReason = 3, initial = "", onConfirm, onCancel }: {
  initial?: string; title: string; children?: ReactNode; confirmLabel: string; danger?: boolean; reasonLabel?: string; minReason?: number;
  onConfirm: (reason: string) => Promise<void> | void; onCancel: () => void;
}) {
  const [reason, setReason] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const ok = !reasonLabel || reason.trim().length >= minReason;
  async function go() {
    setBusy(true); setError(null);
    try { await onConfirm(reason.trim()); } catch (e) { setError(e instanceof Error ? e.message : "Failed"); setBusy(false); }
  }
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" role="dialog" aria-modal="true" aria-label={title} onClick={onCancel}
      onKeyDown={(e) => { if (e.key === "Escape") onCancel(); }}>
      <div className="w-full max-w-md rounded-md bg-white p-5 shadow-xl" onClick={(e) => e.stopPropagation()}>
        <h3 className="mb-2 text-base font-semibold text-blue-950">{title}</h3>
        <div className="mb-3 text-sm text-slate-700">{children}</div>
        {reasonLabel && (
          <label className="mb-3 block text-xs font-medium text-slate-600"><span className="mb-1 block">{reasonLabel} *</span>
            <Input autoFocus value={reason} onChange={(e) => setReason(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && ok && !busy) { e.preventDefault(); void go(); } }} /></label>
        )}
        <ErrorBox message={error} />
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onCancel} disabled={busy}>Cancel</Button>
          <Button variant={danger ? "danger" : "primary"} onClick={go} disabled={busy || !ok}>{busy ? "Working…" : confirmLabel}</Button>
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ archive / duplicate / delete / restore for one record */
export function LifecycleBar({ projectId, type, id, state, onDone, onGone, setError }: {
  projectId: string; type: string; id: string; state: "active" | "archived" | "deleted"; onDone: () => Promise<void> | void; onGone: () => Promise<void> | void; setError: (m: string | null) => void;
}) {
  const { can } = useAuth();
  const [ask, setAsk] = useState<null | "delete" | "purge">(null);
  const base = `/projects/${projectId}/lifecycle/${type}/${id}`;
  const run = async (action: string, body?: unknown) => {
    setError(null);
    try { await api(`${base}/${action}`, { method: "POST", body: body ?? {} }); return true; }
    catch (e) { setError(e instanceof Error ? e.message : "Failed"); return false; }
  };
  if (!can("projects:write")) return null;
  return (
    <div className="mb-4 flex flex-wrap items-center gap-2 border-t border-slate-200 pt-3 text-sm">
      {state === "active" && <>
        <Button variant="ghost" onClick={async () => { if (await run("archive")) await onGone(); }}>Archive</Button>
        <Button variant="ghost" onClick={async () => { if (await run("duplicate")) await onDone(); }}>Duplicate</Button>
        <Button variant="danger" onClick={() => setAsk("delete")}>Delete</Button>
      </>}
      {state !== "active" && <Button variant="ghost" onClick={async () => { if (await run("restore")) await onGone(); }}>Restore</Button>}
      {state === "archived" && <Button variant="danger" onClick={() => setAsk("delete")}>Move to trash</Button>}
      {state === "deleted" && can("projects:create") && <Button variant="danger" onClick={() => setAsk("purge")}>Delete permanently</Button>}
      {state !== "active" && <Badge tone={state === "deleted" ? "red" : "amber"}>{state === "deleted" ? "in the trash" : "archived"}</Badge>}
      {ask === "delete" && (
        <ConfirmDialog title="Move to the trash?" confirmLabel="Move to trash" danger onCancel={() => setAsk(null)} onConfirm={async () => { if (await run("delete")) { setAsk(null); await onGone(); } }}>
          It disappears from lists, the plan and every dashboard. Links and history are kept, and it can be restored from the project&apos;s Archive tab or the Trash list.
        </ConfirmDialog>
      )}
      {ask === "purge" && (
        <ConfirmDialog title="Delete permanently?" confirmLabel="Delete permanently" danger onCancel={() => setAsk(null)} onConfirm={async () => { if (await run("purge", { confirm: true })) { setAsk(null); await onGone(); } }}>
          This removes the record, its links and its revision history for good. It cannot be undone. The audit log keeps a copy of what was deleted.
        </ConfirmDialog>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ comments + attachments */
type Cmt = { id: string; body: string; author_email: string | null; created_at: string };
type Att = { id: string; filename: string; size_bytes: number; note: string | null; uploaded_by_email: string | null; created_at: string };
const kb = (n: number) => (n < 1024 ? `${n} B` : n < 1048576 ? `${(n / 1024).toFixed(0)} KB` : `${(n / 1048576).toFixed(1)} MB`);

export function Discussion({ projectId, type, id, readOnly }: { projectId: string; type: string; id: string; readOnly?: boolean }) {
  const { can, me } = useAuth();
  const canRead = can("comments:read");
  const canComment = can("comments:write") && !readOnly;
  const [comments, setComments] = useState<Cmt[]>([]);
  const [files, setFiles] = useState<Att[]>([]);
  const [text, setText] = useState("");
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const q = qs({ entity_type: type, entity_id: id });

  const load = useCallback(async () => {
    if (!canRead) return; // customers do not see internal comments or files
    try {
      setComments(await api<Cmt[]>(`/projects/${projectId}/comments${q}`));
      setFiles(await api<Att[]>(`/projects/${projectId}/attachments${q}`));
    } catch (e) { setError(e instanceof Error ? e.message : "Failed to load"); }
  }, [projectId, q, canRead]);
  useEffect(() => { void load(); }, [load]);

  async function post(e: React.FormEvent) {
    e.preventDefault(); setError(null);
    try { await api(`/projects/${projectId}/comments`, { method: "POST", body: { entity_type: type, entity_id: id, body: text } }); setText(""); await load(); }
    catch (err) { setError(err instanceof Error ? err.message : "Could not post"); }
  }
  async function removeComment(cid: string) {
    try { await api(`/projects/${projectId}/comments/${cid}`, { method: "DELETE" }); await load(); } catch (err) { setError(err instanceof Error ? err.message : "Could not remove"); }
  }
  async function upload(file: File) {
    setBusy(true); setError(null);
    const form = new FormData();
    form.append("entity_type", type); form.append("entity_id", id); form.append("file", file); if (note.trim()) form.append("note", note.trim());
    try {
      const res = await fetch(`${API_BASE}/api/v1/projects/${projectId}/attachments`, { method: "POST", body: form, headers: { Authorization: `Bearer ${tokenStore.get() ?? ""}` } });
      if (!res.ok) { const b = await res.json().catch(() => null); throw new Error(typeof b?.detail === "string" ? b.detail : `Upload failed (${res.status})`); }
      setNote(""); if (fileRef.current) fileRef.current.value = ""; await load();
    } catch (err) { setError(err instanceof Error ? err.message : "Upload failed"); } finally { setBusy(false); }
  }
  async function download(a: Att) {
    try {
      const res = await fetch(`${API_BASE}/api/v1/projects/${projectId}/attachments/${a.id}/download`, { headers: { Authorization: `Bearer ${tokenStore.get() ?? ""}` } });
      if (!res.ok) throw new Error(`Download failed (${res.status})`);
      const url = URL.createObjectURL(await res.blob());
      const link = document.createElement("a"); link.href = url; link.download = a.filename; link.click(); URL.revokeObjectURL(url);
    } catch (err) { setError(err instanceof Error ? err.message : "Download failed"); }
  }
  async function removeFile(aid: string) {
    try { await api(`/projects/${projectId}/attachments/${aid}`, { method: "DELETE" }); await load(); } catch (err) { setError(err instanceof Error ? err.message : "Could not remove"); }
  }
  const mine = (email: string | null) => email === me?.email;
  if (!canRead) return null;

  return (
    <section className="mb-6">
      <h3 className="mb-1 text-sm font-semibold text-blue-950">Comments ({comments.length})</h3>
      <ErrorBox message={error} />
      {comments.length === 0 ? <p className="mb-2 text-sm text-slate-500">No comments yet.</p> : (
        <ul className="mb-2 divide-y divide-slate-100 text-xs">
          {comments.map((c) => (
            <li key={c.id} className="py-1.5">
              <div className="text-slate-500">{c.author_email} · {fmt(c.created_at.slice(0, 10))} {c.created_at.slice(11, 16)}
                {(mine(c.author_email) || can("projects:write")) && !readOnly && <button className="ml-2 text-red-700" onClick={() => removeComment(c.id)} aria-label="Remove comment">remove</button>}</div>
              <div className="whitespace-pre-wrap text-slate-800">{c.body}</div>
            </li>
          ))}
        </ul>
      )}
      {canComment && (
        <form onSubmit={post} className="mb-4 flex gap-2">
          <Input value={text} onChange={(e) => setText(e.target.value)} placeholder="Add a comment" maxLength={4000} />
          <Button type="submit" disabled={!text.trim()}>Post</Button>
        </form>
      )}
      <h3 className="mb-1 text-sm font-semibold text-blue-950">Attachments ({files.length})</h3>
      {files.length === 0 ? <p className="mb-2 text-sm text-slate-500">No files attached.</p> : (
        <ul className="mb-2 divide-y divide-slate-100 text-xs">
          {files.map((a) => (
            <li key={a.id} className="flex items-center justify-between gap-2 py-1.5">
              <div className="min-w-0"><button className="truncate text-blue-900 hover:underline" onClick={() => download(a)}>{a.filename}</button>
                <div className="text-[11px] text-slate-500">{kb(a.size_bytes)} · {a.uploaded_by_email} · {fmt(a.created_at.slice(0, 10))}{a.note ? ` · ${a.note}` : ""}</div></div>
              {!readOnly && (mine(a.uploaded_by_email) || can("projects:write")) && <button className="shrink-0 text-red-700" onClick={() => removeFile(a.id)} aria-label="Remove attachment">✕</button>}
            </li>
          ))}
        </ul>
      )}
      {canComment && (
        <div className="flex flex-wrap items-center gap-2">
          <input ref={fileRef} type="file" disabled={busy} className="max-w-60 text-xs" aria-label="Choose a file to attach"
            onChange={(e) => { const f = e.target.files?.[0]; if (f) void upload(f); }} />
          <Input className="max-w-52" value={note} onChange={(e) => setNote(e.target.value)} placeholder="Note (optional)" maxLength={300} />
          {busy && <span className="text-xs text-slate-500">Uploading…</span>}
        </div>
      )}
      <p className="mt-1 text-[11px] text-slate-400">Documents, spreadsheets, decks, images, text and zip files up to 25 MB.</p>
    </section>
  );
}

/* ------------------------------------------------------------------ action item steps */
export function ActionSteps({ projectId, rec, onDone, setError }: { projectId: string; rec: { id: string; status?: unknown; last_action?: unknown; last_action_by?: unknown; last_action_at?: unknown; escalation_level?: unknown; escalated_to?: unknown; resolution_note?: unknown }; onDone: () => Promise<void> | void; setError: (m: string | null) => void }) {
  const { can } = useAuth();
  const [ask, setAsk] = useState<null | "escalate" | "resolve" | "reopen">(null);
  const [to, setTo] = useState("");
  const status = String(rec.status ?? "open");
  const go = async (verb: "escalate" | "resolve" | "reopen", reason: string) => {
    setError(null);
    await api(`/projects/${projectId}/records/action-items/${rec.id}/${verb}`, { method: "POST", body: { reason, to: verb === "escalate" && to.trim() ? to.trim() : undefined } });
    setAsk(null); setTo(""); await onDone();
  };
  const copy = { escalate: ["Escalate this action", "Why is it being escalated?", "Escalate"], resolve: ["Mark as resolved", "What resolved it?", "Mark resolved"], reopen: ["Reopen this action", "Why is it being reopened?", "Reopen"] } as const;
  return (
    <section className="mb-4 rounded-md border border-slate-200 bg-slate-50 p-3 text-xs">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <Badge tone={status === "resolved" ? "green" : status === "escalated" ? "red" : status === "in_progress" ? "amber" : "slate"}>{status.replace("_", " ")}</Badge>
        {Number(rec.escalation_level) > 0 && <span className="text-slate-600">escalation level {String(rec.escalation_level)}{rec.escalated_to ? ` to ${String(rec.escalated_to)}` : ""}</span>}
        {rec.resolution_note ? <span className="text-slate-600">Resolution: {String(rec.resolution_note)}</span> : null}
      </div>
      {rec.last_action ? <div className="mb-2 text-slate-600">Latest action: <b>{String(rec.last_action)}</b> — {String(rec.last_action_by ?? "")} {rec.last_action_at ? fmt(String(rec.last_action_at).slice(0, 10)) : ""}</div> : null}
      {can("projects:write") && (
        <div className="flex gap-2">
          {status !== "resolved" && <Button variant="ghost" onClick={() => setAsk("escalate")}>Escalate</Button>}
          {status !== "resolved" && <Button variant="ghost" onClick={() => setAsk("resolve")}>Resolve</Button>}
          {status === "resolved" && <Button variant="ghost" onClick={() => setAsk("reopen")}>Reopen</Button>}
        </div>
      )}
      {ask && (
        <ConfirmDialog title={copy[ask][0]} confirmLabel={copy[ask][2]} reasonLabel={copy[ask][1]} onCancel={() => setAsk(null)} onConfirm={(r) => go(ask, r)}>
          {ask === "escalate" && <label className="block text-xs font-medium text-slate-600"><span className="mb-1 block">Escalate to (optional)</span><Input value={to} onChange={(e) => setTo(e.target.value)} /></label>}
        </ConfirmDialog>
      )}
    </section>
  );
}
