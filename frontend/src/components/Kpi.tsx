import type { KpiProps } from "../types/ui";

export function Kpi({ label, children }: KpiProps) {
  return (
    <div className="rounded-lg border border-line p-3">
      <p className="text-xs text-muted">{label}</p>
      <div className="mt-1 text-xl font-semibold tabular-nums">{children}</div>
    </div>
  );
}
