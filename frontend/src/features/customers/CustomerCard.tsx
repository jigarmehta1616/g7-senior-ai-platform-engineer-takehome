import { Alert, Badge, Card, Kpi, Locked } from "../../components";
import { formatCurrency } from "../../lib/format";
import type { DataSource } from "../../types/api";
import type { CustomerCardProps } from "../../types/customers";
import type { Tone } from "../../types/ui";
import { UsageChart } from "./UsageChart";

const SOURCE_TONE: Record<DataSource["status"], Tone> = { ok: "ok", stale: "warn", unavailable: "bad" };
const TREND = { up: "↑", down: "↓", flat: "→" } as const;

const describe = (s: DataSource) => `${s.source} ${s.status}${s.reason ? ` (${s.reason})` : ""}`;

export function CustomerCard({ customer: c }: CustomerCardProps) {
  const degraded = c.dataSources.filter((s) => s.status !== "ok");
  const arr = c.contract.arrUsd;

  return (
    <Card className="grid gap-4">
      <div className="flex flex-wrap items-baseline gap-2">
        <h2 className="text-xl font-semibold break-words">{c.name}</h2>
        <Badge>{c.supportTier}</Badge>
        <span className="text-sm text-muted">{c.id}</span>
      </div>

      {c.degraded && <Alert>Partial data: {degraded.map(describe).join(", ")}</Alert>}

      <div className="grid grid-cols-[repeat(auto-fit,minmax(150px,1fr))] gap-3">
        <Kpi label="Renewal">
          {c.contract.endDate} <span className="text-sm text-muted">({c.contract.renewalInDays}d)</span>
        </Kpi>
        <Kpi label="ARR">{arr === undefined ? <Locked scope="finance:read" /> : formatCurrency(arr ?? 0)}</Kpi>
        <Kpi label="Active cases">{c.cases ? `${String(c.cases.active)} (${String(c.cases.activeP1)} P1)` : "unavailable"}</Kpi>
        <Kpi label="Protected TB">{c.usage ? `${String(c.usage.protectedTb)} ${TREND[c.usage.protectedTbTrend]}` : "unavailable"}</Kpi>
        <Kpi label="Active users">{c.usage?.activeUsers ?? "unavailable"}</Kpi>
      </div>

      {c.usage && <UsageChart history={c.usage.history} />}

      <div className="flex flex-wrap items-center gap-2">
        {c.dataSources.map((s) => (
          <Badge key={s.source} tone={SOURCE_TONE[s.status]}>
            {s.source}: {s.status}
          </Badge>
        ))}
        {c.redactedFields.length > 0 && <span className="text-sm text-muted">withheld: {c.redactedFields.join(", ")}</span>}
      </div>
    </Card>
  );
}
