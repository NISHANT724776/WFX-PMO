"use client";

import { useEffect, useState } from "react";
import { useToast } from "@/components/Toast";
import { Button, Empty, ErrorBox, Label, Select, Loading } from "@/components/ui";
import { api, downloadFile, qs, type Row } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmt } from "@/lib/plan";

type Entry = { key: string; label: string; description: string; needs_product: boolean; takes_period: boolean; formats: string[] };
const FORMATS: [string, string][] = [["xlsx", "Excel"], ["pdf", "PDF"], ["pptx", "PowerPoint"]];
const PRODUCT_OPTIONAL = ["coverage", "attention", "overdue"]; // these can be narrowed to one product; the product report needs one

/** Every management report in Excel, PDF and PowerPoint. All of them are built from the same numbers as the dashboards, as of the report date above. */
export default function Reports({ projectId, products, asOf }: { projectId: string; products: Row[]; asOf: string }) {
  const { can } = useAuth();
  const toast = useToast();
  const [list, setList] = useState<Entry[] | null>(null);
  const [productId, setProductId] = useState("");
  const [period, setPeriod] = useState("next_week");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { api<Entry[]>(`/projects/${projectId}/exports`).then(setList).catch((e) => setError(e instanceof Error ? e.message : "Failed to load")); }, [projectId]);
  useEffect(() => { if (!productId && products.length) setProductId(String(products[0].id)); }, [products, productId]);
  const allowed = can("dashboards:export");

  async function get(e: Entry, fmt: string) {
    const id = `${e.key}.${fmt}`;
    setBusy(id); setError(null);
    const useProduct = e.needs_product || (PRODUCT_OPTIONAL.includes(e.key) && !!productId && onlyProduct[e.key]);
    try {
      await downloadFile(`/projects/${projectId}/exports/${e.key}${qs({ format: fmt, as_of: asOf, product_id: useProduct ? productId : undefined, period: e.takes_period ? period : undefined })}`, `${e.key}.${fmt}`);
      toast.ok(`${e.label}: ${FORMATS.find(([k]) => k === fmt)![1]} file downloaded`);
    } catch (err) { setError(err instanceof Error ? err.message : "Export failed"); toast.err(`${e.label}: export failed`); }
    finally { setBusy(null); }
  }
  const [onlyProduct, setOnlyProduct] = useState<Record<string, boolean>>({});

  return (
    <div>
      <div className="mb-3"><h2 className="text-xl font-semibold text-blue-950">Reports and exports</h2>
        <p className="text-xs text-slate-500">Each report is built from the project database as of {fmt(asOf)} (change the report date above). The numbers are the ones on the dashboards. PowerPoint keeps the layout of the status slides; Excel has one sheet per table; PDF is ready to print or send.</p></div>
      <ErrorBox message={error} />
      {!allowed && <Empty>Your role can read the dashboards but not export them.</Empty>}
      {allowed && (
        <>
          <div className="mb-4 flex flex-wrap items-end gap-3 rounded-lg border border-slate-200 bg-slate-50/70 p-3">
            <Label text="Product (for the product report, and where ticked)"><Select value={productId} onChange={(e) => setProductId(e.target.value)}>{products.map((p) => <option key={String(p.id)} value={String(p.id)}>{String(p.code)} · {String(p.name)}</option>)}</Select></Label>
            <Label text="Period (week plan)"><Select value={period} onChange={(e) => setPeriod(e.target.value)}><option value="this_week">This week</option><option value="next_week">Next week</option><option value="next_month">Next month</option></Select></Label>
          </div>
          {!list ? <Loading /> : (
            <ul className="divide-y divide-slate-200 rounded-md border border-slate-200">
              {list.map((e) => (
                <li key={e.key} className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
                  <div className="min-w-0 max-w-xl">
                    <div className="text-sm font-semibold text-blue-950">{e.label}</div>
                    <div className="text-xs text-slate-600">{e.description}</div>
                    {PRODUCT_OPTIONAL.includes(e.key) && <label className="mt-1 block text-[11px] text-slate-600"><input type="checkbox" checked={!!onlyProduct[e.key]} onChange={(ev) => setOnlyProduct((s) => ({ ...s, [e.key]: ev.target.checked }))} /> only the product chosen above</label>}
                    {e.needs_product && !productId && <div className="text-[11px] text-amber-700">Choose a product first.</div>}
                  </div>
                  <div className="flex gap-2">
                    {FORMATS.filter(([k]) => e.formats.includes(k)).map(([k, l]) => (
                      <Button key={k} variant={k === "pdf" ? "primary" : "ghost"} disabled={busy !== null || (e.needs_product && !productId)} onClick={() => get(e, k)}>{busy === `${e.key}.${k}` ? "Preparing…" : l}</Button>
                    ))}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </div>
  );
}
