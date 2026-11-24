import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { ApiError } from "../api/client";
import type { Toast, ToastApi } from "../types/toast";
import { ToastContext } from "./ToastContext";

const TOAST_MS = 6000;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toast, setToast] = useState<Toast | null>(null);
  const timer = useRef<number | undefined>(undefined);

  const show = useCallback((next: Toast) => {
    setToast(next);
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => {
      setToast(null);
    }, TOAST_MS);
  }, []);

  useEffect(
    () => () => {
      window.clearTimeout(timer.current);
    },
    [],
  );

  const value = useMemo<ToastApi>(
    () => ({
      notify: (title, detail) => {
        show({ title, detail, tone: "ok" });
      },
      fail: (error) => {
        if (error instanceof ApiError) {
          const p = error.problem;
          show({
            title: `${String(p.status)} ${p.title}`,
            detail: `${p.detail ?? ""} (correlationId ${p.correlationId})`,
            tone: "error",
          });
        } else {
          show({ title: "Something went wrong", detail: String(error), tone: "error" });
        }
      },
    }),
    [show],
  );

  return (
    <ToastContext.Provider value={value}>
      {children}
      {toast && (
        <div
          role="alert"
          className={`fixed right-4 bottom-12 z-30 max-w-md rounded-lg border border-l-4 border-line bg-surface px-4 py-3 shadow-lg ${
            toast.tone === "ok" ? "border-l-ok" : "border-l-bad"
          }`}
        >
          <p className="font-semibold">{toast.title}</p>
          {toast.detail && <p className="mt-1 text-sm text-muted">{toast.detail}</p>}
        </div>
      )}
    </ToastContext.Provider>
  );
}
