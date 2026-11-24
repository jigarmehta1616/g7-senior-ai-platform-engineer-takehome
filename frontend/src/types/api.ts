// Wire types mirroring openapi.yaml (components/schemas). Keep in sync with the contract.

export type Priority = "P1" | "P2" | "P3";
export type CaseStatus = "open" | "in_progress" | "pending_customer" | "resolved" | "closed";
export type SupportTier = "Platinum" | "Gold" | "Silver" | "Standard";
export type EscalationReason =
  | "customer_impact"
  | "sla_breach_risk"
  | "security_incident"
  | "executive_request"
  | "other";

export interface Problem {
  type: string;
  title: string;
  status: number;
  detail?: string;
  instance?: string;
  correlationId: string;
  code?: string;
  upstream?: string;
  errors?: { pointer: string; detail: string }[];
}

export interface AccountRef {
  id: string;
  name: string;
  supportTier: SupportTier;
  renewalDate: string;
}

export interface CaseSummary {
  id: string;
  accountId: string;
  priority: Priority;
  status: CaseStatus;
  subject: string;
  openedAt: string;
  updatedAt: string;
  ageHours: number;
  escalationLevel: number;
  commentCount: number;
  account?: AccountRef | null;
}

export interface Comment {
  id: string;
  author: string;
  body: string;
  createdAt: string;
  visibility: "internal" | "public";
}

export interface CaseDetail extends CaseSummary {
  escalation: { level: number; targetTeam: string | null; reason: string | null };
  comments: Comment[];
}

export interface CaseList {
  data: CaseSummary[];
  page: { limit: number; nextCursor: string | null };
  degraded: boolean;
  staleSources: string[];
}

export interface UsageMonth {
  month: string;
  protectedTb: number;
  apiCalls: number;
  activeUsers: number;
}

export interface DataSource {
  source: "entitlements" | "usage" | "cases";
  status: "ok" | "stale" | "unavailable";
  asOf?: string;
  reason?: string;
}

export interface CustomerSummary {
  id: string;
  name: string;
  supportTier: SupportTier;
  contract: { endDate: string; renewalInDays: number; arrUsd?: number | null };
  primaryContact?: { email: string | null };
  usage: {
    latestMonth: string | null;
    protectedTb: number | null;
    apiCalls: number | null;
    activeUsers: number | null;
    protectedTbTrend: "up" | "down" | "flat";
    history: UsageMonth[];
  } | null;
  cases: { active: number; activeP1: number; escalated: number } | null;
  degraded: boolean;
  dataSources: DataSource[];
  redactedFields: string[];
}

export interface AuditEvent {
  seq: number;
  eventId: string;
  occurredAt: string;
  correlationId: string;
  actor: { subject: string; agent: string | null; clientId: string };
  action: string;
  resourceType: string | null;
  resourceId: string | null;
  outcome: "success" | "denied" | "failed";
  httpStatus: number;
}

export interface AuditEventList {
  data: AuditEvent[];
  integrity: { chainValid: boolean; eventsChecked: number };
}

export interface Persona {
  id: string;
  subject: string;
  name: string;
  scopes: string[];
}

export type FaultMode = "ok" | "error" | "timeout" | "flaky";
export type Upstream = "cases" | "entitlements" | "usage";

export interface ReceivedWebhook {
  verified: boolean;
  error?: string;
  event?: {
    type: string;
    data: {
      caseId: string;
      escalationLevel: number;
      targetTeam: string;
      escalatedBy: { subject: string; agent: string | null };
    };
  };
}
