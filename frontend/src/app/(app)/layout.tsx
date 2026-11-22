import AppShell from "@/components/AppShell";

// Every page here sits behind client-side sign-in, so there is no static shell to validate (dev-only insight).
export const instant = false;

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return <AppShell>{children}</AppShell>;
}
