"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ErpFlow } from "@/components/illustrations";
import { Button, ErrorBox, Input, Label } from "@/components/ui";
import { useAuth } from "@/lib/auth";

export default function LoginPage() {
  const { me, loading, login } = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!loading && me) router.replace("/");
  }, [loading, me, router]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(email, password);
      router.replace("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="grid min-h-screen bg-canvas lg:grid-cols-2">
      <div className="hidden flex-col justify-between bg-gradient-to-br from-blue-950 via-blue-950 to-blue-800 p-10 text-white lg:flex">
        <div className="flex items-center gap-2.5"><span className="grid h-8 w-8 place-items-center rounded-lg bg-white/15 text-sm font-bold">W</span><span className="font-semibold tracking-tight">WFX PMO</span></div>
        <div>
          <div className="text-3xl font-semibold leading-tight tracking-tight">ERP implementation tracking,<br />without the spreadsheets</div>
          <p className="mt-3 max-w-md text-sm text-blue-100">One place for the plan, delivery, pending items, UAT and sign-offs, with every original date kept.</p>
          <div className="mt-8"><ErpFlow dark /></div>
        </div>
        <div className="text-xs text-blue-200">Project Management &amp; Delivery Governance</div>
      </div>
      <div className="flex items-center justify-center px-4">
      <form onSubmit={submit} className="wfx-enter w-full max-w-sm space-y-4 rounded-xl border border-slate-200 bg-white p-7 shadow-[0_8px_30px_rgba(16,24,40,0.06)]">
        <div>
          <span className="mb-4 grid h-9 w-9 place-items-center rounded-lg bg-gradient-to-br from-blue-700 to-blue-950 text-sm font-bold text-white shadow-sm lg:hidden">W</span>
          <h1 className="text-xl font-semibold tracking-tight text-blue-950">Sign in to WFX PMO</h1>
          <p className="mt-0.5 text-sm text-slate-500">Project Management &amp; Delivery Governance</p>
        </div>
        <ErrorBox message={error} />
        <Label text="Email">
          <Input type="email" required autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} />
        </Label>
        <Label text="Password">
          <Input type="password" required autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />
        </Label>
        <Button type="submit" disabled={busy} className="w-full">
          {busy ? "Signing in…" : "Sign in"}
        </Button>
      </form>
      </div>
    </main>
  );
}
