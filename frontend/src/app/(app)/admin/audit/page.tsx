import Client from "./client";

// The screen is a client component behind sign-in; there is no static shell to validate (silences the dev-only instant-navigation error).
export const instant = false;

export default function Page() {
  return <Client />;
}
