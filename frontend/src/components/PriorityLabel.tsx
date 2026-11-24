import type { Priority } from "../types/api";
import type { PriorityLabelProps } from "../types/ui";

const TONE: Record<Priority, string> = { P1: "text-bad", P2: "text-warn", P3: "text-muted" };

export function PriorityLabel({ priority }: PriorityLabelProps) {
  return <span className={`font-bold ${TONE[priority]}`}>{priority}</span>;
}
