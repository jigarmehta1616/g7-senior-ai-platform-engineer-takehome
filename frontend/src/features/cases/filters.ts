import type { Priority, SupportTier } from "../../types/api";
import type { CaseFilterValues } from "../../types/cases";

const HOUR_MS = 3_600_000;
const DAY_MS = 86_400_000;
const ACTIVE = "open,in_progress,pending_customer";

export const PRIORITIES: readonly Priority[] = ["P1", "P2", "P3"];
export const TIERS: readonly SupportTier[] = ["Platinum", "Gold", "Silver", "Standard"];

export const EMPTY_FILTERS: CaseFilterValues = {
  priorities: [],
  status: ACTIVE,
  tier: "",
  minOpenHours: "",
  renewalDays: "",
  sort: "-openedAt",
};

/** "Which Platinum customers have P1 cases open > 48h and a renewal in the next 90 days?" */
export const SAMPLE_QUESTION: CaseFilterValues = {
  priorities: ["P1"],
  status: ACTIVE,
  tier: "Platinum",
  minOpenHours: "48",
  renewalDays: "90",
  sort: "openedAt",
};

/** Converts the form's relative values into the absolute params the API contract uses. */
export function toQuery(filters: CaseFilterValues, now: number = Date.now()): URLSearchParams {
  const q = new URLSearchParams({ include: "account", limit: "15", sort: filters.sort });
  if (filters.priorities.length) q.set("priority", filters.priorities.join(","));
  if (filters.status) q.set("status", filters.status);
  if (filters.tier) q.set("supportTier", filters.tier);
  const hours = Number(filters.minOpenHours);
  if (hours > 0) q.set("openedBefore", new Date(now - hours * HOUR_MS).toISOString().replace(/\.\d+Z$/, "Z"));
  const days = Number(filters.renewalDays);
  if (days > 0) q.set("renewalBefore", new Date(now + days * DAY_MS).toISOString().slice(0, 10));
  return q;
}
