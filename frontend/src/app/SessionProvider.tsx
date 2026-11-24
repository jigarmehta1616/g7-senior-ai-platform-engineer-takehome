import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";

import { ApiError, api } from "../api/client";
import type { Persona } from "../types/api";
import type { Session, SessionStatus } from "../types/session";
import { SessionContext } from "./SessionContext";

const STORAGE_KEY = "support-console.persona";
const DEFAULT_PERSONA = "support-lead";

function readSavedPersona(): string | null {
  try {
    return localStorage.getItem(STORAGE_KEY);
  } catch {
    return null; // storage can be unavailable (private mode, blocked site data)
  }
}

function savePersona(id: string): void {
  try {
    localStorage.setItem(STORAGE_KEY, id);
  } catch {
    /* a per-viewer convenience only */
  }
}

const describe = (error: unknown): string =>
  error instanceof ApiError ? (error.problem.detail ?? error.problem.title) : "Unexpected error while signing in.";

export function SessionProvider({ children }: { children: ReactNode }) {
  const [personas, setPersonas] = useState<Persona[]>([]);
  const [persona, setPersona] = useState<string | null>(null);
  const [scopes, setScopes] = useState<string[]>([]);
  const [status, setStatus] = useState<SessionStatus>("signing-in");
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  /** Switch user. On failure the previous user stays signed in and the error is re-thrown for the caller. */
  const signIn = useCallback(async (id: string) => {
    const { token, scopes: granted } = await api.signIn(id);
    api.setToken(token);
    setPersona(id);
    setScopes(granted);
    setStatus("ready");
    setError(null);
    savePersona(id);
  }, []);

  useEffect(() => {
    let active = true;
    const boot = async () => {
      const list = await api.personas();
      if (!active) return;
      setPersonas(list);
      const known = (id: string | null): id is string => id !== null && list.some((p) => p.id === id);
      const saved = readSavedPersona();
      const first = known(saved) ? saved : known(DEFAULT_PERSONA) ? DEFAULT_PERSONA : list[0]?.id;
      if (!first) throw new Error("The identity provider returned no personas.");
      await signIn(first);
    };
    boot().catch((err: unknown) => {
      if (!active) return;
      setStatus("error");
      setError(describe(err));
    });
    return () => {
      active = false;
    };
  }, [signIn, attempt]);

  const retry = useCallback(() => {
    setStatus("signing-in");
    setError(null);
    setAttempt((n) => n + 1);
  }, []);

  const value = useMemo<Session>(
    () => ({
      personas,
      persona,
      scopes,
      status,
      error,
      ready: status === "ready",
      signIn,
      retry,
      can: (scope) => scopes.includes(scope),
    }),
    [personas, persona, scopes, status, error, signIn, retry],
  );
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}
