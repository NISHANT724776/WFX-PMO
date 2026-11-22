"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { Badge, Button, Empty, ErrorBox, PageHeader, Pager, Loading } from "@/components/ui";
import { api, qs, type Page } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtSize, uploadWorkbook, type Batch } from "@/lib/imports";

const SIZE = 15;
const TONE: Record<string, "green" | "amber" | "red" | "slate"> = {
  ready: "amber", committed: "green", failed: "red", rolled_back: "slate", analyzing: "slate", uploaded: "slate",
};

export default function ExcelIntelligencePage() {
  const { can } = useAuth();
  const [data, setData] = useState<Page<Batch> | null>(null);
  const [page, setPage] = useState(1);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [drag, setDrag] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    try {
      setData(await api<Page<Batch>>(`/imports${qs({ page, size: SIZE })}`));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load imports");
    }
  }, [page]);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    if (!data?.items.some((b) => b.status === "uploaded" || b.status === "analyzing")) return;
    const t = setTimeout(() => void load(), 1500);
    return () => clearTimeout(t);
  }, [data, load]);

  async function send(file: File | undefined) {
    if (!file) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const b = await uploadWorkbook(file);
      if (b.duplicate_of) setNotice("This exact file was already imported before. You can still analyse it, but it cannot be committed into the same project twice.");
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Upload failed");
    } finally {
      setBusy(false);
      if (input.current) input.current.value = "";
    }
  }

  const canUpload = can("imports:upload");

  return (
    <>
      <PageHeader title="Excel Intelligence" subtitle="Upload a workbook, review the suggested mapping, validate, then import" />
      <ErrorBox message={error} />
      {notice && <div className="mb-3 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">{notice}</div>}
      {canUpload ? (
        <div
          onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
          onDragLeave={() => setDrag(false)}
          onDrop={(e) => { e.preventDefault(); setDrag(false); void send(e.dataTransfer.files[0]); }}
          className={`mb-6 flex flex-col items-center gap-2 rounded-md border-2 border-dashed p-8 text-center text-sm ${drag ? "border-blue-700 bg-blue-50" : "border-slate-300 bg-slate-50"}`}
        >
          <p className="text-slate-700">{busy ? "Uploading…" : "Drag a workbook here, or"}</p>
          <Button disabled={busy} onClick={() => input.current?.click()}>Choose file</Button>
          <input ref={input} type="file" accept=".xlsx,.xls,.csv" className="hidden" onChange={(e) => void send(e.target.files?.[0])} />
          <p className="text-xs text-slate-500">XLSX, XLS or CSV, up to 25 MB. Macro-enabled workbooks are not accepted.</p>
        </div>
      ) : (
        <Empty>You do not have permission to upload workbooks.</Empty>
      )}
      <h2 className="mb-2 text-sm font-semibold text-blue-950">Import history</h2>
      {!data ? <Loading /> : data.items.length === 0 ? <Empty>No imports yet.</Empty> : (
        <>
          <table className="w-full text-left text-sm">
            <thead className="border-b border-slate-300 text-xs uppercase text-slate-500">
              <tr><th className="py-2 pr-4">File</th><th className="pr-4">Size</th><th className="pr-4">Uploaded</th><th className="pr-4">By</th><th className="pr-4">Status</th><th /></tr>
            </thead>
            <tbody>
              {data.items.map((b) => (
                <tr key={b.id} className="border-b border-slate-100">
                  <td className="py-1.5 pr-4">{b.filename}{b.template && <span className="ml-2 text-xs text-slate-500">template: {b.template}</span>}</td>
                  <td className="pr-4">{fmtSize(b.size_bytes)}</td>
                  <td className="pr-4 whitespace-nowrap">{new Date(b.uploaded_at).toLocaleString()}</td>
                  <td className="pr-4">{b.uploaded_by}</td>
                  <td className="pr-4"><Badge tone={TONE[b.status] ?? "slate"}>{b.status.replace("_", " ")}</Badge></td>
                  <td className="text-right"><Link className="text-blue-900 underline" href={`/excel-intelligence/${b.id}`}>Open</Link></td>
                </tr>
              ))}
            </tbody>
          </table>
          <Pager page={page} size={SIZE} total={data.total} onPage={setPage} />
        </>
      )}
    </>
  );
}
