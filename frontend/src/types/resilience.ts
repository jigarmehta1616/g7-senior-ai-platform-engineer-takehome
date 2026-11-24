import type { FaultMode, ReceivedWebhook, Upstream } from "./api";

/** What the Resilience lab shows: current fault modes and webhooks the demo receiver got. */
export interface LabState {
  faults: Record<Upstream, FaultMode>;
  webhooks: ReceivedWebhook[];
}
