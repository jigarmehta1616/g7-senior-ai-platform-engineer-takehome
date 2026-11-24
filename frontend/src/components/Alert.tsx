import type { AlertProps } from "../types/ui";

const BORDER = { ok: "border-ok", warn: "border-warn", bad: "border-bad" } as const;

export function Alert({ tone = "warn", children }: AlertProps) {
  return (
    <p role="status" className={`rounded-md border-l-4 bg-canvas px-3 py-2 text-sm ${BORDER[tone]}`}>
      {children}
    </p>
  );
}
