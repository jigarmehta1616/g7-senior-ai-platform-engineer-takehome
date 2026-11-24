import { useCallback } from "react";

import { api } from "../../api/client";
import { useSession } from "../../app/useSession";
import { useToast } from "../../app/useToast";
import { Badge, Button, DataTable, Locked } from "../../components";
import { useLoader } from "../../hooks/useLoader";
import { formatTime } from "../../lib/format";
import type { AuditEvent } from "../../types/api";
import type { Column, Tone } from "../../types/ui";

const OUTCOME_TONE: Record<AuditEvent["outcome"], Tone> = { success: "ok", denied: "warn", failed: "bad" };

const COLUMNS: Column<AuditEvent>[] = [
  { header: "#", cell: (e) => e.seq, className: "tabular-nums" },
  { header: "When", cell: (e) => formatTime(e.occurredAt) },
  { header: "User", cell: (e) => e.actor.subject },
  { header: "Agent", cell: (e) => e.actor.agent ?? "—" },
  { header: "Action", cell: (e) => e.action },
  { header: "Resource", cell: (e) => e.resourceId ?? "—" },
  { header: "Outcome", cell: (e) => <Badge tone={OUTCOME_TONE[e.outcome]}>{e.outcome} {e.httpStatus}</Badge> },
  { header: "Correlation", cell: (e) => <span className="font-mono text-xs text-muted">{e.correlationId.slice(0, 12)}</span> },
];

const fetchAudit = async () => (await api.auditEvents()).data;

export function AuditPage() {
  const { can } = useSession();
  const toast = useToast();
  const allowed = can("audit:read");
  const loader = useCallback(() => fetchAudit(), []);
  const { data: audit, reload } = useLoader(allowed ? loader : null, toast.fail);

  if (!allowed) return <Locked scope="audit:read (try the Support Lead persona)" />;

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-3">
        <Button onClick={reload}>Refresh</Button>
        {audit && (
          <Badge tone={audit.integrity.chainValid ? "ok" : "bad"}>
            {audit.integrity.chainValid ? `✓ hash chain valid (${String(audit.integrity.eventsChecked)} events)` : "✗ chain broken"}
          </Badge>
        )}
      </div>
      <DataTable columns={COLUMNS} rows={audit?.data ?? []} rowKey={(e) => e.eventId} empty="No audit events yet." />
    </div>
  );
}
