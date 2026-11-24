import type { CustomerSummary, UsageMonth } from "./api";

export interface CustomerCardProps {
  customer: CustomerSummary;
}

export interface UsageChartProps {
  history: UsageMonth[];
}
