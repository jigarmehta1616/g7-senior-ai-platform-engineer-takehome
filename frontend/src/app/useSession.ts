import { useContext } from "react";

import type { Session } from "../types/session";
import { SessionContext } from "./SessionContext";

export function useSession(): Session {
  const ctx = useContext(SessionContext);
  if (!ctx) throw new Error("useSession must be used inside <SessionProvider>");
  return ctx;
}
