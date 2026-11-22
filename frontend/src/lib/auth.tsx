"use client";

import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api, tokenStore } from "./api";

export type Me = {
  id: string;
  email: string;
  full_name: string;
  role: string;
  is_global_scope: boolean;
  permissions: string[];
};

type AuthState = {
  me: Me | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
  can: (perm: string) => boolean; // UI hint only; the backend enforces permissions
};

const Ctx = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!tokenStore.get()) {
      setLoading(false);
      return;
    }
    api<Me>("/auth/me")
      .then(setMe)
      .catch(() => tokenStore.clear())
      .finally(() => setLoading(false));
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const t = await api<{ access_token: string }>("/auth/login", { method: "POST", body: { email, password } });
    tokenStore.set(t.access_token);
    setMe(await api<Me>("/auth/me"));
  }, []);

  const logout = useCallback(() => {
    tokenStore.clear();
    setMe(null);
  }, []);

  const can = useCallback((p: string) => !!me?.permissions.includes(p), [me]);

  return <Ctx.Provider value={{ me, loading, login, logout, can }}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthState {
  const v = useContext(Ctx);
  if (!v) throw new Error("useAuth outside AuthProvider");
  return v;
}
