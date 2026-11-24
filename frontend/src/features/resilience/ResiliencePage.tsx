import { useCallback } from "react";

import { api } from "../../api/client";
import { useToast } from "../../app/useToast";
import { Badge, Button, Card } from "../../components";
import { useLoader } from "../../hooks/useLoader";
import type { FaultMode, ReceivedWebhook, Upstream } from "../../types/api";
import type { LabState } from "../../types/resilience";

const MODES: readonly FaultMode[] = ["ok", "error", "timeout", "flaky"];
const UPSTREAMS: readonly Upstream[] = ["cases", "entitlements", "usage"];

async function fetchLab(): Promise<LabState> {
  const [current, webhooks] = await Promise.all([api.faults(), api.receivedWebhooks()]);
  return {
    faults: { cases: current.cases.mode, entitlements: current.entitlements.mode, usage: current.usage.mode },
    webhooks: webhooks.slice().reverse(),
  };
}

function describeWebhook(w: ReceivedWebhook): string {
  if (!w.event) return w.error ?? "invalid delivery";
  const { caseId, escalationLevel, targetTeam, escalatedBy } = w.event.data;
  const via = escalatedBy.agent ? ` via ${escalatedBy.agent}` : "";
  return `${w.event.type} ${caseId} → L${String(escalationLevel)} ${targetTeam} by ${escalatedBy.subject}${via}`;
}

export function ResiliencePage() {
  const toast = useToast();
  const loader = useCallback(() => fetchLab(), []);
  const { data: lab, error, reload } = useLoader(loader);

  const choose = async (target: Upstream, mode: FaultMode) => {
    try {
      await api.setFault(target, mode);
      toast.notify(`${target} → ${mode}`);
    } catch (err) {
      toast.fail(err);
    }
    reload();
  };

  if (error) {
    return (
      <div className="space-y-3">
        <p className="text-muted">Mock upstreams not reachable on port 8081.</p>
        <Button variant="ghost" onClick={reload}>Retry</Button>
      </div>
    );
  }
  if (!lab) return <p className="text-muted">Loading…</p>;

  return (
    <div className="space-y-4">
      <p className="text-sm text-muted">
        Inject failures into the mock upstreams, then reload a customer to see partial-failure handling (degraded flag,
        stale snapshot, circuit breaker).
      </p>
      <div className="grid grid-cols-[repeat(auto-fit,minmax(220px,1fr))] gap-3">
        {UPSTREAMS.map((u) => (
          <Card key={u} className="grid gap-2">
            <strong>{u}</strong>
            <div className="flex flex-wrap gap-1">
              {MODES.map((m) => (
                <Button key={m} variant={lab.faults[u] === m ? "primary" : "ghost"} aria-pressed={lab.faults[u] === m}
                  onClick={() => void choose(u, m)}>
                  {m}
                </Button>
              ))}
            </div>
          </Card>
        ))}
      </div>
      <div className="flex items-center gap-2">
        <h3 className="font-semibold">Webhook receiver</h3>
        <Button variant="ghost" onClick={reload}>Refresh</Button>
      </div>
      <ul className="grid gap-2">
        {lab.webhooks.length === 0 && <li className="text-sm text-muted">No webhooks received yet. Escalate a case.</li>}
        {lab.webhooks.map((w, i) => (
          <li key={w.event ? `${w.event.data.caseId}-${String(i)}` : `err-${String(i)}`} className="rounded-lg border border-line bg-surface px-3 py-2 text-sm">
            <Badge tone={w.verified ? "ok" : "bad"}>{w.verified ? "signature ✓" : "signature ✗"}</Badge> {describeWebhook(w)}
          </li>
        ))}
      </ul>
    </div>
  );
}
