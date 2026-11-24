import type { Persona } from "./api";

export type SessionStatus = "signing-in" | "ready" | "error";

export interface Session {
  personas: Persona[];
  persona: string | null;
  scopes: string[];
  status: SessionStatus;
  /** Why sign-in failed, when status is "error". */
  error: string | null;
  ready: boolean;
  signIn: (persona: string) => Promise<void>;
  /** Retry the initial sign-in after a failure. */
  retry: () => void;
  can: (scope: string) => boolean;
}
